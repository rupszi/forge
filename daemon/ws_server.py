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
from .memory.knowledge import KnowledgeBase
from .models import ProjectContext
from .scanner.project import scan_project

logger = logging.getLogger(__name__)

_clients: set = set()


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
        return {
            "type": "project_context",
            **ctx.to_dict(),
            "knowledge_count": kb.count(),
        }

    if msg_type == "status":
        return {
            "type": "status",
            "sessions": db.list_sessions(limit=5),
            "knowledge_count": kb.count(),
            "budget": budget.to_dict(),
            "table_counts": db.table_counts(),
        }

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
        kid = kb.add(
            category=msg.get("category", "gotcha"),
            topic=msg.get("topic", "general"),
            content=msg.get("content", ""),
            source="user",
            confidence=0.8,
        )
        return {"type": "knowledge_updated", "id": kid}

    if msg_type == "delete_knowledge":
        kb.delete(msg.get("item_id", 0))
        return {"type": "knowledge_updated", "deleted": True}

    if msg_type == "get_sessions":
        sessions = db.list_sessions(limit=msg.get("limit", 20))
        return {"type": "sessions_list", "sessions": sessions}

    return {"type": "error", "error": f"Unknown message type: {msg_type}"}


async def _handler(ws, path, db: ForgeDB, budget: BudgetController):
    """Handle a WebSocket connection."""
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
