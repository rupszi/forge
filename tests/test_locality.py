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

    def test_models_pull_dry_run(self, capsys):
        from types import SimpleNamespace

        from daemon import cli

        rc = cli.cmd_models(SimpleNamespace(action="pull", dry_run=True))
        out = capsys.readouterr().out
        # Either a dry-run plan printed (rc 0) or a disk refusal (rc 1) — both
        # are honest outcomes; neither should pull anything.
        assert rc in (0, 1)
        assert "Plan:" in out
