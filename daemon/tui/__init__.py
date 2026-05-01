"""Terminal UI for Forge — Sprint 6.5.

Built on Textual (Python's Ink-equivalent reactive-component TUI library).
Same WebSocket interface as the Next.js dashboard, just a different
client; both can run simultaneously against the same daemon.

Entry point: ``forge tui`` (defined in daemon/cli.py).

Why Textual:
  - Reactive components / event-driven model matches Claude Code's Ink
    feel (vs Codex's immediate-mode Ratatui paradigm)
  - Stays in Python — no second language for the daemon's primary surface
  - First-class CSS-like styling, mouse + keyboard support, async-native
  - Will McGugan's library (Rich author); mature, well-maintained
"""

from __future__ import annotations

# Lazy import so the daemon never imports textual unless the user runs
# `forge tui`. textual is in the `forge[tui]` optional extra; absent
# users see a friendly install hint.
__all__ = ["run_tui"]


def run_tui() -> int:
    """Launch the TUI. Returns exit code."""
    try:
        from .app import ForgeTUI
    except ImportError as e:
        print(  # noqa: T201
            "\nForge TUI requires the [tui] extra. Install:\n"
            "  pip install -e '.[tui]'\n"
            "  # or\n"
            "  uv pip install -e '.[tui]'\n"
        )
        print(f"  (specifically: {e})")  # noqa: T201
        return 1

    app = ForgeTUI()
    app.run()
    return 0
