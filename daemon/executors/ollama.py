"""Ollama REST API executor — Forge's primary local-model backend.

Ollama wraps llama.cpp and exposes a REST API on ``http://localhost:11434``
by default. Forge defaults to Ollama for the planner / cheap-tier generator /
evaluator paths because:

  - Free at the marginal token (GPU is the user's; no API bill)
  - One-line install on macOS (``brew install ollama``)
  - Native quantization (Q4_K_M / Q4_0) lets ~30B-class models fit on M-series 48GB
  - Works fully offline — aligns with ADR-007 (local-first; no telemetry)
  - Tool calling via llama.cpp's per-model templates (Hermes for Qwen3, Mistral
    for Devstral, harmony for gpt-oss). Reliability is good as of April 2026.

Phase 1 Week 1 hardening applied to this file:

  1. **Tools array passed through** — when callers provide a ``tools=[]`` list
     in OpenAI function-calling shape, we forward it to Ollama which routes
     to the per-model parser. Response ``tool_calls`` is captured and
     serialized via the same sentinel-prefix scheme as ``openai_compatible.py``.
  2. **``keep_alive`` request parameter** — defaults to 30 minutes, configurable
     via ``OLLAMA_KEEP_ALIVE`` env var. Ollama unloads models on idle by default
     (~5 min); keeping models warm across sprints in a session eliminates the
     model-load latency on every call. Critical for the planner→generator→
     evaluator cycle which makes 3+ Ollama calls in sequence.
  3. **Per-role temperature** — exposed as a parameter so the evaluator can
     pass 0.0 (deterministic), the planner can pass 0.4 (more creative
     decomposition), and generators stay at 0.2 (balanced).
  4. **``num_ctx`` parameter** — Ollama's per-call context window cap. Defaults
     to model-default; callers from ``generator.py`` set it explicitly based on
     the model's known max via ``MODEL_CONTEXT_LIMITS``.

This executor uses the same ``ExecutionResult`` shape as
``openai_compatible.py`` so the scheduler doesn't need to know which one ran.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from ..config import OLLAMA_BASE_URL, TASK_TIMEOUT_SECONDS
from ..models import ExecutionResult
from .openai_compatible import TOOL_CALL_PREFIX

logger = logging.getLogger(__name__)

# Default keep_alive duration. Ollama accepts seconds (number) or duration
# strings ("30m", "1h", "0" to unload immediately). Keep-alive matters because
# the planner→generator→evaluator cycle makes ≥3 Ollama calls per sprint, and
# each cold start of a 27B+ model on M-series Mac is 5–15 seconds. With the
# default keep-alive, the model stays loaded across the cycle.
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

# Default per-call timeout. Overridable for users on slow hardware.
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", str(TASK_TIMEOUT_SECONDS)))

# Default system prompt. Generic; evaluator and planner override.
DEFAULT_SYSTEM = "You are a precise software development assistant."


async def execute(
    prompt: str,
    model: str = "qwen3-coder-next",
    *,
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | str | None = None,
    temperature: float = 0.2,
    num_ctx: int | None = None,
    num_predict: int | None = None,
    system_prompt: str = DEFAULT_SYSTEM,
    keep_alive: str | int | None = None,
) -> ExecutionResult:
    """Run via Ollama REST API. Zero cost.

    Parameters
    ----------
    prompt
        User-message content. Caller is responsible for prompt-cache-friendly
        prefix structuring (system/project/memory upfront, variable task last).
        Ollama / llama.cpp does not have explicit prompt caching but vLLM-style
        prefix matching can engage if the user runs Ollama with prefix-cache
        flags — recent llama.cpp builds (Mar 2026+) support this.
    model
        Ollama model identifier. Default ``qwen3-coder-next`` per ADR-003.
        Examples: ``gpt-oss:20b``, ``qwen3.6:27b``, ``deepseek-v4-flash``,
        ``devstral-small-2507``.
    tools
        Optional OpenAI-shape tool definitions. Forwarded to Ollama which
        routes through llama.cpp's per-model parser. Response ``tool_calls``
        is captured and serialized via the ``TOOL_CALL_PREFIX`` sentinel.
    response_format
        Pass ``"json"`` to enable Ollama's native JSON-mode (constrained
        decoding via llama.cpp grammar). Pass a JSON-schema dict to enforce
        a specific schema (Ollama 0.5.5+; falls back to JSON mode on older
        builds).
    temperature
        0.0 for deterministic (evaluator), 0.2 for code generation (default),
        0.4–0.6 for creative decomposition (planner).
    num_ctx
        Per-call context-window cap. None = model default. Set this from
        ``MODEL_CONTEXT_LIMITS[model]`` in the generator to ensure the model
        actually uses the requested window (Ollama's default is often 2048
        regardless of the model's max).
    num_predict
        Max output tokens. None = unlimited (until model-default stop).
    system_prompt
        Default is generic. Planner / evaluator override with their full
        system prompt.
    keep_alive
        Override the default ``OLLAMA_KEEP_ALIVE``. Useful for the post-
        session learner ("keep_alive=0" to free the model after one call) or
        for batch evals ("keep_alive=1h").
    """
    start = time.time()

    options: dict[str, Any] = {"temperature": temperature}
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    if num_predict is not None:
        options["num_predict"] = num_predict

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": options,
        "keep_alive": keep_alive if keep_alive is not None else OLLAMA_KEEP_ALIVE,
    }

    if tools is not None:
        body["tools"] = tools

    if response_format is not None:
        # Ollama's ``format`` field accepts "json" (legacy) or a JSON-schema
        # object (modern). We forward whatever the caller passed.
        body["format"] = response_format

    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SECONDS) as client:
            r = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=body)
            r.raise_for_status()
            data = r.json()

    except asyncio.CancelledError:
        # ADR-006 / ENGINEERING_STANDARDS.md §8: never swallow CancelledError.
        logger.info("ollama.execute cancelled for model=%s", model)
        raise

    except httpx.HTTPStatusError as e:
        msg = _extract_error(e.response)
        logger.warning("Ollama HTTP %d on %s: %s", e.response.status_code, model, msg)
        return ExecutionResult(
            success=False,
            error=f"HTTP {e.response.status_code}: {msg}",
            duration_seconds=time.time() - start,
        )

    except httpx.HTTPError as e:
        logger.warning("Ollama network error for %s: %s", model, e)
        return ExecutionResult(
            success=False,
            error=f"Network error: {e!s}",
            duration_seconds=time.time() - start,
        )

    except Exception as e:
        logger.exception("ollama.execute unexpected error for %s", model)
        return ExecutionResult(
            success=False,
            error=f"Unexpected: {e!s}",
            duration_seconds=time.time() - start,
        )

    # ---- Parse Ollama response ----
    # Ollama's /api/chat shape:
    #   {"message": {"role": "assistant", "content": "...",
    #                "tool_calls": [{"function": {"name": "...", "arguments": {...}}}]},
    #    "prompt_eval_count": N, "eval_count": M, ...}
    # Note: ``tool_calls[].function.arguments`` is a *dict* in Ollama's response,
    # not a JSON string like OpenAI. We normalize to OpenAI shape for parity
    # with openai_compatible.py.
    message = data.get("message") or {}
    content = message.get("content", "") or ""
    tool_calls_raw = message.get("tool_calls") or []
    tokens_in = int(data.get("prompt_eval_count", 0))
    tokens_out = int(data.get("eval_count", 0))

    if tool_calls_raw:
        # Normalize Ollama's argument dict to OpenAI's argument JSON-string
        # shape so callers parse uniformly via parse_tool_response.
        normalized = []
        for i, call in enumerate(tool_calls_raw):
            fn = call.get("function") or {}
            args = fn.get("arguments")
            # Ollama returns args as dict; OpenAI returns as JSON string.
            if isinstance(args, dict):
                import json

                args_str = json.dumps(args, ensure_ascii=False)
            else:
                args_str = str(args) if args is not None else "{}"
            normalized.append(
                {
                    "id": call.get("id") or f"call_{i}",
                    "type": call.get("type", "function"),
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": args_str,
                    },
                }
            )
        content = _serialize_tool_response(content, normalized)

    return ExecutionResult(
        success=True,
        output=content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=0.0,
        duration_seconds=time.time() - start,
    )


def _serialize_tool_response(content: str, tool_calls: list[dict[str, Any]]) -> str:
    """Encode tool calls into the output string with the sentinel prefix used
    by ``openai_compatible.py``. Identical scheme so callers can use the same
    ``parse_tool_response`` helper regardless of which executor produced the
    output."""
    import json

    payload = {"content": content, "tool_calls": tool_calls}
    return TOOL_CALL_PREFIX + json.dumps(payload, ensure_ascii=False)


def _extract_error(response: httpx.Response) -> str:
    """Best-effort extraction of a human-readable error from an Ollama HTTP
    error response. Ollama returns ``{"error": "..."}`` on most failures
    (model not found, out-of-memory, etc.)."""
    try:
        data = response.json()
        if isinstance(data, dict) and "error" in data:
            return str(data["error"])
        return str(data)[:200]
    except (ValueError, httpx.DecodingError):
        return response.text[:200] if response.text else "(empty body)"
