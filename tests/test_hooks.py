"""Hooks system tests (Sprint 7.1).

Hooks are user-supplied scripts that fire at well-defined lifecycle
points (PreToolUse / PostToolUse / PreCompact / SubagentStop /
SessionStart). The contract is identical to Claude Code's so users
can drop existing hooks in unchanged.

Coverage:
  - hooks.toml load: empty / missing / malformed → empty + WARNING
  - matcher regex against tool_name
  - blocking behavior: structured {"action": "block"} OR non-zero exit
  - first-block-short-circuits the chain
  - timeout kills the subprocess and returns blocked
  - JSON-on-stdin / JSON-on-stdout round trip
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from daemon.hooks import (
    SUPPORTED_EVENTS,
    HookSpec,
    has_blocking_result,
    load_hooks,
    run_hooks,
)

# ---- HookSpec validation ----


def test_unknown_event_rejected() -> None:
    with pytest.raises(ValueError, match="unknown hook event"):
        HookSpec(event="bogus", matcher=".*", command=["echo"])


def test_empty_command_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        HookSpec(event="PreToolUse", matcher=".*", command=[])


def test_supported_events_match_brief() -> None:
    """The brief specifies five events. Any drift surfaces here."""
    assert set(SUPPORTED_EVENTS) == {
        "PreToolUse",
        "PostToolUse",
        "PreCompact",
        "SubagentStop",
        "SessionStart",
    }


# ---- load_hooks ----


def test_load_hooks_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_hooks(tmp_path / "nope.toml") == {}


def test_load_hooks_round_trip(tmp_path: Path) -> None:
    cfg = tmp_path / "hooks.toml"
    cfg.write_text(
        """
[[hooks.PreToolUse]]
matcher = "Bash"
command = ["python", "check.py"]
timeout = 5

[[hooks.PostToolUse]]
matcher = "Edit|Write"
command = ["pre-commit", "run"]
timeout = 60
"""
    )
    out = load_hooks(cfg)
    assert len(out["PreToolUse"]) == 1
    assert out["PreToolUse"][0].matcher == "Bash"
    assert out["PreToolUse"][0].command == ["python", "check.py"]
    assert out["PreToolUse"][0].timeout == 5
    assert len(out["PostToolUse"]) == 1


def test_load_hooks_skips_malformed_rows(tmp_path: Path, caplog) -> None:
    """A bad row doesn't break the others."""
    import logging

    cfg = tmp_path / "hooks.toml"
    cfg.write_text(
        """
[[hooks.PreToolUse]]
matcher = "ok"
command = ["echo"]

[[hooks.PreToolUse]]
matcher = "bad"
command = []
"""
    )
    with caplog.at_level(logging.WARNING, logger="daemon.hooks"):
        out = load_hooks(cfg)
    # The empty-command row was skipped; the valid one survived.
    assert len(out["PreToolUse"]) == 1
    assert out["PreToolUse"][0].matcher == "ok"
    assert any("skipping bad" in rec.message for rec in caplog.records)


def test_load_hooks_invalid_toml_treated_as_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "hooks.toml"
    cfg.write_text("this is not valid TOML [[[")
    assert load_hooks(cfg) == {}


# ---- run_hooks: matching + blocking ----


def _make_hooks_config(tmp_path: Path, content: str) -> Path:
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    cfg = forge_dir / "hooks.toml"
    cfg.write_text(content)
    return cfg


@pytest.mark.asyncio
async def test_run_hooks_no_match_returns_empty(tmp_path: Path) -> None:
    cfg = _make_hooks_config(
        tmp_path,
        f"""
[[hooks.PreToolUse]]
matcher = "Bash"
command = [{sys.executable!r}, "-c", "print('{{}}')"]
""",
    )
    results = await run_hooks(
        "PreToolUse",
        {"tool_name": "Edit"},
        config_path=cfg,
        target="Edit",
    )
    # Bash matcher doesn't match Edit → no hook ran
    assert results == []


@pytest.mark.asyncio
async def test_run_hooks_allow_path(tmp_path: Path) -> None:
    """A hook that exits 0 with no JSON on stdout is treated as allow."""
    cfg = _make_hooks_config(
        tmp_path,
        f"""
[[hooks.PreToolUse]]
matcher = ".*"
command = [{sys.executable!r}, "-c", "import sys; sys.stdin.read(); print('ok')"]
""",
    )
    results = await run_hooks(
        "PreToolUse",
        {"tool_name": "Bash"},
        config_path=cfg,
        target="Bash",
    )
    assert len(results) == 1
    assert results[0].action == "allow"
    assert results[0].blocked is False
    assert "ok" in results[0].stdout


@pytest.mark.asyncio
async def test_run_hooks_block_via_structured_response(tmp_path: Path) -> None:
    """A hook that prints {"action": "block", "reason": "..."} blocks."""
    cfg = _make_hooks_config(
        tmp_path,
        f"""
[[hooks.PreToolUse]]
matcher = ".*"
command = [{sys.executable!r}, "-c", "import sys, json; sys.stdin.read(); print(json.dumps({{'action': 'block', 'reason': 'rm -rf /'}}))"]
""",
    )
    results = await run_hooks(
        "PreToolUse",
        {"tool_name": "Bash"},
        config_path=cfg,
        target="Bash",
    )
    assert len(results) == 1
    assert results[0].action == "block"
    assert results[0].blocked is True
    assert "rm -rf /" in results[0].reason


