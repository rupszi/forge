"""Generator: executes sprint code in a worktree. Thin wrapper over executors.

The generator is deliberately **minimal**. Its only responsibilities:

  1. Build a prompt with the right *prefix structure* for prompt caching
     (stable system / project / memory blocks first, variable task last).
  2. Inject the repomap (Phase 1 Week 3) alongside the memory context.
  3. Truncate to fit the target model's context window (Phase 1 Week 3
     hardening — see ``MODEL_CONTEXT_LIMITS``).
  4. Dispatch to the right executor (Claude / Ollama / OpenAI-compatible).
  5. **Never self-evaluate.** The evaluator is a separate process per ADR-006.

Prompt-caching layout (matches the discipline from ENGINEERING_STANDARDS.md §9):

    [stable system prelude]      ← cached
    [stable project context]     ← cached
    [stable memory context]      ← cached
    [stable repomap]             ← cached
    [variable task description]  ← uncached
    [variable revision feedback] ← uncached  (when present)

vLLM's prefix caching engages on the stable prefix; Claude's
``cache_control`` breakpoints engage at the same boundary; Ollama via
recent llama.cpp builds also benefits. Same prompt structure, three
caching mechanisms, one win.
"""

from __future__ import annotations

import logging

from ..config import MODEL_CONTEXT_LIMITS
from ..executors import (
    claude_code as claude_executor,
    mlx as mlx_executor,
    ollama as ollama_executor,
    openai_compatible as openai_compatible_executor,
)
from ..models import ExecutionResult, SprintContract

logger = logging.getLogger(__name__)


