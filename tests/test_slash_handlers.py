"""Slash-command handler tests (Sprint 6.3).

Slash commands flow through the WS server as ``{type: "slash.<cmd>"}``
messages. Each command is a small async callable registered in
``daemon/slash.py``. These tests cover the full registry — every
command in HANDLERS gets at least one happy-path test plus the
relevant error-path coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from daemon.budget import BudgetController
from daemon.db import ForgeDB
from daemon.memory.knowledge import KnowledgeBase
from daemon.mode import ModeState
from daemon.slash import HANDLERS, SlashContext, dispatch_slash


@pytest.fixture
def ctx(tmp_path: Path) -> SlashContext:
    db = ForgeDB(str(tmp_path / "forge.db"))
    return SlashContext(
        db=db,
        budget=BudgetController(),
        mode_state=ModeState(),
        kb=KnowledgeBase(db),
    )


# ---- registry shape ----


def test_handlers_registered() -> None:
    """Every command the docs and TUI advertise has a handler."""
    expected = {
        "help",
        "clear",
        "quit",
        "mode",
        "model",
        "memory",
        "budget",
        "connectors",
        "skills",
        "llms",
        "wizard",
    }
    assert expected.issubset(set(HANDLERS.keys()))


# ---- dispatch_slash routing ----


@pytest.mark.asyncio
async def test_dispatch_returns_none_for_non_slash(ctx: SlashContext) -> None:
    """Non-slash message types return None so the caller's normal
    handler chain continues."""
    result = await dispatch_slash("set_mode", "", ctx)
    assert result is None


@pytest.mark.asyncio
async def test_dispatch_unknown_slash_returns_error(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.megamax", "", ctx)
    assert result is not None
    assert result["type"] == "error"
    assert "unknown slash command" in result["error"]


# ---- /help ----


@pytest.mark.asyncio
async def test_help_lists_all_commands(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.help", "", ctx)
    assert result["type"] == "slash_help"
    text = result["text"]
    for cmd in ("help", "clear", "mode", "model", "memory", "budget"):
        assert f"/{cmd}" in text


# ---- /clear, /quit (UI-side acks) ----


@pytest.mark.asyncio
async def test_clear_acks(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.clear", "", ctx)
    assert result == {"type": "slash_ack", "command": "clear"}


@pytest.mark.asyncio
async def test_quit_acks(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.quit", "", ctx)
    assert result == {"type": "slash_ack", "command": "quit"}


# ---- /mode ----


@pytest.mark.asyncio
async def test_mode_no_arg_returns_current(ctx: SlashContext) -> None:
    ctx.mode_state.set("ask")
    result = await dispatch_slash("slash.mode", "", ctx)
    assert result == {"type": "mode_changed", "mode": "ask"}


@pytest.mark.asyncio
async def test_mode_with_arg_updates(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.mode", "plan", ctx)
    assert result["type"] == "mode_changed"
    assert result["mode"] == "plan"
    assert ctx.mode_state.mode == "plan"


@pytest.mark.asyncio
async def test_mode_unknown_returns_error_state_unchanged(ctx: SlashContext) -> None:
    ctx.mode_state.set("auto")
    result = await dispatch_slash("slash.mode", "evil", ctx)
    assert result["type"] == "error"
    assert ctx.mode_state.mode == "auto"


# ---- /model ----


@pytest.mark.asyncio
async def test_model_arg_required(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.model", "", ctx)
    assert result["type"] == "error"
    assert "usage" in result["error"]


@pytest.mark.asyncio
async def test_model_echoes_choice(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.model", "qwen3-coder-next", ctx)
    assert result == {
        "type": "model_changed",
        "model": "qwen3-coder-next",
        "via": "slash",
    }


# ---- /memory ----


@pytest.mark.asyncio
async def test_memory_summary_default(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.memory", "", ctx)
    assert result["type"] == "knowledge_summary"
    assert "count" in result
    assert "items" in result


@pytest.mark.asyncio
async def test_memory_search(ctx: SlashContext) -> None:
    """KB search matches against content (not topic) — the slash handler
    surfaces whatever ``kb.search`` returns."""
    ctx.kb.add("gotcha", "supabase", "RLS needs service_role bypass for admin")
    result = await dispatch_slash("slash.memory", "search service_role", ctx)
    assert result["type"] == "knowledge_results"
    assert any("service_role" in (it.get("content") or "") for it in result["items"])


@pytest.mark.asyncio
async def test_memory_add_persists(ctx: SlashContext) -> None:
    result = await dispatch_slash(
        "slash.memory",
        "add gotcha next.js use server is required for server actions",
        ctx,
    )
    assert result["type"] == "knowledge_updated"
    # Round-trip check
    rows = ctx.kb.search(query="server actions")
    assert any("server actions" in r["content"] for r in rows)


@pytest.mark.asyncio
async def test_memory_add_usage_error(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.memory", "add only-one-arg", ctx)
    assert result["type"] == "error"
    assert "usage" in result["error"]


# ---- /budget ----


@pytest.mark.asyncio
async def test_budget_returns_status(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.budget", "", ctx)
    assert result["type"] == "budget_status"
    # to_dict from BudgetController exposes spent_usd and budget_usd
    assert "spent_usd" in result or "budget_usd" in result


# ---- /connectors, /skills, /llms ----


@pytest.mark.asyncio
async def test_connectors_lists_from_lock(ctx: SlashContext, tmp_path: Path, monkeypatch) -> None:
    """Lists connector entries from the project's plugins.lock."""
    monkeypatch.chdir(tmp_path)
    from daemon.skills import PluginsLock, default_lock_path

    lock = PluginsLock(default_lock_path(tmp_path))
    lock.pin("connector", "github", sha256="a" * 64, version="0.1.0")
    lock.pin("connector", "vercel", sha256="b" * 64, version="0.1.0")
    lock.pin("skill", "scribe", sha256="c" * 64)  # should NOT show up
    (tmp_path / ".forge").mkdir(exist_ok=True)
    lock.save()

    result = await dispatch_slash("slash.connectors", "", ctx)
    assert result["type"] == "connectors_list"
    assert set(result["names"]) == {"github", "vercel"}


