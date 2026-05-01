"""Git worktree lifecycle: create, remove, list, diff."""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import re
import signal

from .config import MAX_PARALLEL_AGENTS, WORKTREE_NAME_PATTERN

logger = logging.getLogger(__name__)

# Task 2.1: a set + lock replaces the previous list-based tracker. Two
# concurrent ``create()`` calls for the same name no longer double-register
# (the prior list path had a TOCTOU window between the duplicate check and
# the append). The lock is also what makes the MAX_PARALLEL_AGENTS gate
# atomic instead of "two creates squeak past the threshold check together".
_active_worktrees: set[str] = set()
_active_worktrees_lock = asyncio.Lock()


def sanitize_worktree_name(name: str) -> str:
    """Ensure worktree name is alphanumeric + hyphens only."""
    sanitized = re.sub(r"[^a-zA-Z0-9\-]", "-", name)
    return sanitized[:64] or "worktree"


def _validate_name(name: str) -> bool:
    return bool(re.match(WORKTREE_NAME_PATTERN, name))


async def _run_git(args: list[str], cwd: str = None) -> tuple:
    """Run a git command safely (no shell=True)."""
    cmd = ["git"] + args
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    return (
        proc.returncode,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


async def create(name: str, base_path: str = None) -> str:
    """Create a git worktree. Returns the worktree path.

    The cap check, registration, and (for already-existing paths) the early
    return all happen under ``_active_worktrees_lock`` so two concurrent
    ``create()`` calls for the same name converge on the same wt_path
    without double-registering or squeaking past the cap together.
    """
    if not _validate_name(name):
        name = sanitize_worktree_name(name)

    base = base_path or os.getcwd()
    wt_dir = os.path.join(base, ".forge", "worktrees")
    wt_path = os.path.join(wt_dir, name)

    async with _active_worktrees_lock:
        # If another caller already registered this path (or it exists on
        # disk), we don't re-create — just return the same wt_path.
        if wt_path in _active_worktrees or os.path.exists(wt_path):
            _active_worktrees.add(wt_path)
            return wt_path

        # Cap check is now atomic with the registration.
        if len(_active_worktrees) >= MAX_PARALLEL_AGENTS:
            raise RuntimeError(f"Max {MAX_PARALLEL_AGENTS} concurrent worktrees reached")

        os.makedirs(wt_dir, exist_ok=True)
        branch_name = f"forge/{name}"
        code, _out, err = await _run_git(["worktree", "add", "-b", branch_name, wt_path], cwd=base)
        if code != 0:
            # Branch might already exist, try without -b
            code, _out, err = await _run_git(["worktree", "add", wt_path], cwd=base)
            if code != 0:
                raise RuntimeError(f"Failed to create worktree '{name}': {err}")

        _active_worktrees.add(wt_path)
        logger.info("Created worktree: %s", wt_path)
        return wt_path


async def remove(name_or_path: str, base_path: str = None) -> None:
    """Remove a git worktree."""
    base = base_path or os.getcwd()

    if os.path.isabs(name_or_path):
        wt_path = name_or_path
    else:
        wt_path = os.path.join(base, ".forge", "worktrees", name_or_path)

    code, _, err = await _run_git(["worktree", "remove", wt_path, "--force"], cwd=base)
    if code != 0:
        logger.warning("Failed to remove worktree %s: %s", wt_path, err)

    # Set discard is idempotent — safe whether or not we registered it.
    _active_worktrees.discard(wt_path)

    # Clean up branch
    name = os.path.basename(wt_path)
    branch = f"forge/{name}"
    await _run_git(["branch", "-D", branch], cwd=base)


async def get_diff(name_or_path: str, base_path: str = None) -> str:
    """Get the git diff for a worktree."""
    base = base_path or os.getcwd()
    if os.path.isabs(name_or_path):
        wt_path = name_or_path
    else:
        wt_path = os.path.join(base, ".forge", "worktrees", name_or_path)

    code, diff, _ = await _run_git(["diff", "HEAD"], cwd=wt_path)
    if code != 0:
        # Try diff against main
        code, diff, _ = await _run_git(["diff", "main...HEAD"], cwd=wt_path)
    return diff


async def list_worktrees(base_path: str = None) -> list[dict]:
    """List all git worktrees."""
    base = base_path or os.getcwd()
    code, out, _ = await _run_git(["worktree", "list", "--porcelain"], cwd=base)
    if code != 0:
        return []

    worktrees = []
    current = {}
    for line in out.split("\n"):
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]
        elif line == "bare":
            current["bare"] = True
    if current:
        worktrees.append(current)

    return worktrees


async def cleanup_all(base_path: str = None) -> None:
    """Remove all forge worktrees. Called on exit."""
    for wt_path in list(_active_worktrees):
        try:
            await remove(wt_path, base_path)
        except Exception as e:
            logger.error("Failed to cleanup worktree %s: %s", wt_path, e)
    _active_worktrees.clear()


def _sync_cleanup():
    """Synchronous cleanup for atexit/signal handlers."""
    import subprocess

    for wt_path in list(_active_worktrees):
        try:
            subprocess.run(
                ["git", "worktree", "remove", wt_path, "--force"], capture_output=True, timeout=10
            )
        except Exception:
            pass
    _active_worktrees.clear()


# Register cleanup handlers
atexit.register(_sync_cleanup)


def register_signal_handlers():
    """Register SIGINT/SIGTERM handlers for worktree cleanup."""
    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def handler(signum, frame):
        _sync_cleanup()
        if signum == signal.SIGINT and callable(original_sigint):
            original_sigint(signum, frame)
        elif signum == signal.SIGTERM and callable(original_sigterm):
            original_sigterm(signum, frame)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
