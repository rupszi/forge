"""Performance tests: DB operations, memory retrieval, dependency resolution."""

import os
import tempfile
import time

from daemon.budget import estimate_cost
from daemon.db import ForgeDB
from daemon.memory.retriever import Retriever
from daemon.models import SprintContract
from daemon.scheduler import dependency_waves


class TestDBPerformance:
    def test_bulk_knowledge_insert(self):
        """200 knowledge items should insert in under 1 second."""
        with tempfile.TemporaryDirectory() as tmp:
            db = ForgeDB(os.path.join(tmp, "perf.db"))
            start = time.time()
            for i in range(200):
                db.add_knowledge(
                    "gotcha",
                    f"topic{i % 20}",
                    f"Knowledge item {i} with unique content",
                    f"s{i}",
                    0.5,
                )
            elapsed = time.time() - start
            assert elapsed < 1.0, f"200 inserts took {elapsed:.2f}s"
            assert db.knowledge_count() == 200
            db.close()

    def test_knowledge_search_speed(self):
        """Search across 200 items should complete in under 100ms."""
        with tempfile.TemporaryDirectory() as tmp:
            db = ForgeDB(os.path.join(tmp, "perf.db"))
            for i in range(200):
                db.add_knowledge(
                    "gotcha", "auth", f"Auth knowledge item {i}", f"s{i}", 0.5 + (i % 5) * 0.1
                )

            start = time.time()
            for _ in range(100):
                db.search_knowledge(query="auth", limit=10)
            elapsed = time.time() - start
            assert elapsed < 1.0, f"100 searches took {elapsed:.2f}s"
            db.close()

    def test_retriever_speed(self):
        """Retriever context building should complete in under 50ms."""
        with tempfile.TemporaryDirectory() as tmp:
            db = ForgeDB(os.path.join(tmp, "perf.db"))
            for i in range(100):
                db.add_knowledge(
                    "gotcha", "supabase", f"Supabase gotcha {i} about RLS policies", f"s{i}", 0.7
                )
            for i in range(50):
                db.save_episode(
                    f"ep-{i}",
                    "s1",
                    f"sp-{i}",
                    f"Build supabase auth feature {i}",
                    "sonnet",
                    "claude_code",
                    "generator",
                    "failed",
                    error=f"Error {i}: missing RLS policy",
                )

            retriever = Retriever(db)
            start = time.time()
            for _ in range(50):
                retriever.get_context_for_task("Configure supabase RLS policies for auth")
            elapsed = time.time() - start
            assert elapsed < 2.5, f"50 retrievals took {elapsed:.2f}s"
            db.close()

    def test_bulk_episode_insert(self):
        """1000 episodes should insert in under 2 seconds."""
        with tempfile.TemporaryDirectory() as tmp:
            db = ForgeDB(os.path.join(tmp, "perf.db"))
            start = time.time()
            for i in range(1000):
                db.save_episode(
                    f"ep-{i}",
                    "s1",
                    f"sp-{i}",
                    f"Task {i}",
                    "sonnet",
                    "claude_code",
                    "generator",
                    "completed",
                )
            elapsed = time.time() - start
            assert elapsed < 2.0, f"1000 episode inserts took {elapsed:.2f}s"
            db.close()


class TestSchedulerPerformance:
    def test_dependency_waves_large(self):
        """100 sprints with complex dependencies should resolve in under 100ms."""
        sprints = []
        for i in range(100):
            deps = [f"s-{i - 1}"] if i > 0 and i % 5 != 0 else []
            sprints.append(SprintContract(id=f"s-{i}", depends_on=deps))

        start = time.time()
        waves = dependency_waves(sprints)
        elapsed = time.time() - start
        assert elapsed < 0.1, f"100 sprints resolution took {elapsed:.3f}s"
        assert len(waves) > 0

    def test_dependency_waves_wide(self):
        """50 independent sprints should form 1 wave instantly."""
        sprints = [SprintContract(id=f"s-{i}", depends_on=[]) for i in range(50)]
        start = time.time()
        waves = dependency_waves(sprints)
        elapsed = time.time() - start
        assert elapsed < 0.01
        assert len(waves) == 1
        assert len(waves[0]) == 50


class TestBudgetPerformance:
    def test_cost_estimation_speed(self):
        """10000 cost estimations should complete in under 100ms."""
        start = time.time()
        for _ in range(10000):
            estimate_cost("opus", 50000)
            estimate_cost("sonnet", 10000)
            estimate_cost("ollama", 10000)
        elapsed = time.time() - start
        assert elapsed < 0.1
