"""Reference connector tests (Sprint 6.4).

Two reference plugins ship with the daemon as worked examples of the
plugin contract:

  reference_plugins/git/             — read-only git ops on a worktree
  reference_plugins/web_research/    — allow-listed HTTP fetch

These tests exercise both end-to-end through the dispatcher. They are
the only tests in the suite that load *real* plugin manifests off
disk and run them through the live sandbox runtime.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from daemon.db import ForgeDB
from daemon.scheduler import dispatch_plugin
from daemon.skills import PluginsLock
from daemon.skills.registry import load_skill

# Repo root — where reference_plugins/ lives.
REPO_ROOT = Path(__file__).resolve().parent.parent
GIT_PLUGIN_DIR = REPO_ROOT / "reference_plugins" / "git"
WEB_PLUGIN_DIR = REPO_ROOT / "reference_plugins" / "web_research"


# ---- Manifest sanity ----


def test_git_manifest_loads() -> None:
    """The git reference connector's manifest passes all the
    refused-capability gates (no shell, no wildcard network, no system
    paths) and exposes the expected scope."""
    entry = load_skill(GIT_PLUGIN_DIR)
    assert entry.manifest.name == "git"
    assert entry.manifest.network == []
    assert entry.manifest.filesystem == ["${WORKTREE}"]
    assert entry.manifest.exec == []
    assert entry.manifest.secrets_read == []
    # SHA-256 hex
    assert len(entry.manifest_sha256) == 64


def test_web_research_manifest_loads() -> None:
    entry = load_skill(WEB_PLUGIN_DIR)
    assert entry.manifest.name == "web_research"
    # Allow-list is the contract — verify the docs hosts are present
    assert "*.python.org" in entry.manifest.network
    assert "developer.mozilla.org" in entry.manifest.network
    assert "raw.githubusercontent.com" in entry.manifest.network
    # No secrets needed
    assert entry.manifest.secrets_read == []


# ---- git connector — dispatch end-to-end ----


@pytest.mark.asyncio
async def test_git_connector_healthcheck_via_dispatcher(tmp_path: Path) -> None:
    """Pin the git plugin in a fresh lock, dispatch with no args,
    expect git's --version to appear on stdout."""
    if not shutil.which("git"):
        pytest.skip("git not on PATH")

    db = ForgeDB(str(tmp_path / "forge.db"))
    lock = PluginsLock(tmp_path / "plugins.lock")

    entry = load_skill(GIT_PLUGIN_DIR)
    lock.pin("skill", "git", sha256=entry.manifest_sha256)

    # Initialize a small repo in tmp_path so cwd has something for git
    # to talk to. The plugin's cwd defaults to plugin_path; we override
    # to the tmp repo.
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)

    result = await dispatch_plugin(
        kind="skill",
        name="git",
        plugin_path=GIT_PLUGIN_DIR,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        args=[],  # healthcheck
        db=db,
        lock=lock,
        cwd=tmp_path,
    )

    assert result.ok, result.error
    assert result.sandbox_result is not None
    assert "git version" in result.sandbox_result.stdout
    db.close()


@pytest.mark.asyncio
async def test_git_connector_status_returns_clean_tree(tmp_path: Path) -> None:
    if not shutil.which("git"):
        pytest.skip("git not on PATH")

    # Keep the SQLite DB OUT of the tmp git repo so it doesn't show as
    # untracked in `git status`.
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    db = ForgeDB(str(db_dir / "forge.db"))
    lock = PluginsLock(db_dir / "plugins.lock")

    entry = load_skill(GIT_PLUGIN_DIR)
    lock.pin("skill", "git", sha256=entry.manifest_sha256)

    subprocess.run(["git", "init", "-q"], cwd=str(repo_dir), check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@x",
            "-c",
            "user.name=T",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )

    result = await dispatch_plugin(
        kind="skill",
        name="git",
        plugin_path=GIT_PLUGIN_DIR,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        args=["status", "--short"],
        db=db,
        lock=lock,
        cwd=repo_dir,
    )

    assert result.ok, result.error
    # Empty stdout for `git status --short` on a clean tree
    assert result.sandbox_result.stdout == ""
    db.close()


