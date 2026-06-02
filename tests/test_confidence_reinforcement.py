"""M3 — confidence reinforcement: the KB self-corrects from outcomes.

The audit found this loop stubbed. After a task, KB items that were injected get
marked helpful (success) or unhelpful (failure), nudging confidence so good
items rise and bad ones decay out.
"""

from __future__ import annotations

from daemon.memory.knowledge import KnowledgeBase
from daemon.memory.retriever import Retriever


class TestRetrieverExposesInjectedIds:
    def test_get_context_and_ids_returns_injected_ids(self, tmp_db):
        kb = KnowledgeBase(tmp_db)
        kid = kb.add("gotcha", "supabase", "supabase RLS requires service_role for testing")
        r = Retriever(tmp_db)
        context, ids = r.get_context_and_ids("fix the supabase RLS policy testing")
        assert "service_role" in context
        assert kid in ids

    def test_plain_get_context_still_works(self, tmp_db):
        kb = KnowledgeBase(tmp_db)
        kb.add("gotcha", "vercel", "vercel edge functions have a cold-start penalty")
        r = Retriever(tmp_db)
        ctx = r.get_context_for_task("optimize the vercel edge function latency")
        assert "cold-start" in ctx


class TestReinforce:
    def test_helpful_raises_confidence(self, tmp_db):
        kb = KnowledgeBase(tmp_db)
        kid = kb.add("gotcha", "auth", "jwt tokens must be validated server-side", confidence=0.5)
        kb.reinforce([kid], helpful=True)
        item = next(i for i in kb.get_all() if i["id"] == kid)
        assert item["confidence"] > 0.5

    def test_unhelpful_lowers_confidence(self, tmp_db):
        kb = KnowledgeBase(tmp_db)
        kid = kb.add("gotcha", "auth", "some questionable claim", confidence=0.5)
        kb.reinforce([kid], helpful=False)
        item = next(i for i in kb.get_all() if i["id"] == kid)
        assert item["confidence"] < 0.5

    def test_reinforce_empty_is_noop(self, tmp_db):
        kb = KnowledgeBase(tmp_db)
        kb.reinforce([], helpful=True)  # must not raise
