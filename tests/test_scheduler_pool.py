"""M2 — scheduler wires the model pool around generation.

Proves that a generator leased through the pool is reflected as resident while
it runs, and that pool_state is pushed to the broadcast sink so the UI RAM
meter is live. Generator/evaluator/worktree are mocked so no models actually
load.
"""

from __future__ import annotations

import pytest

from daemon import scheduler
from daemon.models import EvaluatorResult, ExecutionResult, ProjectContext, SprintContract
from daemon.pool import ModelPool


def _sprint(model="qwen3-coder-next"):
    return SprintContract(
        id="sprint-pooltest",
        session_id="sess-pooltest",
        description="add a function",
        done_criteria=["it works"],
        assigned_model=model,
    )


class TestSchedulerPoolWiring:
    @pytest.mark.asyncio
    async def test_generator_model_is_resident_during_generation(self, monkeypatch):
        pool = ModelPool(budget_gb=40.0)
        seen_resident: list[bool] = []

        async def fake_generate(sprint, **kwargs):
            # While the generator runs, its model must be resident in the pool.
            seen_resident.append(pool.is_resident(sprint.assigned_model))
            return ExecutionResult(success=True, output="done")

        async def fake_get_diff(path):
            return "diff --git a b"

        async def fake_evaluate(sprint, diff, ctx):
            return EvaluatorResult(verdict="APPROVED", feedback="ok")

        monkeypatch.setattr(scheduler.generator, "generate", fake_generate)
        monkeypatch.setattr(scheduler.worktree, "get_diff", fake_get_diff)
        monkeypatch.setattr(scheduler.evaluator, "evaluate", fake_evaluate)

        gen, ev = await scheduler._run_one_attempt(
            _sprint(), ProjectContext(path="."), "/tmp/wt", "", "", pool=pool
        )
        assert gen.success
        assert ev.verdict == "APPROVED"
        assert seen_resident == [True]

    @pytest.mark.asyncio
    async def test_pool_emits_state_on_change(self):
        events: list[dict] = []
        pool = ModelPool(budget_gb=40.0, on_change=events.append)
        async with pool.lease("qwen3-coder-next", size_gb=9.0):
            pass
        assert any(e["type"] == "pool_state" for e in events)

    @pytest.mark.asyncio
    async def test_no_pool_still_runs(self, monkeypatch):
        # Backwards-compat: direct callers that pass no pool keep working.
        async def fake_generate(sprint, **kwargs):
            return ExecutionResult(success=True, output="done")

        async def fake_get_diff(path):
            return "d"

        async def fake_evaluate(sprint, diff, ctx):
            return EvaluatorResult(verdict="APPROVED")

        monkeypatch.setattr(scheduler.generator, "generate", fake_generate)
        monkeypatch.setattr(scheduler.worktree, "get_diff", fake_get_diff)
        monkeypatch.setattr(scheduler.evaluator, "evaluate", fake_evaluate)

        gen, ev = await scheduler._run_one_attempt(
            _sprint(), ProjectContext(path="."), "/tmp/wt", "", "", pool=None
        )
        assert gen.success
