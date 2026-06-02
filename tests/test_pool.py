"""M2 — Model Pool Manager: spawn on demand, evict under a RAM budget, no OOM.

The pool is the safety mechanism that lets a 48 GB Apple Silicon machine run an
orchestrator plus spawned agent models without exhausting RAM. These tests pin
the load/evict/pin/wait semantics (guardrails G-RAM-1..3).
"""

from __future__ import annotations

import asyncio

import pytest

from daemon.pool import ModelPool, PoolCapacityError


class TestResidency:
    @pytest.mark.asyncio
    async def test_acquire_makes_model_resident(self):
        pool = ModelPool(budget_gb=20.0)
        async with pool.lease("coder", size_gb=9.0):
            assert pool.is_resident("coder")
            assert pool.resident_gb() == pytest.approx(9.0)

    @pytest.mark.asyncio
    async def test_released_model_stays_resident_for_reuse(self):
        pool = ModelPool(budget_gb=20.0)
        async with pool.lease("coder", size_gb=9.0):
            pass
        # Still resident (warm) after release — reuse is free.
        assert pool.is_resident("coder")

    @pytest.mark.asyncio
    async def test_reacquire_does_not_double_count(self):
        pool = ModelPool(budget_gb=20.0)
        async with pool.lease("coder", size_gb=9.0):
            async with pool.lease("coder", size_gb=9.0):
                assert pool.resident_gb() == pytest.approx(9.0)


class TestEviction:
    @pytest.mark.asyncio
    async def test_lru_evicted_to_make_room(self):
        pool = ModelPool(budget_gb=20.0)
        async with pool.lease("a", size_gb=9.0):
            pass
        async with pool.lease("b", size_gb=9.0):
            pass
        # a and b resident (18 GB). Acquiring c (9) needs an eviction; a is LRU.
        async with pool.lease("c", size_gb=9.0):
            assert pool.is_resident("c")
            assert not pool.is_resident("a")  # LRU evicted
            assert pool.is_resident("b")
        assert pool.resident_gb() <= 20.0

    @pytest.mark.asyncio
    async def test_budget_never_exceeded_on_acquire(self):
        pool = ModelPool(budget_gb=20.0)
        for name in ("a", "b", "c", "d", "e"):
            async with pool.lease(name, size_gb=9.0):
                # At the moment a lease is held, the pool must be within budget.
                assert pool.resident_gb() <= 20.0

    @pytest.mark.asyncio
    async def test_eviction_happens_before_load(self):
        # The invariant: resident_gb never transiently exceeds budget. We probe
        # it right after acquire returns (load complete).
        pool = ModelPool(budget_gb=12.0)
        async with pool.lease("a", size_gb=9.0):
            pass
        async with pool.lease("b", size_gb=9.0):
            assert pool.resident_gb() == pytest.approx(9.0)
            assert not pool.is_resident("a")


class TestPinning:
    @pytest.mark.asyncio
    async def test_pinned_model_never_evicted(self):
        pool = ModelPool(budget_gb=20.0, pinned={"orchestrator"})
        async with pool.lease("orchestrator", size_gb=5.0):
            pass
        async with pool.lease("a", size_gb=9.0):
            pass
        async with pool.lease("b", size_gb=9.0):  # forces eviction of non-pinned
            assert pool.is_resident("orchestrator")  # pinned survives
            assert pool.is_resident("b")

    @pytest.mark.asyncio
    async def test_pin_at_runtime(self):
        pool = ModelPool(budget_gb=20.0)
        await pool.pin("embed", size_gb=0.3)
        async with pool.lease("a", size_gb=9.0):
            pass
        async with pool.lease("b", size_gb=9.0):
            pass
        async with pool.lease("c", size_gb=9.0):
            assert pool.is_resident("embed")  # pinned, never evicted


class TestUnfittable:
    @pytest.mark.asyncio
    async def test_model_larger_than_budget_raises(self):
        pool = ModelPool(budget_gb=10.0)
        with pytest.raises(PoolCapacityError) as exc:
            async with pool.lease("huge", size_gb=20.0):
                pass
        assert "budget" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_model_plus_pinned_over_budget_raises(self):
        pool = ModelPool(budget_gb=10.0, pinned={"orchestrator"})
        await pool.pin("orchestrator", size_gb=6.0)
        with pytest.raises(PoolCapacityError):
            async with pool.lease("big", size_gb=8.0):  # 6 + 8 > 10
                pass

    @pytest.mark.asyncio
    async def test_raises_fast_does_not_hang(self):
        pool = ModelPool(budget_gb=10.0)
        # G-RAM-3: an unfittable request fails quickly, never hangs.
        async with asyncio.timeout(2.0):
            with pytest.raises(PoolCapacityError):
                await pool.acquire("huge", size_gb=50.0)


class TestSerializeLargeModels:
    @pytest.mark.asyncio
    async def test_competing_large_acquire_waits_then_proceeds(self):
        # Two large models that don't co-fit. The second acquire must wait for
        # the first to release (in-use models are not evictable), then proceed.
        pool = ModelPool(budget_gb=20.0)
        order: list[str] = []

        async def hold(name: str, hold_s: float):
            async with pool.lease(name, size_gb=15.0):
                order.append(f"start-{name}")
                await asyncio.sleep(hold_s)
                order.append(f"end-{name}")

        await asyncio.gather(hold("a", 0.15), hold("b", 0.05))
        # Whoever ran first fully finished before the other started (no overlap
        # beyond budget): an end-* precedes the next start-*.
        assert order[0].startswith("start-")
        assert order[1].startswith("end-")
        assert order[2].startswith("start-")
        assert order[3].startswith("end-")
        assert pool.resident_gb() <= 20.0


class TestState:
    @pytest.mark.asyncio
    async def test_state_payload_shape(self):
        pool = ModelPool(budget_gb=20.0, pinned={"orchestrator"})
        await pool.pin("orchestrator", size_gb=5.0)
        async with pool.lease("coder", size_gb=9.0):
            state = pool.state()
        assert state["type"] == "pool_state"
        assert state["budget_gb"] == 20.0
        assert state["resident_gb"] == pytest.approx(14.0)
        names = {m["name"] for m in state["models"]}
        assert {"orchestrator", "coder"} <= names
        orch = next(m for m in state["models"] if m["name"] == "orchestrator")
        assert orch["pinned"] is True

    @pytest.mark.asyncio
    async def test_on_change_callback_fires(self):
        events: list[dict] = []
        pool = ModelPool(budget_gb=20.0, on_change=events.append)
        async with pool.lease("coder", size_gb=9.0):
            pass
        # At least a load event fired with the pool state shape.
        assert events
        assert events[-1]["type"] == "pool_state"
