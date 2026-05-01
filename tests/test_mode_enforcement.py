"""Mode-state and scheduler enforcement tests (Sprint 6.2).

Five modes from the UI mode picker:

  auto / accept_edits  → daemon runs end-to-end
  plan                 → planner runs, wave loop skipped
  ask                  → prompt addendum injected at generator boundary
  bypass               → behaviour same as auto, audit-log warning emitted

These tests cover the mode-state object, the prompt-addendum surface,
the WS-server set_mode handler, and the scheduler's plan-only branch
that returns immediately after planning.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from daemon.budget import BudgetController
from daemon.db import ForgeDB
from daemon.mode import (
    DEFAULT_MODE,
    VALID_MODES,
    InvalidMode,
    ModeState,
    mode_prompt_addendum,
)

# ---- ModeState dataclass ----


def test_default_mode_is_auto() -> None:
    state = ModeState()
    assert state.mode == "auto"
    assert DEFAULT_MODE == "auto"


def test_valid_modes_are_the_five_picker_options() -> None:
    assert set(VALID_MODES) == {"auto", "accept_edits", "plan", "ask", "bypass"}


def test_set_returns_resolved_mode() -> None:
    state = ModeState()
    assert state.set("plan") == "plan"
    assert state.mode == "plan"


def test_set_rejects_unknown_mode() -> None:
    state = ModeState()
    with pytest.raises(InvalidMode, match="unknown mode"):
        state.set("megamax")
    # State unchanged after rejection
    assert state.mode == "auto"


def test_set_to_same_mode_is_idempotent() -> None:
    state = ModeState(mode="ask")
    assert state.set("ask") == "ask"
    assert state.mode == "ask"


def test_helper_predicates() -> None:
    assert ModeState(mode="plan").is_plan_only() is True
    assert ModeState(mode="auto").is_plan_only() is False
    assert ModeState(mode="bypass").is_bypass() is True
    assert ModeState(mode="auto").is_bypass() is False
    assert ModeState(mode="ask").is_ask() is True
    assert ModeState(mode="auto").is_ask() is False


# ---- mode_prompt_addendum ----


def test_addendum_empty_for_default_modes() -> None:
    """Auto and accept_edits don't change the prompt — keeps the cache
    boundary stable for the most common code path."""
    assert mode_prompt_addendum("auto") == ""
    assert mode_prompt_addendum("accept_edits") == ""
    assert mode_prompt_addendum("plan") == ""  # plan-only, never reaches generator


def test_addendum_for_ask_mode_mentions_destructive_ops() -> None:
    text = mode_prompt_addendum("ask")
    assert "ASK" in text
    assert "destructive" in text


def test_addendum_for_bypass_mode_mentions_waiver() -> None:
    text = mode_prompt_addendum("bypass")
    assert "BYPASS" in text


# ---- Generator picks up the addendum ----


def test_generator_prompt_includes_ask_addendum() -> None:
    """The generator's _build_prompt must inject the addendum at the
    front of the cacheable prefix when mode='ask'."""
    from daemon.agents.generator import _build_prompt
    from daemon.models import SprintContract

    sprint = SprintContract(
        id="s1",
        description="add a deletion endpoint",
        done_criteria=["DELETE /api/users/:id works"],
    )
    prompt = _build_prompt(sprint, memory_context="", mode="ask")
    assert "ASK" in prompt
    # The task description still lands AFTER the addendum — order matters
    # for prompt caching.
    assert prompt.index("ASK") < prompt.index("add a deletion endpoint")


def test_generator_prompt_omits_addendum_for_auto_mode() -> None:
    """Auto mode produces no addendum — the cacheable prefix is the same
    shape it was before Sprint 6.2."""
    from daemon.agents.generator import _build_prompt
    from daemon.models import SprintContract

    sprint = SprintContract(id="s1", description="x", done_criteria=["y"])
    prompt = _build_prompt(sprint, memory_context="", mode="auto")
    assert "Operating mode:" not in prompt


# ---- Scheduler plan-only branch ----


@pytest.mark.asyncio
async def test_scheduler_skips_wave_execution_in_plan_mode(tmp_path: Path) -> None:
    """In plan mode the planner runs and persists sprints, but the wave
    loop does NOT — ``execute_sprint`` should never be called."""
    from daemon.models import ProjectContext, SprintContract
    from daemon.scheduler import execute_session

    db = ForgeDB(str(tmp_path / "forge.db"))
    budget = BudgetController()
    ctx = ProjectContext(path=str(tmp_path), is_git=False)
    mode_state = ModeState(mode="plan")

    fake_sprints = [
        SprintContract(
            id="sprint-a",
            description="schema",
            done_criteria=["ok"],
            session_id="",
        ),
        SprintContract(
            id="sprint-b",
            description="api",
            done_criteria=["ok"],
            session_id="",
            depends_on=["sprint-a"],
        ),
    ]

    async def fake_plan(*args, **kwargs):
        return fake_sprints

    # Counter for wave invocations — must stay zero.
    sprint_run_count = 0

    async def fake_execute_sprint(*args, **kwargs):
        nonlocal sprint_run_count
        sprint_run_count += 1
        return SprintContract()

    broadcast_msgs: list[dict] = []

    with (
        patch("daemon.scheduler.planner.plan", side_effect=fake_plan),
        patch("daemon.scheduler.execute_sprint", side_effect=fake_execute_sprint),
    ):
        session = await execute_session(
            objective="x",
            ctx=ctx,
            db=db,
            budget=budget,
            broadcast=broadcast_msgs.append,
            mode_state=mode_state,
        )

    assert sprint_run_count == 0
    # Sprints persisted for later run-after-flip-to-auto
    assert session.total_sprints == 2
    # plan_only signal in the broadcast trail
    types = [m.get("type") for m in broadcast_msgs]
    assert any("session_complete" in t for t in types if t)
    plan_only_msgs = [m for m in broadcast_msgs if m.get("plan_only")]
    assert plan_only_msgs, "expected at least one broadcast with plan_only=True"
    db.close()


@pytest.mark.asyncio
async def test_scheduler_bypass_mode_logs_warning(tmp_path: Path, caplog) -> None:
    """Bypass behaves like auto but emits a loud warning so the audit
    trail (and `forge replay`) shows the user's choice."""
    import logging

    from daemon.models import ProjectContext, SprintContract
    from daemon.scheduler import execute_session

    db = ForgeDB(str(tmp_path / "forge.db"))
    budget = BudgetController()
    ctx = ProjectContext(path=str(tmp_path), is_git=False)
    mode_state = ModeState(mode="bypass")

    async def fake_plan(*args, **kwargs):
        return []  # empty plan → no waves to run

    async def fake_execute_sprint(*args, **kwargs):
        return SprintContract()

    with (
        caplog.at_level(logging.WARNING, logger="daemon.scheduler"),
        patch("daemon.scheduler.planner.plan", side_effect=fake_plan),
        patch("daemon.scheduler.execute_sprint", side_effect=fake_execute_sprint),
    ):
        await execute_session(
            objective="x",
            ctx=ctx,
            db=db,
            budget=budget,
            mode_state=mode_state,
        )

    # The warning identifies bypass and is loud (level WARNING)
    bypass_warnings = [
        rec for rec in caplog.records if "BYPASS" in rec.message and rec.levelname == "WARNING"
    ]
    assert bypass_warnings, "expected a WARNING-level BYPASS log"
    db.close()


