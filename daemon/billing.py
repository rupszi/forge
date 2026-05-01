"""Billing-tier detection for the dashboard's cost meter.

The dashboard's ContextMeter wants to know which "tier" the user is on
so it can decide whether to show:

  free          → Ollama-only or vLLM-on-localhost — no $ display, just
                  a "Free (Ollama)" badge + the context-window meter
  metered       → Paid API in use (OpenAI / Anthropic API direct without
                  a plan) — show a live $ bar against BudgetController
  subscription  → Anthropic plan-based (Pro / Max / Team) — show 5h/weekly
                  plan-tier bars instead of $ (we don't see the $ anyway)

Detection logic, in order of decreasing certainty:

  1. ``FORGE_BILLING_TIER`` env var explicitly set → use that
  2. Anthropic plan markers (claude.ai cookie present, ``CLAUDE_PRO=1``,
     ``CLAUDE_PLAN`` env var) → subscription
  3. ``ANTHROPIC_API_KEY`` set or ``OPENAI_API_KEY`` set → metered
     (we assume API direct ≠ plan unless proven otherwise)
  4. Default → free (Ollama / vLLM-on-localhost)

This module is the single source of truth — UI must NOT infer tier
from the model name (the previous client-side heuristic in
ContextMeter.tsx). Server-side detection lets the user override per
project (`.forge/config.toml [billing] tier = "metered"`) and survives
model swaps mid-session.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

Tier = Literal["free", "metered", "subscription"]


def detect_tier(project_path: str | None = None) -> Tier:
    """Determine the current billing tier.

    Parameters
    ----------
    project_path
        Project root to look up `.forge/config.toml` overrides. Use the
        scanner's resolved path; falls back to cwd.
    """
    # Layer 1: explicit env override (always wins)
    env_tier = os.environ.get("FORGE_BILLING_TIER", "").strip().lower()
    if env_tier in ("free", "metered", "subscription"):
        return env_tier  # type: ignore[return-value]

    # Layer 2: per-project config override
    cfg_tier = _read_project_tier_override(project_path)
    if cfg_tier is not None:
        return cfg_tier

    # Layer 3: Anthropic plan markers
    if any(os.environ.get(k) for k in ("CLAUDE_PRO", "CLAUDE_PLAN", "CLAUDE_MAX")):
        return "subscription"

    # Layer 4: API keys present → metered
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return "metered"

    # Layer 5: vLLM via OPENAI_BASE_URL pointing at localhost → still free
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    if base_url and not _is_localhost_url(base_url):
        # Remote OpenAI-compat endpoint (Together, OpenRouter, …) → metered
        return "metered"

    return "free"


def _read_project_tier_override(project_path: str | None) -> Tier | None:
    """Read ``.forge/config.toml [billing] tier`` if present."""
    if not project_path:
        return None
    config_path = Path(project_path) / ".forge" / "config.toml"
    if not config_path.is_file():
        return None
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError):
        return None
    val = data.get("billing", {}).get("tier", "").strip().lower()
    if val in ("free", "metered", "subscription"):
        return val  # type: ignore[return-value]
    return None


def _is_localhost_url(url: str) -> bool:
    """True if ``url`` points to localhost / 127.0.0.1 / 0.0.0.0."""
    return any(
        h in url
        for h in (
            "://localhost",
            "://127.0.0.1",
            "://0.0.0.0",
            "://[::1]",
        )
    )
