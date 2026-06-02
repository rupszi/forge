"""File-fetch primitive + WS handler (lazy file load)."""

from __future__ import annotations

import json

import pytest

from daemon import filefetch


class TestReadFileText:
    def test_reads_text(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("print('hi')")
        out = filefetch.read_file_text(str(f))
        assert out["ok"] is True
        assert "print('hi')" in out["content"]
        assert out["truncated"] is False

    def test_missing_file(self, tmp_path):
        out = filefetch.read_file_text(str(tmp_path / "nope.txt"))
        assert out["ok"] is False

    def test_binary_rejected(self, tmp_path):
        f = tmp_path / "b.bin"
        f.write_bytes(b"\x00\x01\xff\xfe")
        out = filefetch.read_file_text(str(f))
        assert out["ok"] is False
        assert "binary" in out["error"].lower()

    def test_truncates_large_file(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 5000)
        out = filefetch.read_file_text(str(f), max_bytes=1000)
        assert out["ok"] is True
        assert out["truncated"] is True
        assert len(out["content"]) == 1000


class TestWsHandler:
    @pytest.mark.asyncio
    async def test_file_fetch_in_scope(self, tmp_db, tmp_path, monkeypatch):
        from daemon import ws_server
        from daemon.budget import BudgetController

        monkeypatch.setattr(ws_server, "_validate_init_path", lambda p: True)
        f = tmp_path / "x.txt"
        f.write_text("fetch me")
        resp = await ws_server._handle_message(
            object(),
            json.dumps({"type": "file.fetch", "path": str(f)}),
            tmp_db,
            None,
            BudgetController(),
        )
        assert resp["type"] == "file_content"
        assert resp["ok"] is True
        assert "fetch me" in resp["content"]

    @pytest.mark.asyncio
    async def test_file_fetch_out_of_scope(self, tmp_db, monkeypatch):
        from daemon import ws_server
        from daemon.budget import BudgetController

        monkeypatch.setattr(ws_server, "_validate_init_path", lambda p: False)
        resp = await ws_server._handle_message(
            object(),
            json.dumps({"type": "file.fetch", "path": "/etc/passwd"}),
            tmp_db,
            None,
            BudgetController(),
        )
        assert resp["type"] == "error"
