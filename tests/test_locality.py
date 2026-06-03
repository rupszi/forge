"""M1 — honest locality state (G-LOC-2): the indicator must match reality."""

from __future__ import annotations

from daemon import locality


class TestLocalityState:
    def test_local_when_cloud_disabled(self, monkeypatch):
        monkeypatch.delenv("FORGE_CLOUD_ENABLED", raising=False)
        state = locality.locality_state()
        assert state["mode"] == "local"
        assert state["cloud_enabled"] is False
        assert state["type"] == "locality"

    def test_cloud_when_enabled(self, monkeypatch):
        monkeypatch.setenv("FORGE_CLOUD_ENABLED", "1")
        state = locality.locality_state()
        assert state["mode"] == "cloud"
        assert state["cloud_enabled"] is True


class TestModelsCli:
    def test_models_list_runs(self, capsys):
        from types import SimpleNamespace

        from daemon import cli

        rc = cli.cmd_models(SimpleNamespace(action="list"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "Default local model lineup" in out
        assert "Free disk" in out

    def test_models_pull_dry_run(self, capsys, monkeypatch):
        from types import SimpleNamespace

        from daemon import cli, model_setup

        # Deterministic: ample free disk so the plan is accepted and the dry-run
        # branch (not the disk-refusal branch) is the one exercised.
        monkeypatch.setattr(model_setup, "free_disk_gb", lambda _p: 100_000.0)

        # Hard guard: a dry run must NEVER actually pull a model.
        def _must_not_pull(name):
            raise AssertionError(f"dry run pulled {name!r}")

        monkeypatch.setattr(cli, "_ollama_pull", _must_not_pull)

        rc = cli.cmd_models(SimpleNamespace(action="pull", dry_run=True))
        out = capsys.readouterr().out
        assert rc == 0
        assert "Plan:" in out
        assert "dry run — nothing pulled" in out
