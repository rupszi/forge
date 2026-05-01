"""Session-level mode state — Sprint 6.2.

Forge's UI exposes a five-position mode picker (auto / accept_edits / plan /
ask / bypass), modeled on Claude Code's permission modes. Until now the
WS server stashed the choice on ``budget._mode`` as a hack; this module
gives modes a real home and threads them through the scheduler so they
*actually change behavior*.

Semantics for each mode at the scheduler boundary:

  ``auto``         — default. The agent loop runs end-to-end without
                     interruption. Used for headless / batch runs.

  ``accept_edits`` — same as ``auto`` for the daemon (Forge always edits
                     in an isolated worktree, so per-edit prompts don't
                     map). Surfaced as an explicit choice so the UI can
                     visually distinguish "I want it to keep going" from
                     "I might step in" without changing daemon behavior.

  ``plan``         — produce the plan; do NOT execute waves. The user
                     reviews the sprints in the UI / TUI before clicking
                     "Run all" (which sends ``set_mode auto`` then ``run``).

  ``ask``          — inject a "describe your approach before destructive
                     operations" preamble into the generator prompt and
                     pause after each sprint for user review. v0.1.0
                     implementation is the prompt nudge only; a full
                     interactive checkpoint flow lands in Sprint 7.

  ``bypass``       — warn loudly (audit-log + WS event) but otherwise
                     behave as ``auto``. There's nothing for the daemon
                     to "bypass" today — every action already runs in
                     a worktree with capability scope. The mode exists
                     because users coming from Claude Code expect it.

The state is process-wide: a single ``ModeState`` instance is created by
the daemon at startup, mutated via ``set_mode``, and consulted by the
scheduler at the wave boundary. The TUI / UI subscribes to
``mode_changed`` events and reflects the choice in the status bar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


VALID_MODES: tuple[str, ...] = ("auto", "accept_edits", "plan", "ask", "bypass")
DEFAULT_MODE: str = "auto"


class InvalidMode(ValueError):
    """Raised when ``set_mode`` receives an unrecognized mode string."""


@dataclass
class ModeState:
    """Process-wide mode state — read by the scheduler, mutated by the WS server.

    Default is ``auto``. The instance is constructed once at daemon startup
    and threaded into ``scheduler.execute_session`` (and into prompt
    builders in the generator) so the agent loop can branch on it.
    """

    mode: str = DEFAULT_MODE

    def set(self, new_mode: str) -> str:
        """Update the active mode. Returns the resolved mode string.

        Unknown modes raise ``InvalidMode``; we never silently fall back
        to a default (would mask UI bugs).
        """
        if new_mode not in VALID_MODES:
            raise InvalidMode(f"unknown mode {new_mode!r}; valid modes are {VALID_MODES}")
        if new_mode == self.mode:
            return self.mode
        old = self.mode
        self.mode = new_mode
        logger.info("mode changed: %s → %s", old, new_mode)
        return self.mode

    def is_plan_only(self) -> bool:
        """True iff the scheduler should produce the plan but skip execution."""
        return self.mode == "plan"

    def is_bypass(self) -> bool:
        """True iff capability prompts should be suppressed.

        Currently the daemon doesn't *have* per-action capability prompts —
        all enforcement happens at the dispatcher boundary regardless of
        mode. This flag exists so future per-tool checkpoints (Sprint 7)
        can branch on it without re-plumbing ModeState.
        """
        return self.mode == "bypass"

    def is_ask(self) -> bool:
        """True iff the generator should be prompted to describe its
        approach before destructive operations."""
        return self.mode == "ask"

    def to_dict(self) -> dict[str, str]:
        return {"mode": self.mode}


def mode_prompt_addendum(mode: str) -> str:
    """Return the extra system-prompt text to inject for the given mode.

    Stable per-mode (cacheable in the prompt-prefix block). Empty string
    for modes that don't change generator behavior — keeps the cache
    boundary stable for ``auto`` / ``accept_edits`` runs.
    """
    if mode == "ask":
        return (
            "Operating mode: ASK. Before any destructive operation "
            "(file delete, schema migration, force push, secret access), "
            "describe what you're about to do and why on a single line "
            "prefixed with 'PLAN:' so the user can interrupt. Non-destructive "
            "edits (creating files, adding tests, refactoring) need no preamble."
        )
    if mode == "bypass":
        return (
            "Operating mode: BYPASS. The user has explicitly waived "
            "interactive checkpoints. Proceed directly; rely on the test "
            "and evaluator gates for safety."
        )
    return ""
