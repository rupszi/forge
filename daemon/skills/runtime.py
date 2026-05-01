"""Skill / connector / LLM-adapter sandbox runtime.

Implements layers 1, 4, 5 of the seven-layer security model from
docs/SKILLS.md. Layers 2 (capability declaration) and 3 (signed manifests)
live in ``registry.py``; layers 6 (egress filter) and 7 (audit log) live
in ``daemon/skills/audit.py`` and the network-shim helper.

This module is the single entry point for invoking ANY plugin (skill,
connector, LLM adapter) — the security model is identical, only the API
surface differs.

Threat-model alignment: subprocess isolation prevents shared-interpreter
exploits; resource limits cap fork bombs and OOM; path scoping prevents
escape via symlink traversal. See docs/SECURITY_AUDIT.md §7 (Sandbox
escape).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from ..redact import filtered_subprocess_env

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """Result of a sandboxed plugin invocation."""

    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_seconds: float = 0.0
    error: str | None = None
    capability_violations: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.capability_violations is None:
            self.capability_violations = []


async def run_skill(
    skill_path: Path,
    entry_script: str,
    args: list[str],
    *,
    secrets_allowed: list[str],
    network_allowlist: list[str],
    fs_writable: list[str],
    cpu_seconds: int = 60,
    wall_seconds: int = 120,
    memory_mb: int = 1024,
    cwd: Path | None = None,
) -> SandboxResult:
    """Run a skill / connector / LLM-adapter entry script in a sandbox.

    Layer 1 — Subprocess isolation: spawned via asyncio.create_subprocess_exec
    with an argument list (never a shell string).

    Layer 4 — Path scoping: cwd is the worktree (or skill sandbox dir).
    The script inherits a filtered env (Layer 2 of the redaction
    discipline) so unrelated AWS / GH PAT vars don't leak.

    Layer 5 — Resource limits: applied via preexec_fn on POSIX. On
    Windows the limits are best-effort (Job Objects would be the right
    answer; not implemented here yet).

    Network allow-list (Layer 6) is enforced inside the spawned script
    via the ``forge_plugin_api`` shim httpx client — the runtime exports
    ``FORGE_NETWORK_ALLOWLIST`` env so the shim can read it.

    The append-only audit log (Layer 7) is written by the caller after
    this returns.
    """
    start = time.time()

    # Filter env: only secrets the manifest declared, plus runtime flags.
    extra_env = {
        # The shim httpx client reads this and refuses non-allowlisted hosts
        "FORGE_NETWORK_ALLOWLIST": ",".join(network_allowlist),
        # The path scoper reads this
        "FORGE_FS_WRITABLE": ":".join(fs_writable),
        # Identifier for audit log correlation
        "FORGE_INVOCATION_ID": os.urandom(8).hex(),
    }
    env = filtered_subprocess_env(extra_keys=set(secrets_allowed))
    env.update(extra_env)

    script_path = skill_path / entry_script
    if not script_path.is_file():
        return SandboxResult(
            ok=False,
            error=f"entry script not found: {entry_script}",
            duration_seconds=time.time() - start,
        )

    # Determine interpreter — Python scripts get python3; binary scripts
    # are invoked directly (must be in [exec] capability — caller validated).
    if entry_script.endswith(".py"):
        cmd = ["python3", str(script_path), *args]
    else:
        cmd = [str(script_path), *args]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd or skill_path),
            env=env,
            preexec_fn=_make_resource_limiter(cpu_seconds, memory_mb),
        )
    except FileNotFoundError as e:
        return SandboxResult(
            ok=False,
            error=f"interpreter not found: {e}",
            duration_seconds=time.time() - start,
        )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=wall_seconds)
    except asyncio.TimeoutError:
        # Layer 5 enforcement at the wall-clock boundary. Per Task 2.4
        # discipline (kill on timeout), we kill the subprocess so it
        # doesn't linger as a zombie.
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return SandboxResult(
            ok=False,
            error=f"wall-clock timeout after {wall_seconds}s; killed",
            duration_seconds=time.time() - start,
        )

    return SandboxResult(
        ok=(proc.returncode == 0),
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
        exit_code=proc.returncode if proc.returncode is not None else -1,
        duration_seconds=time.time() - start,
    )


def _make_resource_limiter(cpu_seconds: int, memory_mb: int):
    """Build a preexec_fn that applies POSIX rlimit constraints.

    On systems without ``resource`` (Windows), returns None — the limits
    silently don't apply. Document this in SKILLS.md "Roadmap".
    """
    try:
        import resource
    except ImportError:
        return None

    def apply():
        try:
            # Memory: hard cap at memory_mb
            limit_bytes = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
            # CPU time
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            # File size: 100 MB max output per file
            fsize = 100 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            # No core dumps
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            # Cap on number of child processes (anti fork-bomb)
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (50, 50))
            except (ValueError, OSError):
                # macOS doesn't support per-user RLIMIT_NPROC reliably; skip
                pass
        except (ValueError, OSError) as e:
            # We're in a forked child here; can only write to stderr.
            # Using os.write avoids the T201 lint rule that bans `print`
            # and works without re-importing the logging module mid-fork.
            import sys

            sys.stderr.write(f"[skill-runtime] resource limit setup failed: {e}\n")

    return apply
