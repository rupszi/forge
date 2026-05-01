"""Safety: destructive-operation allow/deny lists + structured silent-catch
helper (Phase 3 Week 11).

Forge's threat model is "agent makes a mistake" rather than "agent is
malicious" (per ADR-013, SECURITY.md). Worktrees provide filesystem isolation;
this module adds a second layer: **a structured allow/deny list that catches
specific destructive shell commands the agent might emit even with the best
intentions.**

The reference TS/RN repo's pattern (Fittssy CLAUDE.md rule 28: "never trust
client-supplied user IDs", rule 19: "silentCatch helper for any catch block
that intentionally drops an error so it's grep-able") translates directly:

  1. ``is_destructive(command)`` — classifies a shell command as destructive
     by pattern match. Used by the MergeGate before applying generator-
     authored shell instructions, and by ``--sandbox=docker`` per-command
     gates.
  2. ``silent_catch(scope, exc)`` — explicit "we know this can fire and we're
     deliberately not propagating it" sink. Logs once via the ``forge.silent``
     logger so it's grep-able in audit logs.

What this module DOES NOT do:
  - Block execution (that's the caller's job — this module classifies)
  - Prompt the user (that's the UI layer)
  - Sandbox at the OS level (that's ``--sandbox=docker`` / worktrees)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)
silent_logger = logging.getLogger("forge.silent")


@dataclass(frozen=True)
class DestructiveOp:
    """Classification of a destructive command.

    ``severity`` is one of:
      - ``"warn"`` — should prompt the user but is recoverable (e.g., file delete)
      - ``"block"`` — should never run without explicit approval (rm -rf $HOME, force-push to main)
      - ``"audit"`` — non-destructive but audit-worthy (sudo, schema migration on prod)
    """

    pattern: str
    severity: str
    reason: str


# ---- Destructive-command catalog ----
#
# Each entry is a regex matched against the full command string. Order
# matters — the FIRST match wins so we put the most-specific rules first.
# Patterns are case-insensitive.
#
# When the user wants to *override* a block, the right path is per-tool
# allow/deny lists in ``.forge/safety.toml`` (read by load_user_overrides()).
# Don't softcoding bypasses here — every blocker should be surfaced to the
# user with a clear reason.

_DESTRUCTIVE_RULES: tuple[DestructiveOp, ...] = (
    # ---- BLOCK: never run without explicit approval ----
    DestructiveOp(
        pattern=r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-rf|-fr)\s+[~$/]",
        severity="block",
        reason="rm -rf with absolute path or $HOME — would wipe user data",
    ),
    DestructiveOp(
        pattern=r"\brm\s+-rf\s+/(?!\w)",
        severity="block",
        reason="rm -rf / — catastrophic",
    ),
    DestructiveOp(
        pattern=r"\bgit\s+push\s+(--force|--force-with-lease|-f)\s+.*\b(main|master|production|prod)\b",
        severity="block",
        reason="force-push to a protected branch",
    ),
    DestructiveOp(
        pattern=r"\bdrop\s+database\b",
        severity="block",
        reason="DROP DATABASE — would destroy production data",
    ),
    DestructiveOp(
        pattern=r"\btruncate\s+table\b",
        severity="block",
        reason="TRUNCATE TABLE — irreversible",
    ),
    DestructiveOp(
        # Classic ``:(){ :|:& };:`` fork bomb. Match the distinctive
        # ``:|:&`` substring + paren/brace shape; word boundaries don't
        # apply because ``:`` isn't a word character.
        pattern=r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
        severity="block",
        reason="fork bomb",
    ),
    # ---- BLOCK: catastrophic disk-level commands (Task 1.8) ----
    DestructiveOp(
        # mkfs is always catastrophic — it formats a device.
        pattern=r"\bmkfs\.\w+\b",
        severity="block",
        reason="mkfs — would format a filesystem",
    ),
    DestructiveOp(
        # ``dd of=/dev/<disk>`` writes raw bytes to a block device.
        # /dev/null, /dev/zero, /dev/stdout, /dev/stderr are safe targets.
        pattern=r"\bdd\s+(?:if=\S+\s+)?of=/dev/(?!null|zero|stdout|stderr)",
        severity="block",
        reason="dd of=/dev/<disk> — would overwrite a raw device",
    ),
    # ---- WARN: recoverable but should prompt ----
    DestructiveOp(
        pattern=r"\brm\s+-rf\s+",
        severity="warn",
        reason="rm -rf — recoverable from version control if the path is in repo",
    ),
    # ---- WARN: cloud-destructive ops (Task 1.8) ----
    DestructiveOp(
        # Match either flag order — operands can sit between the verb
        # ("rb"/"rm") and the flags. We require both an aws s3 verb that
        # deletes AND a --force flag somewhere in the command.
        pattern=r"\baws\s+s3\s+(?:rb|rm)\b.*\B--force\b",
        severity="warn",
        reason="aws s3 rb/rm --force — could delete buckets or objects",
    ),
    DestructiveOp(
        pattern=r"\bgh\s+repo\s+delete\b",
        severity="warn",
        reason="gh repo delete — removes a GitHub repository",
    ),
    DestructiveOp(
        pattern=r"\bkubectl\s+delete\s+(namespace|ns|all)\s+(--all\b|-A\b)",
        severity="warn",
        reason="kubectl delete --all — bulk namespace deletion",
    ),
    DestructiveOp(
        pattern=r"\bterraform\s+destroy\b",
        severity="warn",
        reason="terraform destroy — tears down infrastructure",
    ),
    DestructiveOp(
        pattern=r"\bdocker\s+system\s+prune\s+(-a|--all)\b",
        severity="warn",
        reason="docker system prune -a — removes all unused images + containers",
    ),
    DestructiveOp(
        # chmod -R 000 (or its symbolic equivalent ``---``) on a tree renders
        # the entire subtree inaccessible — recoverable, but only by an admin
        # with elevated privs.
        pattern=r"\bchmod\s+-R\s+(?:000|---)\b",
        severity="warn",
        reason="chmod -R 000 — renders entire tree inaccessible",
    ),
    DestructiveOp(
        pattern=r"\bgit\s+reset\s+--hard\b",
        severity="warn",
        reason="git reset --hard — discards local changes",
    ),
    DestructiveOp(
        pattern=r"\bgit\s+clean\s+-[fdx]+",
        severity="warn",
        reason="git clean -fdx — removes untracked files including ignored",
    ),
    DestructiveOp(
        pattern=r"\bgit\s+checkout\s+\.\b",
        severity="warn",
        reason="git checkout . — discards working-tree changes",
    ),
    DestructiveOp(
        pattern=r"\bgit\s+branch\s+-D\s+",
        severity="warn",
        reason="git branch -D — force-delete branch",
    ),
    DestructiveOp(
        pattern=r"\bnpm\s+(install|i)\s+",
        severity="warn",
        reason="npm install — runs arbitrary postinstall scripts",
    ),
    DestructiveOp(
        pattern=r"\bpip\s+install\s+",
        severity="warn",
        reason="pip install — runs arbitrary setup.py / build hooks",
    ),
    # ---- AUDIT: not destructive but worth recording ----
    DestructiveOp(
        pattern=r"\bsudo\b",
        severity="audit",
        reason="sudo — privilege elevation",
    ),
    DestructiveOp(
        pattern=r"\bcurl\s+.+\|\s*(bash|sh|zsh|python)\b",
        severity="audit",
        reason="curl | sh — pipe-to-shell installer",
    ),
    DestructiveOp(
        pattern=r"\bsupabase\s+db\s+(reset|push|migration\s+up)\b",
        severity="audit",
        reason="Supabase DB migration — production-affecting",
    ),
    DestructiveOp(
        pattern=r"\bvercel\s+(--prod|deploy\s+--prod)\b",
        severity="audit",
        reason="Vercel production deploy",
    ),
    DestructiveOp(
        pattern=r"\bstripe\s+(payments|charges)\s+create\b",
        severity="audit",
        reason="Stripe charge creation",
    ),
)


def is_destructive(command: str) -> DestructiveOp | None:
    """Classify a shell command. Returns the matching ``DestructiveOp`` or
    None if the command appears safe.

    The match is **substring/regex-based**, not full parsing. We accept some
    false positives (commands that look destructive but aren't, like
    ``echo "rm -rf bad-input"``) in exchange for being conservative — better
    to ask the user than silently run something dangerous.

    For multi-command lines (``cmd1 && cmd2 || cmd3``) the function returns
    the first match found anywhere in the string. The caller is expected to
    show the matched ``reason`` to the user.
    """
    if not command:
        return None
    for rule in _DESTRUCTIVE_RULES:
        if re.search(rule.pattern, command, re.IGNORECASE):
            return rule
    return None


def severity_blocks(severity: str) -> bool:
    """Return True iff a command at this severity should be hard-blocked
    (no user override at the per-tool level — only via explicit
    ``--sandbox=danger-full-access`` flag, equivalent to Codex's mode)."""
    return severity == "block"


# ---- silent_catch helper ----


def silent_catch(scope: str, exc: BaseException, *, log_level: int = logging.WARNING) -> None:
    """Explicitly drop an exception you know about, in a grep-able way.

    Pattern from the reference engineering standards (Fittssy CLAUDE.md
    rule 19): empty ``except: pass`` blocks are forbidden. When you
    intentionally swallow an exception:

        try:
            do_thing()
        except OSError as e:
            silent_catch(__name__, e)

    The exception is logged via the dedicated ``forge.silent`` logger so
    audit-log scans can grep ``"silent_catch"`` to find every place this
    happens. Each call adds:

      - The scope (typically ``__name__`` of the calling module)
      - The exception class + message
      - The full traceback (via ``exc_info=True``)

    Why this exists: an empty ``except: pass`` hides bugs — at scale you
    end up with silent data loss because some intermittent error is being
    swallowed and the project's audit log has no record of it. Forcing
    every silent-catch through this helper makes them grep-able and
    countable.
    """
    silent_logger.log(
        log_level,
        "silent_catch in %s: %s: %s",
        scope,
        type(exc).__name__,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
