"""Native folder-picker dialog (Finder / zenity / kdialog) for the daemon.

The daemon runs on the user's machine, so it can pop the OS folder chooser and
return the chosen absolute path to the browser UI. We test the command builder
and the result parsing with an injected runner (no real dialog in CI).
"""

from __future__ import annotations

import pytest

from daemon import folder_dialog


class TestDialogCommand:
    def test_macos_uses_osascript(self):
        cmd = folder_dialog._dialog_command(platform="darwin", which=lambda _n: None)
        assert cmd[0] == "osascript"
        assert any("choose folder" in part for part in cmd)

    def test_linux_prefers_zenity(self):
        cmd = folder_dialog._dialog_command(
            platform="linux", which=lambda n: f"/usr/bin/{n}" if n == "zenity" else None
        )
        assert cmd[0] == "zenity"
        assert "--directory" in cmd

    def test_linux_falls_back_to_kdialog(self):
        cmd = folder_dialog._dialog_command(
            platform="linux", which=lambda n: "/usr/bin/kdialog" if n == "kdialog" else None
        )
        assert cmd[0] == "kdialog"

    def test_linux_none_available(self):
        cmd = folder_dialog._dialog_command(platform="linux", which=lambda _n: None)
        assert cmd is None


class TestPickFolder:
    @pytest.mark.asyncio
    async def test_returns_chosen_path(self):
        async def fake_runner(cmd, timeout=300):
            return 0, "/Users/dev/my project/\n", ""

        res = await folder_dialog.pick_folder(runner=fake_runner, platform="darwin")
        assert res["ok"] is True
        assert res["path"] == "/Users/dev/my project"  # trailing slash + newline stripped

    @pytest.mark.asyncio
    async def test_cancel_returns_cancelled(self):
        async def fake_runner(cmd, timeout=300):
            return 1, "", "User canceled."

        res = await folder_dialog.pick_folder(runner=fake_runner, platform="darwin")
        assert res["ok"] is False
        assert res.get("cancelled") is True

    @pytest.mark.asyncio
    async def test_no_dialog_tool(self):
        res = await folder_dialog.pick_folder(platform="linux", which=lambda _n: None)
        assert res["ok"] is False
        assert "no folder" in res["error"].lower()

    @pytest.mark.asyncio
    async def test_runner_error_is_graceful(self):
        async def boom(cmd, timeout=300):
            raise OSError("display not available")

        res = await folder_dialog.pick_folder(runner=boom, platform="darwin")
        assert res["ok"] is False
        assert "display" in res["error"].lower()


class TestWsHandler:
    @pytest.mark.asyncio
    async def test_folder_pick_returns_branches_for_chosen_path(
        self, tmp_db, tmp_path, monkeypatch
    ):
        import json
        import subprocess

        from daemon import folder_dialog, ws_server
        from daemon.budget import BudgetController

        # Make a real repo and pretend the user picked it.
        repo = tmp_path / "picked"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.dev"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        (repo / "f").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=repo, check=True, capture_output=True)

        async def fake_pick():
            return {"ok": True, "path": str(repo)}

        monkeypatch.setattr(folder_dialog, "pick_folder", fake_pick)
        resp = await ws_server._handle_message(
            object(), json.dumps({"type": "folder.pick"}), tmp_db, None, BudgetController()
        )
        assert resp["type"] == "branches"
        assert resp["path"] == str(repo)
        assert resp["is_git"] is True

    @pytest.mark.asyncio
    async def test_folder_pick_cancel(self, tmp_db, monkeypatch):
        import json

        from daemon import folder_dialog, ws_server
        from daemon.budget import BudgetController

        async def fake_pick():
            return {"ok": False, "cancelled": True}

        monkeypatch.setattr(folder_dialog, "pick_folder", fake_pick)
        resp = await ws_server._handle_message(
            object(), json.dumps({"type": "folder.pick"}), tmp_db, None, BudgetController()
        )
        assert resp["type"] == "folder_picked"
        assert resp.get("cancelled") is True
