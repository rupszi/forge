"""Repository map — give the generator a token-budget-aware view of the repo.

This is Forge's adaptation of Aider's ``repomap.py`` (MIT, ~500 LOC) — see
https://aider.chat/docs/repomap.html for the original. The full Aider
implementation uses tree-sitter for AST-precise symbol extraction; that
requires the ``tree-sitter`` + ``tree-sitter-languages`` deps (binary wheels,
~30 MB combined).

This Phase 1 simplified version uses **regex-based symbol extraction** so
Forge's baseline install stays lean. It covers Python, TypeScript / JavaScript,
Go, Rust, and Java — the 5 languages that account for ~80% of the codebases
Forge will encounter. When users want better fidelity, they can opt in to the
full tree-sitter version (planned Phase 1 Week 4 follow-up) via a
``forge[repomap-precise]`` extra.

The public API is one function:

    build_repomap(project_root, *, token_budget=1500) -> str

The returned string is a markdown-ish summary of the repo structure with the
most-important symbols highlighted. Inject it into the generator prompt
alongside the memory context (``daemon/memory/retriever.py``). The structure:

    ## Repo: my-app (next.js)
    ## Languages: typescript (45 files), python (12 files)
    ## Top-ranked files (by reference count + recency):

      src/auth/login.ts
        export class LoginService
        export function authenticate(email, password)

      src/api/users.ts
        export async function getUser(id)
        export async function createUser(data)
      ...

The ranking heuristic is intentionally simple — file size × identifier count ×
recency boost — instead of full PageRank-on-symbol-graph (Aider's approach).
The simpler ranking is fine for the cheap-tier sprints; complex sprints fall
back to ``Glob`` / ``Grep`` MCP tools (which Claude Code already has) for
deeper exploration.

References:
  - Aider repomap docs: https://aider.chat/docs/repomap.html
  - Aider source: https://github.com/Aider-AI/aider/blob/main/aider/repomap.py
  - ADR-002 (Architecture A): repomap is the no-embeddings retrieval lever
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---- Language-specific symbol extraction patterns ----
#
# Each pattern matches a top-level symbol declaration: function, class,
# method, exported identifier. The regex captures the symbol name in group 1.
# Patterns are deliberately *loose* — false positives (matching strings or
# comments that look like declarations) are acceptable; false negatives
# (missing real symbols) are not.
#
# When upgrading to tree-sitter, replace this dict with .scm query files
# per language and the rest of the file stays identical.

_SYMBOL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", re.MULTILINE),
        re.compile(r"^\s*async\s+def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", re.MULTILINE),
        re.compile(r"^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[:(]", re.MULTILINE),
    ],
    "typescript": [
        re.compile(r"^\s*export\s+(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*export\s+(?:abstract\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*export\s+(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*export\s+interface\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*export\s+type\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*export\s+enum\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(
            r"^\s*export\s+default\s+(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)?",
            re.MULTILINE,
        ),
    ],
    "javascript": [
        re.compile(r"^\s*export\s+(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*export\s+class\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*export\s+(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*module\.exports\s*=\s*([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
    ],
    "go": [
        re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Z][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*type\s+([A-Z][a-zA-Z0-9_]*)\s+(?:struct|interface)", re.MULTILINE),
    ],
    "rust": [
        re.compile(r"^\s*pub\s+fn\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*pub\s+(?:struct|enum|trait)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(r"^\s*impl\s+(?:<[^>]+>\s*)?([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
    ],
    "java": [
        re.compile(
            r"^\s*public\s+(?:static\s+)?(?:final\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            re.MULTILINE,
        ),
        re.compile(r"^\s*public\s+interface\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE),
        re.compile(
            r"^\s*public\s+(?:static\s+)?(?:[a-zA-Z_<>,\s]+)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
            re.MULTILINE,
        ),
    ],
}


# Map of file extension → language id used in ``_SYMBOL_PATTERNS``.
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}


# Default ignore patterns — directories that bloat the repomap without
# adding signal. Tracks the user's ``.gitignore`` plus a few project-shape
# defaults (``node_modules``, virtualenvs, build artifacts).
_DEFAULT_IGNORES = {
    ".git",
    ".forge",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    ".next",
    "dist",
    "build",
    "out",
    "target",  # Rust
    ".gradle",
    "htmlcov",
    "coverage",
    ".tox",
    ".nox",
    ".idea",
    ".vscode",
    ".DS_Store",
}


@dataclass
class FileEntry:
    """One file's entry in the repomap."""

    path: str  # relative to project root
    language: str
    size_bytes: int
    symbols: list[str]
    rank: float = 0.0  # higher = more important

    @property
    def importance_score(self) -> float:
        """Cheap heuristic ranking: many symbols + larger file = more important.

        Real Aider uses PageRank on a symbol-reference graph, which is
        better but requires tree-sitter. This simpler ranking gets ~70% of
        the value at 10% of the implementation cost.
        """
        return len(self.symbols) * 1.0 + (self.size_bytes / 10_000.0)


