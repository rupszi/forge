"""Forge KB-as-MCP server export — Phase 1 Week 6.

Exposes Forge's persistent knowledge base, episodic store, and research cache
as a Model Context Protocol server so any MCP-aware agent (Claude Desktop,
Cursor, Continue.dev, Goose, Cline, Zed's agent panel) can query into Forge's
accumulated learning without running the Forge daemon.

This is the **highest-leverage feature** in Phase 1 (per [research/competitive-
landscape-and-architecture.md §3.3](research/competitive-landscape-and-architecture.md))
because it lets *every other tool the user already runs* benefit from
whatever Forge has learned about their projects. ~one day of work, zero new
UI, immediately useful.

Run standalone:

    forge mcp-serve  # exposes via stdio (the default MCP transport)

Or register in ``~/.claude/settings.json`` so Claude Desktop / Code starts it:

    "mcpServers": {
        "forge-kb": {
            "command": "uv",
            "args": ["run", "forge", "mcp-serve"]
        }
    }

Tools exposed (all prefixed ``forge_*`` per the namespacing recommendation in
Anthropic's "Writing Tools for Agents" guide):

    forge_kb_search        — search KB for gotchas/patterns/solutions
    forge_kb_add           — record a new knowledge item
    forge_episode_search   — look up past task failures + resolutions
    forge_research_lookup  — check research cache before fresh web search
    forge_session_summary  — read a session's full trajectory

Resources (read-only, fetched at session start by MCP-aware clients):

    forge://stats                         — KB summary (counts, top topics)
    forge://session/{session_id}/summary  — per-session human-readable summary

Prompts (parameterized templates the user can invoke):

    review_with_forge_kb(file_path)       — review a file using the KB

The implementation depends on the ``mcp`` Python SDK (FastMCP), which ships
in the optional ``forge[mcp]`` extra. We import lazily inside ``main()`` so
the rest of Forge runs without the dep installed.

References:
  - MCP spec: https://modelcontextprotocol.io
  - FastMCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
  - ADR-014 (surface plan: browser dashboard for v1; MCP server export is the
    asymmetric move that gives Forge presence in every other agent)
  - docs/research/notes/04-anthropic-best-practices.md §B (skeleton outline)
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import DB_PATH

logger = logging.getLogger(__name__)


def _load_db():
    """Lazy-load the Forge DB. Imports are scoped to main() callers so
    downstream tools (testing, type-check) don't pull DB I/O at import time."""
    from .db import ForgeDB  # local import — DB layer instantiates on construction

    return ForgeDB(Path(DB_PATH))


