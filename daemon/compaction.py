"""Auto-compaction — summarize context that would overflow the window.

Forge already trims oversized context by truncation; compaction is the smarter
version: when the assembled memory/context approaches the model's window, a
local model *summarizes* the bulk (preserving facts, file names, decisions)
instead of chopping the tail off. Falls back to truncation if the summarizer
is unavailable or returns something still too big — so it never hangs or grows.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

Summarizer = Callable[[str, int], Awaitable[str]]

# Budget for the assembled memory block (KB + attachments + scratchpad) before
# the scheduler compacts it. Generous — the generator does the final per-model
# window trim; this just keeps the *memory* portion from dominating the window.
MEMORY_CONTEXT_BUDGET_TOKENS = 3000


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def should_compact(used: int, cap: int, threshold: float = 0.8) -> bool:
    """True when ``used`` tokens are within ``threshold`` of the ``cap``."""
    return cap > 0 and used >= cap * threshold


def _truncate(text: str, target_tokens: int) -> str:
    return text[: max(0, target_tokens * 4)] + "\n…(truncated)"


async def compact_text(text: str, target_tokens: int, summarizer: Summarizer) -> str:
    """Return ``text`` if it fits ``target_tokens``; otherwise summarize it.

    The summary is accepted only if it actually fits (within 20% slack). On any
    failure — summarizer error, or a summary that's still too long — we fall
    back to hard truncation so the caller always gets something within budget.
    """
    if estimate_tokens(text) <= target_tokens:
        return text
    try:
        summary = await summarizer(text, target_tokens)
    except Exception as e:
        logger.warning("compaction summarizer failed, truncating: %s", e)
        return _truncate(text, target_tokens)
    if summary and estimate_tokens(summary) <= int(target_tokens * 1.2):
        return summary.strip()
    return _truncate(text, target_tokens)


async def ollama_summarizer(text: str, target_tokens: int) -> str:
    """Default summarizer — a local model condenses the context."""
    from .config import LOCAL_PLAN_MODEL
    from .executors import ollama as ollama_executor

    prompt = (
        f"Condense the following context to at most ~{target_tokens} tokens. "
        "Preserve concrete facts, file names, error messages, and decisions; "
        "drop redundancy. Output only the condensed context.\n\n"
        f"{text}"
    )
    result = await ollama_executor.execute(prompt, model=LOCAL_PLAN_MODEL)
    return result.output if result.success else ""
