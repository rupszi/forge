"""External-egress guard for Forge Studio's local-first guarantee (G-LOC-1).

A context manager that patches the socket layer so any attempt to open a
connection to a non-loopback address raises ``ExternalEgressError``. Tests wrap
the *default* code path in it to prove Forge makes no outbound inference calls
unless the user opts into cloud.

This is a testing utility (not collected by pytest — filename does not start
with ``test_``). Import it explicitly:

    from tests.egress_guard import assert_no_external_egress, ExternalEgressError

Loopback (``127.0.0.0/8``, ``::1``, ``localhost``) and AF_UNIX sockets pass
through to the real ``connect``; everything else is blocked before a packet
leaves the machine.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import contextmanager

# Hostnames/addresses considered local. ``0.0.0.0`` and ``""`` are bind-side
# sentinels that never represent an outbound destination in practice.
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "", "::ffff:127.0.0.1"}


class ExternalEgressError(AssertionError):
    """Raised when code under ``assert_no_external_egress`` tries to dial out."""


def _is_local(host: object) -> bool:
    if host is None:
        return True
    h = str(host)
    if h in _LOCAL_HOSTS:
        return True
    # IPv4 loopback block 127.0.0.0/8 and IPv4-mapped IPv6 form.
    return h.startswith("127.") or h.startswith("::ffff:127.")


def _extract_host(address: object) -> object:
    if isinstance(address, tuple) and address:
        return address[0]
    return address


@contextmanager
def assert_no_external_egress() -> Iterator[None]:
    """Block (and surface) any non-local socket connection inside the block.

    AF_UNIX connections and loopback TCP/UDP are allowed through to the real
    implementation so legitimate local IPC (the daemon's own WS, Ollama on
    ``localhost``) keeps working.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(sock: socket.socket, address: object) -> None:
        if getattr(sock, "family", None) == socket.AF_UNIX:
            return
        host = _extract_host(address)
        if not _is_local(host):
            raise ExternalEgressError(
                f"external network egress to {address!r} blocked on the local-first path"
            )

    def guard(self: socket.socket, address: object):  # type: ignore[no-untyped-def]
        _check(self, address)
        return real_connect(self, address)

    def guard_ex(self: socket.socket, address: object):  # type: ignore[no-untyped-def]
        _check(self, address)
        return real_connect_ex(self, address)

    socket.socket.connect = guard  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = guard_ex  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
