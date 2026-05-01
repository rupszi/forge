"""Tests for daemon/memory/episodic.py — primarily that the recorded
agent_type matches what the rest of the system would dispatch through
(via classifier.select_executor)."""

from __future__ import annotations

import os
import tempfile

import pytest

from daemon.db import ForgeDB
from daemon.memory.episodic import EpisodicStore
from daemon.models import EvaluatorResult, ExecutionResult, SprintContract


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "forge.db"))
        yield db
        db.close()


def test_store_uses_correct_agent_type_for_each_model_family(tmp_db, monkeypatch):
    """Episode agent_type matches what classifier.select_executor returns
    across every model family Forge currently dispatches to.

    Regression: prior to Task 1.2 the store had a hardcoded check
    ``in ("opus", "sonnet")``, which mislabeled haiku, every full-name
    Claude (claude-sonnet-4-7, …), and every open-weight model
    (qwen, devstral, deepseek, gpt-oss) inconsistently. select_executor
    now drives the decision so all surfaces stay aligned.
    """
    # Ensure OPENAI_BASE_URL is unset so non-Anthropic models route to
    # ollama (matches the test's "expected" column).
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    episodic = EpisodicStore(tmp_db)
    cases = [
        ("claude-sonnet-4-7", "claude_code"),
        ("opus", "claude_code"),
        ("haiku", "claude_code"),  # was previously mislabeled "ollama"
        ("qwen3-coder-next", "ollama"),
        ("devstral-small-2507", "ollama"),
        ("gpt-oss:20b", "ollama"),
    ]
    for model, expected_agent in cases:
        sprint = SprintContract(
            id=f"sp-{model}",
            session_id="sess-1",
            description=f"test for {model}",
            done_criteria=["x"],
            assigned_model=model,
        )
        episodic.store(
            "sess-1",
            sprint,
            ExecutionResult(success=True),
            EvaluatorResult(verdict="APPROVED"),
        )
        eps = tmp_db.get_episodes_for_session("sess-1")
        matching = [e for e in eps if e["sprint_id"] == sprint.id]
        assert matching, f"no episode for {model}"
        assert matching[0]["agent_type"] == expected_agent, (
            f"{model}: expected agent_type={expected_agent}, got {matching[0]['agent_type']}"
        )


def test_store_routes_to_openai_compatible_when_base_url_set(tmp_db, monkeypatch):
    """When OPENAI_BASE_URL is set, non-Anthropic models route through
    openai_compatible — episodic must record that, not "ollama"."""
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    episodic = EpisodicStore(tmp_db)
    sprint = SprintContract(
        id="sp-vllm",
        session_id="sess-vllm",
        description="vllm-routed task",
        done_criteria=["x"],
        assigned_model="qwen3-coder-next",
    )
    episodic.store("sess-vllm", sprint, ExecutionResult(success=True), None)

    eps = tmp_db.get_episodes_for_session("sess-vllm")
    assert eps and eps[0]["agent_type"] == "openai_compatible"
