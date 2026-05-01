"""Task classifier: routes tasks by complexity using heuristic + procedural + LLM.

This module decides three things per sprint:

  1. **Complexity tier** — low / medium / high. Drives generator model choice.
  2. **Generator model** — what to dispatch the writing work to.
  3. **Evaluator model** — must be from a *different family* than the generator
     to avoid the same-family self-evaluation bias documented in MT-Bench (Claude-v1
     +25% self-bias, GPT-4 +10%) and Anthropic's harness research. See ADR-006.

The decision is layered:

  1. **Procedural lookup** — if the project's procedural-memory store has a
     high-confidence pattern for similar tasks (>0.8 success rate, ≥2 samples),
     use that routing. This is online RouteLLM (Phase 1 Week 6 wires up the
     writeback loop).
  2. **Heuristic regex** — fast, deterministic. Catches the common low/high
     phrases (typo / readme / lint = low; architect / migration / rewrite = high).
  3. **LLM fallback** — when the heuristic returns ambiguous, ask the local
     classify model for a 1–10 complexity score.

When a task description matches none of the layers, default to **medium** —
that's the safest "Forge will spend an evaluator pass on this" tier.
"""

from __future__ import annotations

import logging
import re

import httpx

from ..config import (
    LOCAL_CLASSIFY_MODEL,
    LOCAL_CODE_MODEL,
    LOCAL_MID_MODEL,
    LOCAL_PREMIUM_MODEL,
    OLLAMA_BASE_URL,
    model_family,
)

# Task 2.6: select_executor is owned by ``daemon.routing`` (a leaf module
# importable from both classifier.py and generator.py without cycles).
# Re-exported so existing call sites continue to work.
from ..routing import select_executor

logger = logging.getLogger(__name__)

# ---- Heuristic patterns ----
#
# These are deliberately conservative — false positives are expensive (we
# would route a hard task to the cheap tier). When the pattern is ambiguous
# the function returns None and the caller falls through to the LLM classifier.

_LOW_PATTERNS = re.compile(
    r"\b(typo|readme|comment|rename|format|lint|docstring|whitespace|"
    r"spelling|reword|copyright|license header|changelog|remove unused|"
    r"update version|add type hint)\b",
    re.IGNORECASE,
)

_HIGH_PATTERNS = re.compile(
    r"\b(architect|design system|security audit|migration|"
    r"refactor entire|rewrite|distributed|consensus|"
    r"performance optim|database schema|api design|infrastructure|"
    r"load balanc|sharding|caching layer|message queue|event sourcing|"
    r"microservice|monorepo)\b",
    re.IGNORECASE,
)

# ---- Routing: complexity → (generator_model, agent_type) ----
#
# Updated 2026-04-30 (ADR-003) for the post-Apr-23 open-weight ceiling shift.
# Generator-model defaults map to env vars in config.py so users can override
# without editing this file.
#
# The ``agent_type`` field tells the scheduler which executor to dispatch
# through. ``select_executor()`` (below) picks dynamically based on whether
# the user has set ``OPENAI_BASE_URL`` — if so, all default tiers route to
# ``openai_compatible`` (vLLM / Together / OpenRouter); otherwise to
# ``ollama``. The ROUTING constants record the *static* default for tests
# and procedural-memory fallbacks.
ROUTING: dict[str, tuple[str, str]] = {
    "low": (LOCAL_CODE_MODEL, "ollama"),  # qwen3-coder-next via Ollama
    "medium": (LOCAL_MID_MODEL, "ollama"),  # qwen3.6:27b via Ollama
    "high": (LOCAL_PREMIUM_MODEL, "ollama"),  # deepseek-v4-flash via Ollama
}


# (select_executor re-export lives at module top — see above.)


def heuristic_classify(description: str) -> str | None:
    """Returns 'low', 'high', or None (ambiguous)."""
    if _LOW_PATTERNS.search(description):
        return "low"
    if _HIGH_PATTERNS.search(description):
        return "high"
    return None


async def llm_classify(description: str) -> str:
    """Ask local LLM to rate complexity 1-10. Falls back to 'medium'."""
    prompt = (
        "Rate this software task complexity from 1-10. "
        "Reply with ONLY a number.\n\nTask: " + description[:500]
    )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": LOCAL_CLASSIFY_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 5},
                },
            )
            r.raise_for_status()
            text = r.json()["message"]["content"].strip()
            m = re.search(r"\d+", text)
            if m:
                score = int(m.group())
                if score <= 3:
                    return "low"
                if score <= 7:
                    return "medium"
                return "high"
    except Exception as e:
        logger.warning("LLM classify failed, defaulting to medium: %s", e)
    return "medium"


