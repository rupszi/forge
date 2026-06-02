"""Model Pool Manager — spawn agent models on demand under a RAM budget (M2).

On a 48 GB Apple Silicon machine the orchestrator stays resident while coder /
evaluator models are loaded on demand and evicted when memory is tight. The
pool enforces a hard RAM budget (``FORGE_LOCAL_RAM_BUDGET_GB``) with three
guarantees:

- **No OOM (G-RAM-1):** a model is only marked resident *after* enough room has
  been freed; ``resident_gb()`` never exceeds the budget once an acquire returns.
- **Pinned survive:** the orchestrator and embedding model are pinned and never
  evicted.
- **No hang, no thrash (G-RAM-3):** a request larger than the budget (minus
  pinned) fails fast with ``PoolCapacityError``; two large models that don't
  co-fit are *serialized* (the second waits for the first to release) rather
  than evicting an in-use model.

The pool tracks *logical* residency (which models Ollama should keep warm via
``keep_alive``); it does not itself load weights. Eviction here means "let this
model's keep-alive lapse" — the executor layer honors it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from .config import local_ram_budget_gb

_DEFAULT_SIZE_GB = 8.0

# Most-recently-created session pool, so the WS layer can answer a "pool" query
# (pull) in addition to the on_change pushes. Not a singleton the scheduler
# reuses — each session builds its own pool bound to its event loop and
# registers it here for read-only state queries.
_active_pool: ModelPool | None = None


def set_active_pool(pool: ModelPool) -> None:
    global _active_pool
    _active_pool = pool


def active_pool_state() -> dict:
    """Current pool state for the UI, or an empty/idle payload if none yet."""
    if _active_pool is None:
        return {
            "type": "pool_state",
            "budget_gb": local_ram_budget_gb(),
            "resident_gb": 0.0,
            "models": [],
        }
    return _active_pool.state()


class PoolCapacityError(RuntimeError):
    """A model can never fit (its size + pinned footprint exceeds the budget)."""


@dataclass
class _Entry:
    name: str
    size_gb: float
    pinned: bool = False
    in_use: int = 0
    last_used: float = field(default_factory=time.monotonic)


class ModelPool:
    """Async-safe registry of resident local models bounded by a RAM budget."""

    def __init__(
        self,
        budget_gb: float | None = None,
        pinned: Iterable[str] | None = None,
        on_change: Callable[[dict], None] | None = None,
    ) -> None:
        self.budget_gb = budget_gb if budget_gb is not None else local_ram_budget_gb()
        self._pinned_names = set(pinned or ())
        self._on_change = on_change
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        # Signalled whenever a model is released, so waiters blocked on an
        # in-use (non-evictable) model can re-evaluate.
        self._released = asyncio.Condition(self._lock)

    # -- introspection (sync; cheap reads) --

    def is_resident(self, name: str) -> bool:
        return name in self._entries

    def resident_gb(self) -> float:
        return round(sum(e.size_gb for e in self._entries.values()), 6)

    def state(self) -> dict:
        return {
            "type": "pool_state",
            "budget_gb": self.budget_gb,
            "resident_gb": self.resident_gb(),
            "models": [
                {
                    "name": e.name,
                    "size_gb": e.size_gb,
                    "pinned": e.pinned,
                    "in_use": e.in_use,
                }
                for e in sorted(self._entries.values(), key=lambda x: x.last_used)
            ],
        }

    def _emit(self) -> None:
        if self._on_change is not None:
            self._on_change(self.state())

    # -- mutation --

    async def pin(self, name: str, size_gb: float = _DEFAULT_SIZE_GB) -> None:
        """Mark a model as pinned (resident + never evicted). Idempotent."""
        async with self._lock:
            self._pinned_names.add(name)
            entry = self._entries.get(name)
            if entry is None:
                await self._make_room_locked(size_gb, exclude=name)
                self._entries[name] = _Entry(name, size_gb, pinned=True)
            else:
                entry.pinned = True
                entry.last_used = time.monotonic()
            self._emit()

    async def acquire(self, name: str, size_gb: float = _DEFAULT_SIZE_GB) -> str:
        """Ensure ``name`` is resident and mark it in-use. Returns the name.

        Pair every ``acquire`` with a ``release`` (or use :meth:`lease`).
        """
        async with self._lock:
            entry = self._entries.get(name)
            if entry is not None:
                entry.in_use += 1
                entry.last_used = time.monotonic()
                return name

            # A model can ever fit iff its size plus the *pinned* footprint
            # (which can't be evicted) stays within budget. Non-pinned models
            # are all evictable, so they don't bound feasibility.
            pinned_other = sum(
                e.size_gb for e in self._entries.values() if e.pinned and e.name != name
            )
            if size_gb + pinned_other > self.budget_gb:
                msg = (
                    f"model {name!r} ({size_gb:.1f} GB) cannot fit the "
                    f"{self.budget_gb:.1f} GB RAM budget alongside pinned models "
                    f"({pinned_other:.1f} GB). Raise FORGE_LOCAL_RAM_BUDGET_GB "
                    "or use a smaller model."
                )
                raise PoolCapacityError(msg)

            await self._make_room_locked(size_gb, exclude=name)
            self._entries[name] = _Entry(
                name,
                size_gb,
                pinned=name in self._pinned_names,
                in_use=1,
            )
            self._emit()
            return name

    async def release(self, name: str) -> None:
        async with self._lock:
            entry = self._entries.get(name)
            if entry is not None and entry.in_use > 0:
                entry.in_use -= 1
                entry.last_used = time.monotonic()
            self._released.notify_all()

    @asynccontextmanager
    async def lease(self, name: str, size_gb: float = _DEFAULT_SIZE_GB):
        await self.acquire(name, size_gb)
        try:
            yield name
        finally:
            await self.release(name)

    # -- internals (call with lock held) --

    async def _make_room_locked(self, needed_gb: float, exclude: str) -> None:
        """Evict LRU non-pinned, not-in-use models until ``needed_gb`` fits.

        If room can't be made because the only candidates are in-use, wait for
        a release and retry. Raises ``PoolCapacityError`` only when nothing
        could ever free enough (no evictable and no in-use to wait on).
        """
        while self.resident_gb() + needed_gb > self.budget_gb:
            evictable = [
                e
                for e in self._entries.values()
                if not e.pinned and e.in_use == 0 and e.name != exclude
            ]
            if evictable:
                victim = min(evictable, key=lambda e: e.last_used)
                del self._entries[victim.name]
                self._emit()
                continue

            # Nothing evictable right now. Is anything in-use we could wait on?
            waitable = [
                e
                for e in self._entries.values()
                if not e.pinned and e.in_use > 0 and e.name != exclude
            ]
            if not waitable:
                msg = (
                    f"cannot free {needed_gb:.1f} GB within the "
                    f"{self.budget_gb:.1f} GB budget (resident {self.resident_gb():.1f} GB, "
                    "all pinned). Raise FORGE_LOCAL_RAM_BUDGET_GB."
                )
                raise PoolCapacityError(msg)
            await self._released.wait()
