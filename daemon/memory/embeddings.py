"""Optional vector recall on the episodic store (Phase 1 Week 4).

Forge's KB is intentionally embeddings-free (ADR-012) — the 200-item cap and
topic-filter discipline make SQLite LIKE on a topic-bucket fast and accurate.

But the **episodic store** grows without bound. After a few months of use,
"find similar past failures" via `LIKE` on a multi-thousand-row corpus is the
weak link — past task descriptions don't share keywords with the current task
even when they're conceptually similar. That's where embeddings earn their
keep.

This module provides an **optional**, **gated** vector recall layer for the
episodic store. Activated via:

    export FORGE_VECTOR_EPISODES=1

When activated:
  - The `daemon.db.ForgeDB` initializer attempts to load the `sqlite-vec`
    extension (ships as a Python wheel with prebuilt binaries for macOS /
    Linux / Windows).
  - On every episode write, this module computes an embedding via Ollama's
    `/api/embeddings` endpoint using `nomic-embed-text` (Apache 2.0, ~270 MB,
    fast on Apple Silicon).
  - On retrieval, callers can use `find_similar_episodes(query, k=5)` to
    pull the k-nearest past episodes by cosine similarity.

When NOT activated:
  - This module's functions degrade to no-ops or raise `EmbeddingsDisabled`
    so callers can skip cleanly.

Why opt-in instead of default-on:
  - Adds two soft deps (`sqlite-vec`, Ollama embedding model)
  - Some users have neither sqlite-vec nor a running Ollama
  - The KB doesn't need it (per ADR-012); only episodic does
  - Lets us measure the win before forcing it on everyone

References:
  - sqlite-vec: https://github.com/asg017/sqlite-vec
  - nomic-embed-text on Ollama: https://ollama.com/library/nomic-embed-text
  - ADR-012 (no embeddings on KB; sqlite-vec optional on episodic)
"""

from __future__ import annotations

import logging
import os

import httpx

from ..config import LOCAL_EMBED_MODEL, OLLAMA_BASE_URL

logger = logging.getLogger(__name__)


# Embedding dimension for nomic-embed-text (the default ``LOCAL_EMBED_MODEL``).
# Other embedding models would change this — set ``FORGE_EMBED_DIMS`` to override.
DEFAULT_EMBED_DIMS = int(os.environ.get("FORGE_EMBED_DIMS", "768"))


class EmbeddingsDisabled(RuntimeError):
    """Raised when callers invoke embedding functions but the feature isn't
    enabled (env var unset or sqlite-vec unavailable)."""


def is_enabled() -> bool:
    """Return True iff the user opted in via ``FORGE_VECTOR_EPISODES=1``."""
    return os.environ.get("FORGE_VECTOR_EPISODES", "0") == "1"


def has_sqlite_vec() -> bool:
    """Return True iff the ``sqlite-vec`` Python wheel is installed and
    loadable. Used by ``daemon.db`` at startup to decide whether to register
    the virtual table."""
    try:
        import sqlite_vec  # noqa: F401

        return True
    except ImportError:
        return False


async def embed(text: str, *, model: str | None = None, timeout: float = 30.0) -> list[float]:
    """Compute an embedding for ``text`` via Ollama.

    Returns the float vector. Raises ``EmbeddingsDisabled`` when the feature
    isn't enabled, ``RuntimeError`` on transport / decoding errors.

    Why a thin wrapper instead of inlining at every call site: keeps the
    Ollama embeddings API surface in one file. If we ever swap to a different
    embedding provider (HF Inference API, OpenAI text-embedding-3-small),
    this is the only file that changes.
    """
    if not is_enabled():
        raise EmbeddingsDisabled(
            "embeddings require FORGE_VECTOR_EPISODES=1. See daemon/memory/embeddings.py."
        )

    model_id = model or LOCAL_EMBED_MODEL

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{OLLAMA_BASE_URL}/api/embeddings",
                json={"model": model_id, "prompt": text},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"embedding request failed: {e}") from e

    vec = data.get("embedding")
    if not isinstance(vec, list):
        raise RuntimeError(f"unexpected embedding response: {data}")
    return [float(x) for x in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-length vectors.

    Pure-Python implementation (no numpy dep). Fast enough for the
    sub-1000-vector scale we expect; if the episodic store grows past
    100k rows, switch to sqlite-vec's KNN index which is what sqlite-vec
    is *for*.
    """
    if len(a) != len(b):
        raise ValueError(f"vector dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---- Episodic-store integration helpers ----
#
# The actual SQL-level wiring lives in daemon/db.py. These helpers exist so
# the db module doesn't have to know about Ollama or HTTP.


def serialize_vector(vec: list[float]) -> bytes:
    """Pack a float vector into compact bytes for SQLite storage.

    Uses 4-byte little-endian floats. Compatible with sqlite-vec's vec0()
    virtual table format.
    """
    import struct

    return b"".join(struct.pack("<f", x) for x in vec)


def deserialize_vector(blob: bytes) -> list[float]:
    """Inverse of ``serialize_vector``."""
    import struct

    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))
