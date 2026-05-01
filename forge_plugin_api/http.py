"""Egress-filtering ``httpx.AsyncClient`` shim for plugins.

Layer 6 of the seven-layer security model (docs/SKILLS.md): plugins must
not be able to reach hosts they did not declare in their manifest's
``[capabilities].network`` list. The runtime exports the allow-list via
the ``FORGE_NETWORK_ALLOWLIST`` env var (set by
``daemon/skills/runtime.py::run_skill``); this module reads that env var
inside the spawned subprocess and refuses any request to a non-listed
host.

Plugin authors use the public factory:

    from forge_plugin_api.http import make_http_client, CapabilityViolation

    async def fetch_thing(url: str) -> str:
        async with make_http_client() as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text

If ``url`` is not on the allow-list, ``client.get(...)`` raises
``CapabilityViolation`` *before* the network call fires — there is no
attempt-then-fail; the request is rejected at composition time.

Allow-list entry shapes (set by the manifest):

  - bare hostname:    ``api.github.com``
  - URL with scheme:  ``https://api.github.com`` (scheme + host required to match)
  - wildcard suffix:  ``*.github.com`` (matches any subdomain, not the apex)
  - full URL prefix:  ``https://api.github.com/v1/`` (path-prefix match)

Wildcard ``*`` alone is rejected by the manifest gate (see
``daemon/connectors/registry.py``); this module assumes a clean list.

The filter applies only to the ``http_client`` factory exported here. A
plugin that bypasses it (instantiates raw ``httpx.AsyncClient`` directly)
is a programming error; ``daemon/skills/runtime.py`` documents the
contract and the reference connectors all use this factory.

Threat model fit:
  - Defends against egress-based exfiltration when an LLM is steered into
    posting secrets to an attacker-controlled URL via a connector that
    *should* only talk to its declared API.
  - Defends against opportunistic plugin authors who declare a narrow
    allow-list at install time and then expand it via runtime input.
  - Does NOT defend against a malicious plugin that imports the raw
    ``httpx`` module and bypasses the factory — that's signed-manifest +
    audit-log territory (Layers 3 + 7).
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

__all__ = [
    "CapabilityViolation",
    "GuardedAsyncClient",
    "make_http_client",
    "parse_allowlist",
]


class CapabilityViolation(RuntimeError):
    """Raised when a plugin attempts an HTTP request outside its allow-list.

    Subclass of ``RuntimeError`` (not ``Exception``) so plugin code that
    does ``except Exception`` still catches it for cleanup, but tests can
    target the specific class. The message names the host and the active
    allow-list so debugging is direct.
    """


def parse_allowlist(raw: str | None) -> list[str]:
    """Parse the ``FORGE_NETWORK_ALLOWLIST`` env var into a clean list.

    Empty / unset returns ``[]`` (deny-all — the safe default for a
    plugin that declared no network capability).
    """
    if not raw:
        return []
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def _entry_matches(url: str, entry: str) -> bool:
    """Return True iff ``url`` is permitted by a single allow-list entry."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    scheme = parsed.scheme or ""

    # Full-URL prefix match (entry has scheme://...). Path-prefix-aware.
    if "://" in entry:
        # Trim trailing slash from entry for stable comparison; preserve
        # path-prefix semantics so "https://api.github.com/v1/" allows
        # "/v1/repos/..." but not "/v2/...".
        normalized_entry = entry.rstrip("/")
        normalized_url = url.split("?", 1)[0].rstrip("/")
        # Exact match OR url starts with entry + "/" so prefix can't
        # bleed into a different path.
        return normalized_url == normalized_entry or normalized_url.startswith(
            normalized_entry + "/"
        )

    # Wildcard suffix: "*.github.com" matches "api.github.com" but not "github.com"
    # itself (apex-domain entry must be listed explicitly to keep authorisation
    # surfaces narrow).
    if entry.startswith("*."):
        suffix = entry[1:]  # ".github.com"
        return host.endswith(suffix) and host != suffix.lstrip(".")

    # Bare hostname — exact match on host. Scheme is implicit (we assume
    # https; http requests still match on host but the runtime scheduler
    # is free to add a scheme-strict mode later via env var).
    return host == entry and scheme in ("https", "http", "")


def _is_allowed(url: str, allowlist: list[str]) -> bool:
    """Return True iff ``url`` matches at least one entry in ``allowlist``.

    Empty allow-list = deny-all. This is intentional: a plugin with
    ``[capabilities].network = []`` should not be able to make any HTTP
    request, even to localhost (data-exfil via DNS rebinding aside —
    that is Layer 5 territory).
    """
    if not allowlist:
        return False
    return any(_entry_matches(url, entry) for entry in allowlist)


class GuardedAsyncClient(httpx.AsyncClient):
    """``httpx.AsyncClient`` subclass that vetoes non-allowlisted requests.

    The veto fires in ``send()`` — every other entrypoint (``get``, ``post``,
    ``stream``, etc.) eventually calls ``send`` so this is the single
    interception point.
    """

    def __init__(self, allowlist: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._forge_allowlist = list(allowlist)

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        url = str(request.url)
        if not _is_allowed(url, self._forge_allowlist):
            host = request.url.host
            raise CapabilityViolation(
                f"plugin attempted egress to {host!r} ({url!r}); "
                f"not in allow-list {self._forge_allowlist}. "
                "Declare it in manifest.toml [capabilities].network and reload."
            )
        return await super().send(request, **kwargs)


def make_http_client(
    allowlist: list[str] | None = None,
    *,
    timeout: float = 30.0,
    **kwargs: Any,
) -> GuardedAsyncClient:
    """Public factory — returns a pre-configured ``GuardedAsyncClient``.

    ``allowlist`` defaults to ``parse_allowlist(os.environ["FORGE_NETWORK_ALLOWLIST"])``
    so plugin authors can call ``make_http_client()`` with no args and get
    the runtime-injected allow-list automatically. Pass an explicit list
    only in tests or when extending the surface for a single call site.
    """
    if allowlist is None:
        allowlist = parse_allowlist(os.environ.get("FORGE_NETWORK_ALLOWLIST"))
    return GuardedAsyncClient(allowlist=allowlist, timeout=timeout, **kwargs)
