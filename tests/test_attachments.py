"""Real file/folder attachment → injected context (M5 / context extension)."""

from __future__ import annotations

import pytest

from daemon import attachments


class TestAddPath:
    def test_add_single_file(self, tmp_path):
        f = tmp_path / "notes.md"
        f.write_text("# Title\n\nsome content here")
        store = attachments.AttachmentStore()
        res = store.add_path(str(f))
        assert res["ok"] is True
        assert res["files"][0]["name"] == "notes.md"
        assert store.list()[0]["tokens"] > 0

    def test_add_directory_recurses(self, tmp_path):
        (tmp_path / "a.py").write_text("print('a')")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.py").write_text("print('b')")
        store = attachments.AttachmentStore()
        res = store.add_path(str(tmp_path))
        assert res["ok"] is True
        names = {f["name"] for f in res["files"]}
        assert {"a.py", "b.py"} <= names

    def test_skips_binary_files(self, tmp_path):
        (tmp_path / "text.txt").write_text("readable")
        (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02\xff\xfe")
        store = attachments.AttachmentStore()
        res = store.add_path(str(tmp_path))
        names = {f["name"] for f in res["files"]}
        assert "text.txt" in names
        assert "bin.dat" not in names  # undecodable → skipped

    def test_missing_path(self, tmp_path):
        store = attachments.AttachmentStore()
        res = store.add_path(str(tmp_path / "nope"))
        assert res["ok"] is False


class TestContext:
    def test_empty_context_is_blank(self):
        assert attachments.AttachmentStore().context() == ""

    def test_context_includes_content(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("def hello(): return 42")
        store = attachments.AttachmentStore()
        store.add_path(str(f))
        ctx = store.context(budget_tokens=1000)
        assert "x.py" in ctx
        assert "def hello" in ctx

    def test_context_respects_token_budget(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("word " * 5000)  # ~25k chars ≈ 6k tokens
        store = attachments.AttachmentStore()
        store.add_path(str(f))
        ctx = store.context(budget_tokens=500)  # ~2000 chars
        assert len(ctx) < 4000
        assert "truncated" in ctx.lower()


class TestManage:
    def test_clear(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("hi")
        store = attachments.AttachmentStore()
        store.add_path(str(f))
        assert store.list()
        store.clear()
        assert store.list() == []

    def test_global_store_singleton(self):
        s1 = attachments.get_store()
        s2 = attachments.get_store()
        assert s1 is s2


class TestWsHandlers:
    async def _send(self, msg, tmp_db):
        import json

        from daemon import ws_server
        from daemon.budget import BudgetController

        return await ws_server._handle_message(
            object(), json.dumps(msg), tmp_db, None, BudgetController()
        )

    @pytest.mark.asyncio
    async def test_attach_path_scoped_and_stored(self, tmp_db, tmp_path, monkeypatch):
        from daemon import attachments as _a, ws_server

        _a.get_store().clear()
        monkeypatch.setattr(ws_server, "_validate_init_path", lambda p: True)
        f = tmp_path / "ctx.md"
        f.write_text("attach me")
        resp = await self._send({"type": "attach.path", "path": str(f)}, tmp_db)
        assert resp["type"] == "attachments"
        assert resp["ok"] is True
        assert any(i["name"] == "ctx.md" for i in resp["items"])
        _a.get_store().clear()

    @pytest.mark.asyncio
    async def test_attach_path_rejects_out_of_scope(self, tmp_db, monkeypatch):
        from daemon import ws_server

        monkeypatch.setattr(ws_server, "_validate_init_path", lambda p: False)
        resp = await self._send({"type": "attach.path", "path": "/etc/passwd"}, tmp_db)
        assert resp["type"] == "error"
