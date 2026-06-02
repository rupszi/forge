"""Executor selection — single source of truth (Task 2.6).

Lives in a leaf module so both ``daemon.agents.classifier`` (which returns
the executor type as a string for procedural-memory writes) and
``daemon.agents.generator`` (which dispatches to the executor module) can
import from the same place without forming an import cycle through
``daemon.agents.*``.

The function signature deliberately mirrors what ``classifier.select_executor``
used to expose, so external callers can switch their import path without
touching call sites.
"""

from __future__ import annotations

import os

from .config import model_family

# Executor strings that reach a paid / cloud endpoint. Selecting one on the
# default (offline) path is a guardrail violation; the generator raises
# ``CloudDisabledError`` at dispatch unless the user opted into cloud.
_CLOUD_EXECUTORS = frozenset({"claude_code", "batch"})


class CloudDisabledError(RuntimeError):
    """Raised when a cloud executor is requested without ``FORGE_CLOUD_ENABLED``.

    Forge Studio is local-first: the default path never dials out. When a
    cloud-only model is assigned (e.g. a Claude model) but cloud is off, we
    fail loudly rather than silently using cloud (G-LOC-2) or silently
    swapping the user's chosen model.
    """


def is_cloud_executor(executor: str) -> bool:
    """True if the executor string reaches a non-local / paid endpoint."""
    return executor in _CLOUD_EXECUTORS


def select_executor(model: str) -> str:
    """Pick the executor type for a given model identifier.

    Logic (unchanged from the prior classifier-local implementation):

      1. Anthropic / closed-Claude models always route through ``claude_code``
         (the ``claude -p`` subprocess executor inherits the user's ``.claude/``
         and MCP setup, so even one Claude call benefits from prompt caching).
      2. If the user has set ``OPENAI_BASE_URL``, every other model routes
         through ``openai_compatible`` (vLLM / SGLang / OpenRouter / Together).
      3. Otherwise, route through ``ollama`` (the default for laptop users).
    """
    # MLX-served weights (Apple Silicon) are addressed with an ``mlx:`` /
    # ``mlx-`` prefix and always run locally via the MLX executor.
    m = model.lower().strip()
    if m.startswith("mlx:") or m.startswith("mlx-"):
        return "mlx"
    fam = model_family(model)
    if fam == "anthropic":
        return "claude_code"
    if os.environ.get("OPENAI_BASE_URL"):
        return "openai_compatible"
    return "ollama"
