"""Tests for daemon/events.py — EventType enum (Task 3.3).

Sanity tests around the canonical event-type registry. The on-the-wire
strings are part of Forge's audit-log contract — once an event lands in
trace.jsonl files in user projects, renaming it without a migration would
break replay tooling. These tests pin the values so a future refactor
trips the gate before shipping.
"""

from __future__ import annotations

from daemon.events import EventType


def test_event_values_are_strings():
    """Every EventType value is a plain string (str-Enum shape)."""
    for member in EventType:
        assert isinstance(member.value, str), member


def test_event_namespacing_matches_section():
    """Every value is dotted (``namespace.event``) and the namespace prefix
    matches its enum section in the source. This catches stray values that
    drifted out of their convention."""
    section_prefix = {
        "SESSION_": "session.",
        "REPOMAP_": "repomap.",
        "PLAN_": "plan.",
        "WAVE_": "wave.",
        "WORKTREE_": "worktree.",
        "SPRINT_": "sprint.",
        "RECOVERY_": "recovery.",
        "BUDGET_": "budget.",
    }
    for member in EventType:
        for prefix, ns in section_prefix.items():
            if member.name.startswith(prefix):
                assert member.value.startswith(ns), (
                    f"{member.name} = {member.value!r} doesn't start with namespace {ns!r}"
                )
                break


def test_known_canonical_values_are_pinned():
    """Specific values that downstream tooling depends on must stay stable.
    If you intentionally rename one of these, update both this test and any
    docs that reference the old name.
    """
    assert EventType.SESSION_START.value == "session.start"
    assert EventType.SPRINT_APPROVED.value == "sprint.approved"
    assert EventType.SPRINT_RECOVERED.value == "sprint.recovered"  # Task 1.1
    assert EventType.BUDGET_EXHAUSTED.value == "budget.exhausted"  # Task 2.2
    assert EventType.RECOVERY_ADAPT_DECOMPOSED.value == "recovery.adapt.decomposed"


def test_no_duplicate_values():
    """Each event type maps to a unique string. Without this guard a typo
    could shadow another event silently."""
    values = [m.value for m in EventType]
    assert len(values) == len(set(values))
