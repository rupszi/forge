"""Budget controller: hard spend cap, model downgrade cascade.

Task 2.2: ``reserve()`` and ``record_spend_async()`` are async / lock-protected
so the check-and-decrement is atomic across parallel waves. The previous
flow (estimate at wave start, record spend later when each generator
completes) had a window where multiple sprints could each see "I'm
affordable" against the same remaining budget and collectively exceed
the cap. Per-sprint reservation under a lock closes that window.
"""

from __future__ import annotations

import asyncio
import logging

from .config import MODEL_COSTS, SESSION_BUDGET_USD
from .models import SprintContract

logger = logging.getLogger(__name__)

# Downgrade cascade: opus -> sonnet -> ollama
DOWNGRADE_MAP = {
    "opus": "sonnet",
    "sonnet": "haiku",
    "haiku": "ollama",
}


def estimate_cost(model: str, tokens: int) -> float:
    """Estimate cost for a sprint given model and estimated tokens."""
    costs = MODEL_COSTS.get(model, MODEL_COSTS.get("sonnet"))
    # Assume 60% input, 40% output
    tokens_in = int(tokens * 0.6)
    tokens_out = int(tokens * 0.4)
    return (tokens_in * costs["input"] + tokens_out * costs["output"]) / 1_000_000


class BudgetController:
    def __init__(self, budget_usd: float = SESSION_BUDGET_USD):
        self.budget_usd = budget_usd
        self.spent_usd = 0.0
        # Async lock for atomic reserve / record_spend_async across waves.
        # Lazy-initialized on first use because Python 3.9's asyncio.Lock()
        # querying ``get_event_loop()`` at construction time raises when
        # called from sync test bodies before any loop exists. The
        # surrounding properties (remaining, exhausted) and record_spend()
        # remain usable without a loop.
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        """Lazily construct the lock once an event loop is available."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget_usd - self.spent_usd)

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.budget_usd

    def record_spend(self, cost_usd: float) -> None:
        """Synchronous spend recorder.

        Kept for the existing scheduler path (per-attempt token costs reported
        after generator/evaluator complete) where the surrounding code is
        already serialized per-sprint. Use :meth:`record_spend_async` from
        contexts that need cross-wave atomicity.
        """
        self.spent_usd += cost_usd
        if self.spent_usd >= self.budget_usd * 0.8:
            logger.warning(
                "Budget %.0f%% used: $%.2f / $%.2f",
                (self.spent_usd / self.budget_usd) * 100,
                self.spent_usd,
                self.budget_usd,
            )

    async def reserve(self, estimated_cost: float) -> bool:
        """Atomically check + reserve budget. Returns True if reserved.

        Used by the scheduler before launching a sprint into a parallel wave:
        if 100 sprints each estimate $1 against a $10 cap and call this
        concurrently, exactly 10 succeed and 90 see False. Caller is expected
        to either downgrade the sprint or mark it failed when reserve()
        returns False.
        """
        async with self._get_lock():
            if self.spent_usd + estimated_cost > self.budget_usd:
                return False
            self.spent_usd += estimated_cost
            return True

    async def record_spend_async(self, actual: float) -> None:
        """Adjust pending estimate to actual spend, lock-protected.

        Use after a sprint completes: ``actual - estimate`` (positive or
        negative) gets folded into ``spent_usd`` so the running total
        reflects truth, not the conservative pre-spend estimate.
        """
        async with self._get_lock():
            self.spent_usd += actual

    def can_afford(self, sprint: SprintContract) -> bool:
        """Check if we can afford this sprint at its current model."""
        est = estimate_cost(sprint.assigned_model, sprint.estimated_tokens or 10000)
        return est <= self.remaining

    def downgrade(self, sprint: SprintContract) -> SprintContract:
        """Downgrade sprint model until affordable or at ollama."""
        original = sprint.assigned_model
        model = sprint.assigned_model
        while model in DOWNGRADE_MAP:
            next_model = DOWNGRADE_MAP[model]
            est = estimate_cost(next_model, sprint.estimated_tokens or 10000)
            model = next_model
            if est <= self.remaining:
                break

        if model != original:
            logger.info("Budget downgrade: %s -> %s for sprint %s", original, model, sprint.id)
        sprint.assigned_model = model
        return sprint

    def to_dict(self) -> dict:
        return {
            "budget_usd": self.budget_usd,
            "spent_usd": round(self.spent_usd, 4),
            "remaining_usd": round(self.remaining, 4),
            "percent_used": round((self.spent_usd / self.budget_usd) * 100, 1)
            if self.budget_usd > 0
            else 0,
            "exhausted": self.exhausted,
        }
