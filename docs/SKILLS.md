# Forge Skills — Sandboxed Capability Imports

Forge supports **Claude-Code-compatible skills** — markdown-based agent capabilities that ship as a directory and add new behaviors to the planner / generator / evaluator. Every skill runs in a **sandbox** with declared capabilities, signed manifests, and resource limits.

This document specifies the security model. For authoring guides see [docs/PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md).

---

## What is a skill?

A skill is a self-contained directory like:

```
~/.forge/skills/pdf-extraction/
├── SKILL.md             user-readable description + when-to-use rules
├── manifest.toml        capability declaration + version + signature
├── scripts/
│   └── extract.py       executable entry point
├── references/          additional context the model reads
│   └── tika-quirks.md
└── examples/            input/output samples
    ├── input.pdf
    └── expected.json
```

When the planner sees a task that matches the skill's `when_to_use`, it loads the skill into the generator's prompt. The generator can then invoke `scripts/extract.py` — but only inside the skill's sandbox.

This format is **wire-compatible with Claude Code skills** so authors who already build for Claude Code can publish for Forge with a one-time `manifest.toml` add.

## Why sandboxing matters

The threat model from the [SECURITY_AUDIT](SECURITY_AUDIT.md) covers 12 attack classes; for skills specifically:

1. **Tool poisoning** — a malicious skill description hijacks the agent (Invariant Labs, April 2025; CVE-2025-6514 mcp-remote)
2. **Supply-chain compromise** — tampered scripts in `~/.forge/skills/` execute with user privileges
3. **Lateral data exfiltration** — a skill reads `.env`, another skill posts it externally (Willison's "lethal trifecta")
4. **Sandbox escape** — `subprocess.run(["sh", "-c", payload])` from skill code

Forge's response: **defense in depth**.

## Security model — the seven layers

### Layer 1 — Subprocess isolation

Every skill invocation runs in a **separate subprocess**, never in Forge's own Python interpreter. The subprocess inherits a **filtered env** (only declared `secrets_read` keys), runs as the same user but with reduced ambient capabilities.

```python
# daemon/skills/runtime.py (sketch)
proc = await asyncio.create_subprocess_exec(
    skill_python_bin, "-m", "forge_skill_runner", manifest_path,
    cwd=worktree_path,
    env=filtered_env(manifest.capabilities.secrets_read),
    stdout=PIPE, stderr=PIPE,
    # No shell=True. Ever.
    preexec_fn=apply_resource_limits,  # see Layer 5
)
```

### Layer 2 — Capability declaration

Every skill must declare what it needs:

```toml
[capabilities]
network = ["https://api.openai.com"]    # domain allow-list (NOT regex)
filesystem = ["${WORKTREE}/output"]     # paths writable; everything else read-only
exec = ["pdftotext"]                    # binaries the skill may exec
secrets_read = ["OPENAI_API_KEY"]       # env vars passed through
```

The runtime enforces these. Calls outside the allow-list raise `CapabilityViolation` and are logged to the **append-only audit log** (Layer 7).

### Layer 3 — Signed manifests + pinned hashes

On first install, Forge:

1. Computes SHA-256 of every file in the skill directory
2. Stores `<file-path>: <sha256>` in `.forge/skills.lock`
3. Records the manifest's declared capabilities

On every subsequent run:

- Recompute hashes; if any differ, refuse to run with `SkillTampered` until user re-approves
- If `manifest.toml` declares NEW capabilities the user hasn't approved, prompt for re-approval ("rug pull" defense — directly addresses Invariant Labs' MCP tool-poisoning research, April 2025)

For the planned **registry workflow** (v0.2.0):
- Maintainers sign skills with their PGP key
- Registry publishes signature + checksum
- `forge skills install <name>` verifies signature against pinned trusted keys

### Layer 4 — Path scoping

Filesystem access is restricted via `os.chroot`-style logic:

- The skill runner runs with `cwd = .forge/skills/<name>/sandbox/` (a fresh tmpfs-style copy, not the source)
- Filesystem capabilities are ABSOLUTE paths, normalized
- Any path that doesn't `startswith()` an allowed path is rejected before the syscall
- Symlink traversal is detected: `os.path.realpath` compared to declared paths

### Layer 5 — Resource limits

```python
def apply_resource_limits():
    import resource
    # Memory: 1 GB hard cap (configurable per skill)
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    # CPU time: 60 seconds default
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    # File size: 100 MB max output
    resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))
    # No core dumps
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # No fork bombs (max 50 children)
    resource.setrlimit(resource.RLIMIT_NPROC, (50, 50))
```

Per-skill overrides allowed in `manifest.toml`:

```toml
[limits]
memory_mb = 2048
cpu_seconds = 300
wall_seconds = 600
```

### Layer 6 — Network egress filtering

The skill subprocess runs with a **shim httpx client** that:

- Validates every request URL against the manifest's `network` capability
- Strips `Authorization` / `Cookie` headers if the destination is outside the allow-list
- Logs every outbound request to the audit log (Layer 7)

For `--sandbox=docker` mode (opt-in tier), the container runs with `--network=none` plus an explicit egress proxy that enforces the allow-list at the IP level.

### Layer 7 — Append-only audit log

Every skill invocation writes to a separate, write-once SQLite table:

