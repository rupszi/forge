"""Shared pytest fixtures (Task 2.5).

Hosts fixtures that were previously duplicated across test files. Adding new
shared fixtures? Put them here.
"""

from __future__ import annotations

import pytest

from daemon import replay


@pytest.fixture
def tmp_db(tmp_path):
    """A clean ForgeDB in an isolated temp dir (WAL mode). Closed on teardown.

    Shared so tests don't each re-declare a db fixture. Existing per-file
    ``db`` fixtures still work; this is the canonical one for new tests.
    """
    from daemon.db import ForgeDB

    d = ForgeDB(str(tmp_path / "test.db"))
    yield d
    d.close()


@pytest.fixture
def tmp_forge_dir(tmp_path, monkeypatch):
    """Redirect the daemon's ``FORGE_DIR`` to a tmp_path-based ``.forge``.

    Yields the ``Path`` to the temp .forge directory. Tests that exercise
    on-disk replay state (``trace.jsonl`` writes, replay rendering) use this to
    keep their I/O isolated. Also patches ``memory_tool.FORGE_DIR`` so the
    working-memory scratchpad lands under the temp dir rather than the real
    ``.forge/memories/`` (F15 — previously "isolated" tests read live state).
    """
    from daemon import memory_tool

    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    monkeypatch.setattr(replay, "FORGE_DIR", str(forge_dir))
    monkeypatch.setattr(memory_tool, "FORGE_DIR", str(forge_dir))
    return forge_dir


@pytest.fixture(autouse=True)
def _reset_global_singletons():
    """Reset process-global singletons before and after every test (F15).

    Without this, test order couples through module state: the attachment store
    persists files across tests, the context-window size/KV preference leaks a
    mid-test mutation into the next test, and the MLX weight cache survives. The
    reset makes the suite order-independent (so ``pytest-randomly`` is honest).
    """
    from daemon import attachments, context_window
    from daemon.executors import mlx

    def _baseline() -> None:
        attachments._store = None
        context_window.set_setting("auto")
        context_window.set_kv_cache_type(context_window._default_kv_type())
        mlx.clear_cache()

    _baseline()
    yield
    _baseline()
