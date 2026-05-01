"""Tests for daemon/recovery.py — ADaPT decomposition + Self-Consistency.

Phase 3 Week 9 deliverable. The tests use mocked ``run_subsprint`` /
``run_attempt`` callables so they exercise the algorithm without spinning up
Forge's full pipeline.

Task 3.4: a ``captured_events`` fixture replaces the previous pattern of
monkeypatching ``append_event`` to a no-op. Tests now both isolate replay
side-effects AND can assert on what got emitted, turning a silent mock
into a behavior contract.
"""

from __future__ import annotations

import pytest

from daemon.models import CriterionResult, EvaluatorResult, ExecutionResult, SprintContract
from daemon.recovery import (
    adapt_failed_sprint,
    is_critical,
    is_eligible_for_decomposition,
    score_attempt,
    self_consistent_run,
    split_into_subsprints,
)


@pytest.fixture
def captured_events(monkeypatch):
    """Capture every ``append_event`` call made by daemon.recovery.

    Returns the captures list — tests can assert against it AND get the
    side-effect-isolation that the previous lambda monkeypatch provided.
    """
    events: list[dict] = []

    def capture(session_id, event_type, *, sprint_id=None, data=None):
        events.append(
            {
                "session_id": session_id,
                "type": event_type,
                "sprint_id": sprint_id,
                "data": data or {},
            }
        )

    monkeypatch.setattr("daemon.recovery.append_event", capture)
    return events


# ---- Eligibility ----


def test_eligible_when_multiple_criteria():
    sprint = SprintContract(
        id="s1",
        description="x",
        done_criteria=["a", "b", "c"],
    )
    assert is_eligible_for_decomposition(sprint) is True


def test_not_eligible_when_single_criterion():
    sprint = SprintContract(id="s1", description="x", done_criteria=["only one"])
    assert is_eligible_for_decomposition(sprint) is False


def test_not_eligible_for_already_decomposed_sprint():
    """A sprint whose worktree is already a 'recovery-' worktree was itself
    a sub-sprint; don't recurse infinitely."""
    sprint = SprintContract(
        id="s1",
        description="x",
        done_criteria=["a", "b"],
        assigned_worktree="recovery-abc",
    )
    assert is_eligible_for_decomposition(sprint) is False


# ---- split_into_subsprints ----


def test_split_one_subsprint_per_criterion():
    parent = SprintContract(
        id="parent-1",
        session_id="sess",
        description="Build feature X",
        done_criteria=["criterion A", "criterion B", "criterion C"],
        files_scope=["src/foo.py"],
        assigned_model="qwen3.6:27b",
    )
    subs = split_into_subsprints(parent)
    assert len(subs) == 3
    assert subs[0].done_criteria == ["criterion A"]
    assert subs[1].done_criteria == ["criterion B"]
    assert subs[2].done_criteria == ["criterion C"]


def test_split_subsprints_inherit_session_and_files():
    parent = SprintContract(
        id="p",
        session_id="sess1",
        description="x",
        done_criteria=["a", "b"],
        files_scope=["f.py"],
        assigned_model="qwen3-coder-next",
    )
    subs = split_into_subsprints(parent)
    for sub in subs:
        assert sub.session_id == "sess1"
        assert sub.files_scope == ["f.py"]
        assert sub.assigned_model == "qwen3-coder-next"


def test_split_subsprints_serialize_dependencies():
    """Each sub-sprint depends on the previous one — the planner shouldn't
    parallelize sub-sprints because they typically share state."""
    parent = SprintContract(id="p", description="x", done_criteria=["a", "b", "c"])
    subs = split_into_subsprints(parent)
    assert subs[0].depends_on == []
    assert subs[1].depends_on == [subs[0].id]
    assert subs[2].depends_on == [subs[0].id, subs[1].id]


# ---- adapt_failed_sprint ----


