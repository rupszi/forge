"""Locality state — the honest "are we local or cloud" indicator (G-LOC-2).

Forge Studio runs fully local by default. The UI shows a "Local-only ●"
badge that flips to "Cloud enabled ▲" only when the user opts in. The daemon
is the single source of truth for that state (never inferred client-side), so
the indicator can't drift from reality.
"""

from __future__ import annotations

from .config import cloud_enabled


def locality_state() -> dict:
    """Return the current locality as a WebSocket-ready payload."""
    enabled = cloud_enabled()
    return {
        "type": "locality",
        "mode": "cloud" if enabled else "local",
        "cloud_enabled": enabled,
    }
