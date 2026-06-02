"""Git branch control for the folder/branch picker (M5 onboarding).

Small async wrappers over ``git`` so the dashboard can: connect a folder
(empty or existing), list its branches, select/create one, and initialize a
repo in an empty folder. All subprocesses use argument lists (no shell), and
branch names are validated against a strict allow-list before they reach git.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

# Git branch names: letters, digits, dot, underscore, slash, hyphen. No spaces,
# no ``..``, no leading ``-``, no ref-magic chars (~^:?*[). Keeps the value safe
# to pass to git and rejects path-traversal-looking input.
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _valid_branch(name: str) -> bool:
    if not name or len(name) > 200:
        return False
    if ".." in name or name.endswith("/") or name.endswith(".lock"):
        return False
    return bool(_BRANCH_RE.match(name))


async def _git(path: str, *args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return (
        proc.returncode,
        out.decode(errors="replace").strip(),
        err.decode(errors="replace").strip(),
    )


async def list_branches(path: str) -> dict:
    """Return ``{is_git, current, branches}`` for a folder."""
    if not (Path(path) / ".git").exists():
        return {"is_git": False, "current": None, "branches": []}
    code, out, _ = await _git(path, "branch", "--format=%(refname:short)")
    branches = [ln.strip() for ln in out.splitlines() if ln.strip()] if code == 0 else []
    code2, cur, _ = await _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    current = cur if code2 == 0 and cur else None
    return {"is_git": True, "current": current, "branches": branches}


async def checkout_branch(path: str, branch: str, create: bool = False) -> dict:
    """Check out ``branch`` (optionally creating it). Returns ``{ok, current?, error?}``."""
    if not _valid_branch(branch):
        return {"ok": False, "error": f"invalid branch name: {branch!r}"}
    args = ["checkout", *(["-b"] if create else []), branch]
    code, out, err = await _git(path, *args)
    if code != 0:
        return {"ok": False, "error": (err or out or "checkout failed")}
    return {"ok": True, "current": branch}


async def init_repo(path: str) -> dict:
    """Initialize a git repo in ``path`` (for connecting an empty folder)."""
    code, out, err = await _git(path, "init")
    if code != 0:
        return {"ok": False, "error": (err or out or "git init failed")}
    return {"ok": True}