@pytest.mark.asyncio
async def test_run_hooks_block_via_nonzero_exit(tmp_path: Path) -> None:
    """No JSON on stdout but exit code != 0 → blocked."""
    cfg = _make_hooks_config(
        tmp_path,
        f"""
[[hooks.PreToolUse]]
matcher = ".*"
command = [{sys.executable!r}, "-c", "import sys; sys.stdin.read(); sys.exit(7)"]
""",
    )
    results = await run_hooks(
        "PreToolUse",
        {"tool_name": "Bash"},
        config_path=cfg,
        target="Bash",
    )
    assert len(results) == 1
    assert results[0].blocked is True
    assert results[0].exit_code == 7


@pytest.mark.asyncio
async def test_run_hooks_first_block_short_circuits(tmp_path: Path) -> None:
    """Hooks run sequentially; first block stops the chain."""
    cfg = _make_hooks_config(
        tmp_path,
        f"""
[[hooks.PreToolUse]]
matcher = ".*"
command = [{sys.executable!r}, "-c", "import sys; sys.stdin.read(); sys.exit(1)"]

[[hooks.PreToolUse]]
matcher = ".*"
command = [{sys.executable!r}, "-c", "import sys; sys.stdin.read(); print('SHOULD NOT RUN'); open('marker.txt', 'w').write('ran')"]
""",
    )
    results = await run_hooks(
        "PreToolUse",
        {"tool_name": "Bash"},
        config_path=cfg,
        target="Bash",
    )
    # Only the first hook ran
    assert len(results) == 1
    assert results[0].blocked is True
    # The second hook's marker never got written
    assert not (cfg.parent / "marker.txt").is_file()


@pytest.mark.asyncio
async def test_run_hooks_timeout_kills_subprocess(tmp_path: Path) -> None:
    cfg = _make_hooks_config(
        tmp_path,
        f"""
[[hooks.PreToolUse]]
matcher = ".*"
command = [{sys.executable!r}, "-c", "import time; time.sleep(60)"]
timeout = 1
""",
    )
    results = await run_hooks(
        "PreToolUse",
        {"tool_name": "Bash"},
        config_path=cfg,
        target="Bash",
    )
    assert len(results) == 1
    assert results[0].timed_out is True
    assert results[0].blocked is True


@pytest.mark.asyncio
async def test_run_hooks_payload_reaches_stdin(tmp_path: Path) -> None:
    """The JSON payload makes it to the hook's stdin verbatim — this is
    the contract that lets users drop in Claude Code hooks."""
    out_path = tmp_path / "received.json"
    cfg = _make_hooks_config(
        tmp_path,
        f"""
[[hooks.PreToolUse]]
matcher = ".*"
command = [{sys.executable!r}, "-c", "import sys; open({str(out_path)!r}, 'w').write(sys.stdin.read())"]
""",
    )
    payload = {"tool_name": "Bash", "tool_args": {"cmd": "ls"}, "session_id": "s-1"}
    await run_hooks(
        "PreToolUse",
        payload,
        config_path=cfg,
        target="Bash",
    )
    received = json.loads(out_path.read_text())
    assert received == payload


@pytest.mark.asyncio
async def test_run_hooks_command_not_found_is_blocking(tmp_path: Path) -> None:
    cfg = _make_hooks_config(
        tmp_path,
        """
[[hooks.PreToolUse]]
matcher = ".*"
command = ["this-binary-does-not-exist-anywhere"]
""",
    )
    results = await run_hooks(
        "PreToolUse",
        {"tool_name": "Bash"},
        config_path=cfg,
        target="Bash",
    )
    assert len(results) == 1
    assert results[0].blocked is True
    assert "not found" in results[0].reason


@pytest.mark.asyncio
async def test_run_hooks_unknown_event_raises() -> None:
    with pytest.raises(ValueError, match="unknown hook event"):
        await run_hooks("Frobnicate", {}, target="x")


# ---- has_blocking_result helper ----


@pytest.mark.asyncio
async def test_has_blocking_result_returns_first(tmp_path: Path) -> None:
    cfg = _make_hooks_config(
        tmp_path,
        f"""
[[hooks.PreToolUse]]
matcher = ".*"
command = [{sys.executable!r}, "-c", "import sys; sys.stdin.read(); sys.exit(3)"]
""",
    )
    results = await run_hooks(
        "PreToolUse",
        {"tool_name": "Bash"},
        config_path=cfg,
        target="Bash",
    )
    blocker = has_blocking_result(results)
    assert blocker is not None
    assert blocker.exit_code == 3


def test_has_blocking_result_none_for_all_allow() -> None:
    from daemon.hooks import HookResult

    results = [HookResult(action="allow"), HookResult(action="allow")]
    assert has_blocking_result(results) is None
