"""`forge serve` should launch the dashboard alongside the daemon (one command).

We don't actually start Next.js here — we test the launcher's decisions:
- skip gracefully when deps/pnpm are missing (daemon still runs),
- spawn the right command when ready,
- terminate cleanly on shutdown.
"""

from __future__ import annotations

from daemon import cli


class TestLaunchUI:
    def test_skips_when_ui_dir_missing(self, tmp_path, capsys):
        proc = cli._launch_ui(ui_dir=tmp_path / "nope")
        assert proc is None
        assert "running daemon only" in capsys.readouterr().out.lower()

    def test_skips_when_node_modules_missing(self, tmp_path, capsys):
        ui = tmp_path / "ui"
        ui.mkdir()
        proc = cli._launch_ui(ui_dir=ui)
        assert proc is None
        assert "dependencies not installed" in capsys.readouterr().out.lower()

    def test_skips_when_no_package_manager(self, tmp_path, monkeypatch):
        ui = tmp_path / "ui"
        (ui / "node_modules").mkdir(parents=True)
        monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
        proc = cli._launch_ui(ui_dir=ui)
        assert proc is None

    def test_spawns_when_ready(self, tmp_path, monkeypatch):
        ui = tmp_path / "ui"
        (ui / "node_modules").mkdir(parents=True)
        monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")

        calls = {}

        class FakeProc:
            def __init__(self, cmd, cwd=None):
                calls["cmd"] = cmd
                calls["cwd"] = cwd

        monkeypatch.setattr(cli.subprocess, "Popen", FakeProc)
        proc = cli._launch_ui(ui_dir=ui)
        assert proc is not None
        assert calls["cmd"][0] in ("pnpm", "npm")
        assert "dev" in calls["cmd"]
        assert str(ui) in str(calls["cwd"])

    def test_prefers_pnpm_over_npm(self, tmp_path, monkeypatch):
        ui = tmp_path / "ui"
        (ui / "node_modules").mkdir(parents=True)
        monkeypatch.setattr(cli.shutil, "which", lambda name: "/x/pnpm" if name == "pnpm" else None)

        class FakeProc:
            def __init__(self, cmd, cwd=None):
                self.cmd = cmd

        monkeypatch.setattr(cli.subprocess, "Popen", FakeProc)
        proc = cli._launch_ui(ui_dir=ui)
        assert proc.cmd[0] == "pnpm"


class TestStopUI:
    def test_terminates_process(self):
        class FakeProc:
            def __init__(self):
                self.terminated = False
                self.killed = False

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

        p = FakeProc()
        cli._stop_ui(p)
        assert p.terminated

    def test_handles_none(self):
        cli._stop_ui(None)  # must not raise

    def test_kills_if_terminate_times_out(self):
        import subprocess

        class StubbornProc:
            def __init__(self):
                self.killed = False

            def terminate(self):
                pass

            def wait(self, timeout=None):
                if not self.killed:
                    raise subprocess.TimeoutExpired(cmd="ui", timeout=timeout)
                return 0

            def kill(self):
                self.killed = True

        p = StubbornProc()
        cli._stop_ui(p)
        assert p.killed
