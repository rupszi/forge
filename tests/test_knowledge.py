"""Tests for knowledge base and episodic store."""

import os
import tempfile

import pytest

from daemon.db import ForgeDB
from daemon.memory.episodic import EpisodicStore
from daemon.memory.knowledge import KnowledgeBase
from daemon.models import EvaluatorResult, ExecutionResult, SprintContract


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        d = ForgeDB(os.path.join(tmp, "test.db"))
        yield d
        d.close()


@pytest.fixture
def kb(db):
    return KnowledgeBase(db)


@pytest.fixture
def episodic(db):
    return EpisodicStore(db)


# --- Knowledge base ---


class TestKnowledgeBase:
    def test_add_and_search(self, kb):
        kb.add("gotcha", "supabase", "RLS requires service_role key for testing", "session-1", 0.7)
        results = kb.search(topic="supabase")
        assert len(results) == 1
        assert "RLS" in results[0]["content"]

    def test_deduplication(self, kb):
        id1 = kb.add("gotcha", "supabase", "RLS requires service_role key", "s1", 0.7)
        id2 = kb.add("gotcha", "supabase", "RLS requires service_role key", "s2", 0.8)
        assert id1 == id2
        assert kb.count() == 1

    def test_confidence_increase_on_helpful(self, kb):
        kid = kb.add("gotcha", "auth", "Always hash passwords with bcrypt", "s1", 0.5)
        kb.mark_helpful(kid)
        items = kb.search(topic="auth")
        assert items[0]["confidence"] == pytest.approx(0.55, abs=0.01)
        assert items[0]["times_helpful"] == 1

    def test_confidence_decrease_on_unhelpful(self, kb):
        kid = kb.add("gotcha", "auth", "Always hash passwords with bcrypt", "s1", 0.5)
        kb.mark_unhelpful(kid)
        items = kb.search(topic="auth")
        assert items[0]["confidence"] == pytest.approx(0.4, abs=0.01)
        assert items[0]["times_helpful"] == 0
        assert items[0]["times_applied"] == 1

    def test_search_by_query(self, kb):
        kb.add("gotcha", "supabase", "RLS requires service_role key", "s1")
        kb.add("solution", "supabase", "Use supabase gen types for TypeScript", "s1")
        kb.add("pattern", "testing", "Always mock external APIs", "s1")
        results = kb.search(query="service_role")
        assert len(results) == 1
        assert "service_role" in results[0]["content"]

    def test_search_by_category(self, kb):
        kb.add("gotcha", "supabase", "RLS issue", "s1")
        kb.add("solution", "supabase", "Use gen types", "s1")
        results = kb.search(category="gotcha")
        assert len(results) == 1
        assert results[0]["category"] == "gotcha"

    def test_get_context_for_task_max_5(self, kb):
        for i in range(10):
            kb.add(
                "gotcha", "auth", f"Auth gotcha number {i} about password handling", f"s{i}", 0.9
            )
        context = kb.get_context_for_task("Fix password handling in auth module")
        lines = [l for l in context.strip().split("\n") if l.startswith("- ")]
        assert len(lines) <= 5

    def test_get_context_for_task_token_budget(self, kb):
        # Each item stays under the 500-char one-liner cap (the kb_guard limit),
        # but enough of them together exceed the ~500-token context budget so
        # the retriever must truncate.
        for i in range(10):
            kb.add(
                "gotcha",
                "auth",
                f"A gotcha about authentication issue number {i} with tokens and sessions " * 4,
                f"s{i}",
                0.9,
            )
        context = kb.get_context_for_task("Fix auth")
        # Should be roughly under 500 tokens (~2000 chars)
        assert len(context) < 3000

    def test_get_context_empty(self, kb):
        assert kb.get_context_for_task("Something unrelated") == ""

    def test_delete(self, kb):
        kid = kb.add("gotcha", "test", "Delete me", "s1")
        kb.delete(kid)
        assert kb.count() == 0

    def test_prune_low_confidence(self, kb):
        kb.add("gotcha", "test", "Low confidence item", "s1", 0.1)
        kb.add("gotcha", "test", "High confidence item", "s1", 0.9)
        pruned = kb.prune(min_confidence=0.2)
        assert pruned >= 1
        assert kb.count() == 1

    def test_prune_max_items(self, db):
        kb = KnowledgeBase(db)
        for i in range(15):
            kb.add("gotcha", f"topic{i}", f"Item {i} unique content", "s1", 0.5 + i * 0.01)
        pruned = kb.prune(max_items=10)
        assert kb.count() <= 10

    def test_get_all(self, kb):
        kb.add("gotcha", "a", "Item A", "s1")
        kb.add("solution", "b", "Item B", "s1")
        all_items = kb.get_all()
        assert len(all_items) == 2


# --- Episodic store ---


class TestEpisodicStore:
    def test_store_and_retrieve(self, episodic):
        sprint = SprintContract(session_id="sess-1", description="Build auth")
        gen_result = ExecutionResult(success=True, output="Done", tokens_in=100, tokens_out=200)
        eval_result = EvaluatorResult(verdict="APPROVED", feedback="All good")

        ep_id = episodic.store("sess-1", sprint, gen_result, eval_result)
        episodes = episodic.get_session_episodes("sess-1")
        assert len(episodes) == 1
        assert episodes[0]["status"] == "completed"
        assert episodes[0]["evaluator_verdict"] == "APPROVED"

    def test_store_failure(self, episodic):
        sprint = SprintContract(session_id="sess-1", description="Build auth")
        gen_result = ExecutionResult(success=False, error="Syntax error on line 42")

        episodic.store("sess-1", sprint, gen_result)
        failures = episodic.get_recent_failures()
        assert len(failures) == 1
        assert "Syntax error" in failures[0]["error"]

    def test_failure_resolution_pairs(self, db):
        episodic = EpisodicStore(db)
        sprint_id = "sprint-abc"

        # Store failure
        db.save_episode(
            "ep-1",
            "sess-1",
            sprint_id,
            "Build auth",
            "sonnet",
            "claude_code",
            "generator",
            "failed",
            error="Missing import",
        )
        # Store resolution
        db.save_episode(
            "ep-2",
            "sess-1",
            sprint_id,
            "Build auth",
            "sonnet",
            "claude_code",
            "generator",
            "completed",
            result="Fixed",
        )

        pairs = episodic.get_failure_resolution_pairs("sess-1")
        assert len(pairs) == 1
        assert pairs[0][0]["status"] == "failed"
        assert pairs[0][1]["status"] == "completed"
