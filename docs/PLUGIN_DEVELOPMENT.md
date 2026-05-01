# Building Forge Plugins — Connectors, Skills, and LLM Adapters

Three plugin types share one sandbox + one capability model:

| Type | Purpose | Where | Doc |
|---|---|---|---|
| **Connector** | Tool integration (Vercel, GitHub, S3, …) | `~/.forge/plugins/<name>/` | [CONNECTORS.md](CONNECTORS.md) |
| **Skill** | Agent capability with `SKILL.md` + scripts | `~/.forge/skills/<name>/` | [SKILLS.md](SKILLS.md) |
| **LLM adapter** | New model provider | `~/.forge/llms/<name>/` | [LLMS.md](LLMS.md) |

This document is the unified author guide. Read [SKILLS.md](SKILLS.md) first — it specifies the security model that applies to all three types.

---

## Quickstart — your first connector

```bash
forge plugin scaffold connector my-tool
cd ~/.forge/plugins/my-tool
# Edit plugin.py + manifest.toml
forge plugin test my-tool
forge connectors enable my-tool
```

The scaffold gives you:

```
~/.forge/plugins/my-tool/
├── manifest.toml         capabilities, version, signature
├── plugin.py             your code
├── tests/
│   └── test_plugin.py    pytest tests against MockSandbox
├── examples/
└── README.md
```

## Manifest schema (v1)

```toml
[plugin]
name = "my-tool"                       # lowercase, hyphenated; matches directory name
version = "0.1.0"                      # semver
description = "Short, one-line"
author = "you@example.com"
license = "MIT"                        # MIT / Apache-2.0 / BSD-3-Clause / proprietary
schema_version = 1                     # Forge plugin manifest schema version
homepage = "https://github.com/you/my-tool"
forge_min_version = "0.1.0"            # require this Forge version or newer

[capabilities]
network = []                            # list of allowed origins; empty = no network
filesystem = []                         # list of writable paths; default read-only
exec = []                               # binaries the plugin may exec
secrets_read = []                       # env vars passed through (rest filtered)
secrets_write = []                      # vars the plugin may set (rare; usually empty)

[limits]
memory_mb = 512                         # default 1024
cpu_seconds = 30                        # default 60
wall_seconds = 60                       # default 120

# For connectors only:
[tools.<name>]
description = "What this tool does"
input_schema = "schemas/<name>.json"   # JSON schema for arguments
output_schema = "schemas/<name>.out.json"
side_effects = "external"               # external | local | readonly
idempotent = true

# For skills only:
[skill]
when_to_use = """
Multi-line natural-language description of when the planner
should pick this skill. The model reads this verbatim.
"""

# For LLM adapters only:
[llm]
provider = "myprovider"                 # used in routing rules
default_model = "myprovider-fast"
endpoint_env = "MYPROVIDER_BASE_URL"
api_key_env = "MYPROVIDER_API_KEY"
```

## Connector authoring

`plugin.py`:

```python
"""Reference connector — replace with your own implementation."""

from __future__ import annotations

from forge_plugin_api import Connector, Tool, ToolResult


class MyToolConnector(Connector):
    name = "my-tool"

    def __init__(self, secrets: dict[str, str], session: dict):
        self.api_key = secrets.get("MY_TOOL_API_KEY")
        self.session = session  # contains: project_path, sprint_id, worktree_path

    @Tool(name="do_thing", side_effects="external")
    async def do_thing(self, arg1: str, arg2: int = 0) -> ToolResult:
        """One-line description (this is what the planner sees)."""
        if not self.api_key:
            return ToolResult(ok=False, error="MY_TOOL_API_KEY not set")

        # The runtime's filtered httpx client enforces the network capability.
        async with self.http_client() as client:
            r = await client.post(
                "https://api.my-tool.com/v1/thing",
                json={"arg1": arg1, "arg2": arg2},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            r.raise_for_status()
            return ToolResult(ok=True, data=r.json())
```

Test:

```python
# tests/test_plugin.py
import pytest
from forge_plugin_api.testing import MockSandbox, FakeHttpClient
from plugin import MyToolConnector


@pytest.mark.asyncio
async def test_do_thing_happy_path():
    sandbox = MockSandbox(
        secrets={"MY_TOOL_API_KEY": "test-key"},
        http=FakeHttpClient({
            "POST https://api.my-tool.com/v1/thing": {"status": 200, "body": {"id": "abc"}}
        }),
    )
    connector = MyToolConnector(sandbox.secrets, sandbox.session)
    connector.http_client = sandbox.http_client_factory  # type: ignore

    result = await connector.do_thing("hello", arg2=42)

    assert result.ok
    assert result.data == {"id": "abc"}
    # Capability assertion — fails if you accidentally call a non-allowlisted host
    sandbox.assert_only_called(["https://api.my-tool.com"])


@pytest.mark.asyncio
async def test_missing_api_key_returns_error():
    sandbox = MockSandbox(secrets={})
    connector = MyToolConnector(sandbox.secrets, sandbox.session)
    result = await connector.do_thing("hello")
    assert not result.ok
    assert "API_KEY" in result.error
```

## Skill authoring

A skill is an instruction-bundle the planner can pull into the generator's prompt. Format wire-compatible with Claude Code skills:

```
~/.forge/skills/csv-cleaner/
├── SKILL.md             user-readable; first 1000 chars are the planner's "when to use"
├── manifest.toml
├── scripts/
│   └── clean.py         executable
├── references/          additional context loaded on-demand by the model
│   └── csv-quirks.md
└── examples/
    └── input.csv → output.csv
```

`SKILL.md`:

```markdown
# CSV Cleaner

Use this skill when:
- The user wants to deduplicate, normalize, or reshape CSV data
- The data has more than 1000 rows
- Standard pandas would be unwieldy

## How to use

The skill exposes one entry point: `scripts/clean.py <input.csv> <output.csv>`.
Inputs and outputs both stay in the worktree.

## What it does

1. Detects column types
2. Deduplicates on a configurable key
3. Normalizes whitespace, dates, currencies
4. Writes UTF-8 with newline=''
```

`scripts/clean.py`:

```python
#!/usr/bin/env python3
"""CSV cleaner — runs in the Forge skill sandbox."""

import csv
import sys


def main(input_path: str, output_path: str) -> int:
    with open(input_path, newline="") as f_in, open(output_path, "w", newline="") as f_out:
        reader = csv.reader(f_in)
        writer = csv.writer(f_out)
        seen = set()
        for row in reader:
            key = tuple(c.strip() for c in row[:2])  # dedup on first two columns
            if key in seen:
                continue
            seen.add(key)
            writer.writerow([c.strip() for c in row])
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
```

The script runs in the sandbox with:
- `cwd` = worktree
- `network = []` (no network unless you declare it)
- `filesystem = ["${WORKTREE}"]` (read+write inside worktree only)
- `exec = []` (no shelling out to other binaries)

If you need network or extra binaries, declare them in `manifest.toml` `[capabilities]`.

## LLM adapter authoring

An LLM adapter implements one interface:

```python
# ~/.forge/llms/myprovider/plugin.py
from __future__ import annotations

from forge_plugin_api import LLMAdapter, GenerationRequest, GenerationResult


class MyProviderAdapter(LLMAdapter):
    name = "myprovider"
    family = "myfamily"  # used for cross-family evaluator selection

    def __init__(self, secrets: dict[str, str]):
        self.api_key = secrets["MYPROVIDER_API_KEY"]
        self.base_url = secrets.get("MYPROVIDER_BASE_URL", "https://api.myprovider.com/v1")

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        async with self.http_client() as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": request.model,
                    "messages": request.messages,
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            r.raise_for_status()
            data = r.json()
        return GenerationResult(
            text=data["choices"][0]["message"]["content"],
            tokens_in=data["usage"]["prompt_tokens"],
            tokens_out=data["usage"]["completion_tokens"],
            cost_usd=self._price(data["usage"], request.model),
            stop_reason=data["choices"][0]["finish_reason"],
        )

    def supports_tools(self, model: str) -> bool:
        return model.endswith("-tools")

    def _price(self, usage: dict, model: str) -> float:
        # Per-million-token pricing; consult your provider's pricing page
        per_m_in, per_m_out = 0.50, 1.50
        return (usage["prompt_tokens"] / 1e6) * per_m_in + \
               (usage["completion_tokens"] / 1e6) * per_m_out
```