@pytest.mark.asyncio
async def test_adapt_returns_pass_when_all_subsprints_succeed(tmp_path, captured_events):
    """Verifies algorithm AND that the canonical events are emitted (Task 3.4)."""
    parent = SprintContract(
        id="p1",
        session_id="sess1",
        description="x",
        done_criteria=["a", "b", "c"],
    )

    async def runner(sub):
        return (
            ExecutionResult(success=True, output="ok"),
            EvaluatorResult(verdict="APPROVED"),
        )

    result = await adapt_failed_sprint(parent, run_subsprint=runner)
    assert result.final_verdict == "PASS"
    assert result.all_passed is True
    assert len(result.sub_sprints) == 3
    assert len(result.sub_results) == 3

    # Task 3.4: assert on emitted events, not just on the return value.
    types = [e["type"] for e in captured_events]
    assert "recovery.adapt.decomposed" in types
    # One subsprint_passed per criterion when all three pass.
    assert types.count("recovery.adapt.subsprint_passed") == 3


@pytest.mark.asyncio
async def test_adapt_stops_at_first_failure(captured_events):
    """Algorithm + asserts that subsprint_failed lands in the trace."""
    parent = SprintContract(id="p", session_id="s", description="x", done_criteria=["a", "b", "c"])

    call_count = {"n": 0}

    async def runner(sub):
        call_count["n"] += 1
        if call_count["n"] == 2:
            # Second sub-sprint fails
            return (
                ExecutionResult(success=False, error="bad"),
                EvaluatorResult(verdict="REVISE"),
            )
        return (ExecutionResult(success=True), EvaluatorResult(verdict="APPROVED"))

    result = await adapt_failed_sprint(parent, run_subsprint=runner)
    # Only 2 attempts before stopping
    assert call_count["n"] == 2
    assert result.final_verdict == "PARTIAL"  # one passed, one failed
    # Task 3.4: trace must record the failure (was previously a silent mock).
    types = [e["type"] for e in captured_events]
    assert "recovery.adapt.subsprint_failed" in types


@pytest.mark.asyncio
async def test_adapt_handles_runner_exception(captured_events):

    parent = SprintContract(id="p", session_id="s", description="x", done_criteria=["a", "b"])

    async def crashing_runner(sub):
        raise RuntimeError("boom")

    result = await adapt_failed_sprint(parent, run_subsprint=crashing_runner)
    assert result.final_verdict == "FAIL"
    assert "crash" in result.sub_results[0].error.lower()


@pytest.mark.asyncio
async def test_adapt_returns_fail_when_not_eligible():
    parent = SprintContract(
        id="p",
        session_id="s",
        description="x",
        done_criteria=["only one"],  # ineligible: single criterion
    )

    called = []

    async def runner(sub):
        called.append(sub)
        return (ExecutionResult(success=True), EvaluatorResult(verdict="APPROVED"))

    result = await adapt_failed_sprint(parent, run_subsprint=runner)
    assert result.final_verdict == "FAIL"
    assert "not eligible" in result.notes
    assert called == []  # runner never invoked


# ---- is_critical ----


def test_critical_marker_at_start():
    sprint = SprintContract(description="[CRITICAL] schema migration on prod")
    assert is_critical(sprint) is True


def test_critical_marker_lowercase():
    sprint = SprintContract(description="[critical] do this carefully")
    assert is_critical(sprint) is True


def test_not_critical_when_marker_absent():
    sprint = SprintContract(description="ordinary task")
    assert is_critical(sprint) is False


def test_critical_with_extra_qualifier():
    """[critical:high] etc. count as critical."""
    sprint = SprintContract(description="ordinary [critical:high] task")
    assert is_critical(sprint) is True


# Task 3.2: structured ``critical: bool`` field is the primary signal


def test_critical_field_takes_precedence_over_description():
    """If ``critical=True`` is set on the dataclass, is_critical returns True
    even when the description has no marker. This is the new structured path
    introduced by Task 3.2.
    """
    sprint = SprintContract(description="ordinary task", critical=True)
    assert is_critical(sprint) is True


def test_critical_legacy_string_prefix_still_works():
    """Backwards-compat: hand-crafted prompts without the new field still
    flag critical via the legacy ``[critical]`` prefix scan."""
    sprint = SprintContract(description="[critical] migration", critical=False)
    assert is_critical(sprint) is True


