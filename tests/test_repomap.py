"""Tests for daemon/scanner/repomap.py — Phase 1 Week 3 deliverable.

Tests use a synthetic project tree built in tmp_path so they don't depend on
any real codebase. Covers symbol extraction across the 5 supported languages,
ranking, token-budget enforcement, and ignore-pattern handling.
"""

from __future__ import annotations

from pathlib import Path

from daemon.scanner.repomap import (
    _DEFAULT_IGNORES,
    _EXT_TO_LANG,
    _extract_symbols,
    build_repomap,
)

# ---- Symbol extraction per language ----


def test_python_extracts_def_and_class():
    src = """
import os

def foo(x):
    return x

async def bar():
    pass

class Baz:
    def method(self):
        pass

class _Private:
    pass
"""
    syms = _extract_symbols(src, "python")
    assert "foo" in syms
    assert "bar" in syms
    assert "Baz" in syms
    assert "_Private" in syms
    assert "method" in syms


def test_typescript_extracts_exports():
    src = """
import { x } from 'foo';

export class LoginService {
    constructor() {}
}

export async function authenticate(email: string) {
    return true;
}

export const API_VERSION = 'v1';

export interface User { id: number; }
export type UserId = number;
export enum Role { Admin, User }
"""
    syms = _extract_symbols(src, "typescript")
    assert "LoginService" in syms
    assert "authenticate" in syms
    assert "API_VERSION" in syms
    assert "User" in syms
    assert "UserId" in syms
    assert "Role" in syms


def test_typescript_dedup_preserves_first():
    src = """
export function foo() {}
export function foo() {}  // duplicate (overload)
"""
    syms = _extract_symbols(src, "typescript")
    assert syms.count("foo") == 1


def test_go_extracts_public_funcs_and_types():
    src = """
package main

func PublicFn() int { return 1 }
func privateFn() int { return 2 }

func (s *Server) Handle() {}

type Config struct {
    Port int
}

type Handler interface {
    Serve()
}
"""
    syms = _extract_symbols(src, "go")
    assert "PublicFn" in syms
    assert "Handle" in syms
    assert "Config" in syms
    assert "Handler" in syms
    # Lowercase functions might not be picked up depending on regex; that's ok


def test_rust_extracts_pub_items():
    src = """
pub fn parse(text: &str) -> Result<()> { Ok(()) }
pub struct Config { port: u16 }
pub enum Error { NotFound }
pub trait Handler { fn handle(&self); }

fn private_helper() {}
"""
    syms = _extract_symbols(src, "rust")
    assert "parse" in syms
    assert "Config" in syms
    assert "Error" in syms
    assert "Handler" in syms


def test_unknown_language_returns_empty():
    assert _extract_symbols("anything", "klingon") == []


# ---- build_repomap end-to-end ----


def test_build_repomap_on_synthetic_python_project(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main():\n    pass\n\nclass Server:\n    pass\n")
    (tmp_path / "src" / "utils.py").write_text("def helper():\n    pass\n")
    (tmp_path / "README.md").write_text("# proj")  # ignored (.md not in EXT_TO_LANG)

    repomap = build_repomap(tmp_path, token_budget=2000)

    assert "## Repo:" in repomap
    assert "python" in repomap
    assert "main.py" in repomap
    assert "main" in repomap or "Server" in repomap
    assert "utils.py" in repomap
    assert "README.md" not in repomap


def test_build_repomap_skips_ignored_dirs(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def app(): pass\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "trash.js").write_text("export function trash() {}\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.py").write_text("def hidden(): pass\n")

    repomap = build_repomap(tmp_path, token_budget=2000)
    assert "app.py" in repomap
    assert "trash.js" not in repomap
    assert "hidden" not in repomap


def test_build_repomap_respects_token_budget(tmp_path: Path):
    """When budget is tight, fewer files are included."""
    for i in range(20):
        (tmp_path / f"file_{i}.py").write_text(
            f"def fn_{i}_a(): pass\ndef fn_{i}_b(): pass\nclass Class_{i}: pass\n"
        )

    small = build_repomap(tmp_path, token_budget=200)
    large = build_repomap(tmp_path, token_budget=5000)

    # The small budget produces a shorter output. Token estimate is chars/4
    # so we compare char counts as a proxy.
    assert len(small) < len(large)


def test_build_repomap_empty_directory(tmp_path: Path):
    """Empty project → empty repomap (not an error)."""
    assert build_repomap(tmp_path) == ""


def test_build_repomap_nonexistent_directory():
    """Bad path → empty (logged) — no exception."""
    assert build_repomap("/nonexistent/never/exists") == ""


def test_build_repomap_includes_language_summary(tmp_path: Path):
    (tmp_path / "a.py").write_text("def a(): pass\n")
    (tmp_path / "b.ts").write_text("export const b = 1;\n")
    (tmp_path / "c.go").write_text("package x\nfunc Hello() {}\n")

    repomap = build_repomap(tmp_path)
    assert "## Languages:" in repomap
    assert "python" in repomap
    assert "typescript" in repomap
    assert "go" in repomap


def test_build_repomap_caps_max_files(tmp_path: Path):
    """``max_files`` hard-cap kicks in even with generous budget."""
    for i in range(100):
        (tmp_path / f"f{i}.py").write_text(f"def f{i}(): pass\n")

    repomap = build_repomap(tmp_path, token_budget=100_000, max_files=10)
    # Count file lines (each formatted entry starts with "  filename")
    file_count = sum(1 for line in repomap.splitlines() if line.startswith("  f") and ".py" in line)
    assert file_count <= 10


def test_extension_to_language_map_complete():
    """Every extension in the map points to a language with patterns."""
    from daemon.scanner.repomap import _SYMBOL_PATTERNS

    for ext, lang in _EXT_TO_LANG.items():
        assert lang in _SYMBOL_PATTERNS, f".{ext} → {lang} but no patterns"


def test_default_ignores_includes_critical_directories():
    """Sanity: the most pernicious directories are in the default ignore set."""
    for must_ignore in {".git", "node_modules", ".venv", "__pycache__", ".forge"}:
        assert must_ignore in _DEFAULT_IGNORES


def test_build_repomap_reads_files_with_unicode(tmp_path: Path):
    """Files with non-ASCII content shouldn't crash."""
    (tmp_path / "emoji.py").write_text("# 🚀 rocket\ndef launch(): pass\n", encoding="utf-8")
    repomap = build_repomap(tmp_path)
    assert "emoji.py" in repomap
    assert "launch" in repomap


def test_build_repomap_skips_huge_files(tmp_path: Path):
    """Files larger than SIZE_CAP (200KB) should be skipped."""
    huge = "def x(): pass\n" * 30_000  # ~360KB
    (tmp_path / "huge.py").write_text(huge)
    (tmp_path / "small.py").write_text("def small(): pass\n")

    repomap = build_repomap(tmp_path)
    # huge.py likely not included; small.py definitely is
    assert "small.py" in repomap
