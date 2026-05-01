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
    fam = model_family(model)
    if fam == "anthropic":
        return "claude_code"
    if os.environ.get("OPENAI_BASE_URL"):
        return "openai_compatible"
    return "ollama"
