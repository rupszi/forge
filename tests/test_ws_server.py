"""Tests for daemon/ws_server.py rate limiting + input validation + lifecycle.

Guards Task 1.4 (rate limit + size cap + path validation) and Task 1.7
(graceful shutdown via shutdown_event).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from daemon.budget import BudgetController
from daemon.db import ForgeDB
from daemon.ws_server import (
    _MAX_CONCURRENT_HANDLERS,
    _MAX_MESSAGE_BYTES,
    _RATE_LIMIT_MAX_MSG,
    _client_msg_times,
    _message_semaphore,
    _rate_limit_check,
    _validate_init_path,
    start_server,
)

# ---- Rate limiter ----


def test_rate_limiter_allows_burst_within_window():
    _client_msg_times.clear()
    for _ in range(_RATE_LIMIT_MAX_MSG):
        assert _rate_limit_check(client_id=1) is True


def test_rate_limiter_rejects_after_burst_exceeds_max():
    _client_msg_times.clear()
    for _ in range(_RATE_LIMIT_MAX_MSG):
        _rate_limit_check(client_id=2)
    assert _rate_limit_check(client_id=2) is False


def test_rate_limiter_recovers_after_window():
    _client_msg_times.clear()
    for _ in range(_RATE_LIMIT_MAX_MSG):
        _rate_limit_check(client_id=3)
    # Manually expire the deque (simulates window having passed).
    _client_msg_times[3].clear()
    assert _rate_limit_check(client_id=3) is True


def test_rate_limiter_keys_per_client():
    """Two clients each get their own budget."""
    _client_msg_times.clear()
    for _ in range(_RATE_LIMIT_MAX_MSG):
        _rate_limit_check(client_id=10)
    # Client 10 is exhausted, client 20 is fresh.
    assert _rate_limit_check(client_id=10) is False
    assert _rate_limit_check(client_id=20) is True


# ---- Path validation ----


def test_validate_init_path_accepts_home():
    assert _validate_init_path(os.path.expanduser("~")) is True


def test_validate_init_path_accepts_subdir_of_home():
    assert _validate_init_path(os.path.join(os.path.expanduser("~"), "anywhere")) is True


def test_validate_init_path_accepts_cwd_relative():
    assert _validate_init_path(".") is True


def test_validate_init_path_rejects_etc():
    """/etc is not under home or cwd (in any normal test environment)."""
    # On a CI runner where the test happens to live inside /etc/something,
    # this assertion would degenerate; that's not a real environment we
    # support, so the assertion is fine as-is.
    assert _validate_init_path("/etc/passwd") is False


def test_validate_init_path_rejects_var():
    assert _validate_init_path("/var/log/system.log") is False


def test_validate_init_path_normalizes_traversal():
    """Traversal-style input is normalized; the absolute form determines acceptance.

    The function does not blindly accept ``../../etc/passwd`` — it normalizes
    via ``os.path.abspath`` and re-checks against home / cwd. Since the
    test runs from somewhere inside the user's home (typical) or CI's
    workspace, the normalized path will resolve outside both anchors → rejected.
    """
    out = _validate_init_path("../../../../../etc/passwd")
    assert out is False


# ---- Size cap (constant assertion) ----


def test_message_size_cap_is_one_mb():
    """Sanity: the cap is the documented value, not silently inflated."""
    assert _MAX_MESSAGE_BYTES == 1_000_000


# ---- Task 2.3: handler semaphore ----


def test_message_handler_semaphore_caps_at_documented_limit():
    """The semaphore's initial value matches the documented constant.

    Real concurrency-bound testing (spawning N>limit handlers and observing
    the throttle) is integration territory — for the unit guard, asserting
    the constant + the underlying semaphore value matches is enough.
    """
    assert _MAX_CONCURRENT_HANDLERS == 10
    # Semaphore._value is private but stable across asyncio versions; this
    # is a sanity check, not a public-API assertion.
    assert _message_semaphore._value == _MAX_CONCURRENT_HANDLERS


# ---- Graceful shutdown (Task 1.7) ----


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "forge.db"))
        yield db
        db.close()


@pytest.mark.asyncio
async def test_start_server_returns_when_shutdown_event_set(tmp_db, monkeypatch):
    """The server returns cleanly when shutdown_event is set, without hanging.

    We patch WS_PORT to a high random-ish port to avoid colliding with a
    locally-running daemon.
    """
    monkeypatch.setattr("daemon.ws_server.WS_PORT", 0)  # 0 = OS-assigned

    shutdown = asyncio.Event()
    budget = BudgetController(budget_usd=10.0)

    async def trigger_shutdown_soon():
        await asyncio.sleep(0.05)
        shutdown.set()

    # If shutdown plumbing is wrong this test hangs — surface that as a
    # 2 s timeout rather than letting CI stall.
    await asyncio.wait_for(
        asyncio.gather(
            start_server(tmp_db, budget, shutdown_event=shutdown),
            trigger_shutdown_soon(),
        ),
        timeout=2.0,
    )
