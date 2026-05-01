"""Connector registry — MCP-first, native plugins as the second path.

This package is the runtime side of [docs/CONNECTORS.md]. It registers tool
connectors so the planner and generator can call them, and enforces the
capability sandbox declared in each connector's manifest.toml.

Two connector mechanisms:

  1. **MCP** — anything with an MCP server. Forge auto-discovers from
     ``.claude/settings.json``; the connector registry exposes them via
     a unified tool list. No code in this package is needed for MCP — it
     all routes through ``daemon.scanner.claude_code.read_mcp_config``.

  2. **Native** (this package) — Python plugins for tools that don't ship
     an MCP server, or where MCP can't express the integration cleanly.
     Each native connector lives at ``~/.forge/plugins/<name>/`` with a
     ``manifest.toml`` and a ``plugin.py`` implementing the
     ``Connector`` interface from ``forge_plugin_api``.

Loading a native connector
--------------------------

    from daemon.connectors import load_connector
    connector = load_connector("~/.forge/plugins/sendgrid")
    # The runtime verifies the manifest signature, hashes match the lock
    # file, capabilities are within bounds, then loads in a subprocess.

Capability enforcement
----------------------

Every connector method invocation goes through the same sandbox layers
documented in docs/SKILLS.md (subprocess isolation, capability declaration,
hash pinning, path scoping, resource limits, egress filter, audit log).
The skills/connectors/llm-adapters split is purely organizational — they
share one runtime.
"""

from __future__ import annotations

from .registry import ConnectorRegistry, list_connectors, load_connector

__all__ = ["ConnectorRegistry", "list_connectors", "load_connector"]