# Heuristic: tokens per character. Used for client-side budgeting before the
# real tokenization happens at the inference engine. Cheap and consistent.
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate ``text`` so its estimated token count is ≤ ``max_tokens``.

    Truncation is from the end (we keep the beginning, where the memory
    context's most-relevant items live by retriever ordering). Adds a
    single-line marker so the model knows truncation happened.
    """
    target_chars = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= target_chars:
        return text
    return text[:target_chars] + "\n\n[... truncated to fit context window ...]"


def _build_prompt(
    sprint: SprintContract,
    memory_context: str,
    repomap: str = "",
    revision_feedback: str = "",
    *,
    target_model: str = "",
    mode: str = "auto",
) -> str:
    """Assemble the full prompt with prompt-cache-friendly ordering.

    The model's context window is split:
      - ~10–20% : stable system + project context (cacheable)
      - ~30%    : memory + repomap (cacheable)
      - ~50–60% : task description + revision feedback (variable)
      - reserved: output budget (handled by the executor)

    When the assembled prompt exceeds 80% of the target model's context
    window, sections are trimmed in this priority order (least-important
    first):

      1. Repomap — first to shrink (regenerate in a tighter budget)
      2. Memory context — second
      3. Revision feedback — last (the model needs this to converge)
      4. Task description — never trimmed (a truncated task is worse than
         a context-overflow error, which the executor would surface anyway)
    """
    # Split prompt into ``stable_prefix`` (memory + repomap, cacheable) and
    # ``variable_suffix`` (task + criteria + feedback). Truncation only ever
    # touches the prefix; the suffix is sacred.
    prefix_parts: list[str] = []
    # Mode addendum is stable per-mode and goes at the front of the prefix
    # so the cacheable boundary stays the same for ``auto`` runs (which
    # produce an empty addendum). See daemon/mode.py::mode_prompt_addendum.
    from ..mode import mode_prompt_addendum

    addendum = mode_prompt_addendum(mode)
    if addendum:
        prefix_parts.append(addendum)
    if memory_context:
        prefix_parts.append(memory_context)
    if repomap:
        prefix_parts.append(repomap)

    suffix_parts: list[str] = []
    suffix_parts.append(f"## Task\n{sprint.description}")
    suffix_parts.append("## Done criteria (you must satisfy ALL of these)")
    for i, criterion in enumerate(sprint.done_criteria, 1):
        suffix_parts.append(f"{i}. {criterion}")
    if revision_feedback:
        suffix_parts.append(
            f"## Revision feedback (apply these specific fixes)\n{revision_feedback}"
        )
    suffix_parts.append("\nImplement this. Run tests if applicable. Do not evaluate your own work.")

    stable_prefix = "\n\n".join(prefix_parts)
    variable_suffix = "\n\n".join(suffix_parts)

    # ---- Context-window enforcement ----

    if target_model:
        ctx_limit = MODEL_CONTEXT_LIMITS.get(target_model, 32_000)
        # Reserve 20% for output. Trim if input exceeds 80% of window.
        max_input_tokens = int(ctx_limit * 0.8)
        suffix_tokens = _estimate_tokens(variable_suffix)
        prefix_tokens = _estimate_tokens(stable_prefix)

        if prefix_tokens + suffix_tokens > max_input_tokens:
            logger.warning(
                "generator prompt exceeds 80%% of %s window (%d tokens); trimming",
                target_model,
                ctx_limit,
            )
            # Suffix gets first claim on the budget — the model needs the
            # task description and revision feedback intact. Whatever's left
            # goes to the prefix.
            prefix_budget = max(0, max_input_tokens - suffix_tokens)
            stable_prefix = _truncate_to_budget(stable_prefix, prefix_budget)

    if stable_prefix:
        return stable_prefix + "\n\n" + variable_suffix
    return variable_suffix


# Task 2.6: routing.select_executor returns the executor *string*; we map
# it to the executor *module* through a small dispatch table. One source
# of truth (``routing.select_executor``) drives both the procedural-memory
# string and the dispatch module.
_EXECUTOR_MAP = {
    "claude_code": claude_executor,
    "ollama": ollama_executor,
    "openai_compatible": openai_compatible_executor,
    "mlx": mlx_executor,
}


def _select_executor(sprint: SprintContract):
    """Pick an executor module based on the sprint's ``assigned_model``.

    Backwards-compat alias: still keeps the legacy short Anthropic names
    (``"opus"``, ``"sonnet"``, ``"haiku"``) routing to claude_code even
    when ``model_family`` returns "unknown" for them. The shared
    ``routing.select_executor`` already covers full-name Claudes.

    Local-first gate (G-LOC-2): if the resolved executor reaches the cloud
    and ``FORGE_CLOUD_ENABLED`` is off, raise ``CloudDisabledError`` rather
    than dial out silently or swap the user's model behind their back.
    """
    from .. import routing
    from ..config import cloud_enabled

    model = sprint.assigned_model
    if model in ("opus", "sonnet", "haiku"):
        executor_str = "claude_code"
    else:
        executor_str = routing.select_executor(model)

    if routing.is_cloud_executor(executor_str) and not cloud_enabled():
        msg = (
            f"model {model!r} routes to the cloud executor {executor_str!r}, but "
            "FORGE_CLOUD_ENABLED is off. Forge Studio is local-first: enable cloud "
            "explicitly or assign a local model."
        )
        raise routing.CloudDisabledError(msg)

    return _EXECUTOR_MAP[executor_str]


async def generate(
    sprint: SprintContract,
    memory_context: str = "",
    worktree_path: str | None = None,
    *,
    repomap: str = "",
    revision_feedback: str = "",
    mode: str = "auto",
) -> ExecutionResult:
    """Execute a sprint in a worktree. Do NOT self-evaluate.

    Parameters
    ----------
    sprint
        The sprint contract to execute. ``sprint.assigned_model`` drives
        executor selection and context-window sizing.
    memory_context
        Output of ``daemon/memory/retriever.get_context_for_task()``. Stable
        for the duration of a sprint (across revisions); cacheable.
    worktree_path
        Filesystem path of the isolated git worktree. Passed through to the
        Claude Code executor; ignored by the open-weight executors which
        don't need to ``cd`` into a worktree (they just write a diff).
    repomap
        Output of ``daemon/scanner/repomap.build_repomap()``. Stable per
        session; cacheable.
    revision_feedback
        Evaluator feedback from the previous revision attempt. Variable;
        appended after the stable prefix so the cache stays warm.

    Returns
    -------
    ExecutionResult
        Same shape regardless of which executor ran. Tool calls (when
        present) are surfaced via the ``TOOL_CALL_PREFIX`` sentinel —
        callers that asked for tools parse via
        ``executors.openai_compatible.parse_tool_response``.
    """
    prompt = _build_prompt(
        sprint,
        memory_context,
        repomap=repomap,
        revision_feedback=revision_feedback,
        target_model=sprint.assigned_model,
        mode=mode,
    )

    executor = _select_executor(sprint)

    # Each executor has the same async ``execute`` interface but slightly
    # different positional args. Dispatch accordingly.
    if executor is claude_executor:
        return await executor.execute(prompt, worktree_path, sprint.assigned_model)
    return await executor.execute(prompt, model=sprint.assigned_model)
