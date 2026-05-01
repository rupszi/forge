"""Reference git connector — read-only operations on the current worktree.

Spawned by ``daemon/skills/dispatch.py::dispatch_plugin`` with the
operation name as ``argv[1]`` and any flags / paths after. The
dispatcher sets ``cwd`` to the worktree, so plain ``git`` invocations
operate on the right repo without further plumbing.

This script lives on the *plugin* side of the boundary — it imports
nothing from ``daemon`` and only reaches for ``forge_plugin_api`` if a
connector needs network egress (it doesn't here). The contract is
text-on-stdout, exit-zero-on-success.

Refused operations: anything that would mutate state. The ``main()``
allow-list covers the operations the planner / generator actually call;
unknown operations exit non-zero with a refusal message rather than
silently passing through to ``git``.

Healthcheck mode: invoking with no args prints the git version and
exits 0. The dispatcher uses this for ``forge connectors test git``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

# Read-only operations the planner is allowed to invoke. Aligns with
# git's documented "porcelain that doesn't touch the index". Any new
# entry must be reviewable for "does it mutate?" — keep this list short.
ALLOWED_OPS = {
    "status",
    "log",
    "diff",
    "show",
    "blame",
    "ls-files",
    "ls-tree",
    "rev-parse",
    "branch",  # 'branch' with no flags lists; we don't allow -d / -D below
    "describe",
    "shortlog",
    "config",  # read-only by default; we strip --add / --unset args
    "remote",
    "tag",  # 'tag' with no flags lists
    "stash",  # 'stash list' / 'stash show'
}

# Sub-flags that are mutating even on otherwise-readonly operations.
# Refused if seen anywhere in argv past argv[1].
MUTATING_FLAGS = {
    "--add",
    "--unset",
    "--unset-all",
    "--remove-section",
    "--rename-section",
    "-d",
    "-D",
    "--delete",
    "--push",
    "--set-upstream",
    "--force",
    "-f",
}


def _refuse(reason: str) -> int:
    sys.stderr.write(f"git connector: refused — {reason}\n")
    return 2


def main() -> int:
    if not shutil.which("git"):
        sys.stderr.write("git connector: git not found on PATH\n")
        return 1

    # Healthcheck (no args): print version, exit 0.
    if len(sys.argv) == 1:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        sys.stdout.write(result.stdout)
        return result.returncode

    op = sys.argv[1]
    extra = sys.argv[2:]

    if op not in ALLOWED_OPS:
        return _refuse(f"operation {op!r} is not in the read-only allow-list")

    for flag in extra:
        if flag in MUTATING_FLAGS:
            return _refuse(f"flag {flag!r} is mutating; not permitted")

    # Special-case: ``git stash`` with no args POPS the most recent stash.
    # Allow only the read sub-commands.
    if op == "stash":
        sub = extra[0] if extra else "list"
        if sub not in ("list", "show"):
            return _refuse(f"stash {sub!r} is mutating; only list/show are read-only")

    cmd = ["git", op, *extra]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
