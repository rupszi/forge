"""Tests for reviewer: perspective parsing, synthesis, defaults."""

from unittest.mock import patch

import pytest

from daemon.agents.reviewer import (
    DEFAULT_PERSPECTIVES,
    PERSPECTIVES,
    _build_review_prompt,
    _parse_perspective_result,
    review,
)
from daemon.models import ExecutionResult

# --- Parsing ---


def test_parse_pass_verdict():
    output = "Code looks clean.\n\nVERDICT: PASS"
    result = _parse_perspective_result(output, "security")
    assert result.verdict == "PASS"
    assert result.name == "security"


def test_parse_fail_verdict():
    output = "- ISSUE: SQL injection in login handler\n- SUGGESTION: Use parameterized queries\n\nVERDICT: FAIL"
    result = _parse_perspective_result(output, "security")
    assert result.verdict == "FAIL"
    assert len(result.issues) == 1
    assert "SQL injection" in result.issues[0]
    assert len(result.suggestions) == 1


def test_parse_multiple_issues():
    output = """
- ISSUE: Missing input validation
- ISSUE: No rate limiting
- SUGGESTION: Add zod validation
- SUGGESTION: Add rate limiter middleware
VERDICT: FAIL
"""
    result = _parse_perspective_result(output, "security")
    assert len(result.issues) == 2
    assert len(result.suggestions) == 2


def test_parse_no_verdict_defaults_pass():
    output = "Everything looks fine."
    result = _parse_perspective_result(output, "performance")
    assert result.verdict == "PASS"


# --- Prompt building ---


def test_build_prompt_includes_system():
    config = PERSPECTIVES["security"]
    prompt = _build_review_prompt(config, "diff here", "some context")
    assert "security" in prompt.lower()
    assert "diff here" in prompt
    assert "some context" in prompt


def test_build_prompt_truncates_diff():
    config = PERSPECTIVES["performance"]
    long_diff = "x" * 20000
    prompt = _build_review_prompt(config, long_diff)
    assert len(prompt) < 15000  # diff capped at 8000


# --- Full review (mocked) ---


@pytest.mark.asyncio
async def test_review_all_pass():
    mock_result = ExecutionResult(success=True, output="All clean.\n\nVERDICT: PASS")
    with patch("daemon.executors.ollama.execute", return_value=mock_result):
        with patch("daemon.executors.claude_code.execute", return_value=mock_result):
            result = await review("some diff", perspectives=["security", "maintainability"])

    assert result.overall_verdict == "PASS"
    assert len(result.perspectives) == 2
    assert len(result.critical_issues) == 0


@pytest.mark.asyncio
async def test_review_multiple_fails():
    mock_fail = ExecutionResult(success=True, output="- ISSUE: Bad code\nVERDICT: FAIL")
    with patch("daemon.executors.ollama.execute", return_value=mock_fail):
        with patch("daemon.executors.claude_code.execute", return_value=mock_fail):
            result = await review("diff", perspectives=["security", "correctness"])

    assert result.overall_verdict == "FAIL"


@pytest.mark.asyncio
async def test_review_default_perspectives():
    mock_result = ExecutionResult(success=True, output="OK\nVERDICT: PASS")
    with patch("daemon.executors.ollama.execute", return_value=mock_result):
        with patch("daemon.executors.claude_code.execute", return_value=mock_result):
            result = await review("diff")

    assert len(result.perspectives) == len(DEFAULT_PERSPECTIVES)


@pytest.mark.asyncio
async def test_review_critical_issues_flagged_by_multiple():
    mock_sec = ExecutionResult(success=True, output="- ISSUE: XSS vulnerability\nVERDICT: FAIL")
    mock_cor = ExecutionResult(success=True, output="- ISSUE: XSS vulnerability\nVERDICT: FAIL")
    mock_maint = ExecutionResult(success=True, output="OK\nVERDICT: PASS")

    async def mock_exec(prompt, model=None):
        return mock_sec

    with patch("daemon.executors.ollama.execute", return_value=mock_maint):
        with patch("daemon.executors.claude_code.execute", side_effect=[mock_sec, mock_cor]):
            result = await review("diff", perspectives=["security", "correctness"])

    assert "XSS vulnerability" in result.critical_issues


@pytest.mark.asyncio
async def test_review_invalid_perspective_ignored():
    mock_result = ExecutionResult(success=True, output="OK\nVERDICT: PASS")
    with patch("daemon.executors.ollama.execute", return_value=mock_result):
        with patch("daemon.executors.claude_code.execute", return_value=mock_result):
            result = await review("diff", perspectives=["nonexistent", "security"])

    # Should only run security (nonexistent filtered out)
    perspective_names = [p.name for p in result.perspectives]
    assert "security" in perspective_names
    assert "nonexistent" not in perspective_names
