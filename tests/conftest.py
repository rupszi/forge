"""Shared pytest fixtures (Task 2.5).

Hosts fixtures that were previously duplicated across test files. Adding new
shared fixtures? Put them here.
"""

from __future__ import annotations

import pytest

from daemon import replay


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
