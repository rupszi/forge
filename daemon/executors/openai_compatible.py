"""OpenAI-compatible HTTP executor.

This is the executor Forge uses to talk to *any* HTTP endpoint that speaks the
OpenAI Chat Completions / tool-calling protocol. That covers a lot of ground:

  - vLLM with `--api-server` (self-hosted, fast, prefix-cached)
  - SGLang in OpenAI-compat mode
  - Together AI, OpenRouter, Hyperbolic, Nebius (managed open-weight providers)
  - LM Studio, Llama.cpp's openai-compat server, Mistral Le Plateforme
  - LiteLLM as a router in front of any of the above
  - Anthropic's `https://api.anthropic.com/v1/messages` is NOT OpenAI-compatible
    by default — for direct Claude API access, use ``executors/batch.py`` or the
    ``claude -p`` subprocess executor (see ``executors/claude_code.py``).

Why a separate executor instead of extending ``ollama.py``?

  - Ollama's REST surface is ``/api/chat`` with a slightly different schema.
  - vLLM and friends speak the formal OpenAI ``/v1/chat/completions`` contract.
  - Forge's classifier can route the same model to different executors (e.g.
    Qwen3-Coder-Next via local Ollama for cheap sprints, the same model via a
    remote vLLM endpoint for bursts). Keeping them separate keeps each executor
    small and focused.

Tool-calling reliability strategy (the load-bearing part):

  vLLM and SGLang ship per-model parsers (``--tool-call-parser hermes`` for
  Qwen3, ``mistral`` for Devstral, ``llama3_json`` for Llama 3.x, ``deepseek_v3``
  for DeepSeek, ``harmony`` for gpt-oss). When you POST to
  ``/v1/chat/completions`` with a ``tools`` array, the server returns parsed
  ``tool_calls`` in the response — no client-side regex needed.

  But raw API responses still go wrong: malformed JSON in arguments, parser
  drift between model versions, schema-non-compliance under temperature > 0.5.
  Forge's full defense is three layers per ADR-003:

    1. Native parser (this file passes through whatever the server returned).
    2. Constrained decoding via xgrammar — pass ``response_format`` to enforce
       a JSON schema server-side. Wired up at session boundaries (planner JSON
       output, evaluator verdict) where strict validity matters.
    3. Tolerant client-side parser via BAML (optional ``forge[robust]`` extra)
       in ``daemon/parsing.py`` — handles JSON-in-markdown and partial outputs.

  This executor implements layer 1 only. Layers 2 and 3 are wired up by the
  planner / evaluator code that calls into this executor.

Prompt caching (vLLM prefix caching specifically):

  vLLM enables automatic prefix caching when you launch with
  ``--enable-prefix-caching``. The cache hit happens when consecutive requests
  share a token-identical prefix. To benefit, structure prompts as:

      [stable system prelude]      ← cached
      [stable project context]     ← cached
      [stable memory context]      ← cached
      [variable task description]  ← uncached
      [variable revision feedback] ← uncached

  This file does not enforce that ordering — it's the caller's responsibility.
  See ``daemon/agents/generator.py`` for the prompt-build code that does it.

Timeout and cancellation:

  - Hard timeout per request: ``OPENAI_COMPAT_TIMEOUT_SECONDS`` (default 300s).
  - On ``asyncio.CancelledError``, the httpx client is closed cleanly and the
    error is re-raised. We never swallow ``CancelledError`` — see ADR-006 and
    ENGINEERING_STANDARDS.md §8.
  - Budget: this executor returns ``cost_usd=0.0`` for self-hosted endpoints
    (you provide the GPU). For paid endpoints (OpenRouter, Together) the
    provider's invoice is your source of truth — Forge can't observe the
    real per-token price for arbitrary endpoints. If you need accurate cost
    tracking against a paid OpenAI-compat endpoint, set ``cost_per_million_in``
    and ``cost_per_million_out`` on the ``execute()`` call.

See also:
  - ADR-002 (Architecture A — open-weight first)
  - ADR-003 (default model lineup; family registry)
  - ENGINEERING_STANDARDS.md §8 (async patterns)
  - daemon/executors/ollama.py (sibling executor; same shape, Ollama API)
  - daemon/agents/classifier.py (chooses which executor to dispatch to)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from ..config import TASK_TIMEOUT_SECONDS
from ..models import ExecutionResult

logger = logging.getLogger(__name__)

# Default timeout for OpenAI-compat HTTP calls. Same as TASK_TIMEOUT_SECONDS by
# default but overridable via env so users with slow remote endpoints (Together,
# OpenRouter) can dial it up without affecting the Claude/Ollama paths.
OPENAI_COMPAT_TIMEOUT_SECONDS = int(
    os.environ.get("OPENAI_COMPAT_TIMEOUT_SECONDS", str(TASK_TIMEOUT_SECONDS))
)

# Default base URL for an OpenAI-compatible endpoint. The user sets this to
# point at vLLM, SGLang, OpenRouter, Together, etc. If unset, the executor
# raises a clear error rather than silently defaulting to OpenAI proper —
# Forge is open-weight-first and does not assume the user wants to ship
# requests to OpenAI. Set ``OPENAI_BASE_URL`` to a self-hosted vLLM endpoint
# (e.g., http://localhost:8000/v1) for the recommended default.
DEFAULT_BASE_URL = os.environ.get("OPENAI_BASE_URL", "")

# Some endpoints require an API key (Together, OpenRouter); self-hosted vLLM
# usually doesn't but accepts a placeholder. We send whatever the user set,
# falling back to a placeholder so vLLM doesn't 401 on missing-Authorization
# (vLLM accepts any non-empty bearer by default).
DEFAULT_API_KEY = os.environ.get("OPENAI_API_KEY", "EMPTY")


async def execute(
    prompt: str,
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    system_prompt: str = "You are a precise software development assistant.",
    cost_per_million_in: float = 0.0,
    cost_per_million_out: float = 0.0,
) -> ExecutionResult:
    """Run a single chat completion against an OpenAI-compatible endpoint.

    Parameters
    ----------
    prompt
        The user-message content. Caller is responsible for any system-prompt-
        plus-prefix structuring needed for prompt caching (see module docstring).
    model
        Model identifier as the endpoint expects it. Examples:
        ``qwen3-coder-next``, ``qwen3.6:27b``, ``deepseek-v4-flash``,
        ``meta-llama/Llama-3.3-70B-Instruct`` (HF-style for vLLM), or
        ``anthropic/claude-sonnet-4`` (OpenRouter-style).
    base_url
        Override for ``OPENAI_BASE_URL``. Useful for tests and for the classifier
        to dispatch the same model to two different endpoints (cheap local vs
        burst remote).
    api_key
        Override for ``OPENAI_API_KEY``. Most self-hosted vLLM deployments
        accept any non-empty bearer; paid providers require their key.
    tools
        Optional list of tool definitions in OpenAI function-calling shape. The
        server's ``--tool-call-parser`` (or equivalent) handles per-model parsing.
        If provided and the model emits tool calls, the parsed list is returned
        in ``ExecutionResult.output`` as a JSON-encoded ``tool_calls`` field via
        a sentinel prefix — see ``_serialize_tool_response`` below.
    response_format
        Optional JSON-schema or ``{"type": "json_object"}`` constraint. vLLM /
        SGLang use xgrammar to enforce this server-side. Pass this for the
        planner sprint-contract output and the evaluator verdict — both are
        cases where invalid JSON is fatal.
    temperature
        Sampling temperature. Default 0.2 for code generation. Evaluator code
        should pass 0.0 for determinism; the planner can use 0.4–0.6 for more
        creative decomposition.
    max_tokens
        Optional output cap. Mostly used by callers that have already estimated
        the response budget (see ``budget.py``).
    system_prompt
        Default is generic. Callers like the planner and evaluator override
        this with their full system prompt and rely on prefix caching to keep
        cost down.
    cost_per_million_in / cost_per_million_out
        For paid endpoints (OpenRouter, Together). Self-hosted vLLM should leave
        these at 0.0. Caller is responsible for knowing the rate.

    Returns
    -------
    ExecutionResult
        ``success`` is False on any HTTP, network, or parsing failure. The
        ``error`` field has a one-line human-readable message; full traceback
        is in the daemon log via ``logger.exception``.
    """
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if not base:
        return ExecutionResult(
            success=False,
            error=(
                "OpenAI-compatible base URL not configured. "
                "Set OPENAI_BASE_URL env var or pass base_url= explicitly. "
                "Forge does not silently default to api.openai.com."
            ),
        )

    key = api_key or DEFAULT_API_KEY

    # Build the request body. Only include keys the server expects — some
    # endpoints (especially older vLLM builds) reject unknown fields.
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if tools is not None:
        # OpenAI function-calling shape. Each tool is a dict with keys
        # {type: "function", function: {name, description, parameters}}.
        # vLLM expects this exact structure regardless of the per-model parser
        # — the parser only affects how the *response* is decoded, not the
        # request schema.
        body["tools"] = tools
        # ``tool_choice="auto"`` is the OpenAI default; making it explicit
        # protects against endpoints that don't default to auto.
        body["tool_choice"] = "auto"
    if response_format is not None:
        # Triggers xgrammar-backed constrained decoding on vLLM/SGLang. For
        # JSON object: {"type": "json_object"}. For full schema enforcement:
        # {"type": "json_schema", "json_schema": {...}}.
        body["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    url = f"{base}/chat/completions"
    start = time.time()

    try:
        # Why no async-with on the client at module scope: each call gets a
        # fresh client to avoid the connection-pool sharing pitfall when the
        # event loop is cancelled mid-flight (asyncio.shield won't save you if
        # the underlying HTTPX pool is half-closed). Per-call clients are
        # cheap and simpler. If profiling shows this is a bottleneck, switch
        # to a module-level client guarded by an asyncio.Lock.
        async with httpx.AsyncClient(timeout=OPENAI_COMPAT_TIMEOUT_SECONDS) as client:
            r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()

    except asyncio.CancelledError:
        # Hard rule per ADR-006 / ENGINEERING_STANDARDS.md §8: never swallow
        # CancelledError. Cleanup happens via httpx context manager exit; we
        # just need to re-raise so the scheduler knows the sprint was cancelled.
        logger.info("openai_compatible.execute cancelled for model=%s", model)
        raise

    except httpx.HTTPStatusError as e:
        # 4xx/5xx from the endpoint. Body usually contains a structured error
        # we can show the user (e.g., "model not found", "rate limit").
        msg = _extract_error_message(e.response)
        logger.warning("OpenAI-compat HTTP %d on %s: %s", e.response.status_code, model, msg)
        return ExecutionResult(
            success=False,
            error=f"HTTP {e.response.status_code}: {msg}",
            duration_seconds=time.time() - start,
        )

    except httpx.HTTPError as e:
        # Network / DNS / timeout / TLS — anything below the HTTP response.
        logger.warning("OpenAI-compat network error for %s: %s", model, e)
        return ExecutionResult(
            success=False,
            error=f"Network error: {e!s}",
            duration_seconds=time.time() - start,
        )

    except Exception as e:
        # JSON parse error on response, programming error, etc. Log full
        # traceback to the daemon log; surface a brief message to the caller.
        logger.exception("openai_compatible.execute unexpected error for %s", model)
        return ExecutionResult(
            success=False,
            error=f"Unexpected: {e!s}",
            duration_seconds=time.time() - start,
        )

    # ---- Parse a successful response ----

    # OpenAI shape: data["choices"][0]["message"]["content"] (string),
    # plus optional data["choices"][0]["message"]["tool_calls"] (list of dicts).
    # ``usage`` block: {"prompt_tokens", "completion_tokens", "total_tokens"}.
    try:
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
    except (KeyError, IndexError, TypeError) as e:
        logger.warning("OpenAI-compat response shape unexpected: %s", data)
        return ExecutionResult(
            success=False,
            error=f"Malformed response: missing choices/message ({e!s})",
            duration_seconds=time.time() - start,
        )

    # If the model emitted tool calls, surface them via a sentinel-prefixed
    # JSON encoding in ``output``. Callers that requested tools will look for
    # this prefix and parse out the structured calls; callers that didn't see
    # the empty content unchanged. We deliberately don't return a separate
    # ``tool_calls`` field on ExecutionResult to keep the dataclass shape
    # compatible across all executors (Ollama returns the same way).
    if tool_calls:
        content = _serialize_tool_response(content, tool_calls)

    usage = data.get("usage") or {}
    tokens_in = int(usage.get("prompt_tokens", 0))
    tokens_out = int(usage.get("completion_tokens", 0))

    cost = (tokens_in / 1_000_000) * cost_per_million_in + (
        tokens_out / 1_000_000
    ) * cost_per_million_out

    return ExecutionResult(
        success=True,
        output=content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        duration_seconds=time.time() - start,
    )


# ---- Helpers ----

# Sentinel marker that prefixes serialized tool-call output. Callers that
# requested ``tools`` strip this prefix and parse the JSON tail; callers that
# didn't request tools never see it (because they pass tools=None and the
# server won't emit tool_calls).
TOOL_CALL_PREFIX = "<<FORGE_TOOL_CALLS>>"


def _serialize_tool_response(content: str, tool_calls: list[dict[str, Any]]) -> str:
    """Encode tool calls into the output string with a sentinel prefix.

    We use a sentinel-prefixed JSON encoding instead of adding a separate
    ``tool_calls`` field to ``ExecutionResult`` because:

      1. All four executors (claude_code, ollama, openai_compatible, batch)
         must return the same dataclass shape so the scheduler doesn't need
         to know which one ran.
      2. Tool-calling is the exception, not the rule — adding a field every
         executor has to populate (with most leaving it empty) is overhead.
      3. Callers that asked for tools know to look for the prefix; callers
         that didn't never see it.

    The serialization is human-readable JSON for debuggability (it ends up in
    trace.jsonl audit logs).
    """
    import json

    payload = {
        "content": content,
        "tool_calls": tool_calls,
    }
    return TOOL_CALL_PREFIX + json.dumps(payload, ensure_ascii=False)


def parse_tool_response(output: str) -> tuple[str, list[dict[str, Any]]]:
    """Inverse of ``_serialize_tool_response``.

    Returns
    -------
    (content, tool_calls)
        ``content`` is the model's text response (often empty when tool calls
        are emitted). ``tool_calls`` is the parsed list of {id, type, function:
        {name, arguments}} dicts. If the output has no sentinel prefix, returns
        ``(output, [])`` unchanged.
    """
    import json

    if not output.startswith(TOOL_CALL_PREFIX):
        return output, []
    try:
        payload = json.loads(output[len(TOOL_CALL_PREFIX) :])
    except json.JSONDecodeError as e:
        logger.warning("parse_tool_response: failed to decode payload: %s", e)
        return output, []
    return payload.get("content", ""), payload.get("tool_calls", [])


def _extract_error_message(response: httpx.Response) -> str:
    """Best-effort extraction of a human-readable error message from a 4xx/5xx.

    OpenAI-compat servers vary in error shape. Try the common ones; fall back
    to the raw body capped at 200 chars so we don't dump megabytes into logs.
    """
    try:
        data = response.json()
    except (ValueError, httpx.DecodingError):
        return response.text[:200] if response.text else "(empty body)"

    # OpenAI / vLLM shape: {"error": {"message": "..."}}
    err = data.get("error")
    if isinstance(err, dict) and "message" in err:
        return str(err["message"])
    # Some endpoints return {"detail": "..."}
    if "detail" in data:
        return str(data["detail"])
    # Fallback to the whole JSON body, capped
    return str(data)[:200]
