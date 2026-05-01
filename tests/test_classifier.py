"""Tests for classifier: heuristic, procedural lookup, LLM fallback."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from daemon.agents.classifier import classify, classify_sync, heuristic_classify
from daemon.db import ForgeDB

# --- Heuristic ---


def test_heuristic_low_typo():
    assert heuristic_classify("Fix typo in README") == "low"


def test_heuristic_low_lint():
    assert heuristic_classify("Fix lint warnings") == "low"


def test_heuristic_low_format():
    assert heuristic_classify("Format code with black") == "low"


def test_heuristic_low_changelog():
    assert heuristic_classify("Update changelog for release") == "low"


def test_heuristic_high_architect():
    assert heuristic_classify("Architect the new microservice system") == "high"


def test_heuristic_high_migration():
    assert heuristic_classify("Write database migration for users") == "high"


def test_heuristic_high_rewrite():
    assert heuristic_classify("Rewrite the payment service") == "high"


def test_heuristic_high_security_audit():
    assert heuristic_classify("Run security audit on auth") == "high"


def test_heuristic_ambiguous():
    assert heuristic_classify("Build a login endpoint") is None


def test_heuristic_case_insensitive():
    assert heuristic_classify("FIX TYPO in header") == "low"


# --- classify_sync ---


def test_sync_low():
    # ADR-003: cheap-tier generator is qwen3-coder-next via Ollama
    from daemon.config import LOCAL_CODE_MODEL

    c, m, a = classify_sync("Fix typo in README")
    assert c == "low"
    assert m == LOCAL_CODE_MODEL
    assert a == "ollama"


def test_sync_high():
    # ADR-003: premium tier is deepseek-v4-flash via Ollama (open-weight default)
    from daemon.config import LOCAL_PREMIUM_MODEL

    c, m, a = classify_sync("Architect distributed database schema")
    assert c == "high"
    assert m == LOCAL_PREMIUM_MODEL
    assert a == "ollama"


def test_sync_medium_default():
    # ADR-003: medium tier is qwen3.6:27b via Ollama
    from daemon.config import LOCAL_MID_MODEL

    c, m, a = classify_sync("Build a login endpoint")
    assert c == "medium"
    assert m == LOCAL_MID_MODEL
    assert a == "ollama"


# --- Async classify ---


@pytest.mark.asyncio
async def test_classify_heuristic_skips_llm():
    c, m, a = await classify("Fix typo in README")
    assert c == "low"


@pytest.mark.asyncio
async def test_classify_llm_low_score():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {"message": {"content": "2"}}

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        c, m, a = await classify("Build something ambiguous")
    assert c == "low"


@pytest.mark.asyncio
async def test_classify_llm_high_score():
    from daemon.config import LOCAL_PREMIUM_MODEL

    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {"message": {"content": "9"}}

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        c, m, a = await classify("Build something ambiguous")
    assert c == "high"
    assert m == LOCAL_PREMIUM_MODEL


@pytest.mark.asyncio
async def test_classify_llm_failure_defaults_medium():
    with patch("httpx.AsyncClient.post", side_effect=Exception("connection refused")):
        c, m, a = await classify("Build something")
    assert c == "medium"


@pytest.mark.asyncio
async def test_classify_procedural_override():
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))
        # Record successful pattern
        for _ in range(3):
            db.save_procedure("Fix login bug", "opus", "claude_code", True, 30.0)
        c, m, a = await classify("Fix login bug", db=db)
        assert m == "opus"
        db.close()


# --- Phase 1 Week 1: dynamic executor selection ---


def test_select_executor_anthropic_models_route_to_claude_code():
    from daemon.agents.classifier import select_executor

    assert select_executor("claude-sonnet-4") == "claude_code"
    assert select_executor("opus") == "claude_code"


def test_select_executor_open_weight_default_is_ollama(monkeypatch):
    """No OPENAI_BASE_URL → ollama for all open-weight models."""
    from daemon.agents.classifier import select_executor

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert select_executor("qwen3-coder-next") == "ollama"
    assert select_executor("devstral-small-2507") == "ollama"
    assert select_executor("gpt-oss:20b") == "ollama"


def test_select_executor_with_openai_base_url_routes_to_openai_compat(monkeypatch):
    """OPENAI_BASE_URL set → openai_compatible for non-Anthropic models."""
    from daemon.agents.classifier import select_executor

    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    assert select_executor("qwen3-coder-next") == "openai_compatible"
    assert select_executor("deepseek-v4-flash") == "openai_compatible"


def test_select_executor_anthropic_overrides_openai_base_url(monkeypatch):
    """Even with OPENAI_BASE_URL set, claude-* models still use claude_code
    (the user's `.claude/` setup is the source of truth for those)."""
    from daemon.agents.classifier import select_executor

    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    assert select_executor("claude-sonnet-4") == "claude_code"


def test_classify_sync_returns_correct_executor(monkeypatch):
    from daemon.agents.classifier import classify_sync

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    _, model, agent = classify_sync("Fix typo in README")
    assert agent == "ollama"  # qwen3-coder-next → ollama path
