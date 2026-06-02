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
    """Redirect ``daemon.replay.FORGE_DIR`` to a tmp_path-based ``.forge``.

    Yields the ``Path`` to the temp .forge directory. Tests that exercise
    on-disk replay state (``trace.jsonl`` writes, replay rendering) use
    this to keep their I/O isolated.
    """
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    monkeypatch.setattr(replay, "FORGE_DIR", str(forge_dir))
    return forge_dir
