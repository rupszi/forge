"""Trace replay — Phase 3 Week 11.

Every Forge session writes a JSONL audit log to
``.forge/sessions/<session_id>/trace.jsonl``. ``forge replay <session_id>``
reads that file back and emits the events to stdout (or to the WebSocket if
the daemon is running) so a developer can:

  - Review what happened, step by step, post-mortem.
  - Re-render a prior session in the dashboard (UI subscribes to the
    replay stream the same way it subscribes to a live session).
  - Export a session to share with another developer ("here's what Forge
    did when I ran X — what would you have done differently?").

Trace event schema (one line of JSON per event in the file):

    {
      "ts": "2026-05-01T12:34:56.789Z",  // ISO-8601 UTC
      "type": "planner.decision" | "generator.invoke" | "evaluator.verdict" | ...,
      "session_id": "session-abc123",
      "sprint_id": "sprint-xyz789" | null,
      "data": { ... event-specific payload ... }
    }

The writer side (``append_event``) is intentionally **not** an asyncio-aware
sink — it's sync stdlib I/O. Trace writing happens from the scheduler /
agents which are already in async context; running fileio sync there is
fine because:

  1. Each event is tiny (~200–500 bytes).
  2. The trace file is line-buffered and append-only.
  3. The OS handles flush-coalescing — no fsync per event.

If profiling shows the sync writes blocking the loop, switch to
``asyncio.to_thread`` for the write (one-line change).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import FORGE_DIR
from .redact import redact_value

logger = logging.getLogger(__name__)


def _trace_path(session_id: str) -> Path:
    """Return the trace file path for a session.

    Resolves under ``.forge/sessions/<session_id>/trace.jsonl``.
    """
    return Path(FORGE_DIR) / "sessions" / session_id / "trace.jsonl"


def append_event(
    session_id: str,
    event_type: str,
    *,
    sprint_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Append a single audit-log event to the session's trace file.

    Creates the parent directory on first write. Failures are logged but
    never raised — the audit log is observability, not a primary code path.

    Parameters
    ----------
    session_id
        Session identifier; determines the trace file path.
    event_type
        Dotted-name identifier (e.g., ``planner.decision``,
        ``generator.invoke``, ``evaluator.verdict``, ``budget.downgrade``,
        ``worktree.created``). Convention: ``<component>.<action>``.
    sprint_id
        Optional sprint identifier. Most events are tied to a sprint;
        session-level events (``session.start`` / ``session.end``) leave
        this None.
    data
        Event-specific payload. JSON-serializable.
    """
    path = _trace_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("trace: cannot create %s: %s", path.parent, e)
        return

    # Redact credentials from the data payload before persisting. This is
    # the single most important leak surface — a generator that echoes an
    # API key from its prompt would otherwise land that key in the audit
    # log on disk. ``redact_value`` recurses into nested dicts/lists so
    # nested ``{"headers": {"Authorization": "Bearer ..."}}`` structures
    # get scrubbed. See daemon/redact.py.
    event = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "type": event_type,
        "session_id": session_id,
        "sprint_id": sprint_id,
        "data": redact_value(data or {}),
    }

    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("trace: failed to append to %s: %s", path, e)


def read_trace(session_id: str) -> list[dict[str, Any]]:
    """Read all events for a session. Returns chronological list.

    Used by ``forge replay <session_id>`` and by the WebSocket replay
    handler. Skips lines that fail to parse (corrupted writes, partial
    flushes) rather than failing the whole replay.
    """
    path = _trace_path(session_id)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_num, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError as e:
                logger.warning("trace: skipping malformed line %d in %s: %s", line_num, path, e)
    return events


def list_sessions() -> list[str]:
    """List all session IDs that have trace files on disk.

    Scans ``.forge/sessions/`` for subdirectories containing a
    ``trace.jsonl`` file. Used by ``forge replay`` (no args) to show the
    user a picklist.
    """
    base = Path(FORGE_DIR) / "sessions"
    if not base.exists():
        return []
    sessions: list[str] = []
    for entry in os.scandir(base):
        if entry.is_dir() and (Path(entry.path) / "trace.jsonl").exists():
            sessions.append(entry.name)
    return sorted(sessions, reverse=True)  # newest first (timestamp-prefixed IDs)


def replay_to_stdout(session_id: str, *, pretty: bool = True) -> int:
    """Read a session's trace and emit each event to stdout.

    Parameters
    ----------
    session_id
        Session to replay.
    pretty
        If True (default), format each event as a human-readable line.
        If False, emit the raw JSONL so the output can be piped to ``jq``
        or another trace processor.

    Returns
    -------
    int
        Number of events emitted; 0 if the session doesn't exist.
    """
    events = read_trace(session_id)
    if not events:
        print(f"No trace found for session {session_id!r}.")
        return 0

    for ev in events:
        if pretty:
            ts = ev.get("ts", "?")
            typ = ev.get("type", "?")
            sprint = f"[{ev['sprint_id']}] " if ev.get("sprint_id") else ""
            data_summary = _summarize_data(ev.get("data") or {})
            print(f"{ts}  {typ:30s} {sprint}{data_summary}")
        else:
            print(json.dumps(ev, ensure_ascii=False))

    return len(events)


def _summarize_data(data: dict[str, Any], max_chars: int = 80) -> str:
    """One-line human summary of an event's payload.

    Keeps the replay output scannable. Long values get truncated with an
    ellipsis; nested dicts and lists are abbreviated.
    """
    if not data:
        return ""
    parts: list[str] = []
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            parts.append(f"{k}=({type(v).__name__})")
        else:
            s = str(v)
            if len(s) > max_chars:
                s = s[:max_chars] + "…"
            parts.append(f"{k}={s}")
    return " ".join(parts)