def test_critical_field_default_is_false():
    """Sanity: existing call sites that don't pass ``critical=`` keep the
    pre-Task-3.2 behavior (only description-prefix triggers)."""
    sprint = SprintContract(description="ordinary work")
    assert sprint.critical is False
    assert is_critical(sprint) is False


# ---- score_attempt ----


def test_score_approved_dominates_revise():
    approved = EvaluatorResult(
        verdict="APPROVED", criteria_results=[CriterionResult(criterion="a", passed=True)]
    )
    revise = EvaluatorResult(
        verdict="REVISE", criteria_results=[CriterionResult(criterion="a", passed=True)]
    )
    assert score_attempt(approved) > score_attempt(revise)


def test_score_more_passing_criteria_wins_at_same_verdict():
    one_pass = EvaluatorResult(
        verdict="APPROVED",
        criteria_results=[CriterionResult(criterion="a", passed=True)],
    )
    three_pass = EvaluatorResult(
        verdict="APPROVED",
        criteria_results=[
            CriterionResult(criterion="a", passed=True),
            CriterionResult(criterion="b", passed=True),
            CriterionResult(criterion="c", passed=True),
        ],
    )
    assert score_attempt(three_pass) > score_attempt(one_pass)


# ---- self_consistent_run ----


@pytest.mark.asyncio
async def test_self_consistency_picks_first_approved(captured_events):
    """Algorithm + asserts the consistency.start + winner events landed."""
    sprint = SprintContract(id="s", session_id="sess", description="x", done_criteria=["a"])
    call_count = {"n": 0}

    async def attempt(s, i):
        call_count["n"] += 1
        # First attempt succeeds → should early-exit
        return (
            ExecutionResult(success=True),
            EvaluatorResult(
                verdict="APPROVED",
                criteria_results=[CriterionResult(criterion="a", passed=True)],
            ),
        )

    result = await self_consistent_run(sprint, n=3, run_attempt=attempt)
    assert call_count["n"] == 1  # early exit
    assert result.final_verdict == "APPROVED"
    assert result.winner_index == 0
    # Task 3.4: emitted start + winner events.
    types = [e["type"] for e in captured_events]
    assert "recovery.consistency.start" in types
    assert "recovery.consistency.winner" in types


@pytest.mark.asyncio
async def test_self_consistency_picks_highest_score_when_no_approved(monkeypatch):
    monkeypatch.setattr("daemon.recovery.append_event", lambda *a, **kw: None)

    sprint = SprintContract(
        id="s", session_id="sess", description="x", done_criteria=["a", "b", "c"]
    )

    async def attempt(s, i):
        # Each attempt fails but with different criteria-pass counts
        return (
            ExecutionResult(success=False),
            EvaluatorResult(
                verdict="REVISE",
                criteria_results=[
                    CriterionResult(criterion="a", passed=(i >= 0)),
                    CriterionResult(criterion="b", passed=(i >= 1)),
                    CriterionResult(criterion="c", passed=(i >= 2)),
                ],
            ),
        )

    result = await self_consistent_run(sprint, n=3, run_attempt=attempt)
    assert len(result.attempts) == 3
    assert result.winner_index == 2  # most passing criteria
    assert result.final_verdict == "REVISE"


@pytest.mark.asyncio
async def test_self_consistency_handles_attempt_crashes(monkeypatch):
    monkeypatch.setattr("daemon.recovery.append_event", lambda *a, **kw: None)

    sprint = SprintContract(id="s", session_id="sess", description="x", done_criteria=["a"])

    async def attempt(s, i):
        if i == 0:
            raise RuntimeError("boom")
        return (
            ExecutionResult(success=True),
            EvaluatorResult(
                verdict="APPROVED",
                criteria_results=[CriterionResult(criterion="a", passed=True)],
            ),
        )

    result = await self_consistent_run(sprint, n=3, run_attempt=attempt)
    # First attempt records as a failure; second succeeds and wins
    assert len(result.attempts) == 2  # crashed + first APPROVED
    assert result.winner_index == 1
    assert result.final_verdict == "APPROVED"
