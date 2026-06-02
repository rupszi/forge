"""File-fetch — pull one file's text on demand (lazy load, vs front-loading).

A small, path-agnostic reader the UI / agent uses to bring a single file into
context only when needed. Path scoping is enforced by the caller (the WS layer
validates against home/cwd before calling this).
"""

from __future__ import annotations

from pathlib import Path

MAX_FETCH_BYTES = 200_000


def read_file_text(path: str, max_bytes: int = MAX_FETCH_BYTES) -> dict:
    """Read a single text file. Returns ``{ok, content?, truncated, error?}``."""
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"not a file: {path}"}
    try:
        raw = p.read_bytes()
    except OSError as e:
        return {"ok": False, "error": str(e)}
    truncated = len(raw) > max_bytes
    try:
        content = raw[:max_bytes].decode("utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "binary or non-UTF-8 file"}
    return {"ok": True, "content": content, "truncated": truncated, "bytes": len(raw)}