# ---- WS server set_mode handler ----


@pytest.mark.asyncio
async def test_ws_set_mode_updates_state_and_broadcasts(tmp_path: Path) -> None:
    """The WS server mutates the process-wide ModeState singleton on
    set_mode and broadcasts mode_changed to all connected clients."""
    from daemon import ws_server
    from daemon.ws_server import _handle_message_inner

    # Reset the singleton for this test.
    ws_server._mode_state.set("auto")

    db = ForgeDB(str(tmp_path / "forge.db"))
    budget = BudgetController()

    class FakeWS:
        pass

    fake_ws = FakeWS()
    msg = json.dumps({"type": "set_mode", "mode": "plan"})

    # Inner handler bypasses the rate-limit / size-cap guards so we can
    # exercise the dispatch logic in isolation.
    response = await _handle_message_inner(fake_ws, msg, db, None, budget)
    assert response == {"type": "mode_changed", "mode": "plan"}
    assert ws_server._mode_state.mode == "plan"

    # Reset for other tests
    ws_server._mode_state.set("auto")
    db.close()


@pytest.mark.asyncio
async def test_ws_set_mode_rejects_unknown(tmp_path: Path) -> None:
    """Unknown mode → error response, state unchanged."""
    from daemon import ws_server
    from daemon.ws_server import _handle_message_inner

    ws_server._mode_state.set("auto")

    db = ForgeDB(str(tmp_path / "forge.db"))
    budget = BudgetController()

    class FakeWS:
        pass

    msg = json.dumps({"type": "set_mode", "mode": "evil"})
    response = await _handle_message_inner(FakeWS(), msg, db, None, budget)
    assert response["type"] == "error"
    assert "unknown mode" in response["error"]
    assert ws_server._mode_state.mode == "auto"

    db.close()


def test_get_mode_state_returns_singleton() -> None:
    """``get_mode_state()`` returns the SAME instance the WS server
    mutates — so cmd_serve threading the result into the scheduler
    keeps both surfaces in sync."""
    from daemon.ws_server import get_mode_state

    a = get_mode_state()
    b = get_mode_state()
    assert a is b
