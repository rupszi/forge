"""Memory tool — a path-scoped disk scratchpad for the agent (context extension).

Implements the Anthropic memory-tool command set over a per-session directory.
The load-bearing property is path containment: no command may read or write
outside the memory root. That's tested adversarially.
"""

from __future__ import annotations

import pytest

from daemon.memory_tool import MemoryTool, MemoryViolation


@pytest.fixture
def mem(tmp_path):
    return MemoryTool(str(tmp_path / "memories" / "sess1"))


class TestRoundTrip:
    def test_create_and_view_file(self, mem):
        mem.create("notes.md", "line one\nline two")
        out = mem.view("notes.md")
        assert "line one" in out and "line two" in out

    def test_view_directory_lists_files(self, mem):
        mem.create("a.md", "x")
        mem.create("b.md", "y")
        listing = mem.view("")
        assert "a.md" in listing and "b.md" in listing

    def test_str_replace(self, mem):
        mem.create("f.md", "hello world")
        mem.str_replace("f.md", "world", "there")
        assert "hello there" in mem.view("f.md")

    def test_insert_at_line(self, mem):
        mem.create("f.md", "a\nc")
        mem.insert("f.md", 1, "b")  # after line 1
        assert mem.view("f.md").count("b") == 1
        body = mem.read("f.md")
        assert body.splitlines() == ["a", "b", "c"]

    def test_delete(self, mem):
        mem.create("gone.md", "bye")
        mem.delete("gone.md")
        assert "gone.md" not in mem.view("")

    def test_rename(self, mem):
        mem.create("old.md", "data")
        mem.rename("old.md", "new.md")
        listing = mem.view("")
        assert "new.md" in listing and "old.md" not in listing

    def test_nested_dirs(self, mem):
        mem.create("plans/sprint1.md", "do the thing")
        assert "do the thing" in mem.view("plans/sprint1.md")


class TestPathContainment:
    @pytest.mark.parametrize(
        "bad",
        ["../escape.md", "../../etc/passwd", "/etc/passwd", "a/../../b", "sub/../../../x"],
    )
    def test_traversal_blocked(self, mem, bad):
        with pytest.raises(MemoryViolation):
            mem.create(bad, "x")
        with pytest.raises(MemoryViolation):
            mem.view(bad)

    def test_symlink_escape_blocked(self, mem, tmp_path):
        # A symlink inside the memory dir pointing outside must not be writable.
        outside = tmp_path / "secret"
        outside.mkdir()
        link = mem.base / "link"
        link.symlink_to(outside)
        with pytest.raises(MemoryViolation):
            mem.create("link/pwn.md", "x")


class TestContextInjection:
    def test_context_includes_scratchpad(self, mem):
        mem.create("findings.md", "the bug is in auth.py")
        ctx = mem.context()
        assert "findings.md" in ctx
        assert "auth.py" in ctx

    def test_empty_context_blank(self, mem):
        assert mem.context() == ""


class TestDispatch:
    def test_create_then_view_via_dispatch(self, tmp_path, monkeypatch):
        from daemon import memory_tool

        monkeypatch.setattr(
            memory_tool, "default_tool", lambda *a, **k: MemoryTool(str(tmp_path / "mem"))
        )
        r = memory_tool.dispatch("create", {"path": "todo.md", "content": "ship it"})
        assert r["ok"] is True
        assert "todo.md" in r["files"]
        v = memory_tool.dispatch("view", {"path": "todo.md"})
        assert "ship it" in v["result"]

    def test_unknown_command(self, tmp_path, monkeypatch):
        from daemon import memory_tool

        monkeypatch.setattr(
            memory_tool, "default_tool", lambda *a, **k: MemoryTool(str(tmp_path / "mem"))
        )
        r = memory_tool.dispatch("rm_rf", {"path": "x"})
        assert r["ok"] is False

    def test_traversal_via_dispatch_blocked(self, tmp_path, monkeypatch):
        from daemon import memory_tool

        monkeypatch.setattr(
            memory_tool, "default_tool", lambda *a, **k: MemoryTool(str(tmp_path / "mem"))
        )
        r = memory_tool.dispatch("create", {"path": "../escape.md", "content": "x"})
        assert r["ok"] is False
        assert "escape" in r["error"].lower() or "'..'" in r["error"]
