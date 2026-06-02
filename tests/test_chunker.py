"""Doc-chunker + map-reduce: process big inputs page-by-page (context extension)."""

from __future__ import annotations

import pytest

from daemon import chunker


class TestChunkText:
    def test_short_text_one_chunk(self):
        out = chunker.chunk_text("a short doc", max_tokens=1000)
        assert out == ["a short doc"]

    def test_long_text_splits(self):
        # ~8000 chars ≈ 2000 tokens; max 500 tokens (~2000 chars) → ~4 chunks.
        text = "\n\n".join(f"paragraph {i} " * 20 for i in range(40))
        chunks = chunker.chunk_text(text, max_tokens=500, overlap_tokens=0)
        assert len(chunks) > 1
        # No chunk grossly exceeds the budget (allow slack for boundary keeping).
        assert all(len(c) <= 500 * 4 * 1.5 for c in chunks)
        # Reassembled content covers every paragraph marker.
        joined = " ".join(chunks)
        assert "paragraph 0" in joined and "paragraph 39" in joined

    def test_overlap_shares_content(self):
        text = "\n\n".join(f"block{i} " * 30 for i in range(20))
        chunks = chunker.chunk_text(text, max_tokens=300, overlap_tokens=50)
        assert len(chunks) >= 2
        # Consecutive chunks share a boundary region (overlap).
        tail = chunks[0][-100:]
        assert any(piece and piece in chunks[1] for piece in [tail[-40:]])

    def test_oversized_single_paragraph_hard_split(self):
        text = "x" * 10000  # one giant token-less blob
        chunks = chunker.chunk_text(text, max_tokens=500, overlap_tokens=0)
        assert len(chunks) > 1


class TestMapReduce:
    @pytest.mark.asyncio
    async def test_single_chunk_maps_once(self):
        calls = []

        async def mapper(chunk, i, total):
            calls.append(i)
            return f"M:{chunk}"

        out = await chunker.map_reduce("tiny", mapper, max_chunk_tokens=1000)
        assert out == "M:tiny"
        assert calls == [0]

    @pytest.mark.asyncio
    async def test_multiple_chunks_mapped_and_combined(self):
        text = "\n\n".join(f"section {i} " * 30 for i in range(20))

        async def mapper(chunk, i, total):
            return f"[{i}]"

        out = await chunker.map_reduce(text, mapper, max_chunk_tokens=300, target_tokens=10_000)
        assert "[0]" in out and "[1]" in out

    @pytest.mark.asyncio
    async def test_recursion_terminates(self):
        # Mapper echoes the chunk → combined stays large → recursion must stop
        # at the depth cap rather than loop forever.
        text = "word " * 4000

        async def mapper(chunk, i, total):
            return chunk  # never shrinks

        out = await chunker.map_reduce(text, mapper, max_chunk_tokens=200, target_tokens=10)
        assert isinstance(out, str) and out  # returned, didn't hang
