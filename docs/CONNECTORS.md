# Forge Connectors — Tool Integrations

Forge connects to external tools via two complementary mechanisms:

1. **MCP-first** — anything with an MCP server (Anthropic's Model Context Protocol) is one config line. Forge auto-discovers MCP servers from your `.claude/settings.json`.
2. **Native plugins** — for tools that don't ship an MCP server (or where MCP can't express the integration cleanly), Forge supports Python connectors with declared capabilities.

This document lists supported connectors, how to configure them, and how to add your own.

---

## How Forge talks to tools (the design)

```
                                 ┌─ MCP server (stdio/HTTP)  ◄── most cloud tools
                                 │
Forge daemon ─── connector ──────┤
                                 │
                                 └─ Native plugin (Python)   ◄── when MCP isn't enough
```

**MCP-first** is the default because:
- Zero code to write — just config in `.claude/settings.json`
- Inherits Claude Code's setup if the user is already using it
- Auth handled by the MCP server (OAuth flows, token refresh, etc.)
- Tool descriptions are model-readable

**Native plugins** are for cases where:
- No MCP server exists yet (or quality is poor)
- The integration is local-only (e.g., Postgres on localhost)
- Performance matters (skip subprocess + JSON-RPC overhead)
- You need fine-grained capability scoping that MCP can't express

Both go through the same **connector registry** so the planner sees a unified tool list.

## Recommended connectors (priority list)

### Tier 1 — Most users want these

| Connector | Mechanism | Capability | Auth | MCP server |
|---|---|---|---|---|
| **GitHub** | MCP | issues, PRs, CI status, code search | `gh auth login` | [`@modelcontextprotocol/server-github`](https://github.com/modelcontextprotocol/servers/tree/main/src/github) |
| **Git (local)** | Native | branches, diffs, commits, worktrees | none | n/a |
| **Vercel** | MCP | deploys, logs, env vars, project info | `vercel login` | `@vercel/mcp-server` (official) |
| **Supabase** | MCP | DB tables, RLS, edge functions, migrations | `supabase login` | [`supabase-community/supabase-mcp`](https://github.com/supabase-community/supabase-mcp) |
| **Postgres** (any) | MCP | query, schema, EXPLAIN | DSN | [`@modelcontextprotocol/server-postgres`](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres) |
| **Stripe** | MCP | charges, customers, webhooks | API key | `@stripe/mcp-server` (official) |

### Tier 2 — Frequently asked

| Connector | Mechanism | Capability | Auth |
|---|---|---|---|
| **GitLab** | MCP | merge requests, pipelines, repos | token |
| **Bitbucket** | Native (planned) | PRs, pipelines | App password |
| **AWS S3** | MCP | objects, buckets, signed URLs | AWS profile |
| **Cloudflare R2** | MCP | objects, buckets | API token |
| **GCS** | Native (planned) | objects, buckets | gcloud creds |
| **Resend** | MCP | send emails, inspect logs | API key |
| **SendGrid** | Native (planned) | send, templates, stats | API key |
| **Postmark** | Native (planned) | send, bounces | server token |
| **AWS SES** | MCP | send, identities, suppressions | AWS profile |
| **Slack** | MCP | post messages, search, channels | bot token |
| **Discord** | MCP | post messages, channels | bot token |
| **Linear** | MCP | issues, projects, cycles | API key |
| **Sentry** | MCP | events, issues, releases | DSN |
| **Datadog** | MCP | metrics, logs, monitors | API key |
| **Posthog** | MCP | events, feature flags, insights | API key |
| **Clerk** | Native (planned) | users, sessions, orgs | secret key |

### Tier 3 — Niche but supported

DNS (Cloudflare, Route53), search (Algolia, Meilisearch), files (Dropbox, Google Drive), calendar (Google Cal, Cal.com), CI (GitHub Actions, CircleCI), monitoring (Grafana, Honeycomb), feature flags (LaunchDarkly).

## How to add a connector

### Path A — MCP server (recommended)

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}"
      }
    },
    "vercel": {
      "command": "npx",
      "args": ["-y", "@vercel/mcp-server"],
      "env": {
        "VERCEL_TOKEN": "${env:VERCEL_TOKEN}"
      }
    },
    "supabase": {
      "command": "npx",
      "args": ["-y", "@supabase/mcp-server-supabase@latest"],
      "env": {
        "SUPABASE_ACCESS_TOKEN": "${env:SUPABASE_TOKEN}"
      }
    }
  }
}
```

Then:

```bash
forge init                      # re-scans .claude/, picks up new MCP servers
forge connectors list           # confirm Forge sees them
```

When the planner runs, it sees the tool list from each MCP server and can call them.

### Path B — Native Python plugin

Create `~/.forge/plugins/<name>/` with this structure:

```
~/.forge/plugins/sendgrid/
├── manifest.toml         declares capabilities, version, author, signature
├── plugin.py             implements the connector interface
└── README.md
```

`manifest.toml`:

```toml
[plugin]
name = "sendgrid"
version = "0.1.0"
description = "SendGrid email connector"
author = "you@example.com"
license = "MIT"
schema_version = 1

