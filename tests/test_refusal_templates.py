"""Refusal template tests (Sprint 7.10).

Refusal text is shaped like Claude Code's tool-result-error responses
so models trained on Claude tool traces recognize the format and plan
recovery rather than retrying blindly.
"""

from __future__ import annotations

from daemon.hooks import HookResult
from daemon.refusal import (
    from_capability_violation,
    from_destructive_op,
    from_hook_block,
    from_skill_tampered,
)
from daemon.safety import DestructiveOp

# ---- destructive-op refusals ----


def test_destructive_op_includes_rule_fields() -> None:
    op = DestructiveOp(
        pattern=r"\brm\s+-rf\s+/",
        severity="block",
        reason="rm -rf / — catastrophic",
    )
    text = from_destructive_op(op)
    assert "rm -rf" in text
    assert "catastrophic" in text
    assert "block" in text
    assert "bypass mode" in text


def test_destructive_op_text_is_stable() -> None:
    """Same op → same text. Lets prompt caches stay warm across revisions."""
    op = DestructiveOp(pattern="x", severity="warn", reason="y")
    assert from_destructive_op(op) == from_destructive_op(op)


def test_destructive_op_includes_recovery_hint() -> None:
    op = DestructiveOp(pattern="x", severity="block", reason="y")
    text = from_destructive_op(op)
    # The agent needs to know: don't retry, take a different action.
    assert "Do not retry" in text


# ---- hook refusals ----


def test_hook_block_round_trip() -> None:
    result = HookResult(
        action="block",
        reason="pre-commit found lint errors",
        exit_code=1,
    )
    text = from_hook_block(result, hook_event="PostToolUse")
    assert "PostToolUse" in text
    assert "pre-commit found lint errors" in text
    assert "exit_code: 1" in text


def test_hook_block_default_event_is_pretooluse() -> None:
    text = from_hook_block(HookResult(action="block", reason="x"))
    assert "PreToolUse" in text


def test_hook_block_includes_extra_keys() -> None:
    """Extra fields from the hook's stdout JSON ({"detail": "..."}) get
    rendered as labeled lines so the agent sees them."""
    result = HookResult(
        action="block",
        reason="security check failed",
        extra={"file": "auth.py", "rule": "no-eval"},
        exit_code=2,
    )
    text = from_hook_block(result)
    assert "file: auth.py" in text
    assert "rule: no-eval" in text


def test_hook_block_no_reason_fallback() -> None:
    """A hook that exits non-zero with no message still produces useful output."""
    result = HookResult(action="block", reason="", exit_code=3)
    text = from_hook_block(result)
    assert "no reason provided" in text


def test_hook_block_addresses_bypass_misconception() -> None:
    """A common model failure mode is 'switch to bypass mode' as the
    recovery — but bypass does NOT skip hooks. The refusal must say so."""
    result = HookResult(action="block", reason="x")
    text = from_hook_block(result)
    assert "bypass mode does NOT skip user hooks" in text


# ---- capability-violation refusals ----


def test_capability_violation_lists_host_and_allowlist() -> None:
    text = from_capability_violation("evil.com", ["api.github.com", "*.openai.com"])
    assert "evil.com" in text
    assert "api.github.com" in text
    assert "*.openai.com" in text
    # Recovery hint
    assert "manifest" in text


def test_capability_violation_empty_allowlist() -> None:
    text = from_capability_violation("evil.com", [])
    assert "deny-all" in text


# ---- skill-tampered refusals ----


def test_skill_tampered_truncates_long_hashes() -> None:
    text = from_skill_tampered(
        "skill",
        "csv-cleaner",
        expected="a" * 64,
        got="b" * 64,
    )
    assert "csv-cleaner" in text
    # Hashes truncated for readability — full 64 chars would clutter the output
    assert "aaaaaaaaaaaaaaaa" in text  # 16-char prefix
    assert "a" * 64 not in text  # but not the full string
    assert "forge connectors add" in text


def test_skill_tampered_names_kind() -> None:
    text = from_skill_tampered("connector", "github", expected="a" * 64, got="b" * 64)
    assert "connector:github" in text