The `family` attribute is consumed by `daemon/agents/classifier.py::pick_evaluator_model` — it's how Forge enforces the cross-family-evaluator invariant when your adapter is registered as a generator.

## Capability declaration patterns

| Plugin type | Typical capabilities |
|---|---|
| Cloud API connector | `network = ["https://api.example.com"]`, `secrets_read = ["EXAMPLE_API_KEY"]` |
| Local DB connector | `filesystem = ["${HOME}/.local/share/example"]`, `network = []` |
| Code analyzer skill | `filesystem = ["${WORKTREE}"]`, `exec = ["clang-tidy"]` (declare every binary) |
| LLM adapter | `network = ["https://api.provider.com"]`, `secrets_read = ["PROVIDER_API_KEY"]` |
| Email sender | `network = ["https://api.sendgrid.com"]`, `secrets_read = ["SENDGRID_KEY"]` |

## Lethal-trifecta defense

Per the [security audit](SECURITY_AUDIT.md#8-data-exfiltration-via-cooperating-tools), Forge blocks plugin combinations that join:

- (private data — `.env`, secrets) + (untrusted input — web fetch, MCP) + (external egress)

Even if each individual plugin's manifest is valid, the **scheduler** refuses to compose plugin invocations that satisfy all three. This is enforced at orchestration time, not via plugin self-policing. See `daemon/skills/lethal_trifecta.py` for the rule engine.

## Submitting to the registry

(Planned for v0.2.0.)

```bash
# Sign your manifest
forge plugin sign manifest.toml --key ~/.gnupg/your-pgp-key

# Validate
forge plugin validate .

# Publish
forge plugin publish .
```

The registry will be a curated GitHub repo with PR-based review. Every plugin needs:
- Manifest with explicit capabilities
- Test suite with capability assertions
- README with security implications called out
- Maintainer's PGP signature
- Reviewer sign-off (initially manual)

## Migrating from Claude Code skills

Existing Claude Code skills (markdown-only, no manifest) can be imported:

```bash
forge skills import-claude /path/to/claude-code-skill
```

The wizard:
1. Reads the skill's `SKILL.md`
2. Asks you which capabilities the skill needs (default: deny everything)
3. Writes a `manifest.toml`
4. Hashes the directory
5. Installs

You explicitly approve every capability — Forge never silently accepts what the upstream skill claimed.

## Migrating from MCP servers

If you maintain an MCP server and want a native plugin too:

1. Keep the MCP server (Forge consumes it via `.claude/settings.json`)
2. Optionally add a native plugin for hot paths (the connector registry will prefer the lower-priority of the two)
3. The native plugin can `await` the MCP server's tools via `forge_plugin_api.mcp.call(...)` if you want to expose richer ergonomics on top

## Anti-patterns

| Anti-pattern | Why it fails | Do this instead |
|---|---|---|
| `exec = ["bash", "sh"]` | Shells turn capability scoping into a joke | `exec = ["pdftotext", "convert"]` — name every binary |
| `network = ["*"]` | Defeats the egress allow-list | `network = ["https://api.example.com"]` |
| Reading secrets you don't need | Increases blast radius | `secrets_read = []` unless you actually need them |
| Storing the API key in plugin code | Visible in `git log`; not rotatable | Always read from env via `secrets_read` |
| `filesystem = ["/"]` | Permission-bypass disguised as a capability | Scope to `${WORKTREE}` or specific subdirs |
| Forking subprocesses inside the sandbox | Escapes resource limits | Use the runtime's `call_subprocess()` helper |

## Seven-layer security applies to all three plugin types

[SKILLS.md §"The seven layers"](SKILLS.md#security-model--the-seven-layers) is the canonical security spec. Every connector, skill, and LLM adapter goes through:

1. Subprocess isolation
2. Capability declaration
3. Signed manifests + pinned hashes
4. Path scoping
5. Resource limits
6. Network egress filtering
7. Append-only audit log