def pick_evaluator_model(generator_model: str) -> str:
    """Pick an evaluator model from a different family than the generator.

    Implements the cross-family-evaluator invariant from ADR-006. The MT-Bench
    self-enhancement-bias paper quantified that Claude-v1 favors itself by
    +25% and GPT-4 by +10% when grading its own output; Anthropic's harness
    research is even more direct: *"Separating the agent doing the work from
    the agent judging it proves to be a strong lever."* Same-family judges
    share blind spots — Sonnet evaluating Opus is barely better than Opus
    evaluating itself. The fix is to pick an evaluator from a different
    model lineage entirely.

    The selection algorithm is deliberately simple:

      1. Determine the generator's family via ``model_family()``.
      2. Walk through a preference list of evaluator candidates (cheap and
         well-tool-call-tested first) in order, returning the first whose
         family differs from the generator's.
      3. If we somehow exhaust the list (only happens in tests with mocked
         registries), fall back to the cheap-tier code model — better same-
         family than no evaluator.

    Why a static preference list and not e.g. random selection: the same task
    pattern should route to the same evaluator across runs so the procedural
    memory accumulates clean signal. Determinism beats theoretical fairness
    here.

    Why these specific candidates: each is from a distinct, well-supported
    family with reliable tool-call output as of 2026-04-30. Add candidates
    here when new families ship reliable open-weight models.
    """
    gen_family = model_family(generator_model)

    # Preference order: cheap to expensive, well-tested to less-tested.
    # Each candidate is a representative of a family. The classifier picks
    # the first one whose family differs from the generator's.
    candidates = [
        LOCAL_CLASSIFY_MODEL,  # gpt-oss:20b — openai
        LOCAL_BACKUP_MID_MODEL,  # devstral-small-2507 — mistral
        LOCAL_MID_MODEL,  # qwen3.6:27b — qwen
        LOCAL_PREMIUM_MODEL,  # deepseek-v4-flash — deepseek
        LOCAL_CODE_MODEL,  # qwen3-coder-next — qwen
        "claude-sonnet-4",  # anthropic — last resort, requires API
    ]

    for candidate in candidates:
        if model_family(candidate) != gen_family:
            return candidate

    # Pathological fallback. Should be unreachable in any real config.
    logger.warning(
        "No cross-family evaluator candidate for generator=%s (family=%s); "
        "falling back to generator family. Self-eval bias possible.",
        generator_model,
        gen_family,
    )
    return LOCAL_CODE_MODEL


# Late-bind LOCAL_BACKUP_MID_MODEL since pick_evaluator_model references it
# from a closure — keeping the import at the top would create a circular
# import path through config -> classifier -> config in some test contexts.
from ..config import LOCAL_BACKUP_MID_MODEL  # noqa: E402


async def classify(description: str, db=None) -> tuple[str, str, str]:
    """Classify task and return ``(complexity, generator_model, agent_type)``.

    Priority: 1. Procedural lookup  2. Heuristic  3. LLM. Then ``select_executor``
    dynamically picks the executor based on the chosen model and the user's
    ``OPENAI_BASE_URL`` environment.
    """
    # 1. Procedural lookup (past success patterns)
    if db is not None:
        proc = db.get_procedure(description[:100])
        if proc and proc["success_rate"] > 0.8 and proc["sample_count"] >= 2:
            # Procedural memory has a high-confidence answer for this pattern;
            # trust it over the heuristic. Returning "medium" as the complexity
            # bucket is a label-only convention — the *actual* model and agent
            # come from the procedure record itself.
            return ("medium", proc["recommended_model"], proc["recommended_agent"])

    # 2. Heuristic
    complexity = heuristic_classify(description)

    # 3. LLM fallback
    if complexity is None:
        complexity = await llm_classify(description)

    model, _static_agent = ROUTING[complexity]
    # Dynamic agent selection: respects OPENAI_BASE_URL override.
    agent_type = select_executor(model)
    return (complexity, model, agent_type)


def classify_sync(description: str) -> tuple[str, str, str]:
    """Synchronous heuristic-only classification. No LLM call.

    Used by tests and by the planner when the classifier is needed before
    the event loop is established. Falls back to "medium" if the heuristic
    is ambiguous.
    """
    complexity = heuristic_classify(description) or "medium"
    model, _static_agent = ROUTING[complexity]
    agent_type = select_executor(model)
    return (complexity, model, agent_type)
