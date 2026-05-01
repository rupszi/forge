"""Slash-command registry and dispatch — Sprint 6.3.

Slash commands flow through the WS server as ``{type: "slash.<cmd>",
args: "<arg-string>"}`` messages. The TUI's slash palette and the web
dashboard's command bar both produce this shape; the daemon turns each
into a structured response.

We keep the registry small and centralized here rather than expanding
the giant if-chain in ``daemon/ws_server.py``: each handler is a small
callable, registered by name, mostly just translating arg strings into
calls into existing daemon surfaces. New commands land in this file
and the WS server's dispatch loop is unchanged.

Handler contract:

    async def handler(arg: str, ctx: SlashContext) -> dict

The returned dict is the WebSocket response envelope. ``ctx`` carries
the shared daemon objects (DB, budget, mode_state, KB) so each handler
can reach what it needs without re-importing module globals.

Adding a slash command:

  1. Write an ``async def cmd_<name>(arg: str, ctx: SlashContext) -> dict``
  2. Add ``"<name>": cmd_<name>`` to ``HANDLERS``.
  3. (Optional) Update the help text in ``cmd_help``.

There is no client-side state — the WS server treats slash commands
identically to other JSON messages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .budget import BudgetController
from .db import ForgeDB
from .memory.knowledge import KnowledgeBase
from .mode import InvalidMode, ModeState

logger = logging.getLogger(__name__)


@dataclass
class SlashContext:
    """Bundle of daemon objects passed to every slash handler.

    Field-by-field rather than ``**kwargs`` so handlers get type help
    and the contract is auditable. Add fields here when a handler
    needs a new shared resource.
    """

    db: ForgeDB
    budget: BudgetController
    mode_state: ModeState
    kb: KnowledgeBase


# ──────────────────────────────────────────────────────────────────────
#  Handlers
# ──────────────────────────────────────────────────────────────────────


HELP_TEXT = (
    "Available slash commands:\n"
    "  /help                       Show this help\n"
    "  /clear                      Clear the output stream (client-side)\n"
    "  /mode <name>                Set mode: auto / accept_edits / plan / ask / bypass\n"
    "  /model <name>               Switch the next-plan default model\n"
    "  /memory                     Show KB summary\n"
    "  /memory search <query>      Search the knowledge base\n"
    "  /memory add <cat> <topic> <content>\n"
    "                              Add a knowledge item\n"
    "  /budget                     Show spend totals\n"
    "  /connectors                 List pinned connectors\n"
    "  /skills                     List pinned skills\n"
    "  /llms                       List installed LLM adapters\n"
    "  /wizard                     Hint for the connector setup wizard\n"
    "  /quit                       Exit the TUI (client-side)"
)


async def cmd_help(arg: str, ctx: SlashContext) -> dict:
    return {"type": "slash_help", "text": HELP_TEXT}


async def cmd_clear(arg: str, ctx: SlashContext) -> dict:
    """Pure UI-side command — daemon ack so the client doesn't surface
    'unknown slash command'. The client clears its own output buffer."""
    return {"type": "slash_ack", "command": "clear"}


async def cmd_quit(arg: str, ctx: SlashContext) -> dict:
    """Pure UI-side command — same shape as /clear."""
    return {"type": "slash_ack", "command": "quit"}


async def cmd_mode(arg: str, ctx: SlashContext) -> dict:
    """``/mode plan`` — same wiring as the explicit set_mode message,
    just typed in slash form. Empty arg returns the current mode."""
    arg = arg.strip()
    if not arg:
        return {"type": "mode_changed", "mode": ctx.mode_state.mode}
    try:
        new_mode = ctx.mode_state.set(arg)
    except InvalidMode as e:
        return {"type": "error", "error": str(e)}
    return {"type": "mode_changed", "mode": new_mode, "via": "slash"}


async def cmd_model(arg: str, ctx: SlashContext) -> dict:
    """Front-end model switch. The daemon doesn't enforce the choice
    here — actual routing happens at sprint creation in the classifier
    — but it does echo the choice so the UI status bar updates."""
    arg = arg.strip()
    if not arg:
        return {"type": "error", "error": "usage: /model <name>"}
    return {"type": "model_changed", "model": arg, "via": "slash"}


async def cmd_memory(arg: str, ctx: SlashContext) -> dict:
    """``/memory`` summary, ``/memory search <q>``, ``/memory add ...``."""
    parts = arg.strip().split(maxsplit=2)
    sub = parts[0] if parts else ""

    if not sub:
        return {
            "type": "knowledge_summary",
            "count": ctx.kb.count(),
            "items": ctx.kb.search(query="", limit=10),
        }

    if sub == "search":
        query = parts[1] if len(parts) > 1 else ""
        return {
            "type": "knowledge_results",
            "items": ctx.kb.search(query=query, limit=20),
        }

    if sub == "add":
        # Format: ``/memory add <category> <topic> <content...>``
        if len(parts) < 3:
            return {"type": "error", "error": "usage: /memory add <cat> <topic> <content>"}
        rest = parts[2].split(maxsplit=1)
        if len(rest) < 2:
            return {"type": "error", "error": "usage: /memory add <cat> <topic> <content>"}
        topic_and_content = rest[1].split(maxsplit=1)
        if len(topic_and_content) < 2:
            return {"type": "error", "error": "usage: /memory add <cat> <topic> <content>"}
        category = rest[0]
        topic, content = topic_and_content
        kid = ctx.kb.add(category, topic, content, "user", 0.8)
        return {"type": "knowledge_updated", "id": kid}

    return {"type": "error", "error": f"unknown /memory action: {sub!r}"}


async def cmd_budget(arg: str, ctx: SlashContext) -> dict:
    return {"type": "budget_status", **ctx.budget.to_dict()}


async def cmd_connectors(arg: str, ctx: SlashContext) -> dict:
    """List pinned connectors from the project's plugins.lock."""
    from pathlib import Path as _Path

    from .skills import PluginsLock, default_lock_path

    lock = PluginsLock(default_lock_path(_Path.cwd()))
    names = [
        key.split(":", 1)[1] for key in sorted(lock.all_entries()) if key.startswith("connector:")
    ]
    return {"type": "connectors_list", "names": names}


