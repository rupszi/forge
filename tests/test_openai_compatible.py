"""Tests for daemon/executors/openai_compatible.py.

Covers the OpenAI-compatible HTTP executor (vLLM / SGLang / OpenRouter /
Together / Anthropic-via-LiteLLM proxy / etc.) Tests use httpx's MockTransport
to avoid the respx dep — keeps these in the unit suite without needing a
network or a running server.

Test scope:
  - Happy path: text response, token-count parsing
  - Tool-call response shape (sentinel-prefix serialization, parse_tool_response)
  - HTTP errors (4xx/5xx surface a clean error, no exception)
  - Network errors (connection refused / timeout)
  - Malformed response shape
  - response_format / temperature / max_tokens passed through
  - cost_per_million_in/out math
  - Empty base_url returns a clear error (no silent fallback to api.openai.com)

What's NOT tested here:
  - Real vLLM tool-call parser correctness (that's vLLM's responsibility;
    Forge tests against the *response shape* the parser produces).
  - Streaming (Phase 1 doesn't ship streaming).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from daemon.executors import openai_compatible

# Capture the real AsyncClient class once at import time so the patch helpers
# below can construct real clients without infinite-recursing into their own
# patched replacement.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


# ---- Helper: minimal mock transport + patch context manager ----


def _make_transport(
    response_json: dict | None = None,
    status_code: int = 200,
    body: str | None = None,
) -> httpx.MockTransport:
    """Build an httpx.MockTransport that returns a canned response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if body is not None:
            return httpx.Response(status_code, content=body)
        return httpx.Response(status_code, json=response_json or {})

    return httpx.MockTransport(handler)


@contextmanager
def patch_httpx(transport: httpx.MockTransport):
    """Patch ``httpx.AsyncClient`` to return a real client wired to a mock
    transport. Captures the real class reference before patching so the
    factory function inside the patch doesn't recurse."""

    def factory(**kwargs):
        # Caller passes timeout=... etc; we add transport=... and call the
        # real (pre-patch) class.
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    with patch.object(httpx, "AsyncClient", factory):
        yield


# ---- Happy path ----


@pytest.mark.asyncio
async def test_execute_text_response():
    """Standard chat-completions response with content + usage."""
    response = {
        "id": "chatcmpl-1",
        "model": "qwen3-coder-next",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "def add(a, b): return a + b"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 42, "completion_tokens": 17, "total_tokens": 59},
    }
    transport = _make_transport(response)

    with patch_httpx(transport):
        result = await openai_compatible.execute(
            prompt="write add()",
            model="qwen3-coder-next",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
        )

    assert result.success
    assert result.output == "def add(a, b): return a + b"
    assert result.tokens_in == 42
    assert result.tokens_out == 17
    assert result.cost_usd == 0.0  # no price configured -> free
    assert result.duration_seconds >= 0


@pytest.mark.asyncio
async def test_execute_with_paid_endpoint_calculates_cost():
    """When the user supplies per-million-token rates, cost is computed."""
    response = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
    }
    transport = _make_transport(response)

    with patch_httpx(transport):
        result = await openai_compatible.execute(
            prompt="hi",
            model="anthropic/claude-sonnet-4",
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-test",
            cost_per_million_in=3.0,
            cost_per_million_out=15.0,
        )

    # 1M input × $3 + 500k output × $15 = $3.00 + $7.50 = $10.50
    assert result.success
    assert result.cost_usd == pytest.approx(10.50, abs=0.001)


# ---- Tool calls ----


@pytest.mark.asyncio
async def test_execute_with_tool_calls_serializes_correctly():
    """Tool-call responses get sentinel-prefixed JSON encoding in `output`."""
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "src/main.py"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    transport = _make_transport(response)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from disk",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]

    with patch_httpx(transport):
        result = await openai_compatible.execute(
            prompt="read main",
            model="qwen3-coder-next",
            base_url="http://localhost:8000/v1",
            tools=tools,
        )

    assert result.success
    assert result.output.startswith(openai_compatible.TOOL_CALL_PREFIX)

    content, calls = openai_compatible.parse_tool_response(result.output)
    assert content == ""
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "read_file"
    assert calls[0]["function"]["arguments"] == '{"path": "src/main.py"}'


def test_parse_tool_response_handles_plain_text():
    """parse_tool_response returns the unchanged string when no sentinel."""
    content, calls = openai_compatible.parse_tool_response("plain text response")
    assert content == "plain text response"
    assert calls == []


