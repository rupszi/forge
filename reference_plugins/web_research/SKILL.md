# web_research

Fetch reference documentation from a small allow-list of trusted
sources. Use this when the planner / generator needs to look up an
API signature, deprecation notice, or migration guide that isn't in
the project's repomap or knowledge base.

## What this is NOT

Not a general-purpose web fetcher. The allow-list is narrow on
purpose:

- `*.python.org` — Python language docs
- `developer.mozilla.org` — MDN web reference
- `*.github.io` — project doc sites that publish via GitHub Pages
- `raw.githubusercontent.com` — raw README / RFC / docs files

Anything outside this list raises `CapabilityViolation` *before* a
packet hits the wire. The list is the manifest's contract; widening
it requires a re-approval prompt (Sprint 6.1.5).

## Calling pattern

    web_research <url>

The script fetches the URL via `forge_plugin_api.make_http_client()`
(which reads `FORGE_NETWORK_ALLOWLIST` from the env injected by the
dispatcher) and prints the response body to stdout. Non-2xx exits
non-zero with the status code.

## Trifecta classification

reads_untrusted = True (web content is by definition untrusted).
writes_external = True (egress to documented hosts).
reads_private = False (no secrets accessed).

Two of three legs of the trifecta. Composing this connector with one
that reads private data (e.g., a Stripe / Supabase MCP) in the same
session would trip the lethal-trifecta gate. That is by design: when
the model needs both web research AND a credentialed connector, the
user is prompted to choose which one is in scope for the sprint.
