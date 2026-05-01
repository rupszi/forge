"""Hooks system — Sprint 7.1.

User-supplied scripts that fire at well-defined lifecycle points
(PreToolUse, PostToolUse, PreCompact, SubagentStop, SessionStart). The
contract is identical to Claude Code's and Codex CLI's: a JSON envelope
on stdin, a JSON response on stdout (or a non-zero exit to block).

Hooks live in ``.forge/hooks.toml`` at the project root. Example:

    [[hooks.PreToolUse]]
    matcher = "Bash"
    command = ["python", ".forge/hooks/destructive-check.py"]
    timeout = 5

    [[hooks.PostToolUse]]
    matcher = "Edit|Write"
    command = ["pre-commit", "run", "--files"]
    timeout = 60

    [[hooks.SessionStart]]
    matcher = ".*"
    command = ["python", ".forge/hooks/load-session-context.py"]

The matcher is a regex applied to the event's ``tool_name`` (or sprint
description for non-tool events). Hooks for an event run sequentially;
the first one to return ``{"action": "block", "reason": "..."}`` short-circuits
the chain and the agent receives the structured refusal.

Why hooks rather than plugins:
  - Plugins run in the dispatcher sandbox (capability-scoped, hash-pinned).
    That's the *agent's* permission model.
  - Hooks run with the user's full credentials (they're shell scripts the
    user wrote). They're the *user's* defense in depth.
  - The Claude Code / Codex contract makes hook scripts portable; users
    coming from those tools drop their existing hooks into Forge with no
    edits.

Non-goals for v0.1.0:
  - Network egress filtering on hook subprocesses (the user owns them).
  - Hash pinning (the user owns the directory; treat hooks like any
    other shell config).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .redact import filtered_subprocess_env

logger = logging.getLogger(__name__)


SUPPORTED_EVENTS: tuple[str, ...] = (
    "PreToolUse",
    "PostToolUse",
    "PreCompact",
    "SubagentStop",
    "SessionStart",
)

DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class HookSpec:
    """One row from ``[[hooks.<event>]]`` in ``.forge/hooks.toml``."""

    event: str
    matcher: str  # regex
    command: list[str]
    timeout: int = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.event not in SUPPORTED_EVENTS:
            raise ValueError(f"unknown hook event {self.event!r}; supported: {SUPPORTED_EVENTS}")
        if not self.command:
            raise ValueError(f"hook {self.event}/{self.matcher!r}: command list cannot be empty")


@dataclass
class HookResult:
    """Result of one hook execution, surfaced to the agent."""

    action: str = "allow"  # 'allow' | 'block'
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False

    @property
    def blocked(self) -> bool:
        return self.action == "block" or self.exit_code != 0


def load_hooks(config_path: Path) -> dict[str, list[HookSpec]]:
    """Read ``.forge/hooks.toml`` into a per-event dict.

    Returns ``{}`` when the file is absent (typical case — most users
    won't have hooks). Malformed entries are logged at WARNING and
    skipped; one bad row doesn't break the others.
    """
    if not config_path.is_file():
        return {}

    try:
        import tomllib
    except ImportError:  # Python 3.10
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]

    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError) as e:
        logger.warning("hooks.toml unreadable (%s); treating as empty", e)
        return {}

    hooks_block = data.get("hooks", {})
    out: dict[str, list[HookSpec]] = {evt: [] for evt in SUPPORTED_EVENTS}

    for event, rows in hooks_block.items():
        if not isinstance(rows, list):
            logger.warning("hooks.toml: hooks.%s must be an array of tables; skipping", event)
            continue
        for row in rows:
            try:
                spec = HookSpec(
                    event=event,
                    matcher=row.get("matcher", ".*"),
                    command=list(row.get("command", [])),
                    timeout=int(row.get("timeout", DEFAULT_TIMEOUT_SECONDS)),
                )
            except (ValueError, TypeError) as e:
                logger.warning("hooks.toml: skipping bad %s row: %s", event, e)
                continue
            out.setdefault(event, []).append(spec)

    return out


def _matches(spec: HookSpec, target: str) -> bool:
    """Run the matcher regex against ``target`` (tool name or description)."""
    try:
        return bool(re.search(spec.matcher, target))
    except re.error as e:
        logger.warning("hook matcher %r is invalid regex: %s", spec.matcher, e)
        return False


async def _run_one(spec: HookSpec, payload: dict[str, Any], cwd: Path) -> HookResult:
    """Execute one hook subprocess. JSON-on-stdin / JSON-on-stdout contract.

    Non-zero exit OR ``{"action": "block"}`` on stdout means the agent's
    operation is blocked. The structured form lets the daemon surface a
    refusal template (Sprint 7.10) that the agent can recover from.
    """
    payload_bytes = json.dumps(payload).encode("utf-8")
    env = filtered_subprocess_env()

    try:
        proc = await asyncio.create_subprocess_exec(
            *spec.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )
    except FileNotFoundError as e:
        return HookResult(
            action="block",
            reason=f"hook command not found: {e}",
            exit_code=127,
        )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(input=payload_bytes), timeout=spec.timeout
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return HookResult(
            action="block",
            reason=f"hook timeout after {spec.timeout}s; killed",
            timed_out=True,
            exit_code=-1,
        )

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    exit_code = proc.returncode if proc.returncode is not None else -1

    # Try to parse a structured response on stdout. If it parses and
    # contains an explicit action, honor it. Otherwise fall back to the
    # exit code: 0 = allow, non-zero = block.
    action = "allow"
    reason = ""
    extra: dict[str, Any] = {}
    try:
        parsed = json.loads(stdout) if stdout.strip() else {}
        if isinstance(parsed, dict):
            action = str(parsed.get("action", "allow"))
            reason = str(parsed.get("reason", ""))
            extra = {k: v for k, v in parsed.items() if k not in ("action", "reason")}
    except json.JSONDecodeError:
        pass

    if exit_code != 0:
        action = "block"
        if not reason:
            reason = f"hook exit code {exit_code}"

    return HookResult(
        action=action,
        reason=reason,
        extra=extra,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
    )


async def run_hooks(
    event: str,
    payload: dict[str, Any],
    *,
    config_path: Path | None = None,
    target: str = "",
    cwd: Path | None = None,
) -> list[HookResult]:
    """Run every matching hook for ``event``. Returns results in order.

    Iteration stops at the FIRST blocking result so a user's pre-flight
    check fires before any expensive subsequent hooks. Caller (scheduler /
    dispatcher) inspects the last entry: if ``blocked`` is True, the
    agent's operation must be refused with the structured reason.

    Parameters
    ----------
    event
        One of SUPPORTED_EVENTS.
    payload
        Dict serialized as JSON on stdin. Same shape as Claude Code's
        hook payload — at minimum ``tool_name``, ``tool_args``,
        ``cwd``, ``session_id``.
    config_path
        Defaults to ``.forge/hooks.toml`` in cwd or in env-supplied path.
    target
        String the matcher regex runs against (tool name for tool events,
        sprint description for SessionStart, etc.).
    cwd
        Working directory for hook subprocesses. Defaults to the dir
        containing the config file (so relative ``.forge/hooks/...``
        paths resolve correctly).
    """
    if event not in SUPPORTED_EVENTS:
        raise ValueError(f"unknown hook event {event!r}; supported: {SUPPORTED_EVENTS}")

    if config_path is None:
        config_path = Path(os.getcwd()) / ".forge" / "hooks.toml"
    if cwd is None:
        cwd = (
            config_path.parent.parent if config_path.parent.name == ".forge" else config_path.parent
        )

    specs = load_hooks(config_path).get(event, [])
    matching = [s for s in specs if _matches(s, target)]

    results: list[HookResult] = []
    for spec in matching:
        result = await _run_one(spec, payload, cwd)
        results.append(result)
        if result.blocked:
            logger.info("hook %s/%r blocked operation: %s", event, spec.matcher, result.reason)
            break
    return results


def has_blocking_result(results: Sequence[HookResult]) -> HookResult | None:
    """Return the first blocking result, or None. Convenience for callers."""
    for r in results:
        if r.blocked:
            return r
    return None
