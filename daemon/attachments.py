"""User-attached files as injected context (context extension).

The dashboard's Attach button hands the daemon a path (file or folder); the
daemon reads the *text* files there and stores their content. Before a sprint
runs, the attachment context is injected into the generator prompt (budget-
capped, truncated if large) alongside the memory/repomap context. Binary files
are skipped; oversized files are clipped.

A process-global ``get_store()`` is the single-user app's attachment set.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 200_000  # don't read enormous files into memory
MAX_FILES = 200  # cap a folder attach so a huge tree can't blow up


@dataclass
class Attachment:
    name: str
    path: str
    content: str
    tokens: int


def _read_text(p: Path) -> str | None:
    """Return decoded text, or None if the file is binary/unreadable."""
    try:
        data = p.read_bytes()[:MAX_FILE_BYTES]
        return data.decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return None


class AttachmentStore:
    def __init__(self) -> None:
        self._items: dict[str, Attachment] = {}

    def add_path(self, path: str) -> dict:
        """Attach a file, or every text file under a folder. Returns a summary."""
        p = Path(path)
        if p.is_dir():
            # Skip symlinks — a link inside the attached folder could point
            # outside the validated scope (audit fix, 2026-06-03).
            files = [f for f in sorted(p.rglob("*")) if f.is_file() and not f.is_symlink()]
        elif p.is_file() and not p.is_symlink():
            files = [p]
        else:
            return {"ok": False, "error": f"not found or symlink: {path}"}

        added: list[dict] = []
        for f in files[:MAX_FILES]:
            text = _read_text(f)
            if text is None:
                continue  # binary / unreadable → skip
            tokens = max(1, len(text) // 4)
            self._items[str(f)] = Attachment(f.name, str(f), text, tokens)
            added.append({"name": f.name, "path": str(f), "tokens": tokens})
        return {"ok": True, "files": added, "total": len(self._items)}

    def context(self, budget_tokens: int = 4000) -> str:
        """Formatted attachment context, capped at ``budget_tokens`` (~4 chars/token)."""
        if not self._items:
            return ""
        budget_chars = budget_tokens * 4
        out = ["## Attached files (user-provided context)"]
        used = len(out[0])
        for att in self._items.values():
            header = f"\n\n### {att.name} ({att.path})\n"
            if used + len(header) >= budget_chars:
                break
            remaining = budget_chars - used - len(header)
            body = att.content
            if len(body) > remaining:
                body = body[: max(0, remaining)] + "\n…(truncated)"
            out.append(header + body)
            used += len(header) + len(body)
            if used >= budget_chars:
                break
        return "".join(out)

    def list(self) -> list[dict]:
        return [{"name": a.name, "path": a.path, "tokens": a.tokens} for a in self._items.values()]

    def clear(self) -> None:
        self._items.clear()


_store: AttachmentStore | None = None


def get_store() -> AttachmentStore:
    global _store
    if _store is None:
        _store = AttachmentStore()
    return _store
