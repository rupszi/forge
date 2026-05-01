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
