"""Tests for daemon/replay.py — JSONL trace I/O + ``forge replay`` (Phase 3 W11)."""

from __future__ import annotations

import json
from pathlib import Path

from daemon import replay

# ---- append_event ----
# (``tmp_forge_dir`` now lives in tests/conftest.py — Task 2.5)


def test_append_event_creates_session_dir(tmp_forge_dir):
    replay.append_event("session-abc", "session.start", data={"objective": "x"})

    trace_path = tmp_forge_dir / "sessions" / "session-abc" / "trace.jsonl"
    assert trace_path.exists()
    contents = trace_path.read_text().strip()
    parsed = json.loads(contents)
    assert parsed["type"] == "session.start"
    assert parsed["session_id"] == "session-abc"
    assert parsed["data"] == {"objective": "x"}
    assert "ts" in parsed


def test_append_event_includes_timestamp_iso8601(tmp_forge_dir):
    replay.append_event("session-1", "x.y")
    contents = (tmp_forge_dir / "sessions" / "session-1" / "trace.jsonl").read_text()
    parsed = json.loads(contents.strip())
    # Should be parseable as datetime
    from datetime import datetime

    datetime.fromisoformat(parsed["ts"].replace("Z", "+00:00"))


def test_append_event_appends_multiple(tmp_forge_dir):
    for i in range(5):
        replay.append_event("session-x", f"step.{i}", data={"n": i})

    lines = (
        (tmp_forge_dir / "sessions" / "session-x" / "trace.jsonl").read_text().strip().splitlines()
    )
    assert len(lines) == 5
    types = [json.loads(line)["type"] for line in lines]
    assert types == [f"step.{i}" for i in range(5)]


def test_append_event_handles_sprint_id(tmp_forge_dir):
    replay.append_event(
        "session-1", "generator.invoke", sprint_id="sprint-42", data={"model": "qwen"}
    )
    parsed = json.loads(
        (tmp_forge_dir / "sessions" / "session-1" / "trace.jsonl").read_text().strip()
    )
    assert parsed["sprint_id"] == "sprint-42"


def test_append_event_doesnt_raise_on_io_error(tmp_forge_dir, monkeypatch):
    """A failed write logs but doesn't raise — observability shouldn't crash
    the primary code path."""
    # Simulate a permission error by patching Path.open
    original_open = Path.open

    def failing_open(self, *args, **kwargs):
        if "trace.jsonl" in str(self):
            raise PermissionError("denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    # Should NOT raise
    replay.append_event("session-1", "x")


# ---- read_trace ----


def test_read_trace_empty_session_returns_empty_list(tmp_forge_dir):
    assert replay.read_trace("nonexistent") == []


def test_read_trace_returns_chronological_events(tmp_forge_dir):
    replay.append_event("s", "a", data={"i": 1})
    replay.append_event("s", "b", data={"i": 2})
    replay.append_event("s", "c", data={"i": 3})

    events = replay.read_trace("s")
    assert len(events) == 3
    assert [e["type"] for e in events] == ["a", "b", "c"]


def test_read_trace_skips_malformed_lines(tmp_forge_dir):
    """A corrupted line (e.g., partial flush) shouldn't fail the whole replay."""
    trace_path = tmp_forge_dir / "sessions" / "s" / "trace.jsonl"
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-01-01T00:00:00Z",
                "type": "good",
                "session_id": "s",
                "sprint_id": None,
                "data": {},
            }
        )
        + "\n"
        + "{not valid json\n"
        + json.dumps(
            {
                "ts": "2026-01-01T00:00:01Z",
                "type": "also_good",
                "session_id": "s",
                "sprint_id": None,
                "data": {},
            }
        )
        + "\n"
    )

    events = replay.read_trace("s")
    assert len(events) == 2
    assert [e["type"] for e in events] == ["good", "also_good"]


# ---- list_sessions ----


def test_list_sessions_empty_returns_empty_list(tmp_forge_dir):
    assert replay.list_sessions() == []


def test_list_sessions_returns_only_dirs_with_trace(tmp_forge_dir):
    # Create one session with trace and one without
    (tmp_forge_dir / "sessions").mkdir(exist_ok=True)
    (tmp_forge_dir / "sessions" / "session-with-trace").mkdir()
    (tmp_forge_dir / "sessions" / "session-with-trace" / "trace.jsonl").write_text("")
    (tmp_forge_dir / "sessions" / "session-without").mkdir()

    sessions = replay.list_sessions()
    assert "session-with-trace" in sessions
    assert "session-without" not in sessions


def test_list_sessions_returns_newest_first(tmp_forge_dir):
    """Reverse-sorted (timestamp-prefixed IDs sort newest first this way)."""
    for sid in ("session-001", "session-002", "session-003"):
        replay.append_event(sid, "x")

    sessions = replay.list_sessions()
    assert sessions == ["session-003", "session-002", "session-001"]


# ---- replay_to_stdout ----


def test_replay_to_stdout_empty_session(tmp_forge_dir, capsys):
    rc = replay.replay_to_stdout("nonexistent")
    captured = capsys.readouterr()
    assert "No trace" in captured.out
    assert rc == 0


def test_replay_to_stdout_pretty(tmp_forge_dir, capsys):
    replay.append_event("s", "planner.decision", data={"complexity": "medium"})
    replay.append_event(
        "s", "generator.invoke", sprint_id="sprint-1", data={"model": "qwen3.6:27b"}
    )

    rc = replay.replay_to_stdout("s", pretty=True)
    out = capsys.readouterr().out

    assert rc == 2
    assert "planner.decision" in out
    assert "generator.invoke" in out
    assert "sprint-1" in out
    assert "qwen3.6:27b" in out


def test_replay_to_stdout_raw_jsonl(tmp_forge_dir, capsys):
    replay.append_event("s", "x", data={"a": 1})

    replay.replay_to_stdout("s", pretty=False)
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["type"] == "x"


def test_replay_summarize_truncates_long_values(tmp_forge_dir, capsys):
    huge = "x" * 500
    replay.append_event("s", "big", data={"output": huge})

    replay.replay_to_stdout("s", pretty=True)
    out = capsys.readouterr().out
    # Truncated to ~80 chars + ellipsis
    assert "…" in out or len(out) < 500


def test_replay_summarize_handles_nested_data(tmp_forge_dir, capsys):
    replay.append_event("s", "complex", data={"sprints": [{"a": 1}, {"b": 2}]})

    replay.replay_to_stdout("s", pretty=True)
    out = capsys.readouterr().out
    # Should mark nested structure rather than dump it
    assert "list" in out.lower() or "complex" in out
