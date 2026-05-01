"""WebSocket client for the TUI.

Mirrors what ``ui/hooks/useForgeSocket.ts`` does on the browser side:
connects to ws://127.0.0.1:9111, dispatches typed messages, exposes a
send() function.

The TUI uses an asyncio.Queue per consumer so multiple screens can
subscribe to the same event stream without losing messages — Textual's
``post_message`` system handles fan-out from queue → widgets.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

logger = logging.getLogger(__name__)

DEFAULT_WS_URL = "ws://127.0.0.1:9111"


class ForgeWSClient:
    """Async WebSocket client.

    Usage::

        client = ForgeWSClient()
        client.subscribe("project_context", on_context)
        await client.connect()
        await client.send({"type": "init", "path": "."})

    The client auto-reconnects on disconnect with exponential backoff
    capped at 30s — important because users will frequently restart the
    daemon during development.
    """

    def __init__(self, url: str = DEFAULT_WS_URL):
        self.url = url
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._handlers: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}
        self._connected = False
        self._stop = False
        self._reconnect_delay = 1.0

    @property
    def connected(self) -> bool:
        return self._connected

    def subscribe(self, msg_type: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        """Register an async handler for messages of the given type.

        Multiple handlers per type are allowed; they fire in registration
        order. Wildcard ``"*"`` receives every message.
        """
        self._handlers.setdefault(msg_type, []).append(handler)

    async def send(self, message: dict[str, Any]) -> None:
        """Send a message. Silently drops if not connected (no buffering
        — matches the browser client's semantics)."""
        if self._ws is None or not self._connected:
            return
        try:
            await self._ws.send(json.dumps(message))
        except (ConnectionClosed, OSError) as e:
            logger.warning("ws send failed: %s", e)
            self._connected = False

    async def connect(self) -> None:
        """Run the connection loop forever (or until stop() is called).

        Auto-reconnects with exponential backoff. Caller usually wraps
        in asyncio.create_task / Textual's run_worker.
        """
        while not self._stop:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._reconnect_delay = 1.0
                    await self._dispatch({"type": "ws_connected"})
                    await self._receive_loop(ws)
            except (ConnectionClosed, ConnectionRefusedError, InvalidStatus, OSError) as e:
                self._connected = False
                self._ws = None
                await self._dispatch({"type": "ws_disconnected", "error": str(e)})
                logger.debug("ws connect failed: %s; retry in %.1fs", e, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                # Exponential backoff cap at 30s
                self._reconnect_delay = min(30.0, self._reconnect_delay * 1.5)

    async def _receive_loop(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning("ws bad JSON: %s", e)
                continue
            await self._dispatch(msg)

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type", "")
        # Specific handlers first, then wildcards
        for handler in self._handlers.get(msg_type, []):
            with suppress(Exception):
                await handler(msg)
        for handler in self._handlers.get("*", []):
            with suppress(Exception):
                await handler(msg)

    def stop(self) -> None:
        self._stop = True
