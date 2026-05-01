"""Tests for generator.py context-window budgeting (Phase 1 Week 3)."""

from __future__ import annotations

import pytest

from daemon.agents.generator import _build_prompt, _estimate_tokens, _truncate_to_budget
from daemon.models import SprintContract


def test_estimate_tokens_chars_per_4():
    assert _estimate_tokens("a" * 400) == 100
    assert _estimate_tokens("") == 1  # always at least 1


def test_truncate_to_budget_no_op_when_short():
    text = "hi"
    assert _truncate_to_budget(text, max_tokens=100) == "hi"


def test_truncate_to_budget_adds_marker():
    text = "x" * 1000
    truncated = _truncate_to_budget(text, max_tokens=10)
    # 10 tokens × 4 chars ≈ 40 chars + marker
    assert "truncated" in truncated
    assert len(truncated) < len(text)


def test_build_prompt_includes_all_sections():
    sprint = SprintContract(
        description="Add /health endpoint",
        done_criteria=["Endpoint exists", "Returns 200"],
    )
    prompt = _build_prompt(sprint, memory_context="MEMORY", repomap="REPOMAP")
    assert "MEMORY" in prompt
    assert "REPOMAP" in prompt
    assert "Add /health endpoint" in prompt
    assert "Endpoint exists" in prompt
    assert "Returns 200" in prompt
    assert "Do not evaluate your own work" in prompt


def test_build_prompt_orders_stable_prefix_first():
    """Memory + repomap come BEFORE the variable task — for prompt caching."""
    sprint = SprintContract(description="X", done_criteria=["Y"])
    prompt = _build_prompt(sprint, memory_context="STABLE", repomap="REPOMAP")
    stable_idx = prompt.index("STABLE")
    repomap_idx = prompt.index("REPOMAP")
    task_idx = prompt.index("## Task")
    assert stable_idx < repomap_idx < task_idx


def test_build_prompt_appends_revision_feedback_at_end():
    """Revision feedback is the most-variable block; goes last to keep
    the cacheable prefix stable across attempts."""
    sprint = SprintContract(description="X", done_criteria=["Y"])
    prompt = _build_prompt(sprint, memory_context="M", revision_feedback="FIX_THIS")
    fix_idx = prompt.index("FIX_THIS")
    # Should appear after the criteria
    assert fix_idx > prompt.index("## Done criteria")
    assert "Revision feedback" in prompt


def test_build_prompt_omits_repomap_when_empty():
    sprint = SprintContract(description="X", done_criteria=["Y"])
    prompt = _build_prompt(sprint, memory_context="MEM", repomap="")
    assert "MEM" in prompt
    # Empty repomap doesn't add an empty block
    assert "## Repo:" not in prompt


def test_build_prompt_truncates_when_exceeding_window():
    """Generator with a large memory + small target window → trimmed."""
    sprint = SprintContract(description="X", done_criteria=["Y"], assigned_model="gpt-oss:20b")
    huge_memory = "M" * 200_000  # ~50K tokens
    prompt = _build_prompt(sprint, memory_context=huge_memory, target_model="gpt-oss:20b")
    # 32K window × 80% = ~25.6K input tokens × 4 chars/token = ~102.4K chars
    # The trimmed prompt should be far smaller than the input memory alone
    assert len(prompt) < len(huge_memory) + 5_000


def test_build_prompt_preserves_task_when_truncating():
    """Even when the prompt is huge, the actual task description survives
    truncation — that's the priority order: memory/repomap trimmed first."""
    sprint = SprintContract(
        description="UNIQUE_TASK_MARKER", done_criteria=["Y"], assigned_model="gpt-oss:20b"
    )
    huge_memory = "M" * 200_000
    prompt = _build_prompt(sprint, memory_context=huge_memory, target_model="gpt-oss:20b")
    assert "UNIQUE_TASK_MARKER" in prompt


def test_build_prompt_no_truncation_when_target_model_unspecified():
    """Without target_model, no window-based trimming happens."""
    sprint = SprintContract(description="X", done_criteria=["Y"])
    huge_memory = "M" * 200_000
    prompt = _build_prompt(sprint, memory_context=huge_memory)
    # Memory is preserved fully
    assert huge_memory in prompt


# ---- _select_executor dispatch ----


def test_select_executor_anthropic_to_claude_code():
    from daemon.agents.generator import _select_executor
    from daemon.executors import claude_code

    sprint = SprintContract(description="X", done_criteria=["Y"], assigned_model="claude-sonnet-4")
    assert _select_executor(sprint) is claude_code


def test_select_executor_legacy_alias_to_claude_code():
    """Legacy ``sonnet`` / ``opus`` / ``haiku`` aliases route to claude_code."""
    from daemon.agents.generator import _select_executor
    from daemon.executors import claude_code

    for alias in ("sonnet", "opus", "haiku"):
        sprint = SprintContract(description="X", done_criteria=["Y"], assigned_model=alias)
        assert _select_executor(sprint) is claude_code


def test_select_executor_open_weight_default_ollama(monkeypatch):
    from daemon.agents.generator import _select_executor
    from daemon.executors import ollama

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    sprint = SprintContract(description="X", done_criteria=["Y"], assigned_model="qwen3-coder-next")
    assert _select_executor(sprint) is ollama


def test_select_executor_with_openai_base_url(monkeypatch):
    from daemon.agents.generator import _select_executor
    from daemon.executors import openai_compatible

    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    sprint = SprintContract(description="X", done_criteria=["Y"], assigned_model="qwen3-coder-next")
    assert _select_executor(sprint) is openai_compatible


# ---- generate() integration ----


@pytest.mark.asyncio
async def test_generate_dispatches_to_correct_executor(monkeypatch):
    from daemon.agents import generator
    from daemon.models import ExecutionResult

    captured = {}

    async def fake_ollama_execute(prompt, model, **kwargs):
        captured["prompt"] = prompt
        captured["model"] = model
        captured["executor"] = "ollama"
        return ExecutionResult(success=True, output="done")

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(generator.ollama_executor, "execute", fake_ollama_execute)

    sprint = SprintContract(
        description="Task",
        done_criteria=["A"],
        assigned_model="qwen3-coder-next",
    )
    result = await generator.generate(sprint, memory_context="ctx", repomap="map")

    assert result.success
    assert captured["executor"] == "ollama"
    assert captured["model"] == "qwen3-coder-next"
    assert "ctx" in captured["prompt"]
    assert "map" in captured["prompt"]
    assert "Task" in captured["prompt"]


@pytest.mark.asyncio
async def test_generate_passes_revision_feedback(monkeypatch):
    from daemon.agents import generator
    from daemon.models import ExecutionResult

    captured = {}

    async def fake_execute(prompt, model, **kwargs):
        captured["prompt"] = prompt
        return ExecutionResult(success=True, output="done")

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(generator.ollama_executor, "execute", fake_execute)

    sprint = SprintContract(description="t", done_criteria=["A"], assigned_model="qwen3-coder-next")
    await generator.generate(sprint, memory_context="ctx", revision_feedback="UNIQUE_FEEDBACK")

    assert "UNIQUE_FEEDBACK" in captured["prompt"]
    assert "Revision feedback" in captured["prompt"]