@pytest.mark.asyncio
async def test_git_connector_refuses_mutating_op(tmp_path: Path) -> None:
    """``git commit`` is not in the read-only allow-list. The plugin's
    own gate refuses with exit 2 and a 'refused' message — the
    dispatcher reports the failure but the audit log still captures it."""
    if not shutil.which("git"):
        pytest.skip("git not on PATH")

    db = ForgeDB(str(tmp_path / "forge.db"))
    lock = PluginsLock(tmp_path / "plugins.lock")

    entry = load_skill(GIT_PLUGIN_DIR)
    lock.pin("skill", "git", sha256=entry.manifest_sha256)

    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)

    result = await dispatch_plugin(
        kind="skill",
        name="git",
        plugin_path=GIT_PLUGIN_DIR,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        args=["commit", "-m", "boom"],
        db=db,
        lock=lock,
        cwd=tmp_path,
    )

    assert result.ok is False
    assert result.sandbox_result is not None
    assert result.sandbox_result.exit_code == 2
    assert "refused" in result.sandbox_result.stderr
    # Audit captures both rows (start + finish)
    rows = db.list_invocations(plugin_name="git")
    assert len(rows) == 2
    db.close()


@pytest.mark.asyncio
async def test_git_connector_refuses_mutating_flag_on_allowed_op(tmp_path: Path) -> None:
    """``git branch`` is allowed (lists branches), but ``--delete`` is
    in MUTATING_FLAGS — the wrapper refuses regardless of the operation."""
    if not shutil.which("git"):
        pytest.skip("git not on PATH")

    db = ForgeDB(str(tmp_path / "forge.db"))
    lock = PluginsLock(tmp_path / "plugins.lock")

    entry = load_skill(GIT_PLUGIN_DIR)
    lock.pin("skill", "git", sha256=entry.manifest_sha256)

    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)

    result = await dispatch_plugin(
        kind="skill",
        name="git",
        plugin_path=GIT_PLUGIN_DIR,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        args=["branch", "--delete", "main"],
        db=db,
        lock=lock,
        cwd=tmp_path,
    )

    assert result.ok is False
    assert result.sandbox_result.exit_code == 2
    assert "mutating" in result.sandbox_result.stderr.lower()
    db.close()


# ---- web_research connector — dispatch + egress contract ----


@pytest.mark.asyncio
async def test_web_research_healthcheck_proves_env_arrived(tmp_path: Path) -> None:
    """Healthcheck (no args) prints the FORGE_NETWORK_ALLOWLIST it sees,
    proving the dispatcher's env injection landed correctly."""
    db = ForgeDB(str(tmp_path / "forge.db"))
    lock = PluginsLock(tmp_path / "plugins.lock")

    entry = load_skill(WEB_PLUGIN_DIR)
    lock.pin("skill", "web_research", sha256=entry.manifest_sha256)

    # The plugin imports forge_plugin_api — make sure the subprocess
    # can find it. Inheriting PYTHONPATH from the running test env is
    # enough since the test runs with PYTHONPATH=. .
    env_pythonpath = os.environ.get("PYTHONPATH", "")
    if "PYTHONPATH" not in os.environ or str(REPO_ROOT) not in env_pythonpath:
        os.environ["PYTHONPATH"] = (
            f"{REPO_ROOT}{os.pathsep}{env_pythonpath}" if env_pythonpath else str(REPO_ROOT)
        )

    result = await dispatch_plugin(
        kind="skill",
        name="web_research",
        plugin_path=WEB_PLUGIN_DIR,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        args=[],
        db=db,
        lock=lock,
    )

    assert result.ok, result.error
    assert result.sandbox_result is not None
    out = result.sandbox_result.stdout
    assert "web_research healthcheck" in out
    # The allow-list lands intact
    assert "*.python.org" in out
    db.close()


@pytest.mark.asyncio
async def test_web_research_refuses_non_allowlisted_url(tmp_path: Path) -> None:
    """Headline acceptance gate: a fetch to a host NOT on the manifest's
    allow-list is refused by the egress shim before any packet fires.
    Exit code 2, 'refused' on stderr, audit log captures."""
    db = ForgeDB(str(tmp_path / "forge.db"))
    lock = PluginsLock(tmp_path / "plugins.lock")

    entry = load_skill(WEB_PLUGIN_DIR)
    lock.pin("skill", "web_research", sha256=entry.manifest_sha256)

    env_pythonpath = os.environ.get("PYTHONPATH", "")
    if "PYTHONPATH" not in os.environ or str(REPO_ROOT) not in env_pythonpath:
        os.environ["PYTHONPATH"] = (
            f"{REPO_ROOT}{os.pathsep}{env_pythonpath}" if env_pythonpath else str(REPO_ROOT)
        )

    result = await dispatch_plugin(
        kind="skill",
        name="web_research",
        plugin_path=WEB_PLUGIN_DIR,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        args=["https://evil.com/exfil"],
        db=db,
        lock=lock,
    )

    assert result.ok is False
    assert result.sandbox_result is not None
    assert result.sandbox_result.exit_code == 2
    assert "refused" in result.sandbox_result.stderr
    assert "evil.com" in result.sandbox_result.stderr
    db.close()
