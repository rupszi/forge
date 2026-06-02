"""Doc-chunker + map-reduce — process inputs larger than the window.

Splits an oversized input into window-sized chunks (preferring paragraph/line
boundaries, with optional overlap), runs a per-chunk ``mapper`` (e.g. summarize
/ extract), and combines the results — recursively reducing if the combined
output is still too big. Lets a small-window model handle a large file or doc.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from itertools import pairwise

_CHARS_PER_TOKEN = 4
_MAX_REDUCE_DEPTH = 3

# mapper(chunk, index, total) -> str
Mapper = Callable[[str, int, int], Awaitable[str]]


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def chunk_text(text: str, max_tokens: int = 2000, overlap_tokens: int = 100) -> list[str]:
    """Split ``text`` into chunks of ~``max_tokens``, preferring paragraph then
    line boundaries; hard-splits anything still too long. Adds a small overlap
    so context isn't lost at the seams."""
    max_chars = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return [text]

    # Break into boundary-respecting pieces no larger than max_chars.
    pieces: list[str] = []
    for para in text.split("\n\n"):
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        for line in para.split("\n"):
            if len(line) <= max_chars:
                pieces.append(line)
            else:
                # Token-less blob — hard-split.
                pieces.extend(line[i : i + max_chars] for i in range(0, len(line), max_chars))

    # Greedily pack pieces into chunks up to max_chars.
    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        candidate = f"{cur}\n\n{piece}" if cur else piece
        if len(candidate) > max_chars and cur:
            chunks.append(cur)
            cur = piece
        else:
            cur = candidate
    if cur:
        chunks.append(cur)

    if overlap_tokens <= 0 or len(chunks) <= 1:
        return chunks

    # Prepend the tail of each chunk to the next (char-based overlap).
    overlap_chars = overlap_tokens * _CHARS_PER_TOKEN
    overlapped = [chunks[0]]
    for prev, nxt in pairwise(chunks):
        overlapped.append(prev[-overlap_chars:] + "\n\n" + nxt)
    return overlapped


async def map_reduce(
    text: str,
    mapper: Mapper,
    reducer: Callable[[list[str]], str] | None = None,
    max_chunk_tokens: int = 2000,
    target_tokens: int = 1000,
    _depth: int = 0,
) -> str:
    """Chunk → map each chunk → combine. If the combined result is still over
    ``target_tokens``, recursively reduce (hierarchical summarization) up to a
    depth cap so it always terminates."""
    join = reducer or (lambda parts: "\n\n".join(parts))
    chunks = chunk_text(text, max_chunk_tokens, overlap_tokens=0)
    if len(chunks) == 1:
        return await mapper(chunks[0], 0, 1)

    mapped = [await mapper(c, i, len(chunks)) for i, c in enumerate(chunks)]
    combined = join(mapped)
    if estimate_tokens(combined) > target_tokens and _depth < _MAX_REDUCE_DEPTH:
        return await map_reduce(
            combined, mapper, reducer, max_chunk_tokens, target_tokens, _depth + 1
        )
    return combined


async def ollama_digest(text: str, target_tokens: int = 800) -> str:
    """Default digest: summarize ``text`` to ~``target_tokens`` via a local model."""
    from .config import LOCAL_PLAN_MODEL
    from .executors import ollama as ollama_executor

    async def _mapper(chunk: str, i: int, total: int) -> str:
        prompt = (
            f"Summarize part {i + 1}/{total} of a document. Preserve facts, names, "
            f"and decisions; be concise.\n\n{chunk}"
        )
        result = await ollama_executor.execute(prompt, model=LOCAL_PLAN_MODEL)
        return result.output if result.success else chunk[: target_tokens * _CHARS_PER_TOKEN]

    return await map_reduce(text, _mapper, target_tokens=target_tokens)
