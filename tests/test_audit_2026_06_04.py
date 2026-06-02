"""Regression tests for the 2026-06-04 audit findings (F3–F15).

Each test would FAIL against the pre-fix code. Grouped by finding id.
"""

from __future__ import annotations

# ---- F3: scratchpad scoped per (project, session) ----


class TestScratchpadScoping:
    def test_sessions_do_not_see_each_others_notes(self, tmp_path):
        from daemon import memory_tool

        proj = str(tmp_path / "projA")
        a = memory_tool.default_tool(proj, "session-1")
        b = memory_tool.default_tool(proj, "session-2")

        a.create("note.md", "secret from session 1")

        # session-2 must NOT see session-1's note (pre-fix: shared .forge/memories)
        assert b.view("") == "(empty)"
        assert "session 1" in a.view("note.md")
        # the two roots are genuinely different directories
        assert a.base != b.base

    def test_projects_do_not_see_each_others_notes(self, tmp_path):
        from daemon import memory_tool

        a = memory_tool.default_tool(str(tmp_path / "projA"), "s")
        b = memory_tool.default_tool(str(tmp_path / "projB"), "s")
        a.create("note.md", "project A note")
        assert b.view("") == "(empty)"

    def test_session_id_cannot_escape_memories_root(self, tmp_path):
        from daemon import memory_tool

        proj = str(tmp_path / "proj")
        tool = memory_tool.default_tool(proj, "../../etc")
        # The sanitized segment stays under <proj>/.forge/memories/
        memories_root = tmp_path / "proj" / ".forge" / "memories"
        assert memories_root in tool.base.parents or tool.base.parent == memories_root

    def test_default_tool_signature_takes_scoping_args(self):
        """Pre-fix, default_tool() took no args. Guard the new contract."""
        import inspect

        from daemon.memory_tool import default_tool

        params = list(inspect.signature(default_tool).parameters)
        assert params[:2] == ["project_path", "session_id"]

    def test_scheduler_passes_ctx_path_and_session_id(self):
        """The scheduler injection site must scope the scratchpad to the
        sprint's project + session, not the daemon CWD (pre-fix bug)."""
        import inspect

        import daemon.scheduler as scheduler

        src = inspect.getsource(scheduler.execute_sprint)
        assert "_default_mem_tool(ctx.path, session_id)" in src
