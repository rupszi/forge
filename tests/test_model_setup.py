"""M1 — `forge models pull` disk-ceiling guard (G-RAM-2).

The pull planner is a pure function so the refuse/allow decision is testable
without touching the disk or Ollama.
"""

from __future__ import annotations

import pytest

from daemon import model_setup


class TestDefaultModelSet:
    def test_default_set_is_local_and_nonempty(self):
        models = model_setup.DEFAULT_MODEL_SET
        assert len(models) >= 3
        # Every default model carries a positive size estimate.
        assert all(m.size_gb > 0 for m in models)
        # Includes an embedding model for memory recall.
        assert any("embed" in m.name for m in models)


class TestPlanPull:
    def test_allows_when_disk_has_room(self):
        models = [
            model_setup.ModelSpec("a", 5.0),
            model_setup.ModelSpec("b", 4.0),
        ]
        plan = model_setup.plan_pull(models, free_gb=50.0, headroom_gb=10.0)
        assert plan.ok is True
        assert plan.total_gb == 9.0
        assert plan.refused_reason is None

    def test_refuses_when_would_breach_headroom(self):
        models = [model_setup.ModelSpec("big", 35.0)]
        # 35 GB pull, 40 GB free, 10 GB headroom => would leave 5 GB < 10 GB.
        plan = model_setup.plan_pull(models, free_gb=40.0, headroom_gb=10.0)
        assert plan.ok is False
        assert plan.refused_reason is not None
        assert "headroom" in plan.refused_reason.lower()

    def test_skips_already_present_models(self):
        models = [
            model_setup.ModelSpec("present", 20.0),
            model_setup.ModelSpec("missing", 5.0),
        ]
        plan = model_setup.plan_pull(models, free_gb=30.0, headroom_gb=10.0, present={"present"})
        # Only the missing model counts toward the download size.
        assert plan.total_gb == 5.0
        assert plan.ok is True
        assert [m.name for m in plan.to_pull] == ["missing"]

    def test_boundary_exactly_at_headroom_is_allowed(self):
        models = [model_setup.ModelSpec("x", 30.0)]
        # 30 GB pull, 40 GB free, 10 GB headroom => leaves exactly 10 GB == ok.
        plan = model_setup.plan_pull(models, free_gb=40.0, headroom_gb=10.0)
        assert plan.ok is True


class TestFreeDiskGb:
    def test_free_disk_is_positive(self, tmp_path):
        free = model_setup.free_disk_gb(str(tmp_path))
        assert free > 0


class TestEstimateSizeGb:
    def test_known_models_use_table(self):
        # The default lineup carries explicit sizes.
        for m in model_setup.DEFAULT_MODEL_SET:
            assert model_setup.estimate_size_gb(m.name) == m.size_gb

    def test_embedding_models_are_small(self):
        assert model_setup.estimate_size_gb("some-embed-model") == 0.3

    def test_param_count_parsed(self):
        # 27b at ~0.6 GB/B ≈ 16.2 GB
        assert model_setup.estimate_size_gb("qwen3.6:27b") == pytest.approx(16.2)
        assert model_setup.estimate_size_gb("foo-7b") == pytest.approx(4.2)

    def test_unknown_falls_back_to_default(self):
        assert model_setup.estimate_size_gb("mystery-model") == 8.0
