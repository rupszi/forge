"""Append-only audit-log tests for ``skill_invocations`` (Sprint 6.1.3).

Layer 7 of the seven-layer security model: every plugin invocation —
skill, connector, LLM adapter — writes a row that no later code path
can edit or delete. The triggers in daemon/db.py refuse UPDATE / DELETE;
the DB methods only ever INSERT.

These tests verify:

  - record_invocation_start writes a row with the scoped capabilities
  - record_invocation_finish writes a SEPARATE row (not an UPDATE)
  - direct UPDATE / DELETE on the table is refused by the trigger
  - secrets in args / error are redacted at write time
  - list_invocations honours plugin_name and sprint_id filters
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from daemon.db import ForgeDB


@pytest.fixture
def db(tmp_path: Path) -> ForgeDB:
    db_path = str(tmp_path / "forge.db")
    return ForgeDB(db_path)


# ---- INSERT path ----


def test_record_invocation_start_inserts_row(db: ForgeDB) -> None:
    rowid = db.record_invocation_start(
        invocation_id="inv-1",
        plugin_kind="skill",
        plugin_name="csv-cleaner",
        plugin_version="0.2.0",
        manifest_sha256="abc" * 21 + "a",  # 64 chars
        sprint_id="sprint-x",
        session_id="session-y",
        capabilities={"network": ["api.example.com"], "filesystem": ["${WORKTREE}"]},
        args=["--in", "data.csv"],
    )
    assert rowid > 0
    rows = db.list_invocations(plugin_name="csv-cleaner")
    assert len(rows) == 1
    assert rows[0]["plugin_name"] == "csv-cleaner"
    assert rows[0]["plugin_kind"] == "skill"
    assert rows[0]["sprint_id"] == "sprint-x"
    assert rows[0]["finished_at"] is None  # only the start row written


def test_record_invocation_finish_writes_separate_row(db: ForgeDB) -> None:
    """The 'finish' is an INSERT, not an UPDATE. After the pair lands we
    expect two rows for the same invocation_id."""
    db.record_invocation_start(
        invocation_id="inv-2",
        plugin_kind="connector",
        plugin_name="github",
        plugin_version="0.1.0",
        manifest_sha256="d" * 64,
        sprint_id="sprint-y",
        session_id="session-z",
        capabilities={"network": ["api.github.com"]},
        args=[],
    )
    db.record_invocation_finish(
        invocation_id="inv-2",
        plugin_kind="connector",
        plugin_name="github",
        plugin_version="0.1.0",
        manifest_sha256="d" * 64,
        sprint_id="sprint-y",
        session_id="session-z",
        capabilities={"network": ["api.github.com"]},
        duration_seconds=1.23,
        exit_code=0,
        ok=True,
    )
    rows = db.list_invocations(plugin_name="github")
    # newest first, so [0] is the finish row, [1] is the start row
    assert len(rows) == 2
    assert rows[0]["finished_at"] is not None
    assert rows[0]["ok"] == 1
    assert rows[1]["finished_at"] is None
    assert all(r["invocation_id"] == "inv-2" for r in rows)


def test_capability_violations_round_trip(db: ForgeDB) -> None:
    db.record_invocation_finish(
        invocation_id="inv-3",
        plugin_kind="skill",
        plugin_name="bad-plugin",
        plugin_version="0.0.1",
        manifest_sha256="0" * 64,
        sprint_id=None,
        session_id=None,
        capabilities=None,
        duration_seconds=0.05,
        exit_code=1,
        ok=False,
        error="CapabilityViolation: tried to fetch evil.com",
        capability_violations=["egress: evil.com"],
    )
    rows = db.list_invocations(plugin_name="bad-plugin")
    assert len(rows) == 1
    assert "egress: evil.com" in rows[0]["capability_violations"]


# ---- Write-once trigger refuses UPDATE / DELETE ----


def test_update_is_refused(db: ForgeDB) -> None:
    db.record_invocation_start(
        invocation_id="inv-update",
        plugin_kind="skill",
        plugin_name="x",
        plugin_version="0.1.0",
        manifest_sha256="a" * 64,
        sprint_id=None,
        session_id=None,
        capabilities=None,
        args=[],
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db._conn.execute("UPDATE skill_invocations SET plugin_name = 'tampered'")


def test_delete_is_refused(db: ForgeDB) -> None:
    db.record_invocation_start(
        invocation_id="inv-delete",
        plugin_kind="skill",
        plugin_name="y",
        plugin_version="0.1.0",
        manifest_sha256="b" * 64,
        sprint_id=None,
        session_id=None,
        capabilities=None,
        args=[],
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db._conn.execute("DELETE FROM skill_invocations")


def test_truncate_via_delete_all_is_refused(db: ForgeDB) -> None:
    """Even a 'delete everything' attempt fails — the trigger fires per-row."""
    for i in range(3):
        db.record_invocation_start(
            invocation_id=f"inv-mass-{i}",
            plugin_kind="skill",
            plugin_name="z",
            plugin_version="0.1.0",
            manifest_sha256="c" * 64,
            sprint_id=None,
            session_id=None,
            capabilities=None,
            args=[],
        )
    with pytest.raises(sqlite3.IntegrityError):
        db._conn.execute("DELETE FROM skill_invocations WHERE 1=1")


# ---- Secret redaction at write time ----


def test_args_with_credential_get_redacted(db: ForgeDB) -> None:
    """An arg that looks like an API key is replaced with [REDACTED:...] before
    landing in the DB. The audit trail has structural integrity but no key."""
    db.record_invocation_start(
        invocation_id="inv-redact",
        plugin_kind="connector",
        plugin_name="leaky",
        plugin_version="0.1.0",
        manifest_sha256="e" * 64,
        sprint_id=None,
        session_id=None,
        capabilities=None,
        args=[
            "--token",
            "sk-ant-api03-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        ],
    )
    rows = db.list_invocations(plugin_name="leaky")
    args_json = rows[0]["args_json"]
    assert "sk-ant-api03-zzzzzz" not in args_json
    # The redactor should leave a [REDACTED:...] marker so we can prove the
    # row didn't simply lose data (audit usefulness preserved).
    assert "REDACTED" in args_json or "redacted" in args_json.lower()


def test_error_with_credential_redacted_on_finish(db: ForgeDB) -> None:
    db.record_invocation_finish(
        invocation_id="inv-err",
        plugin_kind="skill",
        plugin_name="errsink",
        plugin_version="0.1.0",
        manifest_sha256="f" * 64,
        sprint_id=None,
        session_id=None,
        capabilities=None,
        duration_seconds=0.01,
        exit_code=1,
        ok=False,
        error="401 Bearer sk-ant-api03-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    )
    rows = db.list_invocations(plugin_name="errsink")
    err = rows[0]["error"] or ""
    assert "sk-ant-api03-XXXXXXX" not in err
    assert "REDACTED" in err or "redacted" in err.lower()


# ---- Filters ----


def test_list_invocations_filter_by_sprint(db: ForgeDB) -> None:
    for sid, name in [("s-1", "a"), ("s-1", "b"), ("s-2", "c")]:
        db.record_invocation_start(
            invocation_id=f"inv-{sid}-{name}",
            plugin_kind="skill",
            plugin_name=name,
            plugin_version="0.1.0",
            manifest_sha256="0" * 64,
            sprint_id=sid,
            session_id="sess",
            capabilities=None,
            args=[],
        )
    rows = db.list_invocations(sprint_id="s-1")
    names = {r["plugin_name"] for r in rows}
    assert names == {"a", "b"}


def test_table_counts_includes_skill_invocations(db: ForgeDB) -> None:
    """Doctor / status surfaces the audit-log size — verify it's in the dict."""
    counts = db.table_counts()
    assert "skill_invocations" in counts
    assert counts["skill_invocations"] == 0
