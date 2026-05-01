"""``.forge/plugins.lock`` tests (Sprint 6.1.4).

The lock file is what makes plugin signing real: load → hash → verify
against pinned digest. A mismatch raises SkillTampered, which the
dispatcher catches and refuses-to-run with a clear message.

Coverage:
  - empty / missing file is the empty lock (fresh project)
  - pin → save → re-load round trip preserves all fields
  - verify() on an unpinned plugin raises SkillTampered("not pinned")
  - verify() on a hash mismatch raises SkillTampered("hash mismatch")
  - capability diff returns None when unchanged, dict on change
  - schema_version too-new is rejected at load
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from daemon.skills import PluginsLock, SkillTampered, default_lock_path

# ---- empty / fresh ----


def test_empty_lock_when_file_missing(tmp_path: Path) -> None:
    lock = PluginsLock(tmp_path / "plugins.lock")
    assert lock.all_entries() == {}
    assert lock.has("skill", "anything") is False
    assert lock.get("connector", "anything") is None


def test_default_path_helper() -> None:
    p = default_lock_path(Path("/x/project"))
    assert str(p).endswith(".forge/plugins.lock")


# ---- pin / save / re-load ----


def test_pin_and_save_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "plugins.lock"
    lock = PluginsLock(path)
    lock.pin(
        "skill",
        "csv-cleaner",
        sha256="a" * 64,
        version="0.2.0",
        approved_capabilities={
            "network": ["api.example.com"],
            "filesystem": ["${WORKTREE}"],
            "memory_mb": 256,
        },
    )
    lock.pin(
        "connector",
        "github",
        sha256="b" * 64,
        version="0.1.0",
        approved_capabilities={"network": ["api.github.com"]},
    )
    lock.save()
    assert path.is_file()

    # Round-trip
    reloaded = PluginsLock(path)
    assert reloaded.has("skill", "csv-cleaner")
    assert reloaded.has("connector", "github")
    csv = reloaded.get("skill", "csv-cleaner")
    assert csv is not None
    assert csv.sha256 == "a" * 64
    assert csv.version == "0.2.0"
    assert csv.approved_capabilities["network"] == ["api.example.com"]
    assert csv.approved_capabilities["memory_mb"] == 256


def test_pin_replaces_existing_entry(tmp_path: Path) -> None:
    """Re-pinning the same plugin updates the entry in place — caller
    decides when to do this (typically after a re-approval prompt)."""
    lock = PluginsLock(tmp_path / "plugins.lock")
    lock.pin("skill", "x", sha256="1" * 64, version="0.1.0")
    lock.pin("skill", "x", sha256="2" * 64, version="0.2.0")
    entry = lock.get("skill", "x")
    assert entry is not None
    assert entry.sha256 == "2" * 64
    assert entry.version == "0.2.0"


def test_unpin_removes_entry(tmp_path: Path) -> None:
    lock = PluginsLock(tmp_path / "plugins.lock")
    lock.pin("skill", "x", sha256="0" * 64)
    assert lock.unpin("skill", "x") is True
    assert lock.has("skill", "x") is False
    assert lock.unpin("skill", "x") is False  # second call no-op


def test_make_key_validates_kind() -> None:
    with pytest.raises(ValueError, match="unknown plugin kind"):
        PluginsLock.make_key("invalid", "name")


# ---- verify() refusal cases ----


def test_verify_unpinned_raises_skill_tampered(tmp_path: Path) -> None:
    lock = PluginsLock(tmp_path / "plugins.lock")
    with pytest.raises(SkillTampered, match="not pinned"):
        lock.verify("skill", "ghost", current_sha256="x" * 64)


def test_verify_hash_mismatch_raises_skill_tampered(tmp_path: Path) -> None:
    lock = PluginsLock(tmp_path / "plugins.lock")
    lock.pin("skill", "x", sha256="aaaa" + "0" * 60)
    with pytest.raises(SkillTampered, match="hash mismatch"):
        lock.verify("skill", "x", current_sha256="bbbb" + "0" * 60)


def test_verify_matching_hash_passes_silently(tmp_path: Path) -> None:
    lock = PluginsLock(tmp_path / "plugins.lock")
    lock.pin("skill", "x", sha256="9" * 64)
    # Should not raise
    lock.verify("skill", "x", current_sha256="9" * 64)


def test_skill_tampered_message_names_plugin_and_kind(tmp_path: Path) -> None:
    """The dispatcher / CLI surfaces this directly to the user — must
    contain enough detail to act on."""
    lock = PluginsLock(tmp_path / "plugins.lock")
    lock.pin("connector", "github", sha256="1" * 64)
    with pytest.raises(SkillTampered) as exc_info:
        lock.verify("connector", "github", current_sha256="2" * 64)
    msg = str(exc_info.value)
    assert "github" in msg
    assert "connector" in msg
    assert "hash mismatch" in msg


# ---- capability diff ----


def test_diff_capabilities_returns_none_when_equal(tmp_path: Path) -> None:
    lock = PluginsLock(tmp_path / "plugins.lock")
    lock.pin(
        "skill",
        "x",
        sha256="0" * 64,
        approved_capabilities={"network": ["api.x.com"]},
    )
    assert lock.diff_capabilities("skill", "x", {"network": ["api.x.com"]}) is None


def test_diff_capabilities_surfaces_added_host(tmp_path: Path) -> None:
    lock = PluginsLock(tmp_path / "plugins.lock")
    lock.pin(
        "skill",
        "x",
        sha256="0" * 64,
        approved_capabilities={"network": ["api.x.com"]},
    )
    diff = lock.diff_capabilities("skill", "x", {"network": ["api.x.com", "evil.com"]})
    assert diff is not None
    assert "network" in diff
    old, new = diff["network"]
    assert old == ["api.x.com"]
    assert "evil.com" in new


def test_diff_capabilities_returns_none_for_unknown_plugin(tmp_path: Path) -> None:
    lock = PluginsLock(tmp_path / "plugins.lock")
    assert lock.diff_capabilities("skill", "ghost", {"network": ["x"]}) is None


# ---- schema versioning ----


def test_load_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "plugins.lock"
    path.write_text("schema_version = 99\n")
    with pytest.raises(ValueError, match=r"schema_version=99"):
        PluginsLock(path)


def test_lock_file_is_human_readable(tmp_path: Path) -> None:
    """The lock format is TOML so users can audit it in PRs. Verify the
    serialized form is sensible (not binary, contains the names)."""
    path = tmp_path / "plugins.lock"
    lock = PluginsLock(path)
    lock.pin(
        "skill",
        "csv-cleaner",
        sha256="a" * 64,
        version="0.2.0",
        approved_capabilities={"network": ["api.example.com"]},
    )
    lock.save()
    text = path.read_text()
    assert "csv-cleaner" in text
    assert "api.example.com" in text
    assert "schema_version" in text
    # Not binary, not JSON
    assert text.strip().startswith("#") or "schema_version" in text.split("\n", 1)[0]
    # Idempotent re-save — content shape is stable (sorting)
    lock.save()
    assert path.read_text() == text


# ---- capability snapshot survives round-trip with mixed types ----


def test_capabilities_with_int_and_string_lists_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "plugins.lock"
    lock = PluginsLock(path)
    lock.pin(
        "skill",
        "x",
        sha256="0" * 64,
        approved_capabilities={
            "network": ["a.com", "b.com"],
            "memory_mb": 512,
            "wall_seconds": 90,
        },
    )
    lock.save()
    reloaded = PluginsLock(path)
    caps = reloaded.get("skill", "x").approved_capabilities
    assert caps["network"] == ["a.com", "b.com"]
    assert caps["memory_mb"] == 512
    assert caps["wall_seconds"] == 90


def test_invalid_lock_file_treated_as_empty(tmp_path: Path) -> None:
    """A malformed TOML file shouldn't crash the daemon — treat as empty
    and let the dispatcher raise SkillTampered("not pinned") for any
    plugin that tries to run. This is conservative: never fail open."""
    path = tmp_path / "plugins.lock"
    path.write_text("this is not valid TOML [[[")
    lock = PluginsLock(path)
    # Empty but loaded
    assert lock.all_entries() == {}
    # And SkillTampered fires for any verify attempt
    with pytest.raises(SkillTampered, match=re.compile(r"not pinned")):
        lock.verify("skill", "x", current_sha256="0" * 64)
