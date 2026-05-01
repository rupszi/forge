"""Event-type registry (Task 3.3).

Every trace event Forge emits has an EventType entry here. Why an enum:

  - **Typo safety**: misspelling a literal string at a call site is silent
    failure (the UI's switch statement just doesn't match). Misspelling
    ``EventType.SPRINT_APPROVED`` is an AttributeError at import time.
  - **Discoverability**: the UI and ``forge replay`` CLI key off canonical
    names. Adding a new event is a one-file change here, not "remember to
    update the docs / UI / replay summarizer separately."
  - **Refactor-safety**: renaming an event is a single-file find-and-replace
    on the enum entry rather than a project-wide grep.

The enum is a ``str``-Enum (``StrEnum`` shape) so ``EventType.X.value`` is
the on-the-wire string and ``str(EventType.X)`` works as a drop-in for the
literals that previously sat at every call site.

Adding a new event:
  1. Append the entry below (alphabetize within its section).
  2. Use it at the emit site: ``_emit(EventType.MY_NEW_EVENT.value, ...)``.
  3. If the UI / replay summarizer needs special rendering, surface the
     value in the relevant switch.

Section conventions:
  - ``session.*``        Top-level session lifecycle
  - ``plan.*``           Planner output
  - ``wave.*``           Parallel-sprint group lifecycle
  - ``worktree.*``       Filesystem isolation
  - ``sprint.*``         Per-sprint state machine
  - ``recovery.*``       ADaPT + Self-Consistency
  - ``budget.*``         Spend control
  - ``repomap.*``        Code-search context
"""

from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    """Canonical event names emitted to ``.forge/sessions/<id>/trace.jsonl``."""

    # ---- Session lifecycle ----
    SESSION_START = "session.start"
    SESSION_COMPLETE = "session.complete"
    # Sprint 6.2: emitted when execute_session returns after planning
    # without running waves (plan-only mode picker).
    SESSION_PLAN_ONLY = "session.plan_only"
    # Sprint 6.2: emitted when bypass mode is active for a session.
    SESSION_BYPASS = "session.bypass"
    # Sprint 7.1: emitted when a hook (SessionStart / PreToolUse / ...)
    # blocks an operation. The reason field carries the hook's structured
    # rejection so `forge replay` can show what fired.
    SESSION_HOOK_BLOCKED = "session.hook_blocked"

    # ---- Repomap (built once per session at start) ----
    REPOMAP_BUILT = "repomap.built"

    # ---- Plan ----
    PLAN_CREATED = "plan.created"

    # ---- Wave / parallel sprint group ----
    WAVE_START = "wave.start"
    WAVE_COMPLETE = "wave.complete"

    # ---- Worktree ----
    WORKTREE_CREATED = "worktree.created"
    WORKTREE_CREATE_FAILED = "worktree.create_failed"

    # ---- Sprint lifecycle ----
    SPRINT_ATTEMPT = "sprint.attempt"
    SPRINT_EVALUATED = "sprint.evaluated"
    SPRINT_APPROVED = "sprint.approved"
    SPRINT_REVISING = "sprint.revising"
    SPRINT_RECOVERED = "sprint.recovered"  # Added by Task 1.1 (ADaPT writeback)
    SPRINT_CRASHED = "sprint.crashed"

    # ---- Recovery: ADaPT (recursive decomposition) ----
    RECOVERY_ADAPT_START = "recovery.adapt.start"
    RECOVERY_ADAPT_DECOMPOSED = "recovery.adapt.decomposed"
    RECOVERY_ADAPT_SUBSPRINT_PASSED = "recovery.adapt.subsprint_passed"
    RECOVERY_ADAPT_SUBSPRINT_FAILED = "recovery.adapt.subsprint_failed"
    RECOVERY_ADAPT_COMPLETE = "recovery.adapt.complete"

    # ---- Recovery: Self-Consistency (N=3 attempts for [critical] sprints) ----
    RECOVERY_CONSISTENCY_START = "recovery.consistency.start"
    RECOVERY_CONSISTENCY_ATTEMPT = "recovery.consistency.attempt"
    RECOVERY_CONSISTENCY_WINNER = "recovery.consistency.winner"
    RECOVERY_CONSISTENCY_COMPLETE = "recovery.consistency.complete"
    RECOVERY_CONSISTENCY_NO_WINNER = "recovery.consistency.no_winner"

    # ---- Budget ----
    BUDGET_DOWNGRADE = "budget.downgrade"
    BUDGET_EXHAUSTED = "budget.exhausted"  # Added by Task 2.2 (atomic reserve)