def build_mcp_server():
    """Construct a FastMCP server with the Forge tool/resource/prompt set.

    Factory function so:
      1. Tests can build a server instance against a tmp DB.
      2. The ``mcp`` import is local — failure mode when ``forge[mcp]`` isn't
         installed is a clean ``ImportError`` raised by this function, not at
         module import time.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise ImportError(
            "MCP server export requires the 'mcp' package. "
            "Install with: uv pip install 'forge-orchestrator[mcp]' "
            "or: pip install mcp"
        ) from e

    mcp = FastMCP("forge-kb")
    db = _load_db()

    # ---- Tools ----

    @mcp.tool()
    def forge_kb_search(
        query: str,
        topic: str | None = None,
        category: str | None = None,
        limit: int = 5,
    ) -> str:
        """Search Forge's knowledge base for gotchas, solutions, and patterns.

        Returns up to ``limit`` items as a markdown list, ranked by confidence
        and recent usage. Use this BEFORE writing code that touches unfamiliar
        territory — there's a good chance Forge has already learned something
        relevant from a previous session.

        Args:
            query: keywords to search for (e.g. "supabase RLS")
            topic: optional topic filter (e.g. "supabase", "next.js")
            category: optional category filter ("gotcha", "solution", "pattern")
            limit: max items to return (default 5)
        """
        items = db.search_knowledge(query=query, topic=topic, category=category, limit=limit)
        if not items:
            return "No matching knowledge items."
        return "\n".join(
            f"- [{i.get('category', '?')}/{i.get('topic', '?')}] "
            f"{i.get('content', '')} "
            f"(conf={i.get('confidence', 0):.2f}, src={i.get('source', '?')})"
            for i in items
        )

    @mcp.tool()
    def forge_kb_add(
        category: str,
        topic: str,
        content: str,
        source: str = "agent",
    ) -> str:
        """Record a new gotcha, solution, or pattern in Forge's knowledge base.

        Use SPARINGLY — only for reusable, non-obvious lessons. One imperative
        sentence. Forge automatically deduplicates against existing items.

        Args:
            category: "gotcha" | "solution" | "pattern" | "rule" | "preference"
            topic: domain tag (e.g. "supabase", "next.js", "auth", "testing")
            content: ONE imperative line (e.g. "Supabase RLS test with service_role key, not anon key")
            source: optional provenance tag (default "agent")
        """
        item_id = db.add_knowledge(
            category=category,
            topic=topic,
            content=content,
            source=source,
            confidence=0.5,
        )
        return f"Stored item id={item_id}."

    @mcp.tool()
    def forge_episode_search(error_pattern: str, limit: int = 3) -> str:
        """Look up past task failures matching an error pattern, with resolutions.

        Use when you hit an error to see how Forge resolved it before. Returns
        the closest historical episodes ordered by recency.

        Args:
            error_pattern: substring or keywords from the error
            limit: max episodes to return (default 3)
        """
        eps = db.search_episodes(error_pattern, limit=limit)
        if not eps:
            return "No matching past failures."
        return "\n\n".join(
            f"Task: {e.get('task_description', '')[:120]}\n"
            f"Error: {(e.get('error') or '')[:200]}\n"
            f"Resolution: {(e.get('resolution') or '(none)')[:200]}"
            for e in eps
        )

    @mcp.tool()
    def forge_research_lookup(query: str, max_age_days: int = 30) -> str:
        """Check Forge's research cache before triggering a fresh web search.

        Args:
            query: search query string
            max_age_days: ignore research older than this (default 30)
        """
        hits = db.search_research(query, max_age_days=max_age_days, limit=2)
        if not hits:
            return "No cached research."
        return "\n\n".join(
            f"[{h.get('url', '')}]\n{(h.get('extracted_content') or '')[:600]}" for h in hits
        )

    @mcp.tool()
    def forge_session_summary(session_id: str) -> str:
        """Read a Forge session's high-level summary (objective, sprints,
        cost, learnings)."""
        return db.session_summary_text(session_id)

    # ---- Resources ----

    @mcp.resource("forge://stats")
    def kb_stats() -> str:
        """Summary of Forge's KB: counts by category, top topics, recent additions."""
        return db.kb_summary_text()

    @mcp.resource("forge://session/{session_id}/summary")
    def session_summary(session_id: str) -> str:
        """Per-session summary: sprints, costs, learnings."""
        return db.session_summary_text(session_id)

    # ---- Prompts ----

    @mcp.prompt()
    def review_with_forge_kb(file_path: str) -> str:
        """Review a file using Forge's accumulated patterns and gotchas."""
        return (
            f"Read {file_path}. "
            f"Use forge_kb_search to find relevant gotchas and patterns for this "
            f"file's domain. Cite each KB item ID you apply. "
            f"Flag any code that contradicts a high-confidence KB item."
        )

    return mcp


def main() -> int:
    """Entry point for ``forge mcp-serve`` CLI command.

    Runs the MCP server over stdio (the default MCP transport). Blocks until
    the parent process closes the streams.
    """
    try:
        server = build_mcp_server()
    except ImportError as e:
        # Print and exit cleanly if mcp isn't installed
        logger.error(str(e))
        print(str(e))
        return 1

    server.run()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