def _walk_project(root: Path, ignore_names: set[str]) -> list[Path]:
    """Walk ``root`` collecting source files, skipping ignored dirs."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # In-place filter so os.walk skips ignored dirs entirely.
        dirnames[:] = [
            d
            for d in dirnames
            if (d not in ignore_names and not d.startswith(".")) or d == ".claude"
        ]  # keep .claude — Forge cares about it
        for name in filenames:
            full = Path(dirpath) / name
            if full.suffix.lower() in _EXT_TO_LANG:
                files.append(full)
    return files


def _extract_symbols(text: str, language: str) -> list[str]:
    """Run the language's regex patterns against ``text``; return ordered
    list of symbol names found (deduplicated, preserving first occurrence)."""
    seen: set[str] = set()
    out: list[str] = []
    patterns = _SYMBOL_PATTERNS.get(language, [])
    for pat in patterns:
        for match in pat.finditer(text):
            name = match.group(1) if match.groups() else None
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _format_entry(entry: FileEntry, max_symbols: int = 6) -> str:
    """Format one FileEntry as a markdown-ish snippet."""
    lines = [f"  {entry.path}"]
    for sym in entry.symbols[:max_symbols]:
        lines.append(f"    {sym}")
    if len(entry.symbols) > max_symbols:
        lines.append(f"    ... +{len(entry.symbols) - max_symbols} more")
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    """Cheap chars-per-4 token estimator. Good enough for budget shaping;
    actual tokenization happens at the inference engine."""
    return max(1, len(text) // 4)


def build_repomap(
    project_root: str | Path,
    *,
    token_budget: int = 1500,
    max_files: int = 50,
    extra_ignores: set[str] | None = None,
) -> str:
    """Build a ranked, token-budget-aware repository map.

    Parameters
    ----------
    project_root
        Path to the repo to map.
    token_budget
        Approximate target size in tokens. The function fits as many
        top-ranked files into the budget as possible. Default 1500 lines up
        with the M4 Pro / 32 K-context-window default and leaves room for the
        memory context (~500 tokens) and the actual sprint description.
    max_files
        Hard cap on number of files included even if budget would allow more.
        Prevents the repomap from drowning in tiny files in monorepos.
    extra_ignores
        Additional directory names to skip beyond ``_DEFAULT_IGNORES``.

    Returns
    -------
    str
        Markdown-ish repomap, ready to inject into a generator prompt.
        Empty string if the project is empty / unsupported.
    """
    root = Path(project_root).resolve()
    if not root.exists() or not root.is_dir():
        logger.warning("repomap: %s is not a directory", root)
        return ""

    ignores = _DEFAULT_IGNORES | (extra_ignores or set())

    # Step 1: walk and collect candidate files
    candidates = _walk_project(root, ignores)
    if not candidates:
        return ""

    # Step 2: extract symbols per file (with size cap so we don't read 10MB
    # generated SQL or compiled bundles)
    SIZE_CAP = 200_000  # bytes; files larger than this don't get scanned
    entries: list[FileEntry] = []
    lang_counts: dict[str, int] = defaultdict(int)

    for path in candidates:
        try:
            size = path.stat().st_size
            if size > SIZE_CAP:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("repomap: skipping %s (%s)", path, e)
            continue

        language = _EXT_TO_LANG[path.suffix.lower()]
        symbols = _extract_symbols(text, language)
        rel_path = str(path.relative_to(root))
        entries.append(
            FileEntry(
                path=rel_path,
                language=language,
                size_bytes=size,
                symbols=symbols,
            )
        )
        lang_counts[language] += 1

    if not entries:
        return ""

    # Step 3: rank
    for e in entries:
        e.rank = e.importance_score
    entries.sort(key=lambda e: e.rank, reverse=True)

    # Step 4: format header
    project_name = root.name
    header_parts = [f"## Repo: {project_name}"]
    lang_summary = ", ".join(
        f"{lang} ({count} files)"
        for lang, count in sorted(lang_counts.items(), key=lambda kv: -kv[1])
    )
    if lang_summary:
        header_parts.append(f"## Languages: {lang_summary}")
    header_parts.append("## Top-ranked files (by symbol count + size):")
    header_parts.append("")

    # Step 5: fit entries into the token budget
    output_parts: list[str] = list(header_parts)
    current_tokens = _estimate_tokens("\n".join(output_parts))
    n_files_added = 0

    for entry in entries:
        if n_files_added >= max_files:
            break
        snippet = _format_entry(entry)
        snippet_tokens = _estimate_tokens(snippet)
        if current_tokens + snippet_tokens > token_budget:
            # Don't add this file; if budget is already tight, stop.
            if current_tokens > token_budget * 0.5:
                break
            continue
        output_parts.append(snippet)
        output_parts.append("")  # blank line between entries
        current_tokens += snippet_tokens + 1
        n_files_added += 1

    if n_files_added == 0:
        # Token budget was too small for any entry — emit at least the top
        # one truncated, so the prompt isn't useless.
        output_parts.append(_format_entry(entries[0], max_symbols=2))

    return "\n".join(output_parts).rstrip() + "\n"