def test_parse_tool_response_handles_malformed_payload():
    """A corrupt sentinel-prefixed payload does not raise."""
    bad = openai_compatible.TOOL_CALL_PREFIX + "{not valid json"
    content, calls = openai_compatible.parse_tool_response(bad)
    # Falls back to returning the original string, empty calls list
    assert content == bad
    assert calls == []


# ---- Error paths ----


@pytest.mark.asyncio
async def test_execute_missing_base_url_returns_clear_error():
    """No silent fallback to api.openai.com — Forge is open-weight-first."""
    # Ensure the env default is not set so the executor sees ""
    with patch.object(openai_compatible, "DEFAULT_BASE_URL", ""):
        result = await openai_compatible.execute(prompt="hi", model="qwen3.6:27b")

    assert not result.success
    assert "base URL not configured" in result.error
    assert "api.openai.com" in result.error  # explanation includes the warning


@pytest.mark.asyncio
async def test_execute_http_500_surfaces_clean_error():
    """5xx from the server returns success=False with a parsed message."""
    transport = _make_transport(
        {"error": {"message": "model not loaded"}},
        status_code=503,
    )

    with patch_httpx(transport):
        result = await openai_compatible.execute(
            prompt="hi",
            model="qwen3.6:27b",
            base_url="http://localhost:8000/v1",
        )

    assert not result.success
    assert "503" in result.error
    assert "model not loaded" in result.error


@pytest.mark.asyncio
async def test_execute_http_400_with_detail_field():
    """Some endpoints (FastAPI-based) return {"detail": ...}; we extract it."""
    transport = _make_transport(
        {"detail": "invalid model name"},
        status_code=400,
    )

    with patch_httpx(transport):
        result = await openai_compatible.execute(
            prompt="hi",
            model="bogus",
            base_url="http://localhost:8000/v1",
        )

    assert not result.success
    assert "invalid model name" in result.error


@pytest.mark.asyncio
async def test_execute_network_error():
    """Connection refused / DNS / timeout => clean error, not exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)

    with patch_httpx(transport):
        result = await openai_compatible.execute(
            prompt="hi",
            model="qwen3.6:27b",
            base_url="http://localhost:8000/v1",
        )

    assert not result.success
    assert "Network error" in result.error


@pytest.mark.asyncio
async def test_execute_malformed_response_shape():
    """Server returns 200 but the body has no 'choices' field."""
    transport = _make_transport({"unexpected": "shape"})

    with patch_httpx(transport):
        result = await openai_compatible.execute(
            prompt="hi",
            model="qwen3.6:27b",
            base_url="http://localhost:8000/v1",
        )

    assert not result.success
    assert "Malformed response" in result.error


@pytest.mark.asyncio
async def test_execute_html_error_body_falls_back_gracefully():
    """Some proxies return HTML on 502; we cap at 200 chars and don't crash."""
    transport = _make_transport(status_code=502, body="<html>bad gateway</html>")

    with patch_httpx(transport):
        result = await openai_compatible.execute(
            prompt="hi",
            model="qwen3.6:27b",
            base_url="http://localhost:8000/v1",
        )

    assert not result.success
    assert "502" in result.error


# ---- Request-shape verification ----


@pytest.mark.asyncio
async def test_execute_passes_response_format_through():
    """response_format must reach the server (xgrammar JSON mode)."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    transport = httpx.MockTransport(handler)

    with patch_httpx(transport):
        await openai_compatible.execute(
            prompt="emit json",
            model="qwen3.6:27b",
            base_url="http://localhost:8000/v1",
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=200,
        )

    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["temperature"] == 0.0
    assert captured["body"]["max_tokens"] == 200
    assert captured["body"]["model"] == "qwen3.6:27b"


@pytest.mark.asyncio
async def test_execute_omits_optional_fields_when_unused():
    """Older vLLM builds reject unknown fields; we omit tools/response_format
    when the caller didn't pass them."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    transport = httpx.MockTransport(handler)

    with patch_httpx(transport):
        await openai_compatible.execute(
            prompt="hi",
            model="qwen3-coder-next",
            base_url="http://localhost:8000/v1",
        )

    body = captured["body"]
    assert "tools" not in body
    assert "tool_choice" not in body
    assert "response_format" not in body
    assert "max_tokens" not in body