[capabilities]
network = ["https://api.sendgrid.com"]   # egress allow-list
filesystem = []                            # no file access
exec = []                                  # no subprocess spawning
secrets_read = ["SENDGRID_API_KEY"]        # which env vars it reads

[tools]
# Each tool exposed to the planner / generator
[[tools.send_email]]
description = "Send a single email via SendGrid"
input_schema = "schemas/send_email.json"
side_effects = "external"   # external | local | readonly

[[tools.list_templates]]
description = "List SendGrid templates"
side_effects = "readonly"
```

`plugin.py`:

```python
"""SendGrid connector for Forge.

Runs in a subprocess sandbox (see daemon/connectors/runtime.py). Network
egress restricted to the domains declared in manifest.toml [capabilities].
"""

from __future__ import annotations

from forge_plugin_api import Connector, Tool, ToolResult


class SendGridConnector(Connector):
    name = "sendgrid"

    def __init__(self, secrets: dict[str, str]):
        self.api_key = secrets["SENDGRID_API_KEY"]

    @Tool(name="send_email", side_effects="external")
    async def send_email(self, to: str, subject: str, body: str) -> ToolResult:
        """Send an email."""
        # ... httpx POST to https://api.sendgrid.com/v3/mail/send ...
        return ToolResult(ok=True, data={"message_id": "..."})

    @Tool(name="list_templates", side_effects="readonly")
    async def list_templates(self) -> ToolResult:
        """List active templates."""
        return ToolResult(ok=True, data=[...])
```

Install:

```bash
forge connectors add ~/.forge/plugins/sendgrid
forge connectors list                        # verify
forge connectors enable sendgrid             # opt in (default: disabled until enabled)
```

### Path C — Hybrid (MCP + native)

Some connectors benefit from BOTH paths (e.g., GitHub via MCP for most ops, native for high-volume code search). Forge's connector registry lets the planner pick the cheaper path automatically.

## Capability declaration (security model)

Every native plugin **must** declare its capabilities. Forge enforces these at runtime via the **plugin sandbox** (see [docs/SKILLS.md](SKILLS.md) for the security model — same sandbox runs both):

```toml
[capabilities]
network = ["https://api.example.com"]   # exact domain allow-list
filesystem = ["${WORKTREE}/output"]     # paths the plugin may write (read-only outside)
exec = []                                # no shell-out
secrets_read = ["EXAMPLE_API_KEY"]       # env vars the plugin sees (rest filtered)
secrets_write = []                       # plugin cannot write secrets back
```

If a plugin tries to access a domain or path outside its declared capabilities, the call fails with a `CapabilityViolation` and is logged to the audit trail.

## Configuration reference

`.forge/connectors.toml` (auto-generated; user-editable):

```toml
[connectors.github]
mechanism = "mcp"
enabled = true
priority = 10                        # higher = tried first if multiple connectors offer the same tool

[connectors.sendgrid]
mechanism = "native"
enabled = true
plugin_path = "~/.forge/plugins/sendgrid"
secrets_env = "SENDGRID_API_KEY"

[connectors.vercel]
mechanism = "mcp"
enabled = false                      # disabled per-project; user opts in
```

## CLI commands

```bash
forge connectors list                Show all configured connectors
forge connectors add <name>          Wizard to add a new connector (MCP or native)
forge connectors enable <name>       Enable a configured connector
forge connectors disable <name>      Disable without removing
forge connectors test <name>         Run the connector's healthcheck
forge connectors remove <name>       Remove from registry (preserves plugin files)
```

## Authoring a connector

See [docs/PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md) for the full guide. TL;DR:

1. Pick a name (`my-tool`)
2. Implement `Connector` subclass with `@Tool`-decorated methods
3. Declare capabilities in `manifest.toml`
4. Test against `forge_plugin_api.testing.MockSandbox`
5. Sign manifest (`forge plugin sign manifest.toml`)
6. Submit to the [Forge Plugin Registry](https://github.com/<org>/forge-plugins) (planned)

## Security notes

- **No connector runs without explicit `enable`**. New plugins are loaded but disabled by default.
- **Manifest signature verification** runs on first load and on every update. Tampered manifests are refused.
- **Capability changes** between manifest versions trigger a re-approval prompt (the "rug pull" defense — see [docs/SECURITY_AUDIT.md](SECURITY_AUDIT.md) §3).
- **Secrets** are passed via filtered env, never logged, never written to the trace JSONL (verified by the redaction layer at 5 boundaries).
- **Egress** outside declared `network` capabilities is blocked at the sandbox boundary.

## Roadmap

| Connector | Status | Target |
|---|---|---|
| GitHub (MCP) | ✅ supported via `.claude/settings.json` | shipping |
| Vercel (MCP) | ✅ via official MCP server | shipping |
| Supabase (MCP) | ✅ via community MCP server | shipping |
| Postgres (MCP) | ✅ via official MCP server | shipping |
| Stripe (MCP) | ✅ via official MCP server | shipping |
| Native plugin runtime | 🔨 in progress | v0.1.0 |
| SendGrid (native) | 📅 planned | v0.1.0 |
| Plugin registry | 📅 planned | v0.2.0 |
| Capability sandbox | 🔨 in progress | v0.1.0 |
| Manifest signatures | 📅 planned | v0.1.0 |
