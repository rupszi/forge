"""Tests for worktree manager: create, remove, sanitize, limits."""

import asyncio
import os
import tempfile

import pytest

from daemon.worktree import _validate_name, sanitize_worktree_name


def test_sanitize_valid_name():
    assert sanitize_worktree_name("sprint-abc123") == "sprint-abc123"


def test_sanitize_invalid_chars():
    assert sanitize_worktree_name("sprint/abc def!") == "sprint-abc-def-"


def test_sanitize_long_name():
    assert len(sanitize_worktree_name("x" * 100)) == 64


def test_sanitize_empty():
    assert sanitize_worktree_name("") == "worktree"


def test_validate_name_valid():
    assert _validate_name("sprint-abc123") is True
    assert _validate_name("test") is True


def test_validate_name_invalid():
    assert _validate_name("sprint/abc") is False
    assert _validate_name("has space") is False
    assert _validate_name("") is False


@pytest.mark.asyncio
async def test_create_and_remove():
    with tempfile.TemporaryDirectory() as tmp:
        # Initialize a git repo
        proc = await asyncio.create_subprocess_exec(
            "git",
            "init",
            cwd=tmp,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        # Need at least one commit
        proc = await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "--allow-empty",
            "-m",
            "init",
            cwd=tmp,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        from daemon import worktree

        wt_path = await worktree.create("test-wt", base_path=tmp)
        assert os.path.exists(wt_path)
        assert "test-wt" in wt_path

        # List
        wts = await worktree.list_worktrees(base_path=tmp)
        assert len(wts) >= 2  # main + test-wt

        # Remove
        await worktree.remove("test-wt", base_path=tmp)
        assert not os.path.exists(wt_path)


@pytest.mark.asyncio
async def test_concurrent_create_no_duplicate_tracking(tmp_path):
    """Two concurrent create() calls for the same name converge on a single
    registered wt_path — no double-registration.

    Guards Task 2.1: previously ``_active_worktrees`` was a list and the
    check-then-append wasn't atomic, so two near-simultaneous create() calls
    could each see "not in list" and each append. After the lock-based fix,
    the second caller sees the first one's wt_path already in the set and
    short-circuits to the same path.
    """
    from daemon import worktree

    worktree._active_worktrees.clear()

    # Stub _run_git so we don't shell out to git for this concurrency test.
    git_calls = []

    async def fake_run_git(args, cwd=None):
        git_calls.append(args)
        # Pretend the worktree-add succeeded.
        return (0, "", "")

    original = worktree._run_git
    worktree._run_git = fake_run_git
    try:
        name = "concurrent-test"
        results = await asyncio.gather(
            worktree.create(name, base_path=str(tmp_path)),
            worktree.create(name, base_path=str(tmp_path)),
        )
    finally:
        worktree._run_git = original

    assert results[0] == results[1], "concurrent calls returned different paths"
    matching = [w for w in worktree._active_worktrees if name in w]
    assert len(matching) == 1, f"double-registration: {matching}"


def test_active_worktrees_is_a_set():
    """Sanity: the storage type must be a set (not a list) for O(1) membership
    checks and natural dedup. Regression guard for Task 2.1."""
    from daemon import worktree

    assert isinstance(worktree._active_worktrees, set)


@pytest.mark.asyncio
async def test_get_diff():
    with tempfile.TemporaryDirectory() as tmp:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "init",
            cwd=tmp,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        # Create a file and commit
        with open(os.path.join(tmp, "test.txt"), "w") as f:
            f.write("hello")
        proc = await asyncio.create_subprocess_exec(
            "git",
            "add",
            ".",
            cwd=tmp,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        proc = await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "-m",
            "init",
            cwd=tmp,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        from daemon import worktree

        wt_path = await worktree.create("diff-test", base_path=tmp)

        # Modify a file in worktree
        with open(os.path.join(wt_path, "test.txt"), "w") as f:
            f.write("world")

        diff = await worktree.get_diff(wt_path, base_path=tmp)
        assert "hello" in diff or "world" in diff

        await worktree.remove(wt_path, base_path=tmp)
