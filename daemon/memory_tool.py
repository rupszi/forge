"""Memory tool — a path-scoped disk scratchpad (context extension).

Implements Anthropic's memory-tool command set (``view`` / ``create`` /
``str_replace`` / ``insert`` / ``delete`` / ``rename``) over a per-session
directory under ``<project>/.forge/memories/<session>/``. This is the model's
(and the user's) *working notebook* — distinct from the auto-extracted
knowledge base. Anything written here survives the model's context window and
is re-injected into later sprints in the same session via :meth:`context`.

The scratchpad is scoped to a **(project, session)** pair so notes never bleed
across sessions or projects (audit F3, 2026-06-04): :func:`default_tool` derives
its root from the connected project's path plus the session id. Callers without
a session (the manual WS surface) get a project-local ``_shared`` bucket — still
under the project's ``.forge/``, never the daemon's CWD.

Security: every path is contained to the memory root. Absolute paths, ``..``
segments, and symlink escapes all raise ``MemoryViolation`` — nothing outside
the root can be read or written. The session segment is sanitized to a safe
slug before it touches the filesystem.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import FORGE_DIR

MAX_CONTEXT_TOKENS = 3000


class MemoryViolation(ValueError):
    """A memory operation tried to escape its scoped directory."""


class MemoryTool:
    def __init__(self, base_dir: str) -> None:
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, rel: str) -> Path:
        rel = (rel or "").strip()
        # Reject absolute paths and traversal before touching the filesystem.
        if rel.startswith("/") or rel.startswith("~"):
            raise MemoryViolation(f"absolute paths not allowed: {rel!r}")
        parts = Path(rel).parts
        if ".." in parts:
            raise MemoryViolation(f"'..' not allowed in memory path: {rel!r}")
        # Resolve and re-check containment (this also catches symlink escapes,
        # since resolve() follows links).
        target = (self.base / rel).resolve()
        if target != self.base and self.base not in target.parents:
            raise MemoryViolation(f"path escapes memory root: {rel!r}")
        return target

    # -- commands --

    def view(self, path: str = "") -> str:
        """List a directory, or show a file with 1-based line numbers."""
        target = self._resolve(path)
        if target.is_dir() or path in ("", "."):
            entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
            return "\n".join(entries) if entries else "(empty)"
        if not target.exists():
            raise MemoryViolation(f"no such file: {path!r}")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(f"{i:>4}\t{ln}" for i, ln in enumerate(lines, 1))

    def read(self, path: str) -> str:
        """Raw file content (no line numbers)."""
        target = self._resolve(path)
        return target.read_text(encoding="utf-8", errors="replace")

    def create(self, path: str, content: str) -> str:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"created {path}"

    def str_replace(self, path: str, old: str, new: str) -> str:
        target = self._resolve(path)
        text = target.read_text(encoding="utf-8")
        if old not in text:
            raise MemoryViolation(f"text to replace not found in {path!r}")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        return f"edited {path}"

    def insert(self, path: str, line: int, text: str) -> str:
        """Insert ``text`` as a new line after 1-based ``line`` (0 = top)."""
        target = self._resolve(path)
        lines = target.read_text(encoding="utf-8").splitlines()
        idx = max(0, min(line, len(lines)))
        lines.insert(idx, text)
        target.write_text("\n".join(lines), encoding="utf-8")
        return f"inserted into {path}"

    def delete(self, path: str) -> str:
        target = self._resolve(path)
        if target.is_dir():
            raise MemoryViolation(f"refusing to delete a directory: {path!r}")
        target.unlink(missing_ok=True)
        return f"deleted {path}"

    def rename(self, old: str, new: str) -> str:
        src = self._resolve(old)
        dst = self._resolve(new)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return f"renamed {old} -> {new}"

    # -- context injection --

    def context(self, budget_tokens: int = MAX_CONTEXT_TOKENS) -> str:
        """Formatted scratchpad content for injection into a sprint prompt."""
        files = [p for p in sorted(self.base.rglob("*")) if p.is_file()]
        if not files:
            return ""
        budget_chars = budget_tokens * 4
        out = ["## Working memory (session scratchpad)"]
        used = len(out[0])
        for f in files:
            rel = f.relative_to(self.base)
            header = f"\n\n### {rel}\n"
            if used + len(header) >= budget_chars:
                break
            body = f.read_text(encoding="utf-8", errors="replace")
            remaining = budget_chars - used - len(header)
            if len(body) > remaining:
                body = body[: max(0, remaining)] + "\n…(truncated)"
            out.append(header + body)
            used += len(header) + len(body)
        return "".join(out)


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]")


def _safe_segment(value: str) -> str:
    """Reduce an arbitrary id to a single safe path segment.

    Session ids are internally generated (uuid-shaped) but we sanitize anyway:
    any ``/``, ``..``, or other separator collapses to ``_`` so a crafted id
    can never escape ``memories/``. Empty results fall back to ``_shared``.
    """
    slug = _SAFE_SEGMENT.sub("_", (value or "").strip()).strip(".")
    return slug or "_shared"


def default_tool(project_path: str | None = None, session_id: str | None = None) -> MemoryTool:
    """The working-memory notebook for one ``(project, session)`` pair.

    Root is ``<project_path>/.forge/memories/<session_id>/``. Without a
    ``project_path`` the daemon-relative ``.forge`` is used; without a
    ``session_id`` the project-local ``_shared`` bucket is used. Either way the
    scratchpad is isolated per session so prior sessions' notes never re-inject
    into a later sprint, and one project's notes never reach another (F3).
    """
    root = Path(project_path) / FORGE_DIR if project_path else Path(FORGE_DIR)
    base = root / "memories" / _safe_segment(session_id or "_shared")
    return MemoryTool(str(base))


# Commands the WS surface may dispatch (read + write).
_COMMANDS = {"view", "create", "str_replace", "insert", "delete", "rename"}


def dispatch(command: str, args: dict) -> dict:
    """Run a memory-tool command from the WS layer. Returns ``{ok, result|error}``.

    ``args`` may carry ``project_path`` and ``session_id`` so the manual WS
    surface scopes to the same per-(project, session) bucket the scheduler uses
    (F3). When absent, the project-local ``_shared`` bucket is used.
    """
    if command not in _COMMANDS:
        return {"ok": False, "error": f"unknown memory command: {command!r}"}
    tool = default_tool(args.get("project_path"), args.get("session_id"))
    try:
        method = getattr(tool, command)
        result = method(*_args_for(command, args))
    except (MemoryViolation, OSError, TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": result, "files": _listing(tool)}


def _args_for(command: str, a: dict) -> list:
    if command == "view":
        return [a.get("path", "")]
    if command == "create":
        return [a.get("path", ""), a.get("content", "")]
    if command == "str_replace":
        return [a.get("path", ""), a.get("old", ""), a.get("new", "")]
    if command == "insert":
        return [a.get("path", ""), int(a.get("line", 0)), a.get("text", "")]
    if command == "delete":
        return [a.get("path", "")]
    if command == "rename":
        return [a.get("old", ""), a.get("new", "")]
    return []


def _listing(tool: MemoryTool) -> list[str]:
    return [str(p.relative_to(tool.base)) for p in sorted(tool.base.rglob("*")) if p.is_file()]
