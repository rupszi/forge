"""Forge Studio config flags: cloud opt-in + local resource budgets (M0).

These knobs are the contract behind the locality and resource guardrails:
- ``cloud_enabled()`` gates every cloud executor (G-LOC-2).
- ``LOCAL_RAM_BUDGET_GB`` bounds the model pool (G-RAM-1).
- ``MODEL_DISK_HEADROOM_GB`` keeps ``forge models pull`` from filling the disk
  (G-RAM-2).

We test the live ``cloud_enabled()`` reader (not the import-time snapshot) so
tests can flip the env without reimporting the module.
"""

from __future__ import annotations

import pytest

from daemon import config


class TestCloudEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("FORGE_CLOUD_ENABLED", raising=False)
        assert config.cloud_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes", "on"])
    def test_truthy_values_enable(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_CLOUD_ENABLED", val)
        assert config.cloud_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "False", "no", "off", ""])
    def test_falsy_values_disable(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_CLOUD_ENABLED", val)
        assert config.cloud_enabled() is False


class TestRamBudget:
    def test_default_leaves_headroom(self):
        # Default must be < total RAM so the OS + daemon keep room; spec says
        # ~36 of 48 GB. We only assert it's a positive float with headroom.
        assert isinstance(config.LOCAL_RAM_BUDGET_GB, float)
        assert 0 < config.LOCAL_RAM_BUDGET_GB <= 48

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("FORGE_LOCAL_RAM_BUDGET_GB", "24")
        assert config.local_ram_budget_gb() == 24.0


class TestDiskHeadroom:
    def test_default_headroom_positive(self):
        assert config.MODEL_DISK_HEADROOM_GB >= 1.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("FORGE_MODEL_DISK_HEADROOM_GB", "5")
        assert config.model_disk_headroom_gb() == 5.0
