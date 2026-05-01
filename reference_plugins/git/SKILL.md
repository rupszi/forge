# git (read-only)

Read-only git operations on the current worktree. Use this when the
planner or generator needs to inspect repository state without modifying
it: `status`, `log`, `diff`, `blame`, `show`, or `ls-files`.

## Why this is read-only

This is a *reference* plugin demonstrating the connector contract. It
intentionally stops at read-only operations because:

1. Write operations (commit, push, branch, merge) belong in
   `forge_plugin_api.Connector` subclasses with explicit `side_effects:
   "external"` Tool decorators — not in a sandboxed subprocess.
2. The Forge scheduler already creates / removes worktrees and merges
   approved branches; a generic write-capable git connector would
   compete with that contract.

## Calling pattern

The dispatcher invokes `scripts/main.py` with the operation as the first
argument and any extra args after:

    git status
    git log --oneline -10
    git diff HEAD~1 HEAD
    git blame <file>

Output is plain text on stdout; non-zero exit means the underlying
`git` invocation failed (the wrapper does not synthesize errors).

## Capability scope

| Capability       | Value             | Why                                 |
|------------------|-------------------|-------------------------------------|
| network          | (empty)           | git is local                        |
| filesystem       | `${WORKTREE}`     | reads the working tree              |
| exec             | (empty)           | uses subprocess via stdlib          |
| secrets_read     | (empty)           | no auth needed for read ops         |

## Trifecta classification

This plugin reads private (worktree) but does not read untrusted
(no untrusted input arrives via the script's args — the planner
controls them) and does not write external. Safe by construction.
