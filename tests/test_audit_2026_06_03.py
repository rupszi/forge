"""Regression tests for the 2026-06-03 audit findings (High severity).

1. Evaluator must run LOCALLY by default (not unconditionally on cloud claude -p).
2. _validate_init_path must resolve symlinks before the containment check, and
   attachments must skip symlinks inside an attached folder.
"""

from __future__ import annotations

import os

import pytest


class TestEvaluatorRunsLocalByDefault:
    @pytest.mark.asyncio
    async def test_default_eval_routes_to_ollama_not_cloud(self, monkeypatch):
        """With cloud disabled, evaluating a Qwen sprint must dispatch to the
        local (Ollama) cross-family evaluator — never claude_code."""
        monkeypatch.delenv("FORGE_CLOUD_ENABLED", raising=False)
        from daemon.agents import evaluator
        from daemon.executors import claude_code as cc, ollama as oll
        from daemon.models import ExecutionResult, ProjectContext, SprintContract

        calls = {"claude": 0, "ollama": 0}

        async def fake_claude(*a, **k):
            calls["claude"] += 1
            return ExecutionResult(success=True, output="PASS: x — ok\nAPPROVED")

        async def fake_ollama(prompt, model=None, **k):
            calls["ollama"] += 1
            return ExecutionResult(success=True, output="PASS: x — ok\nAPPROVED")

        monkeypatch.setattr(cc, "execute", fake_claude)
        monkeypatch.setattr(oll, "execute", fake_ollama)

        sprint = SprintContract(
            id="s1",
            session_id="x",
            description="do x",
            done_criteria=["x"],
            assigned_model="qwen2.5-coder:7b",
        )
        await evaluator.evaluate(sprint, "diff --git a b", ProjectContext(path="."))
        assert calls["ollama"] == 1
        assert calls["claude"] == 0

    @pytest.mark.asyncio
    async def test_cloud_eval_model_blocked_when_cloud_off(self, monkeypatch):
        monkeypatch.delenv("FORGE_CLOUD_ENABLED", raising=False)
        from daemon.agents import evaluator
        from daemon.routing import CloudDisabledError

        with pytest.raises(CloudDisabledError):
            await evaluator._dispatch_eval("prompt", "claude-sonnet-4")


class TestSymlinkEscapeBlocked:
    def test_validate_init_path_rejects_symlink_escape(self, tmp_path, monkeypatch):
        from daemon import ws_server

        monkeypatch.chdir(tmp_path)
        link = tmp_path / "innocent.txt"
        link.symlink_to("/etc/passwd")
        # A symlink inside cwd pointing outside must be rejected post-realpath.
        assert ws_server._validate_init_path("innocent.txt") is False

    def test_real_in_scope_file_still_allowed(self, tmp_path, monkeypatch):
        from daemon import ws_server

        monkeypatch.chdir(tmp_path)
        (tmp_path / "real.txt").write_text("ok")
        assert ws_server._validate_init_path("real.txt") is True

    def test_attachments_skip_symlinks(self, tmp_path):
        from daemon import attachments

        (tmp_path / "real.txt").write_text("legit")
        (tmp_path / "leak").symlink_to("/etc/passwd")
        store = attachments.AttachmentStore()
        res = store.add_path(str(tmp_path))
        names = {os.path.basename(f["path"]) for f in res["files"]}
        assert "real.txt" in names
        assert "leak" not in names  # symlink skipped
