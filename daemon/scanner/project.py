"""Project detection: git, stack, framework, package manager."""

import asyncio
import json
from pathlib import Path

from ..models import ProjectContext
from .claude_code import (
    read_agents_md,
    read_auto_memory,
    read_claude_md,
    read_claude_rules,
    read_mcp_config,
)
from .tools import detect_tools


async def _run(cmd: list[str], cwd: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return stdout.decode().strip()
    except Exception:
        return ""


async def get_default_branch(path: str) -> str:
    result = await _run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], path)
    if result:
        return result.split("/")[-1]
    result = await _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], path)
    return result or "main"


async def get_remote_url(path: str) -> str:
    return await _run(["git", "remote", "get-url", "origin"], path)


def detect_framework(pkg: dict) -> str:
    deps = {}
    deps.update(pkg.get("dependencies", {}))
    deps.update(pkg.get("devDependencies", {}))
    if "next" in deps:
        return "next"
    if "nuxt" in deps:
        return "nuxt"
    if "@sveltejs/kit" in deps:
        return "sveltekit"
    if "astro" in deps:
        return "astro"
    if "remix" in deps or "@remix-run/react" in deps:
        return "remix"
    if "vue" in deps:
        return "vue"
    if "react" in deps:
        return "react"
    if "express" in deps:
        return "express"
    if "fastify" in deps:
        return "fastify"
    if "hono" in deps:
        return "hono"
    return ""


def detect_pm(path: str) -> str:
    p = Path(path)
    if (p / "bun.lockb").exists() or (p / "bun.lock").exists():
        return "bun"
    if (p / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (p / "yarn.lock").exists():
        return "yarn"
    return "npm"


def detect_python_framework(path: str) -> str:
    p = Path(path)
    # Check pyproject.toml deps
    pyproject = p / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text()
        if "fastapi" in text.lower():
            return "fastapi"
        if "django" in text.lower():
            return "django"
        if "flask" in text.lower():
            return "flask"
    # Check requirements.txt
    reqs = p / "requirements.txt"
    if reqs.exists():
        text = reqs.read_text().lower()
        if "fastapi" in text:
            return "fastapi"
        if "django" in text:
            return "django"
        if "flask" in text:
            return "flask"
    return ""


def get_project_hash(path: str) -> str:
    """Compute the same project hash that Claude Code uses for memory paths."""
    import hashlib

    normalized = str(Path(path).resolve())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


async def scan_project(path: str) -> ProjectContext:
    """Scan the project directory and build a complete context."""
    ctx = ProjectContext(path=path)
    p = Path(path)

    # 1. Git detection
    ctx.is_git = (p / ".git").exists()
    if ctx.is_git:
        ctx.default_branch = await get_default_branch(path)
        ctx.remote_url = await get_remote_url(path)

    # 2. Stack detection
    pkg_path = p / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text())
            ctx.language = "typescript" if (p / "tsconfig.json").exists() else "javascript"
            ctx.framework = detect_framework(pkg)
            ctx.package_manager = detect_pm(path)
        except json.JSONDecodeError:
            ctx.language = "javascript"
    elif (p / "pyproject.toml").exists():
        ctx.language = "python"
        ctx.framework = detect_python_framework(path)
    elif (p / "Cargo.toml").exists():
        ctx.language = "rust"
    elif (p / "go.mod").exists():
        ctx.language = "go"

    # 3. Claude Code detection
    ctx.has_claude = (p / ".claude").exists()
    if ctx.has_claude:
        ctx.claude_md = read_claude_md(path)
        ctx.mcp_servers = read_mcp_config(path)
        ctx.claude_rules = read_claude_rules(path)

    # 4. Claude Code auto-memory
    project_hash = get_project_hash(path)
    memory_path = Path.home() / ".claude" / "projects" / project_hash / "memory"
    if memory_path.exists():
        ctx.claude_auto_memory = read_auto_memory(str(memory_path))

    # 4b. AGENTS.md root-to-leaf walk (Sprint 7.4). Empty list when the
    # project doesn't use the convention — this is alongside CLAUDE.md,
    # not a replacement.
    ctx.agents_md = read_agents_md(path)

    # 5. Available CLIs
    ctx.available_tools = detect_tools()

    return ctx
