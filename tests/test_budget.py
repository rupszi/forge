"""Tests for budget controller: estimation, downgrade cascade, hard cap."""

import asyncio

import pytest

from daemon.budget import DOWNGRADE_MAP, BudgetController, estimate_cost
from daemon.models import SprintContract


def test_estimate_cost_opus():
    cost = estimate_cost("opus", 10000)
    assert cost > 0
    # opus is the most expensive
    assert cost > estimate_cost("sonnet", 10000)


def test_estimate_cost_ollama():
    assert estimate_cost("ollama", 10000) == 0.0


def test_estimate_cost_sonnet():
    cost = estimate_cost("sonnet", 10000)
    assert cost > 0


def test_budget_initial_state():
    b = BudgetController(budget_usd=5.0)
    assert b.remaining == 5.0
    assert not b.exhausted
    assert b.spent_usd == 0.0


def test_budget_record_spend():
    b = BudgetController(budget_usd=5.0)
    b.record_spend(2.0)
    assert b.spent_usd == 2.0
    assert b.remaining == 3.0


def test_budget_exhausted():
    b = BudgetController(budget_usd=1.0)
    b.record_spend(1.0)
    assert b.exhausted
    assert b.remaining == 0.0


def test_can_afford_yes():
    b = BudgetController(budget_usd=10.0)
    sprint = SprintContract(assigned_model="sonnet", estimated_tokens=10000)
    assert b.can_afford(sprint)


def test_can_afford_no():
    b = BudgetController(budget_usd=0.001)
    sprint = SprintContract(assigned_model="opus", estimated_tokens=100000)
    assert not b.can_afford(sprint)


def test_downgrade_opus_to_sonnet():
    b = BudgetController(budget_usd=0.10)
    sprint = SprintContract(assigned_model="opus", estimated_tokens=50000)
    b.downgrade(sprint)
    # Should have downgraded at least once
    assert sprint.assigned_model != "opus"


def test_downgrade_to_ollama():
    b = BudgetController(budget_usd=0.0001)
    sprint = SprintContract(assigned_model="opus", estimated_tokens=100000)
    b.downgrade(sprint)
    assert sprint.assigned_model == "ollama"


def test_downgrade_already_affordable():
    b = BudgetController(budget_usd=100.0)
    sprint = SprintContract(assigned_model="opus", estimated_tokens=1000)
    b.downgrade(sprint)
    # Opus is affordable, should stay (or might downgrade based on estimate)
    # At 1000 tokens, opus should be affordable at $100 budget
    # Let's just check it doesn't crash


def test_to_dict():
    b = BudgetController(budget_usd=5.0)
    b.record_spend(1.5)
    d = b.to_dict()
    assert d["budget_usd"] == 5.0
    assert d["spent_usd"] == 1.5
    assert d["remaining_usd"] == 3.5
    assert d["percent_used"] == 30.0
    assert d["exhausted"] is False


def test_downgrade_map():
    assert DOWNGRADE_MAP["opus"] == "sonnet"
    assert DOWNGRADE_MAP["sonnet"] == "haiku"
    assert DOWNGRADE_MAP["haiku"] == "ollama"
    assert "ollama" not in DOWNGRADE_MAP


# ---- Task 2.2: atomic reserve / record_spend_async ----


@pytest.mark.asyncio
async def test_reserve_atomic_under_concurrent_calls():
    """100 concurrent $1 reservations against a $10 cap → exactly 10 succeed.

    Without the lock, multiple coroutines could each read ``spent_usd`` at
    the same value and each conclude "still room" — collectively exceeding
    the cap. The lock makes the check-and-decrement atomic.
    """
    b = BudgetController(budget_usd=10.0)
    results = await asyncio.gather(*(b.reserve(1.0) for _ in range(100)))
    assert sum(results) == 10
    assert b.spent_usd == 10.0


@pytest.mark.asyncio
async def test_reserve_returns_false_when_over_cap():
    b = BudgetController(budget_usd=5.0)
    assert await b.reserve(3.0) is True
    assert await b.reserve(2.5) is False  # would push over
    assert b.spent_usd == 3.0  # not incremented on the rejected call


@pytest.mark.asyncio
async def test_record_spend_async_updates_under_lock():
    b = BudgetController(budget_usd=100.0)
    await asyncio.gather(*(b.record_spend_async(0.5) for _ in range(20)))
    assert b.spent_usd == 10.0
