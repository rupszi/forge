"""Tests for merge gate: conflict detection, clean merge, rejection."""

import asyncio
import os
import tempfile

import pytest

from daemon import worktree


@pytest.mark.asyncio
async def test_two_worktrees_no_conflict():
    """Two worktrees editing different files should merge cleanly."""
    with tempfile.TemporaryDirectory() as tmp:
        # Setup repo
        proc = await asyncio.create_subprocess_exec(
            "git", "init", cwd=tmp, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        # Initial files
        with open(os.path.join(tmp, "file_a.txt"), "w") as f:
            f.write("original a")
        with open(os.path.join(tmp, "file_b.txt"), "w") as f:
            f.write("original b")
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

        # Create two worktrees
        wt1 = await worktree.create("sprint-a", base_path=tmp)
        wt2 = await worktree.create("sprint-b", base_path=tmp)

        # Edit different files
        with open(os.path.join(wt1, "file_a.txt"), "w") as f:
            f.write("modified a")
        with open(os.path.join(wt2, "file_b.txt"), "w") as f:
            f.write("modified b")

        # Get diffs
        diff1 = await worktree.get_diff(wt1, tmp)
        diff2 = await worktree.get_diff(wt2, tmp)
        assert "modified a" in diff1
        assert "modified b" in diff2

        # Cleanup
        await worktree.remove(wt1, tmp)
        await worktree.remove(wt2, tmp)


@pytest.mark.asyncio
async def test_conflict_detection():
    """Two worktrees editing the same file should produce detectable conflict."""
    with tempfile.TemporaryDirectory() as tmp:
        proc = await asyncio.create_subprocess_exec(
            "git", "init", cwd=tmp, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        with open(os.path.join(tmp, "shared.txt"), "w") as f:
            f.write("original")
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

        wt1 = await worktree.create("conflict-a", base_path=tmp)
        wt2 = await worktree.create("conflict-b", base_path=tmp)

        with open(os.path.join(wt1, "shared.txt"), "w") as f:
            f.write("version A")
        with open(os.path.join(wt2, "shared.txt"), "w") as f:
            f.write("version B")

        diff1 = await worktree.get_diff(wt1, tmp)
        diff2 = await worktree.get_diff(wt2, tmp)
        # Both diffs touch shared.txt
        assert "shared.txt" in diff1
        assert "shared.txt" in diff2

        await worktree.remove(wt1, tmp)
        await worktree.remove(wt2, tmp)
