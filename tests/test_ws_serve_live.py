"""Regression: a real client must complete a WS round-trip through `serve()`.

The earlier tests exercised ``_handle_message`` directly and so missed a handler
*signature* mismatch with websockets ≥14 (the handler is called with one arg,
not ``(ws, path)``), which broke every real connection with a 1011 error. This
test stands up the actual server and connects a real client end-to-end.
"""

from __future__ import annotations

import asyncio
import json
import socket

import pytest
import websockets

from daemon import ws_server
from daemon.budget import BudgetController


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.asyncio
async def test_real_client_round_trip(tmp_db, monkeypatch):
    port = _free_port()
    monkeypatch.setattr(ws_server, "WS_PORT", port)

    stop = asyncio.Event()
    server_task = asyncio.create_task(
        ws_server.start_server(tmp_db, BudgetController(), shutdown_event=stop)
    )
    try:
        await asyncio.sleep(0.3)  # let the server bind
        async with websockets.connect(
            f"ws://127.0.0.1:{port}", origin="http://localhost:3000"
        ) as ws:
            # The exact messages the dashboard sends on connect.
            for mtype, expected in (
                ("locality", "locality"),
                ("pool", "pool_state"),
                ("status", "status"),
            ):
                await ws.send(json.dumps({"type": mtype}))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert resp["type"] == expected
    finally:
        stop.set()
        await asyncio.wait_for(server_task, timeout=5)


@pytest.mark.asyncio
async def test_disallowed_origin_is_rejected(tmp_db, monkeypatch):
    port = _free_port()
    monkeypatch.setattr(ws_server, "WS_PORT", port)
    stop = asyncio.Event()
    server_task = asyncio.create_task(
        ws_server.start_server(tmp_db, BudgetController(), shutdown_event=stop)
    )
    try:
        await asyncio.sleep(0.3)
        # A cross-site Origin must be refused (Layer 10 defense).
        with pytest.raises(websockets.exceptions.WebSocketException):
            async with websockets.connect(
                f"ws://127.0.0.1:{port}", origin="http://evil.example.com"
            ) as ws:
                await ws.send(json.dumps({"type": "locality"}))
                await asyncio.wait_for(ws.recv(), timeout=5)
    finally:
        stop.set()
        await asyncio.wait_for(server_task, timeout=5)
