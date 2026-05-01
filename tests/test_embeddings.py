"""Tests for daemon/memory/embeddings.py — gated vector recall (Phase 1 Week 4).

The module is opt-in (FORGE_VECTOR_EPISODES=1). These tests cover the gating
logic, the cosine-similarity helper, and the serialize/deserialize round-trip.
The actual Ollama embed() call is mocked because tests must run without a
running Ollama instance.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from daemon.memory.embeddings import (
    EmbeddingsDisabled,
    cosine_similarity,
    deserialize_vector,
    embed,
    has_sqlite_vec,
    is_enabled,
    serialize_vector,
)

_REAL_ASYNC_CLIENT = httpx.AsyncClient


@contextmanager
def patch_httpx(transport: httpx.MockTransport):
    def factory(**kwargs):
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    with patch.object(httpx, "AsyncClient", factory):
        yield


# ---- Gating ----


def test_is_enabled_default_off(monkeypatch):
    monkeypatch.delenv("FORGE_VECTOR_EPISODES", raising=False)
    assert is_enabled() is False


def test_is_enabled_when_set(monkeypatch):
    monkeypatch.setenv("FORGE_VECTOR_EPISODES", "1")
    assert is_enabled() is True


def test_is_enabled_zero_means_off(monkeypatch):
    monkeypatch.setenv("FORGE_VECTOR_EPISODES", "0")
    assert is_enabled() is False


@pytest.mark.asyncio
async def test_embed_raises_when_disabled(monkeypatch):
    monkeypatch.delenv("FORGE_VECTOR_EPISODES", raising=False)
    with pytest.raises(EmbeddingsDisabled):
        await embed("hello")


def test_has_sqlite_vec_returns_bool():
    """Don't assert True/False — depends on whether sqlite-vec is pip-installed."""
    assert isinstance(has_sqlite_vec(), bool)


# ---- Embedding HTTP ----


@pytest.mark.asyncio
async def test_embed_returns_vector_when_enabled(monkeypatch):
    monkeypatch.setenv("FORGE_VECTOR_EPISODES", "1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    transport = httpx.MockTransport(handler)
    with patch_httpx(transport):
        vec = await embed("hello")

    assert vec == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_embed_passes_correct_request_body(monkeypatch):
    monkeypatch.setenv("FORGE_VECTOR_EPISODES", "1")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"embedding": [1.0, 2.0]})

    transport = httpx.MockTransport(handler)
    with patch_httpx(transport):
        await embed("test text", model="custom-embed")

    assert captured["body"]["model"] == "custom-embed"
    assert captured["body"]["prompt"] == "test text"


@pytest.mark.asyncio
async def test_embed_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("FORGE_VECTOR_EPISODES", "1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model not loaded"})

    transport = httpx.MockTransport(handler)
    with patch_httpx(transport):
        with pytest.raises(RuntimeError, match="embedding request failed"):
            await embed("hi")


@pytest.mark.asyncio
async def test_embed_raises_on_unexpected_response_shape(monkeypatch):
    monkeypatch.setenv("FORGE_VECTOR_EPISODES", "1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)
    with patch_httpx(transport):
        with pytest.raises(RuntimeError, match="unexpected"):
            await embed("hi")


# ---- Cosine similarity ----


def test_cosine_identical_vectors():
    v = [1.0, 2.0, 3.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_opposite_vectors():
    a = [1.0, 2.0]
    b = [-1.0, -2.0]
    assert cosine_similarity(a, b) == pytest.approx(-1.0)


def test_cosine_zero_vector_returns_zero():
    """No NaN — return 0.0 cleanly when one input is the zero vector."""
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_dimension_mismatch_raises():
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_similarity([1.0, 2.0], [1.0])


# ---- Serialization round-trip ----


def test_serialize_deserialize_roundtrip():
    vec = [0.1, 0.2, 0.3, -0.4, 1.5]
    blob = serialize_vector(vec)
    recovered = deserialize_vector(blob)
    # Float32 round-trip has some precision loss; use approx
    assert recovered == pytest.approx(vec, abs=1e-6)


def test_serialize_produces_4_bytes_per_dim():
    vec = [0.0] * 768
    assert len(serialize_vector(vec)) == 768 * 4
