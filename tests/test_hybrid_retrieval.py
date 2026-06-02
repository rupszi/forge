"""M3 — hybrid retrieval merge (keyword ∪ vector), dedup, ranked.

The merge logic is a pure function tested with synthetic scored items, so it
doesn't need a real embedding model or sqlite-vec. The live vector pass
activates under FORGE_VECTOR_EPISODES; here we prove the ranking/dedup contract.
"""

from __future__ import annotations

from daemon.memory.retriever import merge_hybrid


class TestMergeHybrid:
    def test_dedups_by_id_keeping_best_score(self):
        keyword = [{"id": 1, "content": "a", "score": 0.3}]
        vector = [{"id": 1, "content": "a", "score": 0.9}]
        merged = merge_hybrid(keyword, vector)
        assert len(merged) == 1
        assert merged[0]["id"] == 1
        assert merged[0]["score"] == 0.9

    def test_ranks_by_score_desc(self):
        keyword = [{"id": 1, "content": "a", "score": 0.4}]
        vector = [{"id": 2, "content": "b", "score": 0.8}]
        merged = merge_hybrid(keyword, vector)
        assert [m["id"] for m in merged] == [2, 1]

    def test_union_of_both_sources(self):
        keyword = [{"id": 1, "content": "a", "score": 0.5}]
        vector = [{"id": 2, "content": "b", "score": 0.5}]
        merged = merge_hybrid(keyword, vector)
        assert {m["id"] for m in merged} == {1, 2}

    def test_limit_respected(self):
        keyword = [{"id": i, "content": str(i), "score": i / 10} for i in range(10)]
        merged = merge_hybrid(keyword, [], limit=3)
        assert len(merged) == 3
        # Highest scores kept.
        assert [m["id"] for m in merged] == [9, 8, 7]

    def test_keyword_only_when_no_vector(self):
        keyword = [{"id": 1, "content": "a", "score": 0.5}]
        merged = merge_hybrid(keyword, [])
        assert [m["id"] for m in merged] == [1]
