"""Tests for ForgeDB lifecycle — close idempotency, atexit registration.

Guards Task 1.3: previously close() was only invoked when callers explicitly
ran it, so a SIGKILL or unhandled exception could leave .forge/forge.db-wal
in an inconsistent state. The atexit handler + __del__ backstop close on
shutdown, and close() itself is now idempotent so the multiple-cleanup
paths can't double-close.
"""

from __future__ import annotations

import os
import tempfile
import weakref

from daemon.db import ForgeDB


def test_close_is_idempotent():
    """Calling close() multiple times must not raise."""
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))
        db.close()
        db.close()  # Should not raise


def test_atexit_safe_close_handles_dead_ref():
    """The atexit lambda doesn't crash if the instance was already GC'd."""
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))
        ref = weakref.ref(db)
        db.close()
        del db
        # Simulate atexit firing after GC — must be a clean no-op.
        ForgeDB._safe_close(ref)


def test_close_flag_prevents_double_close_during_atexit():
    """If close() ran explicitly, atexit handler is a no-op."""
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))
        db.close()
        assert db._closed is True
        # The static safe-close must still run cleanly.
        ForgeDB._safe_close(weakref.ref(db))


def test_safe_close_on_open_db_actually_closes():
    """If atexit fires before explicit close, _safe_close runs the close path."""
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))
        ref = weakref.ref(db)
        assert db._closed is False
        ForgeDB._safe_close(ref)
        assert db._closed is True
        # Idempotent: calling again is still safe.
        ForgeDB._safe_close(ref)