```sql
CREATE TABLE skill_invocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    skill_version TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    invoked_at TEXT NOT NULL,           -- ISO 8601
    args TEXT,                           -- JSON, redacted
    result_status TEXT,                  -- ok | error | capability_violation | timeout
    duration_ms INTEGER,
    network_calls TEXT,                  -- JSON array of URLs
    fs_writes TEXT,                      -- JSON array of paths
    -- No UPDATE allowed; trigger blocks it
);

CREATE TRIGGER skill_invocations_no_update
BEFORE UPDATE ON skill_invocations
FOR EACH ROW BEGIN
    SELECT RAISE(ABORT, 'skill_invocations is append-only');
END;
```

This is the forensic trail after any incident. The trail itself is also subject to redaction (no raw secrets land in `args`).

## Lifecycle

```
forge skills install <source>     ─┐
                                   ├─► verify signature → install to ~/.forge/skills/
                                   │   compute & store file hashes in skills.lock
                                   │   show capability summary; require user approval
                                   ▼
forge skills list                  ─► show installed, capabilities, last invoked
forge skills enable <name>         ─► flip enabled flag
forge skills disable <name>        ─► flip disabled
forge skills test <name>           ─► run the skill's self-test suite in sandbox
forge skills update <name>         ─► re-fetch; if capabilities changed, re-approve
forge skills audit <name>          ─► show append-only audit log entries
forge skills remove <name>         ─► delete from disk; preserve audit log
```

## Refusing skills

Forge refuses to install skills with:

- **No `manifest.toml`** — anything from before the schema is rejected
- **`exec` capability listing `sh`, `bash`, `zsh`, `python` (other than the bundled runner)** — a skill that wants a shell is asking to be exploited
- **`network = ["*"]` or wildcard domains** — must be explicit hostnames
- **`filesystem` capabilities pointing outside the worktree** (with override flag for power users)
- **Manifest version mismatches** — schema version pinned per Forge release
- **Negative resource limits** or missing limits

## Importing Claude Code skills

Existing Claude Code skills (markdown-based, no `manifest.toml`) can be imported via:

```bash
forge skills import-claude <path-or-url>
```

This runs an interactive wizard:

1. Reads the skill's `SKILL.md` and any embedded scripts
2. Asks the user to declare capabilities (default: deny everything; user explicitly grants)
3. Writes a `manifest.toml`
4. Computes hashes
5. Installs into `~/.forge/skills/`

The user's explicit grant of each capability is the **trust anchor** — Forge never silently accepts what the upstream skill declares. This is the "import safely" answer for Claude Code skills.

## Per-skill audit example

```
$ forge skills audit pdf-extraction

Skill: pdf-extraction (v1.2.0)
Manifest hash: sha256:a3b1...
Last 10 invocations:

  2026-05-01 14:32:01  ok    230ms  → /api.openai.com (1)  → out.json (1 write)
  2026-05-01 14:31:58  ok    195ms  → /api.openai.com (1)  → out.json (1 write)
  2026-05-01 14:30:12  capability_violation  attempted POST to api.evil.com
                                     ^ skill REFUSED — domain not in allow-list
  2026-05-01 14:29:50  timeout  60s reached; subprocess killed
  ...

Capabilities (last approved 2026-04-30 by user):
  network: [https://api.openai.com]
  filesystem: [${WORKTREE}/output]
  exec: [pdftotext]
  secrets_read: [OPENAI_API_KEY]
```

## Roadmap

| Feature | Status | Target |
|---|---|---|
| Subprocess isolation | 🔨 in progress | v0.1.0 |
| Capability declaration + manifest schema | 🔨 in progress | v0.1.0 |
| Path scoping | 🔨 in progress | v0.1.0 |
| Resource limits | 🔨 in progress | v0.1.0 |
| Audit log + append-only trigger | 🔨 in progress | v0.1.0 |
| Network egress filter (httpx shim) | 📅 planned | v0.1.0 |
| Manifest signature verification | 📅 planned | v0.1.0 |
| Docker sandbox (`--sandbox=docker`) | 📅 planned | v0.2.0 |
| Skill registry + signed publishing | 📅 planned | v0.2.0 |
| Claude Code skill auto-import wizard | 📅 planned | v0.2.0 |

## Comparing to alternatives

| | Forge skills | Claude Code skills | OpenHands microagents | OpenAI Codex AGENTS.md |
|---|---|---|---|---|
| Declared capabilities | ✅ required | ❌ implicit | ⚠️ Docker-bounded | ❌ none |
| Signed manifests | ✅ planned v0.1.0 | ❌ | ❌ | ❌ |
| Subprocess isolation | ✅ | ⚠️ same process | ✅ Docker | ⚠️ OS sandbox |
| Egress filter | ✅ allow-list | ❌ | ⚠️ Docker net | ✅ via Bubblewrap |
| Append-only audit | ✅ | ❌ | ⚠️ logs | ❌ |
| Resource limits | ✅ rlimit | ❌ | ✅ Docker | ⚠️ partial |
| Re-approval on capability change | ✅ | ❌ | ❌ | ❌ |

Forge's posture is closer to **OpenAI Codex's OS-native sandboxing** than to Claude Code's permission-mode approach. Claude Code's `bypassPermissions` default-on-power-user is the exact failure mode skills sandboxing exists to prevent. See [SECURITY_AUDIT.md §6](SECURITY_AUDIT.md#6-rce-via-shell-tool-calls) for the full analysis.
