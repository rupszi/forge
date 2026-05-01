"""WebSocket Origin allow-list tests (Sprint 9 / Layer 10).

The WebSocket bind is loopback-only, but a malicious page the user
visits can still attempt cross-site WebSocket hijacking by loading
ws://127.0.0.1:9111 from a different origin. The Origin header check
is the defense.
"""

from __future__ import annotations

from daemon.ws_server import _origin_allowed

# ---- allowed origins (browser-issued from localhost variants) ----


def test_localhost_with_port_allowed() -> None:
    assert _origin_allowed("http://localhost:3000") is True


def test_127_0_0_1_with_port_allowed() -> None:
    assert _origin_allowed("http://127.0.0.1:3000") is True


def test_localhost_other_port_allowed() -> None:
    """Custom dev ports — Vite, Astro, etc. — are fine. The bind is
    already loopback; we just verify the origin's HOST is a localhost
    variant."""
    assert _origin_allowed("http://localhost:5173") is True


def test_https_localhost_allowed() -> None:
    """Some dev setups run dev server over HTTPS (mkcert). The protocol
    doesn't matter for the host check."""
    assert _origin_allowed("https://localhost:3000") is True


# ---- non-browser clients (CLI / TUI / native) ----


def test_no_origin_allowed() -> None:
    """Non-browser WS clients don't send an Origin header — they're CLI /
    TUI / IDE plugins that the user explicitly launched."""
    assert _origin_allowed(None) is True
    assert _origin_allowed("") is True


# ---- rejected origins ----


def test_attacker_domain_rejected() -> None:
    """The headline attack: a malicious page tries to open a WS to
    127.0.0.1 from its own origin."""
    assert _origin_allowed("https://attacker.com") is False
    assert _origin_allowed("http://evil.example") is False


def test_subdomain_of_localhost_rejected() -> None:
    """``foo.localhost`` is NOT a localhost variant — it could be any
    DNS-rebinding target."""
    assert _origin_allowed("http://foo.localhost") is False


def test_lookalike_host_rejected() -> None:
    """``127.0.0.1.evil.com`` could trick a substring-match check —
    verify we host-strict-match."""
    assert _origin_allowed("http://127.0.0.1.evil.com:3000") is False


def test_path_in_origin_doesnt_confuse_check() -> None:
    """Origin headers must NOT include a path per RFC 6454 — but be
    defensive: a malformed Origin with a path shouldn't sneak through
    via the host extraction."""
    # Real Origin headers don't have paths, but some attacker may try.
    # Our parser splits on the first ``:`` of the host part, so a
    # path-bearing Origin is treated as scheme://host:port (path becomes
    # part of the port and the host check still rejects).
    assert _origin_allowed("http://attacker.com/127.0.0.1") is False


def test_malformed_origin_rejected() -> None:
    """Garbage Origin → reject. We don't try to be clever."""
    assert _origin_allowed("not-a-url") is False
    # An origin starting with "//" (no scheme) is malformed.
    assert _origin_allowed("//localhost:3000") is False


def test_empty_string_treated_as_no_origin() -> None:
    """Distinct from ``"http://"`` — empty string means the field was
    absent at the HTTP level, same as None."""
    assert _origin_allowed("") is True
