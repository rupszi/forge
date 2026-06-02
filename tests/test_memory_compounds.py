"""M3 integration — memory compounds: relevant KB context cuts revisions.

This proves the *wiring* (retrieve → inject → reinforce → fewer revisions), not
LLM quality. A stub evaluator approves on the first attempt iff the relevant
gotcha reached the generator's memory context; otherwise it forces one revision.
With the KB seeded, the sprint should need fewer revisions and the injected
item's confidence should rise.
"""

from __future__ import annotations

import pytest

from daemon import scheduler
from daemon.budget import BudgetController
from daemon.memory.episodic import EpisodicStore
from daemon.memory.knowledge import KnowledgeBase
from daemon.memory.retriever import Retriever
from daemon.models import EvaluatorResult, ExecutionResult, ProjectContext, SprintContract

MAGIC = "service_role"


def _sprint():
    return SprintContract(
        id="sprint-mem01",
        session_id="sess-mem01",
        description="write a supabase RLS policy and test it with service_role",
        done_criteria=["RLS policy applied", "tested with service_role key"],
        assigned_model="qwen3-coder-next",
    )


@pytest.fixture
def stub_runtime(monkeypatch):
    """Generator echoes the memory context; evaluator approves iff it saw the
    magic gotcha, else REVISEs. Worktree is a no-op."""
    seen = {"memory": ""}

    async def fake_generate(sprint, memory_context="", **kwargs):
        seen["memory"] = memory_context
        return ExecutionResult(success=True, output="patch")

    async def fake_get_diff(path):
        return "diff"

    async def fake_evaluate(sprint, diff, ctx):
        if MAGIC in seen["memory"]:
            return EvaluatorResult(verdict="APPROVED", feedback="used service_role")
        return EvaluatorResult(verdict="REVISE", feedback="must test with service_role key")

    async def fake_create(sid):
        return "/tmp/wt"

    async def fake_remove(sid):
        return None

    monkeypatch.setattr(scheduler.generator, "generate", fake_generate)
    monkeypatch.setattr(scheduler.worktree, "get_diff", fake_get_diff)
    monkeypatch.setattr(scheduler.evaluator, "evaluate", fake_evaluate)
    monkeypatch.setattr(scheduler.worktree, "create", fake_create)
    monkeypatch.setattr(scheduler.worktree, "remove", fake_remove)
    return seen


async def _run(tmp_db):
    sprint = _sprint()
    return await scheduler.execute_sprint(
        sprint,
        ProjectContext(path="."),
        "sess-mem01",
        tmp_db,
        BudgetController(budget_usd=100.0),
        Retriever(tmp_db),
        EpisodicStore(tmp_db),
    )


class TestMemoryCompounds:
    @pytest.mark.asyncio
    async def test_cold_kb_needs_revision(self, tmp_db, stub_runtime):
        # No KB → the gotcha isn't injected → evaluator forces revisions.
        result = await _run(tmp_db)
        assert result.revision_count >= 1

    @pytest.mark.asyncio
    async def test_warm_kb_approves_first_attempt(self, tmp_db, stub_runtime):
        kb = KnowledgeBase(tmp_db)
        kid = kb.add("gotcha", "supabase", "supabase RLS must be tested with the service_role key")
        before = next(i for i in kb.get_all() if i["id"] == kid)["confidence"]

        result = await _run(tmp_db)

        assert result.status == "completed"
        assert result.revision_count == 0  # approved first attempt
        # The injected item was reinforced upward (M3 confidence loop).
        after = next(i for i in kb.get_all() if i["id"] == kid)["confidence"]
        assert after > before