@pytest.mark.asyncio
async def test_skills_lists_from_lock(ctx: SlashContext, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    from daemon.skills import PluginsLock, default_lock_path

    lock = PluginsLock(default_lock_path(tmp_path))
    lock.pin("skill", "csv-cleaner", sha256="d" * 64)
    lock.pin("connector", "x", sha256="e" * 64)
    (tmp_path / ".forge").mkdir(exist_ok=True)
    lock.save()

    result = await dispatch_slash("slash.skills", "", ctx)
    assert result["type"] == "skills_list"
    assert result["names"] == ["csv-cleaner"]


@pytest.mark.asyncio
async def test_llms_returns_list(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.llms", "", ctx)
    assert result["type"] == "llms_list"
    assert "names" in result


# ---- /wizard ----


@pytest.mark.asyncio
async def test_wizard_returns_terminal_hint(ctx: SlashContext) -> None:
    result = await dispatch_slash("slash.wizard", "", ctx)
    assert result["type"] == "wizard_hint"
    assert "forge wizard" in result["message"]


# ---- WS server end-to-end ----


@pytest.mark.asyncio
async def test_ws_server_routes_slash_through_dispatcher(tmp_path: Path) -> None:
    """The WS server's _handle_message_inner now defers to slash.dispatch_slash
    for any ``slash.<name>`` message. Verify the routing actually fires."""
    from daemon.ws_server import _handle_message_inner

    db = ForgeDB(str(tmp_path / "forge.db"))
    budget = BudgetController()

    msg = json.dumps({"type": "slash.help", "args": ""})
    response = await _handle_message_inner(object(), msg, db, None, budget)
    assert response["type"] == "slash_help"

    # Unknown slash → structured error (not the generic 'unknown message')
    msg = json.dumps({"type": "slash.megamax", "args": ""})
    response = await _handle_message_inner(object(), msg, db, None, budget)
    assert response["type"] == "error"
    assert "unknown slash command" in response["error"]
    db.close()
