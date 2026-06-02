"""Auto-compaction: summarize context when it would overflow (context extension)."""

from __future__ import annotations

import pytest

from daemon import compaction


class TestShouldCompact:
    def test_under_threshold(self):
        assert compaction.should_compact(used=100, cap=1000) is False

    def test_over_threshold(self):
        assert compaction.should_compact(used=850, cap=1000, threshold=0.8) is True

    def test_zero_cap_is_safe(self):
        assert compaction.should_compact(used=100, cap=0) is False


class TestCompactText:
    @pytest.mark.asyncio
    async def test_short_text_unchanged(self):
        async def summarizer(text, target):
            raise AssertionError("should not summarize short text")

        out = await compaction.compact_text("tiny", target_tokens=1000, summarizer=summarizer)
        assert out == "tiny"

    @pytest.mark.asyncio
    async def test_long_text_summarized(self):
        async def summarizer(text, target):
            return "SUMMARY"

        long = "word " * 5000  # ~6k tokens
        out = await compaction.compact_text(long, target_tokens=200, summarizer=summarizer)
        assert out == "SUMMARY"

    @pytest.mark.asyncio
    async def test_summarizer_failure_falls_back_to_truncation(self):
        async def summarizer(text, target):
            raise RuntimeError("model down")

        long = "abcde " * 5000
        out = await compaction.compact_text(long, target_tokens=100, summarizer=summarizer)
        # Did not raise; truncated to roughly the budget with a marker.
        assert len(out) < len(long)
        assert "truncated" in out.lower()

    @pytest.mark.asyncio
    async def test_summary_too_long_falls_back(self):
        async def summarizer(text, target):
            return "still enormous " * 5000  # ignores the budget

        long = "x " * 5000
        out = await compaction.compact_text(long, target_tokens=100, summarizer=summarizer)
        assert "truncated" in out.lower()  # rejected the over-budget summary


class TestSchedulerIntegration:
    @pytest.mark.asyncio
    async def test_large_context_triggers_compaction(self, tmp_db, monkeypatch):
        # Inflate the attachment store so the assembled memory exceeds budget,
        # then verify the scheduler invokes the summarizer during a sprint.
        from daemon import attachments, compaction, scheduler
        from daemon.budget import BudgetController
        from daemon.memory.episodic import EpisodicStore
        from daemon.memory.retriever import Retriever
        from daemon.models import EvaluatorResult, ExecutionResult, ProjectContext, SprintContract

        attachments.get_store().clear()
        # ~16k tokens of attachment content → well over the 3000 budget.
        big = "lorem ipsum dolor sit amet " * 2500
        store = attachments.get_store()
        from daemon.attachments import Attachment

        store._items["/x/big.txt"] = Attachment("big.txt", "/x/big.txt", big, len(big) // 4)

        called = {"n": 0}

        async def fake_summarizer(text, target):
            called["n"] += 1
            return "COMPACTED CONTEXT"

        monkeypatch.setattr(compaction, "ollama_summarizer", fake_summarizer)

        captured = {}

        async def fake_generate(sprint, memory_context="", **kwargs):
            captured["memory"] = memory_context
            return ExecutionResult(success=True, output="ok")

        async def fake_diff(p):
            return "d"

        async def fake_eval(s, d, c):
            return EvaluatorResult(verdict="APPROVED")

        async def fake_create(sid):
            return "/tmp/wt"

        monkeypatch.setattr(scheduler.generator, "generate", fake_generate)
        monkeypatch.setattr(scheduler.worktree, "get_diff", fake_diff)
        monkeypatch.setattr(scheduler.evaluator, "evaluate", fake_eval)
        monkeypatch.setattr(scheduler.worktree, "create", fake_create)

        sprint = SprintContract(
            id="sprint-cmp",
            session_id="s",
            description="big context task",
            done_criteria=["x"],
            assigned_model="qwen2.5-coder:7b",
        )
        await scheduler.execute_sprint(
            sprint,
            ProjectContext(path="."),
            "s",
            tmp_db,
            BudgetController(budget_usd=100.0),
            Retriever(tmp_db),
            EpisodicStore(tmp_db),
        )
        attachments.get_store().clear()

        assert called["n"] == 1  # compaction summarizer fired
        assert "COMPACTED CONTEXT" in captured["memory"]
