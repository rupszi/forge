"""AGENTS.md root-to-leaf walk tests (Sprint 7.4).

The agents.md spec — adopted by Codex CLI and now a registered
convention — augments CLAUDE.md with directory-scoped instructions.
Forge walks root → leaf, collecting AGENTS.md (or AGENTS.override.md)
at each level. The planner injects each as its own context block so
the model can attribute guidance to its origin dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from daemon.scanner.claude_code import read_agents_md
from daemon.scanner.project import scan_project

# ---- direct read_agents_md ----


def test_no_agents_md_returns_empty(tmp_path: Path) -> None:
    assert read_agents_md(str(tmp_path)) == []


def test_root_agents_md_only(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Root rules\nUse pytest.\n")
    out = read_agents_md(str(tmp_path))
    assert len(out) == 1
    rel, content = out[0]
    assert rel == "AGENTS.md"
    assert "Use pytest" in content


def test_root_to_leaf_walk_in_order(tmp_path: Path) -> None:
    """Files at deeper directories come AFTER root in the list — the
    planner needs the order to inject most-specific context last."""
    (tmp_path / "AGENTS.md").write_text("root rules")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "AGENTS.md").write_text("src rules")
    (tmp_path / "src" / "ui").mkdir()
    (tmp_path / "src" / "ui" / "AGENTS.md").write_text("ui rules")

    out = read_agents_md(str(tmp_path), cwd=str(tmp_path / "src" / "ui"))
    paths = [rel for rel, _ in out]
    assert paths == ["AGENTS.md", "src/AGENTS.md", "src/ui/AGENTS.md"]


def test_override_takes_precedence_over_agents_md(tmp_path: Path) -> None:
    """At the same level, AGENTS.override.md wins — the user's local
    customization shadows the team's checked-in AGENTS.md."""
    (tmp_path / "AGENTS.md").write_text("team rules")
    (tmp_path / "AGENTS.override.md").write_text("local override")

    out = read_agents_md(str(tmp_path))
    assert len(out) == 1
    rel, content = out[0]
    assert rel == "AGENTS.override.md"
    assert content == "local override"


def test_empty_agents_md_skipped(tmp_path: Path) -> None:
    """An empty / whitespace-only file shouldn't take up tokens."""
    (tmp_path / "AGENTS.md").write_text("   \n\n  ")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "AGENTS.md").write_text("real rules")

    out = read_agents_md(str(tmp_path), cwd=str(tmp_path / "src"))
    paths = [rel for rel, _ in out]
    assert paths == ["src/AGENTS.md"]


def test_cwd_outside_project_falls_back_to_project(tmp_path: Path) -> None:
    """Defense in depth: caller passes a cwd outside the project root
    (bug, hostile input) — the walker stays inside ``project_path``,
    never escapes upward."""
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "AGENTS.md").write_text("project rules")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "AGENTS.md").write_text("SHOULD NOT READ")

    out = read_agents_md(str(tmp_path / "project"), cwd=str(tmp_path / "outside"))
    paths = [rel for rel, _ in out]
    assert paths == ["AGENTS.md"]
    assert "SHOULD NOT READ" not in out[0][1]


def test_default_cwd_is_project_root(tmp_path: Path) -> None:
    """When cwd is unset, walk degrades to project-root only."""
    (tmp_path / "AGENTS.md").write_text("root only")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "AGENTS.md").write_text("inner")

    out = read_agents_md(str(tmp_path))  # no cwd
    paths = [rel for rel, _ in out]
    assert paths == ["AGENTS.md"]


# ---- scan_project integration ----


@pytest.mark.asyncio
async def test_scan_project_populates_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("root agents.md")
    ctx = await scan_project(str(tmp_path))
    assert len(ctx.agents_md) == 1
    rel, content = ctx.agents_md[0]
    assert rel == "AGENTS.md"
    assert "root agents.md" in content


@pytest.mark.asyncio
async def test_scan_project_to_dict_exposes_count(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("a")
    ctx = await scan_project(str(tmp_path))
    d = ctx.to_dict()
    assert d["agents_md_count"] == 1


@pytest.mark.asyncio
async def test_scan_project_no_agents_md(tmp_path: Path) -> None:
    """Projects that don't use the convention scan cleanly with empty list."""
    ctx = await scan_project(str(tmp_path))
    assert ctx.agents_md == []
    assert ctx.to_dict()["agents_md_count"] == 0