async def cmd_skills(arg: str, ctx: SlashContext) -> dict:
    from pathlib import Path as _Path

    from .skills import PluginsLock, default_lock_path

    lock = PluginsLock(default_lock_path(_Path.cwd()))
    names = [key.split(":", 1)[1] for key in sorted(lock.all_entries()) if key.startswith("skill:")]
    return {"type": "skills_list", "names": names}


async def cmd_llms(arg: str, ctx: SlashContext) -> dict:
    from .llms import list_llms

    names = [e.manifest.name for e in list_llms()]
    return {"type": "llms_list", "names": names}


async def cmd_wizard(arg: str, ctx: SlashContext) -> dict:
    """Browser-native wizard is Sprint 7 work. For now point the user at
    the terminal command. Same response shape as the legacy ``wizard``
    message for compatibility with existing clients."""
    return {
        "type": "wizard_hint",
        "message": "Open a terminal in this project and run: forge wizard",
    }


# Registry: command name → handler. Names match the slash command after
# the leading dot (``slash.mode`` → key ``"mode"``).
HANDLERS = {
    "help": cmd_help,
    "clear": cmd_clear,
    "quit": cmd_quit,
    "mode": cmd_mode,
    "model": cmd_model,
    "memory": cmd_memory,
    "budget": cmd_budget,
    "connectors": cmd_connectors,
    "skills": cmd_skills,
    "llms": cmd_llms,
    "wizard": cmd_wizard,
}


async def dispatch_slash(msg_type: str, arg: str, ctx: SlashContext) -> dict | None:
    """Resolve ``slash.<name>`` → handler call. Returns the response
    dict, or ``None`` if ``msg_type`` doesn't match a known slash command
    (caller falls back to its default unknown-message handling).

    Resolution order:
      1. Built-in commands (HANDLERS dict)
      2. Custom commands from ``.forge/commands/*.md`` and
         ``.claude/commands/*.md`` (Sprint 7.3 — user-defined)
      3. Unknown → structured error
    """
    if not msg_type.startswith("slash."):
        return None
    name = msg_type[len("slash.") :]

    handler = HANDLERS.get(name)
    if handler is not None:
        return await handler(arg or "", ctx)

    # Sprint 7.3: try the user's custom commands. We rediscover on each
    # call so dropped-in files take effect without restart — same UX as
    # Claude Code. Discovery cost is one directory listing.
    from pathlib import Path as _Path

    from .custom_commands import discover_commands, render

    custom = discover_commands(_Path.cwd()).get(name)
    if custom is not None:
        rendered = render(custom, arg or "")
        return {
            "type": "custom_command",
            "name": custom.name,
            "objective": rendered,
            "model": custom.model,
            "allowed_tools": custom.allowed_tools,
            "source": str(custom.source_path) if custom.source_path else "",
        }

    return {"type": "error", "error": f"unknown slash command: /{name}"}
