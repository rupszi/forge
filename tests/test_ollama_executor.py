"""Tests for daemon/executors/ollama.py — Phase 1 Week 1 hardening.

Covers the new tools-array support, keep_alive, num_ctx, response_format
passthrough, and the Ollama→OpenAI tool-call normalization.

The executor itself is fronted by httpx.AsyncClient, which we mock via
httpx.MockTransport. Same pattern as test_openai_compatible.py — keeps the
unit suite running without a network or a real Ollama process.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from daemon.executors import ollama, openai_compatible

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _make_transport(response_json: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json)

    return httpx.MockTransport(handler)


@contextmanager
def patch_httpx(transport: httpx.MockTransport):
    def factory(**kwargs):
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    with patch.object(httpx, "AsyncClient", factory):
        yield


@contextmanager
def capture_request():
    """Yield a dict that gets populated with the JSON body of the next request."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "ok"},
                "prompt_eval_count": 5,
                "eval_count": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    with patch_httpx(transport):
        yield captured


# ---- keep_alive ----


@pytest.mark.asyncio
async def test_default_keep_alive_in_request():
    """The default OLLAMA_KEEP_ALIVE value should be sent on every call."""
    with capture_request() as captured:
        await ollama.execute(prompt="hi", model="qwen3-coder-next")

    assert captured["body"]["keep_alive"] == ollama.OLLAMA_KEEP_ALIVE
    # Default is "30m" unless env overridden
    assert captured["body"]["keep_alive"] in ("30m", ollama.OLLAMA_KEEP_ALIVE)


@pytest.mark.asyncio
async def test_keep_alive_override():
    """Caller-supplied keep_alive overrides the default."""
    with capture_request() as captured:
        await ollama.execute(prompt="hi", model="qwen3-coder-next", keep_alive="0")

    assert captured["body"]["keep_alive"] == "0"


@pytest.mark.asyncio
async def test_keep_alive_can_be_integer():
    """Ollama accepts seconds as int."""
    with capture_request() as captured:
        await ollama.execute(prompt="hi", model="qwen3-coder-next", keep_alive=600)

    assert captured["body"]["keep_alive"] == 600


# ---- num_ctx and num_predict ----


@pytest.mark.asyncio
async def test_num_ctx_passed_in_options():
    """When num_ctx is set, it lands inside options dict (Ollama's per-call
    context-window setting)."""
    with capture_request() as captured:
        await ollama.execute(prompt="hi", model="qwen3.6:27b", num_ctx=128_000)

    assert captured["body"]["options"]["num_ctx"] == 128_000


@pytest.mark.asyncio
async def test_num_predict_passed_in_options():
    with capture_request() as captured:
        await ollama.execute(prompt="hi", model="qwen3.6:27b", num_predict=4096)

    assert captured["body"]["options"]["num_predict"] == 4096


@pytest.mark.asyncio
async def test_options_omits_num_ctx_when_unspecified():
    """When num_ctx is None, no num_ctx key in options (use model default)."""
    with capture_request() as captured:
        await ollama.execute(prompt="hi", model="qwen3-coder-next")

    assert "num_ctx" not in captured["body"]["options"]


# ---- response_format ----


@pytest.mark.asyncio
async def test_response_format_json_string():
    """Passing 'json' enables Ollama's legacy JSON mode."""
    with capture_request() as captured:
        await ollama.execute(prompt="emit json", model="qwen3.6:27b", response_format="json")

    assert captured["body"]["format"] == "json"


@pytest.mark.asyncio
async def test_response_format_schema_dict():
    """Passing a JSON schema dict enables modern constrained decoding."""
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    with capture_request() as captured:
        await ollama.execute(prompt="emit json", model="qwen3.6:27b", response_format=schema)

    assert captured["body"]["format"] == schema


# ---- tools ----


@pytest.mark.asyncio
async def test_tools_passed_through():
    """Tools array is forwarded to Ollama which routes via the per-model parser."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]

    with capture_request() as captured:
        await ollama.execute(prompt="read main", model="qwen3-coder-next", tools=tools)

    assert captured["body"]["tools"] == tools


@pytest.mark.asyncio
async def test_tools_omitted_when_unused():
    """Don't send a tools key when caller passes None."""
    with capture_request() as captured:
        await ollama.execute(prompt="hi", model="qwen3-coder-next")

    assert "tools" not in captured["body"]


@pytest.mark.asyncio
async def test_tool_call_response_normalized_to_openai_shape():
    """Ollama returns ``arguments`` as a dict; we normalize to JSON string
    so the same parse_tool_response helper works for both executors."""
    response = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": "src/main.py"},  # dict, not string
                    }
                }
            ],
        },
        "prompt_eval_count": 50,
        "eval_count": 10,
    }
    transport = _make_transport(response)

    with patch_httpx(transport):
        result = await ollama.execute(
            prompt="read",
            model="qwen3-coder-next",
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        )

    assert result.success
    assert result.output.startswith(openai_compatible.TOOL_CALL_PREFIX)

    content, calls = openai_compatible.parse_tool_response(result.output)
    assert content == ""
    assert len(calls) == 1
    # arguments must be a JSON string in the normalized output
    assert isinstance(calls[0]["function"]["arguments"], str)
    parsed = json.loads(calls[0]["function"]["arguments"])
    assert parsed == {"path": "src/main.py"}


@pytest.mark.asyncio
async def test_tool_call_with_id_preserved():
    """If Ollama returns a tool-call id, preserve it; else synthesize one."""
    response = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_abc", "function": {"name": "f", "arguments": {}}},
                {"function": {"name": "g", "arguments": {}}},  # no id
            ],
        },
        "prompt_eval_count": 1,
        "eval_count": 1,
    }
    transport = _make_transport(response)

    with patch_httpx(transport):
        result = await ollama.execute(prompt="x", model="qwen3-coder-next", tools=[{"a": 1}])

    _, calls = openai_compatible.parse_tool_response(result.output)
    assert calls[0]["id"] == "call_abc"
    assert calls[1]["id"] == "call_1"  # synthesized


# ---- temperature + happy path ----


@pytest.mark.asyncio
async def test_default_temperature_is_02():
    with capture_request() as captured:
        await ollama.execute(prompt="hi", model="qwen3-coder-next")

    assert captured["body"]["options"]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_temperature_override():
    with capture_request() as captured:
        await ollama.execute(prompt="hi", model="qwen3-coder-next", temperature=0.0)

    assert captured["body"]["options"]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_happy_path_returns_content_and_tokens():
    response = {
        "message": {"role": "assistant", "content": "hello world"},
        "prompt_eval_count": 7,
        "eval_count": 3,
    }
    transport = _make_transport(response)

    with patch_httpx(transport):
        result = await ollama.execute(prompt="say hello", model="qwen3-coder-next")

    assert result.success
    assert result.output == "hello world"
    assert result.tokens_in == 7
    assert result.tokens_out == 3
    assert result.cost_usd == 0.0  # always free for self-hosted
    assert result.duration_seconds >= 0


# ---- Error paths ----


@pytest.mark.asyncio
async def test_http_error_returns_clean_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'bogus' not found"})

    transport = httpx.MockTransport(handler)

    with patch_httpx(transport):
        result = await ollama.execute(prompt="hi", model="bogus")

    assert not result.success
    assert "404" in result.error
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_network_error_returns_clean_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)

    with patch_httpx(transport):
        result = await ollama.execute(prompt="hi", model="qwen3-coder-next")

    assert not result.success
    assert "Network error" in result.error
