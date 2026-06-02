"""Tests for the external-egress guard itself (G-LOC-1 safety net).

The guard is the load-bearing test utility for Forge Studio's local-first
promise. If it doesn't actually block external connections, every downstream
"this path is offline" assertion is worthless. So we test the guard hard.
"""

from __future__ import annotations

import socket

import pytest

from tests.egress_guard import ExternalEgressError, _is_local, assert_no_external_egress


class TestLocalClassification:
    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1", "127.0.0.5", "::1", "localhost", "0.0.0.0", "", "::ffff:127.0.0.1", None],
    )
    def test_local_hosts_pass(self, host):
        assert _is_local(host) is True

    @pytest.mark.parametrize(
        "host",
        ["8.8.8.8", "93.184.216.34", "api.anthropic.com", "example.com", "10.0.0.1", "192.168.1.5"],
    )
    def test_external_hosts_flagged(self, host):
        # Private LAN addresses count as external too — Forge's promise is
        # "stays on this machine", not "stays on this network".
        assert _is_local(host) is False


class TestGuardBlocksExternal:
    def test_create_connection_to_external_ip_raises(self):
        # A literal IP avoids DNS; the guard must raise on connect() before any
        # packet leaves. 203.0.113.0/24 is TEST-NET-3 (RFC 5737), never routable.
        with assert_no_external_egress():
            with pytest.raises(ExternalEgressError):
                socket.create_connection(("203.0.113.7", 80), timeout=0.05)

    def test_raw_socket_connect_to_external_raises(self):
        with assert_no_external_egress():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                with pytest.raises(ExternalEgressError):
                    s.connect(("198.51.100.23", 443))  # TEST-NET-2
            finally:
                s.close()

    def test_connect_ex_to_external_raises(self):
        with assert_no_external_egress():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                with pytest.raises(ExternalEgressError):
                    s.connect_ex(("198.51.100.24", 443))
            finally:
                s.close()


class TestGuardAllowsLocal:
    def test_loopback_connection_passes_through(self):
        # Stand up a real listener on loopback; connecting to it inside the
        # guard must succeed (proves local traffic reaches the real connect()).
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            with assert_no_external_egress():
                client = socket.create_connection(("127.0.0.1", port), timeout=1.0)
                client.close()
        finally:
            server.close()

    def test_loopback_to_closed_port_is_refused_not_blocked(self):
        # Connecting to a closed *local* port must surface the OS error
        # (ConnectionRefused), NOT ExternalEgressError — proving the guard let
        # it through to the real stack.
        with assert_no_external_egress():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            try:
                with pytest.raises(OSError) as exc:
                    s.connect(("127.0.0.1", 1))  # port 1 closed for normal users
                assert not isinstance(exc.value, ExternalEgressError)
            finally:
                s.close()


class TestGuardRestores:
    def test_originals_restored_after_block(self):
        before_connect = socket.socket.connect
        before_connect_ex = socket.socket.connect_ex
        with assert_no_external_egress():
            assert socket.socket.connect is not before_connect
        assert socket.socket.connect is before_connect
        assert socket.socket.connect_ex is before_connect_ex

    def test_originals_restored_after_exception(self):
        before = socket.socket.connect
        with pytest.raises(ValueError):
            with assert_no_external_egress():
                raise ValueError("boom")
        assert socket.socket.connect is before
