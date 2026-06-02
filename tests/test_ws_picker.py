"""WS handlers for the folder/branch picker + model picker (M5)."""

from __future__ import annotations

import json
import subprocess

import pytest

from daemon import ws_server
from daemon.budget import BudgetController


def _git(path, *args):
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


async def _send(msg, tmp_db):
    return await ws_server._handle_message(
        object(), json.dumps(msg), tmp_db, None, BudgetController()
    )


class TestModelsInstalled:
    @pytest.mark.asyncio
    async def test_returns_models_list(self, tmp_db, monkeypatch):
        monkeypatch.setattr(
            "daemon.ollama_models.installed_models",
            lambda: [{"name": "qwen2.5-coder:7b", "size": "4.7 GB"}],
        )
        resp = await _send({"type": "models.installed"}, tmp_db)
        assert resp["type"] == "models_installed"
        assert resp["models"][0]["name"] == "qwen2.5-coder:7b"


class TestBranchesList:
    @pytest.mark.asyncio
    async def test_lists_branches_for_repo(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setattr(ws_server, "_validate_init_path", lambda p: True)
        p = tmp_path / "proj"
        p.mkdir()
        _git(p, "init")
        _git(p, "config", "user.email", "t@t.dev")
        _git(p, "config", "user.name", "t")
        (p / "f").write_text("x")
        _git(p, "add", ".")
        _git(p, "commit", "-m", "i")
        _git(p, "branch", "feature-y")

        resp = await _send({"type": "branches.list", "path": str(p)}, tmp_db)
        assert resp["type"] == "branches"
        assert resp["is_git"] is True
        assert "feature-y" in resp["branches"]

    @pytest.mark.asyncio
    async def test_path_outside_scope_rejected(self, tmp_db, monkeypatch):
        monkeypatch.setattr(ws_server, "_validate_init_path", lambda p: False)
        resp = await _send({"type": "branches.list", "path": "/etc"}, tmp_db)
        assert resp["type"] == "error"
        assert "scope" in resp["error"]

    @pytest.mark.asyncio
    async def test_empty_folder_init_then_list(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setattr(ws_server, "_validate_init_path", lambda p: True)
        p = tmp_path / "empty"
        p.mkdir()
        init = await _send({"type": "folder.init", "path": str(p)}, tmp_db)
        assert init["ok"] is True
        assert init["branches_state"]["is_git"] is True
