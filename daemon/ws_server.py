"""WebSocket server for UI communication. Binds to 127.0.0.1 ONLY.

Hardened (Task 1.4) against misbehaving local clients via three guards:

  1. Per-client sliding-window rate limiter (10 msg/sec).
  2. 1 MB raw-message cap (rejected before json.loads).
  3. ``init`` path validated against the user's home / cwd to prevent a
     buggy or hostile client from triggering arbitrary file-system scans.

These are belt-and-suspenders given the 127.0.0.1 bind, but a buggy UI
tab or future change-of-bind shouldn't be able to OOM the daemon.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque

import websockets

from .budget import BudgetController
from .config import WS_HOST, WS_PORT
from .db import ForgeDB
from .locality import locality_state
from .memory.knowledge import KnowledgeBase
from .mode import InvalidMode, ModeState
from .models import ProjectContext
from .scanner.project import scan_project

logger = logging.getLogger(__name__)

_clients: set = set()

# Sprint 6.2: process-wide mode state. The WS server mutates it via
# ``set_mode``; the scheduler reads it at session start; the TUI / UI
# subscribe to ``mode_changed`` events to keep their status bars in sync.
# Single instance — Forge is single-tenant by design (ADR-007).
_mode_state = ModeState()


def get_mode_state() -> ModeState:
    """Public accessor for the daemon's mode state singleton.

    Used by ``cmd_serve`` to thread the same instance into
    ``scheduler.execute_session`` so UI flips propagate to running waves.
    """
    return _mode_state


# ---- Per-client rate limiting + size cap (Task 1.4) ----
#
# We key on ``id(ws)`` rather than peer address: same-host connections all
# show 127.0.0.1 anyway. Each client gets a deque of monotonic timestamps;
# if 10 messages land within 1 s the 11th is rejected. The deque self-prunes
# old entries on each check.

_RATE_LIMIT_WINDOW_SEC = 1.0
_RATE_LIMIT_MAX_MSG = 10
_MAX_MESSAGE_BYTES = 1_000_000  # 1 MB
_client_msg_times: dict[int, deque] = defaultdict(lambda: deque(maxlen=_RATE_LIMIT_MAX_MSG))


# Sprint 9 / Layer 10: Origin header allow-list.
#
# The WebSocket bind is loopback-only (ADR-013), but a malicious page
# the user visits can still attempt cross-site WebSocket hijacking by
# loading ws://127.0.0.1:9111 from a different origin. The browser
# sends an Origin header for cross-origin requests; an empty Origin
# (CLI / TUI) is allowed because non-browser clients never send one.
#
# Allowed origins:
#   - http://localhost:3000         (Next.js dev server)
#   - http://127.0.0.1:3000         (same, IP form)
#   - http://localhost:<any>        (custom dev port)
#   - http://127.0.0.1:<any>        (same, IP form)
#   - "" or None                    (CLI / TUI / non-browser)
#
# Anything else (https://attacker.com that loads localhost in an
# iframe / fetches via WS) is rejected with code 4403 (custom close,
# Forge-specific) before any messages flow.
_ALLOWED_ORIGIN_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1")


def _origin_allowed(origin: str | None) -> bool:
    """Return True iff the connection's Origin header passes the allow-list.

    Empty / None / missing Origin = allowed (CLI / TUI / non-browser).
    Browser-issued WS handshakes always include an Origin so the test
    is "is the origin a localhost variant?" rather than "is there one?".
    """
    if not origin:
        return True
    # Origin header format: ``<scheme>://<host>[:<port>]`` (no path).
    # Split off the scheme and verify the host part is a localhost variant.
    if "://" not in origin:
        return False
    _, _, hostport = origin.partition("://")
    host = hostport.split(":", 1)[0]
    return host in _ALLOWED_ORIGIN_HOSTS


# Task 2.3: cap concurrent message handlers so a flood of cheap requests
# from one tab can't starve the daemon's CPU. With 10 in flight at once,
# each over-budget request waits its turn rather than spawning unbounded
# coroutines. Per-message rate limit (above) is the first line; this
# semaphore is the second.
_MAX_CONCURRENT_HANDLERS = 10
_message_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_HANDLERS)


def _rate_limit_check(client_id: int) -> bool:
    """Return True if the client is within its rate budget; False if over.

    Sliding-window: drop entries older than the window before counting.
    Constant-time per call (deque pops cheaply from the left).
    """
    now = time.monotonic()
    times = _client_msg_times[client_id]
    while times and times[0] < now - _RATE_LIMIT_WINDOW_SEC:
        times.popleft()
    if len(times) >= _RATE_LIMIT_MAX_MSG:
        return False
    times.append(now)
    return True


def _validate_init_path(path: str) -> bool:
    """Ensure an ``init`` path stays inside the user's permitted scope.

    A path is permitted if it sits under the user's home directory or under
    the current working directory. Anything else (``/etc``, ``/var``, etc.)
    is rejected even though the bind is loopback — defense in depth against
    a buggy UI walking the filesystem.
    """
    abs_path = os.path.normpath(os.path.abspath(path))
    home = os.path.abspath(os.path.expanduser("~"))
    cwd = os.path.abspath(".")
    return (
        abs_path == home
        or abs_path.startswith(home + os.sep)
        or (abs_path == cwd or abs_path.startswith(cwd + os.sep))
    )


def broadcast(message: dict) -> None:
    """Send a message to all connected clients."""
    data = json.dumps(message)
    for ws in list(_clients):
        try:
            asyncio.ensure_future(ws.send(data))
        except Exception:
            _clients.discard(ws)


async def _handle_message(
    ws, message: str, db: ForgeDB, ctx: ProjectContext | None, budget: BudgetController
) -> dict:
    """Handle a single WebSocket message. Returns response dict."""
    # Concurrency cap (Task 2.3): only N handlers run simultaneously across
    # all clients. Excess waits in line — preferable to an unbounded fan-out
    # that could exhaust descriptors / DB connections.
    async with _message_semaphore:
        return await _handle_message_inner(ws, message, db, ctx, budget)


async def _handle_message_inner(
    ws, message: str, db: ForgeDB, ctx: ProjectContext | None, budget: BudgetController
) -> dict:
    """Inner handler — runs under the message semaphore."""
    # Size cap: reject before json.loads so a 100MB JSON blob doesn't OOM
    # the parser. Counted on the raw frame, not post-decode bytes.
    if len(message) > _MAX_MESSAGE_BYTES:
        return {
            "type": "error",
            "error": f"message exceeds {_MAX_MESSAGE_BYTES // 1000}KB cap",
        }

    # Rate limit: 10 messages / 1 s sliding window per client.
    if not _rate_limit_check(id(ws)):
        return {"type": "error", "error": "rate limit exceeded (10 msg/sec)"}

    try:
        msg = json.loads(message)
    except json.JSONDecodeError:
        return {"type": "error", "error": "Invalid JSON"}

    msg_type = msg.get("type", "")
    kb = KnowledgeBase(db)

    if msg_type == "init":
        path = msg.get("path", ".")
        # Path validation: prevent traversal / scanning outside home or cwd.
        if not _validate_init_path(path):
            return {"type": "error", "error": "path outside permitted scope"}
        ctx = await scan_project(path)
        # Sprint 6.0.1: daemon-side billing-tier detection. The UI uses
        # this instead of inferring tier from model names client-side.
        from .billing import detect_tier

        return {
            "type": "project_context",
            **ctx.to_dict(),
            "knowledge_count": kb.count(),
            "billing_tier": detect_tier(path),
            "locality": locality_state(),
        }

    if msg_type == "status":
        return {
            "type": "status",
            "sessions": db.list_sessions(limit=5),
            "knowledge_count": kb.count(),
            "budget": budget.to_dict(),
            "table_counts": db.table_counts(),
            "locality": locality_state(),
        }

    if msg_type == "locality":
        return locality_state()

    if msg_type == "pool":
        from .pool import active_pool_state

        return active_pool_state()

    if msg_type == "plan":
        objective = msg.get("objective", "")
        if not objective:
            return {"type": "error", "error": "No objective provided"}
        # Planning is handled by the scheduler — just acknowledge
        return {"type": "plan_acknowledged", "objective": objective}

    if msg_type == "search_knowledge":
        query = msg.get("query", "")
        results = kb.search(query=query, limit=20)
        return {"type": "knowledge_results", "items": results}

    if msg_type == "add_knowledge":
        from .memory.kb_guard import KBContentRejected

        try:
            kid = kb.add(
                category=msg.get("category", "gotcha"),
                topic=msg.get("topic", "general"),
                content=msg.get("content", ""),
                source="user",
                confidence=0.8,
            )
        except KBContentRejected as e:
            return {"type": "error", "error": f"knowledge rejected: {e}"}
        return {"type": "knowledge_updated", "id": kid}

    if msg_type == "delete_knowledge":
        kb.delete(msg.get("item_id", 0))
        return {"type": "knowledge_updated", "deleted": True}

    if msg_type == "get_sessions":
        sessions = db.list_sessions(limit=msg.get("limit", 20))
        return {"type": "sessions_list", "sessions": sessions}

    # ── Claude-Code-style UI message handlers ──
    #
    # The new dashboard surfaces (mode picker, slash palette, attach menu,
    # transcript view) all dispatch through here. Each handler is small —
    # the heavy lifting lives in daemon/scheduler.py / daemon/safety.py /
    # daemon/skills/.

    if msg_type == "set_mode":
        # Sprint 6.2: process-wide ModeState. ``plan`` causes the scheduler
        # to skip the wave loop, ``ask`` injects an addendum into the
        # generator prompt, ``bypass`` logs an audit warning. Unknown modes
        # are rejected explicitly rather than silently falling back, so a
        # buggy UI surfaces the mistake instead of running with the wrong mode.
        try:
            new_mode = _mode_state.set(msg.get("mode", "auto"))
        except InvalidMode as e:
            return {"type": "error", "error": str(e)}
        # Broadcast so other connected clients (TUI alongside the browser)
        # update their status bars in lockstep.
        broadcast({"type": "mode_changed", "mode": new_mode})
        return {"type": "mode_changed", "mode": new_mode}

    if msg_type == "set_model":
        # Front-end model switch. The actual routing happens at sprint
        # creation time — this just records the user's preference for the
        # next plan.
        return {"type": "model_changed", "model": msg.get("model", "")}

    if msg_type == "connectors.list":
        from .connectors import ConnectorRegistry

        reg = ConnectorRegistry()
        names = [e.manifest.name for e in reg.list_all()]
        return {"type": "connectors_list", "names": names}

    if msg_type == "skills.list":
        from .skills.registry import DEFAULT_SKILL_ROOT

        names: list[str] = []
        if DEFAULT_SKILL_ROOT.is_dir():
            names = [p.name for p in DEFAULT_SKILL_ROOT.iterdir() if p.is_dir()]
        return {"type": "skills_list", "names": names}

    if msg_type == "llms.list":
        from .llms import list_llms

        names = [e.manifest.name for e in list_llms()]
        return {"type": "llms_list", "names": names}

    if msg_type.startswith("slash."):
        # Sprint 6.3: real handlers in daemon/slash.py. Each command
        # is a small async callable registered in slash.HANDLERS;
        # dispatch_slash returns the response dict directly. Unknown
        # slash commands surface a clear error instead of falling
        # through to the generic "unknown message type" path so the UI
        # can distinguish typos from genuinely unsupported messages.
        from .slash import SlashContext, dispatch_slash

        slash_ctx = SlashContext(
            db=db,
            budget=budget,
            mode_state=_mode_state,
            kb=kb,
        )
        result = await dispatch_slash(msg_type, msg.get("args", ""), slash_ctx)
        if result is not None:
            return result

    if msg_type == "wizard":
        # The CLI handles the interactive wizard; from the browser we just
        # return a hint pointing the user at the terminal command. A
        # browser-native wizard (with form-based capability picking) is
        # Sprint 7 work.
        return {
            "type": "wizard_hint",
            "message": "Open a terminal in this project and run: forge wizard",
        }

    if msg_type in ("attach.files", "attach.folder", "connector.activate", "plugins.gallery"):
        # Stub acknowledgement — full plumbing is Sprint 6+. This avoids
        # the "Unknown message type" error so the UI doesn't surface
        # red text for actions that aren't wired yet.
        return {"type": "ack", "command": msg_type}

    return {"type": "error", "error": f"Unknown message type: {msg_type}"}


async def _handler(ws, path, db: ForgeDB, budget: BudgetController):
    """Handle a WebSocket connection."""
    # Sprint 9 / Layer 10: cross-site WebSocket hijack defense. Reject
    # any handshake whose Origin isn't a localhost variant. Non-browser
    # clients (CLI / TUI) don't send Origin so they pass through.
    origin = None
    try:
        # websockets >=10 exposes request_headers; older fall back to
        # request.headers. Be defensive against both shapes.
        headers = getattr(ws, "request_headers", None) or getattr(
            getattr(ws, "request", None), "headers", {}
        )
        if hasattr(headers, "get"):
            origin = headers.get("Origin") or headers.get("origin")
    except Exception:  # never let header introspection crash a connection
        origin = None

    if not _origin_allowed(origin):
        logger.warning("rejecting WS connection from disallowed Origin: %r", origin)
        await ws.close(code=4403, reason="origin not allowed")
        return

    _clients.add(ws)
    ctx = None
    try:
        async for message in ws:
            response = await _handle_message(ws, message, db, ctx, budget)
            await ws.send(json.dumps(response, default=str))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _clients.discard(ws)
        # Reclaim the rate-limit deque so long-lived servers don't leak
        # memory when many short-lived UI tabs connect and disconnect.
        _client_msg_times.pop(id(ws), None)


async def start_server(
    db: ForgeDB,
    budget: BudgetController,
    *,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Start the WebSocket server. Binds to 127.0.0.1 ONLY.

    Parameters
    ----------
    shutdown_event
        Optional asyncio.Event. When set, the server stops accepting new
        connections, closes existing ones with code 1001 (going away),
        waits for in-flight handlers, then returns. Wired by ``cmd_serve``
        on SIGTERM/SIGINT (Task 1.7).
    """
    if shutdown_event is None:
        shutdown_event = asyncio.Event()

    handler = lambda ws, path: _handler(ws, path, db, budget)
    server = await websockets.serve(handler, WS_HOST, WS_PORT)
    logger.info("WebSocket server running on ws://%s:%d", WS_HOST, WS_PORT)

    try:
        await shutdown_event.wait()
    finally:
        logger.info("Shutting down WebSocket server...")
        # Close existing connections gracefully (code 1001 = going away).
        await asyncio.gather(
            *(ws.close(code=1001, reason="server shutdown") for ws in list(_clients)),
            return_exceptions=True,
        )
        server.close()
        await server.wait_closed()
        logger.info("WebSocket server stopped cleanly.")
