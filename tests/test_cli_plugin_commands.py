"""``forge connectors`` / ``forge skills`` CLI tests (Sprint 6.1.6).

The CLI is the user-visible surface for plugin lifecycle management.
v0.1.0 covers four actions: ``add`` / ``install`` (load + pin),
``list`` (show pinned), ``test`` (healthcheck via dispatcher),
``remove`` (unpin).

Tests run the command functions directly with a parsed args namespace —
no subprocess required. The dispatcher is exercised end-to-end on a
real spawn for the ``test`` action (this is the headline acceptance
gate of 6.1.6).
"""

from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path

import pytest

from daemon.cli import cmd_connectors, cmd_skills
from daemon.skills import PluginsLock, default_lock_path


def _write_minimal_skill(path: Path, *, name: str = "scribe", script: str = "print('ok')") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"# {name}\n\nhealthcheck")
    (path / "manifest.toml").write_text(f"""
[plugin]
name = "{name}"
version = "0.1.0"
description = "test"

[skill]
when_to_use = "test"
entry_script = "scripts/main.py"

[capabilities]
network = []
filesystem = []
exec = []
secrets_read = []

[limits]
memory_mb = 128
cpu_seconds = 5
wall_seconds = 10
""")
    (path / "scripts").mkdir(exist_ok=True)
    (path / "scripts" / "main.py").write_text(script)
    return path


def _write_minimal_connector(path: Path, *, name: str = "github") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.toml").write_text(f"""
[plugin]
name = "{name}"
version = "0.1.0"
description = "test"

[capabilities]
network = []
filesystem = []
exec = []
secrets_read = []

[limits]
memory_mb = 128
cpu_seconds = 5
wall_seconds = 10
""")
    (path / "scripts").mkdir(exist_ok=True)
    (path / "scripts" / "main.py").write_text("print('hi')")
    return path


@pytest.fixture
def chdir_to(tmp_path: Path):
    """cd to tmp_path so the CLI's project-root detection finds .forge/ here."""
    prev = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(prev)


# ---- skills add → list → test → remove ----


