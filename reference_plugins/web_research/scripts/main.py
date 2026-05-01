"""Reference web_research connector — fetch from an allow-listed URL.

The dispatcher injects ``FORGE_NETWORK_ALLOWLIST`` into the env for
this subprocess. ``forge_plugin_api.make_http_client()`` reads it and
returns a ``GuardedAsyncClient`` that vetoes any request to a host
outside the manifest's declared scope.

Healthcheck mode: invoking with no args prints the active allow-list
and exits 0 (proves the env arrived). The dispatcher uses this for
``forge connectors test web_research``.
"""

from __future__ import annotations

import asyncio
import os
import sys

# The plugin is spawned from the worktree (cwd == .forge/worktrees/<id>),
# but ``forge_plugin_api`` lives at the repo root. Tests / install scripts
# put it on PYTHONPATH; if not, we bail early with a clear message.
try:
    from forge_plugin_api import CapabilityViolation, make_http_client
except ImportError:
    sys.stderr.write(
        "web_research: cannot import forge_plugin_api. "
        "Set PYTHONPATH or `pip install -e .` in the daemon checkout.\n"
    )
    sys.exit(1)


async def fetch(url: str) -> int:
    async with make_http_client(timeout=30.0) as client:
        try:
            r = await client.get(url)
        except CapabilityViolation as e:
            sys.stderr.write(f"web_research: refused — {e}\n")
            return 2
        sys.stdout.write(r.text)
        if r.status_code >= 400:
            sys.stderr.write(f"web_research: HTTP {r.status_code}\n")
            return 3
        return 0


def main() -> int:
    if len(sys.argv) == 1:
        # Healthcheck — prove the env arrived. Exits 0 even if the
        # allow-list is empty; the manifest gate refuses empty network
        # capability *at install time*, so reaching the healthcheck
        # means the dispatcher's env wiring is working.
        allowlist = os.environ.get("FORGE_NETWORK_ALLOWLIST", "")
        sys.stdout.write(f"web_research healthcheck: allowlist={allowlist!r}\n")
        return 0

    if len(sys.argv) > 2:
        sys.stderr.write("web_research: usage: web_research <url>\n")
        return 1

    return asyncio.run(fetch(sys.argv[1]))


if __name__ == "__main__":
    sys.exit(main())
