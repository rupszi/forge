"""Tests for daemon/mcp_server.py — KB-as-MCP server export (Phase 1 Week 6).

These tests verify the server can be constructed and that the underlying DB
helpers (``search_episodes``, ``kb_summary_text``, ``session_summary_text``)
work correctly. We don't spawn a real MCP server because that's stdio-bound
and would require the test runner to act as a client.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from daemon.db import ForgeDB
from daemon.models import Session, SprintContract

# ---- Helper DB fixtures ----


@pytest.fixture
def populated_db():
    """A clean DB with a few episodes, KB items, sessions, and sprints."""
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))

        # Add some KB items
        db.add_knowledge("gotcha", "supabase", "RLS test with service_role key", source="manual")
        db.add_knowledge("solution", "supabase", "Use auth.uid() in policy", source="learned")
        db.add_knowledge("pattern", "next.js", "Use server actions for mutations", source="manual")
        db.add_knowledge("gotcha", "next.js", "Hydration error on Date.now()", source="learned")
        db.add_knowledge("rule", "testing", "Always mock external APIs", source="manual")

        # Add a session + sprint + episode
        session = Session(id="session-test", objective="Build /health endpoint", project_path="/p")
        db.save_session(session)

        sprint = SprintContract(
            id="sprint-test",
            session_id="session-test",
            description="Add /health route",
            done_criteria=["Route returns 200"],
            assigned_model="qwen3-coder-next",
        )
        db.save_sprint(sprint)

        # Save an episode with an error
        db.save_episode(
            episode_id="ep-1",
            session_id="session-test",
            sprint_id="sprint-test",
            task_description="Add /health route",
            model="qwen3-coder-next",
            agent_type="ollama",
            agent_role="generator",
            status="failed",
            error="ImportError: cannot import name 'NextRequest'",
            resolution=None,
        )

        yield db
        db.close()


# ---- search_episodes ----


def test_search_episodes_finds_match_by_error_substring(populated_db):
    results = populated_db.search_episodes("ImportError", limit=5)
    assert len(results) == 1
    assert "NextRequest" in results[0]["error"]


def test_search_episodes_case_insensitive(populated_db):
    assert len(populated_db.search_episodes("importerror", limit=5)) == 1


def test_search_episodes_finds_match_by_task_description(populated_db):
    results = populated_db.search_episodes("health", limit=5)
    assert len(results) == 1
    assert "health" in results[0]["task_description"].lower()


def test_search_episodes_returns_empty_on_no_match(populated_db):
    assert populated_db.search_episodes("nonexistent_xyz") == []


def test_search_episodes_respects_limit(populated_db):
    # Add 4 more episodes with similar errors
    for i in range(4):
        populated_db.save_episode(
            episode_id=f"ep-{i + 2}",
            session_id="session-test",
            sprint_id="sprint-test",
            task_description=f"Task {i}",
            model="qwen3-coder-next",
            agent_type="ollama",
            agent_role="generator",
            status="failed",
            error="ImportError: another one",
        )
    # Now 5 ImportError matches; limit=2 should return 2
    assert len(populated_db.search_episodes("ImportError", limit=2)) == 2


# ---- kb_summary_text ----


def test_kb_summary_text_includes_total_count(populated_db):
    summary = populated_db.kb_summary_text()
    assert "Total items: 5" in summary


def test_kb_summary_text_groups_by_category(populated_db):
    summary = populated_db.kb_summary_text()
    assert "gotcha: 2" in summary
    assert "solution: 1" in summary
    assert "pattern: 1" in summary
    assert "rule: 1" in summary


def test_kb_summary_text_includes_top_topics(populated_db):
    summary = populated_db.kb_summary_text()
    assert "supabase" in summary
    assert "next.js" in summary


def test_kb_summary_text_handles_empty_kb():
    with tempfile.TemporaryDirectory() as tmp:
        empty = ForgeDB(os.path.join(tmp, "empty.db"))
        summary = empty.kb_summary_text()
        assert "Total items: 0" in summary
        empty.close()


# ---- session_summary_text ----


def test_session_summary_includes_objective_and_sprints(populated_db):
    summary = populated_db.session_summary_text("session-test")
    assert "session-test" in summary
    assert "Build /health endpoint" in summary
    assert "Add /health route" in summary
    assert "qwen3-coder-next" in summary


def test_session_summary_handles_unknown_session(populated_db):
    summary = populated_db.session_summary_text("session-bogus")
    assert "No session" in summary


def test_session_summary_includes_episode_count(populated_db):
    summary = populated_db.session_summary_text("session-test")
    assert "Episodes: 1" in summary


# ---- mcp_server module ----


def _mcp_installed() -> bool:
    try:
        import mcp.server.fastmcp  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    _mcp_installed(), reason="mcp installed; this test exercises the missing-dep path"
)
def test_build_mcp_server_raises_clear_error_when_mcp_missing():
    """When the ``mcp`` package isn't installed (the default test env),
    build_mcp_server should raise ImportError with installation guidance
    pointing at the forge[mcp] extra."""
    from daemon import mcp_server

    with pytest.raises(ImportError, match=r"forge[- ]?orchestrator\[mcp\]|pip install mcp"):
        mcp_server.build_mcp_server()


@pytest.mark.skipif(
    _mcp_installed(), reason="mcp installed; this test exercises the missing-dep path"
)
def test_mcp_server_main_returns_nonzero_when_mcp_missing(capsys):
    """The ``main()`` entry point exits with code 1 instead of raising."""
    from daemon import mcp_server

    rc = mcp_server.main()
    assert rc == 1
    # User-facing message points them at the install command
    captured = capsys.readouterr()
    assert "forge" in captured.out.lower() or "mcp" in captured.out.lower()


@pytest.mark.skipif(not _mcp_installed(), reason="needs forge[mcp] extra")
def test_build_mcp_server_constructs_when_mcp_installed():
    """When mcp is installed, build_mcp_server returns a server with the
    expected tool / resource / prompt set."""
    from daemon import mcp_server

    server = mcp_server.build_mcp_server()
    assert server is not None
    # FastMCP exposes name; sanity check
    assert getattr(server, "name", None) == "forge-kb"
