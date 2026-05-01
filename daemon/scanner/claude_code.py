"""Read .claude/ directory: CLAUDE.md, settings.json (MCP), rules, auto-memory."""

import json
from pathlib import Path

from ..models import MCPServer


def read_claude_md(project_path: str) -> str:
    p = Path(project_path) / "CLAUDE.md"
    if p.exists():
        return p.read_text()
    return ""


def read_mcp_config(project_path: str) -> list[MCPServer]:
    """Discover configured MCP servers from Claude Code settings."""
    settings_path = Path(project_path) / ".claude" / "settings.json"
    if not settings_path.exists():
        return []
    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        return []
    servers = []
    for name, config in settings.get("mcpServers", {}).items():
        servers.append(
            MCPServer(
                name=name,
                command=config.get("command"),
                args=config.get("args", []),
            )
        )
    return servers


def read_claude_rules(project_path: str) -> list[str]:
    """Read all .claude/rules/*.md files."""
    rules_dir = Path(project_path) / ".claude" / "rules"
    if not rules_dir.exists():
        return []
    rules = []
    for f in sorted(rules_dir.glob("*.md")):
        rules.append(f.read_text())
    return rules


def read_auto_memory(memory_path: str) -> list[str]:
    """Read Claude Code auto-memory files from ~/.claude/projects/<hash>/memory/."""
    p = Path(memory_path)
    if not p.exists():
        return []
    items = []
    for f in sorted(p.glob("*.md")):
        content = f.read_text().strip()
        if content:
            items.append(content)
    return items


# ──────────────────────────────────────────────────────────────────────
#  AGENTS.md ingestion (Sprint 7.4)
# ──────────────────────────────────────────────────────────────────────


def read_agents_md(project_path: str, *, cwd: str | None = None) -> list[tuple[str, str]]:
    """Walk root → leaf collecting AGENTS.md / AGENTS.override.md context.

    Returns a list of ``(relative_path, content)`` pairs in root-first
    order. The convention (now backed by the agents.md spec) is:

      1. Walk from the project root down to the current working directory
         (or ``project_path`` if no cwd is given).
      2. At each level, prefer ``AGENTS.override.md`` if present (it
         supersedes a same-level AGENTS.md); otherwise read ``AGENTS.md``.
      3. Each file's body becomes a separate context block — the planner
         injects them as ``# AGENTS.md instructions for <relpath>`` blocks
         so the model can attribute guidance to its origin directory.

    A project that uses CLAUDE.md but not AGENTS.md gets an empty list;
    no error. A project that uses both gets both — the planner is
    responsible for ordering CLAUDE.md before / after the AGENTS chain
    (current convention: CLAUDE.md first, AGENTS.md root → leaf next).

    Empty AGENTS.md files are skipped — a placeholder file shouldn't
    take up tokens for nothing.
    """
    project = Path(project_path).resolve()
    target = Path(cwd).resolve() if cwd else project
    if not target.is_dir():
        target = project

    # Build the chain of directories from project → target. If target
    # isn't under project (caller mistake), fall back to scanning project
    # only — never escape upward into the user's filesystem.
    try:
        rel = target.relative_to(project)
    except ValueError:
        rel = Path()

    chain: list[Path] = [project]
    accum = project
    for part in rel.parts:
        accum = accum / part
        chain.append(accum)

    out: list[tuple[str, str]] = []
    for d in chain:
        # AGENTS.override.md wins over AGENTS.md at the same level.
        for filename in ("AGENTS.override.md", "AGENTS.md"):
            f = d / filename
            if f.is_file():
                content = f.read_text(encoding="utf-8").strip()
                if content:
                    rel_str = f.relative_to(project).as_posix()
                    out.append((rel_str, content))
                break  # don't read the non-override sibling
    return out
