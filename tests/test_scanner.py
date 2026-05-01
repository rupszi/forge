"""Tests for project scanner. Uses mock file structures."""

import asyncio
import json
import os
import tempfile

import pytest

from daemon.scanner.claude_code import (
    read_auto_memory,
    read_claude_md,
    read_claude_rules,
    read_mcp_config,
)
from daemon.scanner.project import (
    detect_framework,
    detect_pm,
    detect_python_framework,
    get_project_hash,
    scan_project,
)
from daemon.scanner.tools import detect_tools


@pytest.fixture
def project_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _write(base, path, content=""):
    full = os.path.join(base, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)


# --- Framework detection ---


def test_detect_next():
    assert detect_framework({"dependencies": {"next": "14.0.0", "react": "18"}}) == "next"


def test_detect_react():
    assert detect_framework({"dependencies": {"react": "18"}}) == "react"


def test_detect_vue():
    assert detect_framework({"dependencies": {"vue": "3.0"}}) == "vue"


def test_detect_express():
    assert detect_framework({"dependencies": {"express": "4"}}) == "express"


def test_detect_sveltekit():
    assert detect_framework({"devDependencies": {"@sveltejs/kit": "2"}}) == "sveltekit"


def test_detect_remix():
    assert detect_framework({"dependencies": {"@remix-run/react": "2"}}) == "remix"


def test_detect_empty():
    assert detect_framework({"dependencies": {}}) == ""


# --- Package manager detection ---


def test_detect_pm_npm(project_dir):
    assert detect_pm(project_dir) == "npm"


def test_detect_pm_yarn(project_dir):
    _write(project_dir, "yarn.lock")
    assert detect_pm(project_dir) == "yarn"


def test_detect_pm_pnpm(project_dir):
    _write(project_dir, "pnpm-lock.yaml")
    assert detect_pm(project_dir) == "pnpm"


def test_detect_pm_bun(project_dir):
    _write(project_dir, "bun.lockb")
    assert detect_pm(project_dir) == "bun"


# --- Python framework detection ---


def test_detect_fastapi(project_dir):
    _write(project_dir, "pyproject.toml", '[project]\ndependencies = ["fastapi"]')
    assert detect_python_framework(project_dir) == "fastapi"


def test_detect_django(project_dir):
    _write(project_dir, "requirements.txt", "django==4.2\ncelery")
    assert detect_python_framework(project_dir) == "django"


def test_detect_no_python_framework(project_dir):
    assert detect_python_framework(project_dir) == ""


# --- Claude Code reading ---


def test_read_claude_md(project_dir):
    _write(project_dir, "CLAUDE.md", "# My project instructions")
    assert "My project instructions" in read_claude_md(project_dir)


def test_read_claude_md_missing(project_dir):
    assert read_claude_md(project_dir) == ""


def test_read_mcp_config(project_dir):
    config = {
        "mcpServers": {
            "supabase": {"command": "npx", "args": ["supabase-mcp"]},
            "vercel": {"command": "npx", "args": ["vercel-mcp"]},
        }
    }
    _write(project_dir, ".claude/settings.json", json.dumps(config))
    servers = read_mcp_config(project_dir)
    assert len(servers) == 2
    assert servers[0].name == "supabase"
    assert servers[0].command == "npx"
    assert servers[1].name == "vercel"


def test_read_mcp_config_missing(project_dir):
    assert read_mcp_config(project_dir) == []


def test_read_mcp_config_invalid_json(project_dir):
    _write(project_dir, ".claude/settings.json", "not json")
    assert read_mcp_config(project_dir) == []


def test_read_claude_rules(project_dir):
    _write(project_dir, ".claude/rules/01-style.md", "Use TypeScript strict mode")
    _write(project_dir, ".claude/rules/02-testing.md", "Always write tests")
    rules = read_claude_rules(project_dir)
    assert len(rules) == 2
    assert "TypeScript strict mode" in rules[0]


def test_read_claude_rules_missing(project_dir):
    assert read_claude_rules(project_dir) == []


def test_read_auto_memory(project_dir):
    mem_dir = os.path.join(project_dir, "memory")
    os.makedirs(mem_dir)
    _write(project_dir, "memory/item1.md", "Supabase RLS needs service_role key")
    _write(project_dir, "memory/item2.md", "Use server actions for mutations")
    items = read_auto_memory(mem_dir)
    assert len(items) == 2


def test_read_auto_memory_empty(project_dir):
    assert read_auto_memory(os.path.join(project_dir, "nonexistent")) == []


# --- Project hash ---


def test_project_hash_deterministic(project_dir):
    h1 = get_project_hash(project_dir)
    h2 = get_project_hash(project_dir)
    assert h1 == h2
    assert len(h1) == 16


def test_project_hash_different_paths():
    assert get_project_hash("/tmp/a") != get_project_hash("/tmp/b")


# --- Tool detection ---


def test_detect_tools_returns_dict():
    tools = detect_tools()
    assert isinstance(tools, dict)
    assert "gh" in tools
    assert "supabase" in tools
    assert isinstance(tools["gh"], bool)


# --- Full scan ---


@pytest.mark.asyncio
async def test_scan_nextjs_project(project_dir):
    """Scan a mock Next.js project with Claude Code configured."""
    pkg = {"dependencies": {"next": "14.0.0", "react": "18"}}
    _write(project_dir, "package.json", json.dumps(pkg))
    _write(project_dir, "tsconfig.json", "{}")
    _write(project_dir, "pnpm-lock.yaml", "")

    # Git
    await asyncio.create_subprocess_exec("git", "init", cwd=project_dir)
    await asyncio.sleep(0.1)

    # Claude Code
    mcp = {"mcpServers": {"supabase": {"command": "npx", "args": []}}}
    _write(project_dir, ".claude/settings.json", json.dumps(mcp))
    _write(project_dir, "CLAUDE.md", "# Instructions")

    ctx = await scan_project(project_dir)
    assert ctx.is_git is True
    assert ctx.language == "typescript"
    assert ctx.framework == "next"
    assert ctx.package_manager == "pnpm"
    assert ctx.has_claude is True
    assert len(ctx.mcp_servers) == 1
    assert ctx.mcp_servers[0].name == "supabase"
    assert "Instructions" in ctx.claude_md


@pytest.mark.asyncio
async def test_scan_python_project(project_dir):
    _write(project_dir, "pyproject.toml", '[project]\ndependencies = ["fastapi"]')
    ctx = await scan_project(project_dir)
    assert ctx.language == "python"
    assert ctx.framework == "fastapi"
    assert ctx.is_git is False


@pytest.mark.asyncio
async def test_scan_empty_project(project_dir):
    ctx = await scan_project(project_dir)
    assert ctx.language == ""
    assert ctx.framework == ""
    assert ctx.is_git is False
    assert ctx.has_claude is False


@pytest.mark.asyncio
async def test_scan_rust_project(project_dir):
    _write(project_dir, "Cargo.toml", '[package]\nname = "myapp"')
    ctx = await scan_project(project_dir)
    assert ctx.language == "rust"


@pytest.mark.asyncio
async def test_scan_go_project(project_dir):
    _write(project_dir, "go.mod", "module myapp")
    ctx = await scan_project(project_dir)
    assert ctx.language == "go"


@pytest.mark.asyncio
async def test_scan_to_dict(project_dir):
    pkg = {"dependencies": {"next": "14"}}
    _write(project_dir, "package.json", json.dumps(pkg))
    ctx = await scan_project(project_dir)
    d = ctx.to_dict()
    assert "framework" in d
    assert "available_tools" in d