def test_skills_add_pins_to_lock(chdir_to: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugin_dir = _write_minimal_skill(chdir_to / "src" / "scribe")
    args = Namespace(action="add", name=str(plugin_dir), path=None)
    rc = cmd_skills(args)
    assert rc == 0

    out = capsys.readouterr().out
    assert "pinned skill:scribe" in out

    # Verify the lock got the entry
    lock = PluginsLock(default_lock_path(chdir_to))
    assert lock.has("skill", "scribe")


def test_skills_install_alias_works(chdir_to: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``install`` is an alias for ``add`` (familiar to users coming from
    `forge skills install` per the docs)."""
    plugin_dir = _write_minimal_skill(chdir_to / "src" / "x", name="x")
    args = Namespace(action="install", name=str(plugin_dir), path=None)
    rc = cmd_skills(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "pinned skill:x" in out


def test_skills_list_shows_pinned(chdir_to: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugin_dir = _write_minimal_skill(chdir_to / "src" / "viewer", name="viewer")
    cmd_skills(Namespace(action="add", name=str(plugin_dir), path=None))
    capsys.readouterr()  # drain

    rc = cmd_skills(Namespace(action="list", name="", path=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert "viewer" in out


def test_skills_remove_unpins(chdir_to: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugin_dir = _write_minimal_skill(chdir_to / "src" / "v", name="v")
    cmd_skills(Namespace(action="add", name=str(plugin_dir), path=None))
    capsys.readouterr()

    rc = cmd_skills(Namespace(action="remove", name="v", path=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert "unpinned skill:v" in out

    lock = PluginsLock(default_lock_path(chdir_to))
    assert not lock.has("skill", "v")


def test_skills_test_passes_for_healthy_skill(
    chdir_to: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-to-end: pin a skill that exits 0, then run `forge skills test` —
    the dispatcher spawns it via run_skill, audit log records the outcome,
    CLI prints a success line."""
    plugin_dir = _write_minimal_skill(
        chdir_to / "src" / "ok-skill",
        name="ok-skill",
        script="print('healthcheck OK')",
    )
    cmd_skills(Namespace(action="add", name=str(plugin_dir), path=None))
    capsys.readouterr()

    rc = cmd_skills(Namespace(action="test", name="ok-skill", path=str(plugin_dir)))
    assert rc == 0
    out = capsys.readouterr().out
    assert "healthcheck passed" in out


def test_skills_test_fails_for_crashing_skill(
    chdir_to: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plugin_dir = _write_minimal_skill(
        chdir_to / "src" / "broken",
        name="broken",
        script="import sys; sys.exit(7)",
    )
    cmd_skills(Namespace(action="add", name=str(plugin_dir), path=None))
    capsys.readouterr()

    rc = cmd_skills(Namespace(action="test", name="broken", path=str(plugin_dir)))
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out


def test_skills_test_fails_for_unpinned_plugin(
    chdir_to: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plugin that was never approved must not run, even via `forge skills test`."""
    plugin_dir = _write_minimal_skill(
        chdir_to / "src" / "ghost",
        name="ghost",
    )
    # No `add` call → no lock entry
    rc = cmd_skills(Namespace(action="test", name="ghost", path=str(plugin_dir)))
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "not pinned" in out


def test_skills_add_missing_path(chdir_to: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = Namespace(action="add", name="", path=None)
    rc = cmd_skills(args)
    assert rc == 1
    out = capsys.readouterr().out
    assert "Usage:" in out


def test_skills_test_missing_name(chdir_to: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cmd_skills(Namespace(action="test", name="", path=None))
    assert rc == 1
    out = capsys.readouterr().out
    assert "Usage:" in out


def test_skills_test_missing_directory(chdir_to: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cmd_skills(Namespace(action="test", name="ghost", path=None))
    assert rc == 1
    out = capsys.readouterr().out
    assert "no plugin directory" in out


# ---- connectors mirror the same surface ----


def test_connectors_add_pins_separately_from_skills(
    chdir_to: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A connector and a skill can share a name without colliding —
    the lock keys are namespaced by kind."""
    skill_dir = _write_minimal_skill(chdir_to / "src" / "github-skill", name="github")
    connector_dir = _write_minimal_connector(chdir_to / "src" / "github-conn", name="github")

    cmd_skills(Namespace(action="add", name=str(skill_dir), path=None))
    cmd_connectors(Namespace(action="add", name=str(connector_dir), path=None))
    capsys.readouterr()

    lock = PluginsLock(default_lock_path(chdir_to))
    assert lock.has("skill", "github")
    assert lock.has("connector", "github")
    # Different SHAs because different on-disk content
    assert lock.get("skill", "github").sha256 != lock.get("connector", "github").sha256


def test_connectors_list_only_shows_connectors(
    chdir_to: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``forge connectors list`` filters to connector entries only."""
    skill_dir = _write_minimal_skill(chdir_to / "src" / "skill-only", name="skill-only")
    connector_dir = _write_minimal_connector(
        chdir_to / "src" / "connector-only", name="connector-only"
    )
    cmd_skills(Namespace(action="add", name=str(skill_dir), path=None))
    cmd_connectors(Namespace(action="add", name=str(connector_dir), path=None))
    capsys.readouterr()

    cmd_connectors(Namespace(action="list", name="", path=None))
    out = capsys.readouterr().out
    assert "connector-only" in out
    assert "skill-only" not in out


def test_connector_test_runs_through_dispatcher(
    chdir_to: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The connector test path uses the SAME dispatcher as skills, including
    the audit log — a successful run lands two rows."""
    plugin_dir = _write_minimal_connector(
        chdir_to / "src" / "ok-conn",
        name="ok-conn",
    )
    # Connectors don't need scripts/main.py if the manifest's entry_script
    # default still points there — and our helper writes one.
    cmd_connectors(Namespace(action="add", name=str(plugin_dir), path=None))
    capsys.readouterr()

    rc = cmd_connectors(Namespace(action="test", name="ok-conn", path=str(plugin_dir)))
    assert rc == 0
    out = capsys.readouterr().out
    assert "healthcheck passed" in out

    # Audit log captured the dispatch — two rows (start + finish).
    from daemon.config import DB_PATH
    from daemon.db import ForgeDB

    db = ForgeDB(DB_PATH)
    try:
        rows = db.list_invocations(plugin_name="ok-conn")
        assert len(rows) == 2  # start + finish
    finally:
        db.close()
