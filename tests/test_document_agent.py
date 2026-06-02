"""M7 — document agent: brief → local Markdown, graded against its criteria."""

from __future__ import annotations

import pytest

from daemon.agents import document
from daemon.models import ExecutionResult


class TestWriteDocument:
    @pytest.mark.asyncio
    async def test_produces_markdown_from_brief(self, monkeypatch):
        async def fake_execute(prompt, model=None):
            assert "writer" in prompt.lower() or "document" in prompt.lower()
            return ExecutionResult(success=True, output="# README\n\nHello.")

        monkeypatch.setattr(document.ollama_executor, "execute", fake_execute)
        result = await document.write_document(
            "Write a README for a CLI tool", criteria=["has a title"]
        )
        assert result.success
        assert result.content.startswith("# README")

    @pytest.mark.asyncio
    async def test_failure_surfaces(self, monkeypatch):
        async def fake_execute(prompt, model=None):
            return ExecutionResult(success=False, error="model down")

        monkeypatch.setattr(document.ollama_executor, "execute", fake_execute)
        result = await document.write_document("x", criteria=[])
        assert not result.success
        assert "model down" in (result.error or "")

    @pytest.mark.asyncio
    async def test_local_model_default_is_not_cloud(self, monkeypatch):
        captured = {}

        async def fake_execute(prompt, model=None):
            captured["model"] = model
            return ExecutionResult(success=True, output="# Doc")

        monkeypatch.setattr(document.ollama_executor, "execute", fake_execute)
        await document.write_document("brief", criteria=[])
        # Default writer model is a local one (routed via ollama executor).
        from daemon.routing import is_cloud_executor, select_executor

        assert not is_cloud_executor(select_executor(captured["model"]))


class TestWriteAndSave:
    @pytest.mark.asyncio
    async def test_writes_and_saves_artifact(self, monkeypatch, tmp_path):
        async def fake_execute(prompt, model=None):
            return ExecutionResult(success=True, output="# Spec\n\nDetails.")

        monkeypatch.setattr(document.ollama_executor, "execute", fake_execute)
        result = await document.write_document("Write a spec", criteria=["title"])
        path = document.save_document(result, name="spec", fmt="md", base_path=str(tmp_path))
        assert path.endswith("spec.md")
        with open(path) as f:
            assert "# Spec" in f.read()
