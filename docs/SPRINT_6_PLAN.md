# Sprint 6+ Plan — to v0.1.0

> **Status**: locked 2026-05-01 after two parallel research sweeps:
> Claude Code + Codex CLI feature inventory; image / video / multimodal
> integration patterns. Research notes live at the bottom of this doc.

This is the executable plan from current state to v0.1.0 release. Each
sprint has a concrete acceptance criterion. Sprints 6 + 7 are
**Claude-Code parity work** (now sized from research). Sprint 8 is the
**media layer** (image / video / multimodal). Sprints 9–13 close the
remaining gaps tracked in [GAP_ANALYSIS.md](GAP_ANALYSIS.md).

---

## At-a-glance

| Sprint | Theme | Effort | Status |
|---|---|---|---|
| **6.0** | Hot-fixes: tier-aware `$` meter + dev deps + Python install error | 0.5d | ✅ done 2026-05-01 |
| **6.1** | Plugin runtime — make the connector/skill/LLM sandbox actually run subprocesses | 5d | planned |
| **6.2** | Mode-picker daemon enforcement (Codex `--sandbox=` + Claude `permissions.defaultMode`) | 2d | planned |
| **6.3** | Slash-command handlers (the 17 commands wired through to real daemon actions) | 2d | planned |
| **6.4** | First reference connectors (GitHub-via-MCP, Vercel-via-MCP, Postgres-via-MCP, SendGrid-native) | 3d | planned |
| **7.1** | **Hooks system** (PreToolUse / PostToolUse / PreCompact / SubagentStop / Stop / UserPromptSubmit / SessionStart / Notification) | 3d | planned |
| **7.2** | **Subagents** (`.forge/agents/*.md` Markdown + YAML frontmatter, Claude-Code-compatible) | 2d | planned |
| **7.3** | **Custom slash commands** (`.forge/commands/*.md`, Claude-Code-compatible) | 1d | planned |
| **7.4** | **AGENTS.md ingestion** (root-to-leaf walk, Codex convention) | 1d | planned |
| **7.5** | **Memory tool** (Anthropic-compatible `view/create/str_replace/insert/delete/rename` over `.forge/memories/`) | 2d | planned |
| **7.6** | **Output styles** (`.forge/output-styles/*.md`, persona-shaping for planner / evaluator) | 1d | planned |
| **7.7** | **Sandbox profiles** (Codex `read-only` / `workspace-write` / `danger-full-access` via `sandbox-exec` macOS / `bwrap` Linux) | 3d | planned |
| **7.8** | **`apply_patch` adapter** (Codex V4A diff format for GPT-5-Codex generators) | 2d | planned |
| **7.9** | **Background / scheduled sprints** (`forge schedule "every Mon: …"` + cron loop + native notifications) | 2d | planned |
| **7.10** | Per-mode system-prompt overlays + refusal templates | 1d | planned |
| **8.1** | `MediaProvider` plugin contract + asset storage manifest | 2d | planned |
| **8.2** | `forge-media-comfyui` (local-first, Apple Silicon MPS + ComfyUI) | 3d | planned |
| **8.3** | `forge-media-replicate` (Flux Schnell / Flux Pro / Veo 3.1 Lite via Replicate) | 2d | planned |
| **8.4** | `forge-media-openai-image` (gpt-image-1 family, paid API, flips $ tier to metered) | 1.5d | planned |
| **8.5** | `BudgetController` MediaSpend extension + price book | 2d | planned |
| **8.6** | Multimodal input pipeline (vision-LM passthrough + Mistral OCR / Tesseract / vision-LM ladder) | 2d | planned |
| **8.7** | Safety: NSFW post-filter + C2PA / SynthID provenance verification | 1.5d | planned |
| **8.8** | UI MediaPanel + media events (started / progress / complete / failed) | 2d | planned |
| **8.9** | `forge doctor` integration + media-layer docs | 1d | planned |
| **9.1–9.15** | 15 security layers from SECURITY_AUDIT.md | 5d | planned |
| **10** | CI gates + E2E + integration tests | 3d | planned |
| **11** | UI polish + Playwright snapshot tests | 5d | planned |
| **12** | SWE-bench Verified ≥30% on 50-task subset (ADR-015 hard kill) | 5d | planned |
| **13** | Pre-release: demo, migration guides, cookbook, pen-test scoping | 5d | planned |

**Total to v0.1.0 from current state: ~7 weeks.**

---

## Sprint 6.0 — quick fixes (✅ done 2026-05-01)

### 6.0.1 — `$`-meter conditional via daemon-side tier

**Done.** `daemon/billing.py` is the new single source of truth:

- `FORGE_BILLING_TIER` env var explicit override
- `.forge/config.toml [billing] tier = "..."` per-project override
- `CLAUDE_PRO` / `CLAUDE_PLAN` / `CLAUDE_MAX` markers → `subscription`
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` set → `metered`
- `OPENAI_BASE_URL` pointing at non-localhost → `metered`
- Default → `free`

UI receives the tier in the `project_context` message (or via
`tier_changed` mid-session). `ContextMeter.tsx` no longer infers tier
from the model name. When `tier === "free"` no `$` text shows at all —
just the "Free (Ollama)" badge + the context-window meter, exactly as
the user asked. Adding an API key flips the meter to live `$`.

**Acceptance** (✓ verified): pure-Ollama session shows zero `$` text.
Setting `ANTHROPIC_API_KEY` → tier flips to `metered` and the spend
bar appears.

### 6.0.2 — dev deps in `pyproject [dev]` extra

**Done.** New `[project.optional-dependencies].dev` includes pytest /
pytest-asyncio / pytest-cov / respx / hypothesis / syrupy / time-machine /
ruff / pre-commit / editables / hatch-vcs / hatchling. `install.sh` now
installs `forge[dev]` by default; `FORGE_NO_DEV=1` opts out for
end-users who don't run tests.

### 6.0.3 — Python 3.12 enforcement + clearer install error

**Done.** When `install.sh` detects Python <3.10 it now prints three
concrete fix options (homebrew `--force` link, alias, or `~/.local/bin`
symlink) and the exact commands to copy-paste. Re-running picks up.

---

## Sprint 6.1 — plugin runtime (the live wiring)

The connector / skill / LLM-adapter registries exist as data structures
but **nothing actually runs a plugin yet**. Headline missing piece.

| # | Task | File(s) | Acceptance |
|---|---|---|---|
| 6.1.1 | Wire `daemon/skills/runtime.py::run_skill` into the scheduler | `daemon/scheduler.py` | A sprint that references a skill spawns a subprocess with the manifest's capability env (`FORGE_NETWORK_ALLOWLIST`, `FORGE_FS_WRITABLE`) |
| 6.1.2 | Egress filter shim: wrap `httpx.AsyncClient`, refuse non-allowlisted hosts | `forge_plugin_api/http.py` | A plugin trying to fetch a non-allowlisted URL raises `CapabilityViolation` |
| 6.1.3 | Append-only audit log: SQLite `skill_invocations` with write-once trigger | `daemon/db.py` | Every invocation writes a row; UPDATE blocked by trigger |
| 6.1.4 | Manifest hash pinning: `.forge/plugins.lock` + recompute-and-refuse loop | `daemon/connectors/registry.py` | Tampered plugin file refuses to run with `SkillTampered` |
| 6.1.5 | Capability-change re-approval prompt | `daemon/wizard.py` | Plugin manifest with new capability triggers prompt before next run |
| 6.1.6 | `forge connectors test <name>` / `forge skills test <name>` | `daemon/cli.py` | Healthcheck runs in sandbox; pass/fail reported |

---

## Sprint 6.2 — mode-picker daemon enforcement

UI ships `ModePicker`. Daemon needs to honor it. Mode matrix:

| Mode | Generator can write? | Destructive ops prompt? | Plugin sandbox active? |
|---|---|---|---|
| `ask` | only after user OK | yes (every one) | yes |
| `accept_edits` | yes | yes (warn+block tiers) | yes |
| `plan` | NO (planner+evaluator only) | n/a | yes |
| `auto` | yes | only block tier | yes |
| `bypass` | yes | no | NO |

| # | Task | Acceptance |
|---|---|---|
| 6.2.1 | `daemon/session.py` holds `mode` (replaces `BudgetController._mode` hack) | Session-level state object owns mode + verbosity + active model |
| 6.2.2 | Scheduler checks `mode` before generator write | In `plan` mode generator never produces a diff |
| 6.2.3 | Safety classifier checks `mode` | In `bypass` mode classifier returns `None`; audit log records the bypass loudly |
| 6.2.4 | WS emits `permission_request` for `ask` mode; UI confirms via button | Every write triggers a user-prompt event with diff preview |

---

## Sprint 6.3 — slash-command handlers

| Command | Status | Implementation |
|---|---|---|
| `/help` | partial | Enumerate registered commands + their docstrings |
| `/clear` | partial | Client-side OutputStream clear; daemon untouched |
| `/model <name>` | partial | Switch active model on session-state object; emit `model_changed` |
| `/mode <m>` | yes (6.2) | Already handled |
| `/memory [search <q>]` | yes | Already routes to KB |
| `/research <q>` | yes | Already routes to researcher agent |
| `/review <sprint-id>` | yes | Already routes to reviewer panel |
| `/replay <session>` | yes | Routes to replay |
| `/budget` | partial | Emit budget detail msg with breakdown by sprint |
| `/wizard` | yes | Hint at terminal command |
| `/connectors` | yes | Already wired |
| `/skills` | yes | Already wired |
| `/llms` | yes | Already wired |
| `/diff` | **new** | Enumerate worktree diffs; emit |
| `/merge` | **new** | Open merge gate panel |
| `/reset` | yes | Already wired |
| `/quit` | **new** | Trigger graceful shutdown |

---

## Sprint 6.4 — first reference connectors

Four production-grade connectors to prove the plugin runtime end-to-end:

1. **GitHub-via-MCP** — wraps `@modelcontextprotocol/server-github`. Issues, PRs, CI status, code search. Auth via `GITHUB_TOKEN`.
2. **Vercel-via-MCP** — wraps `@vercel/mcp-server`. Deploys, logs, env vars. Auth via `VERCEL_TOKEN`.
3. **Postgres-via-MCP** — wraps `@modelcontextprotocol/server-postgres`. Query, schema, EXPLAIN. Auth via `POSTGRES_DSN`.
4. **SendGrid-native** (Python plugin) — proves the native-plugin path with capability declaration + signed manifest. Auth via `SENDGRID_API_KEY`.

---

## Sprint 7 — Claude-Code + Codex parity (research-informed)

The 2026-05-01 research sweep enumerated 15 features across both tools.
The top 10 by leverage-per-LOC are scheduled here. Five honorable
mentions are deferred to v0.2.0.

### 7.1 — Hooks system

**Why first**: Single biggest unlock per the research. The
existing destructive-op classifier becomes the canonical `PreToolUse`
example.

**Schema**: `.forge/hooks.toml` with `[[hooks.PreToolUse]]` blocks. JSON
on stdin contract identical to Claude Code + Codex (so users can copy
hook scripts wholesale).

```toml
[[hooks.PreToolUse]]
matcher = "Bash"
command = ["python", ".forge/hooks/destructive-check.py"]
timeout = 5

[[hooks.PostToolUse]]
matcher = "Edit|Write"
command = ["pre-commit", "run", "--files"]
timeout = 60

[[hooks.SubagentStop]]
matcher = ".*"
command = ["python", ".forge/hooks/checkpoint-kb.py"]

[[hooks.SessionStart]]
matcher = ".*"
command = ["python", ".forge/hooks/load-session-context.py"]
```

Wire-in points in `daemon/scheduler.py`:
- Before / after every generator tool call → PreToolUse / PostToolUse
- Before context compaction (`learner.compact_session`) → PreCompact
- On subagent stop (Sprint 7.2) → SubagentStop
- On session start → SessionStart

### 7.2 — Subagents

`.forge/agents/<name>.md` with YAML frontmatter:

```markdown
---
name: security-reviewer
description: Reviews diffs for security vulnerabilities. Always use when changing auth, RLS, or input handling code.
tools: [Read, Grep, Glob]
model: claude-opus-4-7
disable-model-invocation: false
---

You are a security-focused code reviewer. Look for:
1. Injection (SQL, command, path traversal)
2. Auth bypass (RLS missing, JWT validation gaps)
3. Secret leakage (logged credentials, exposed keys)
4. ...
```

The planner auto-delegates by matching task description against the
`description` field (semantic match, not exact). User can also invoke
explicitly via `/agents` command.

### 7.3 — Custom slash commands

`.forge/commands/<name>.md` — frontmatter-compatible with Claude Code's
so users don't duplicate. Also reads `.claude/commands/*.md` as
fallback (so Forge inherits any commands the user already has).

```markdown
---
name: deploy
description: Deploy current branch to staging
argument-hint: [branch]
model: claude-sonnet-4-7
allowed-tools: [Bash, Read]
---

Deploy $1 (or current branch if empty) to staging via Vercel.
After deploy, verify the health endpoint at $2 (default: /health) returns 200.
```

Placeholders: `$ARGUMENTS`, `$1`..`$9`, named `$NAME=value`. Restart
not needed — registry watches the directory.

### 7.4 — AGENTS.md ingestion (root-to-leaf walk)

Codex CLI's de-facto convention is now backed by a registered standard
(agents.md). Forge currently reads `CLAUDE.md` only; should also walk
for `AGENTS.override.md` → `AGENTS.md` from project root down to cwd,
inject each as a separate context block titled
`# AGENTS.md instructions for <relpath>`. Add to
`daemon/scanner/claude_code.py`. ~30 LOC.

### 7.5 — Memory tool

Anthropic shipped a memory tool (different from CLAUDE.md and from
auto-memory). The model is given a tool with `view` / `create` /
`str_replace` / `insert` / `delete` / `rename` commands operating on a
virtual filesystem.

For Forge: expose `.forge/memories/<session-id>/` to the generator
agent as a tool the model itself can call. **Distinct from the
auto-extracted KB** — this is the model's working scratchpad.
Compaction events flush relevant memory entries to the KB via the
existing `learner` for cross-session persistence.

### 7.6 — Output styles

`.forge/output-styles/<name>.md` with YAML frontmatter + system-prompt
addendum. Built-in starter set:
- `default` — current behavior
- `terse` — PR-bot voice; minimal prose
- `explanatory` — Insights inline (Claude Code's "Explanatory" style)
- `strict-reviewer` — evaluator persona; harshest grading
- `pr-bot` — output formatted as a PR description

Selectable per-agent in the planner contract.

### 7.7 — Sandbox profiles

Wrap generator subprocess in OS-level sandbox:
- macOS: `sandbox-exec` with a profile derived from worktree path + `.forge/`
- Linux: `bwrap` (Bubblewrap) with bind-mounts for the same scope
- Windows / WSL: documented as not-supported; falls back to worktree-only

Three modes mirroring Codex:
- `read-only` — generator can read project, write nothing
- `workspace-write` (default) — read project, write only worktree + `.forge/`; optional `network_access = false`
- `danger-full-access` — disabled by default; admin opt-in via env

Per-sprint configurable in the planner contract:

```toml
[sprint.sandbox]
profile = "workspace-write"
network_access = false
extra_paths = ["~/.npm/_cacache"]   # gets bind-mounted RW
```

### 7.8 — `apply_patch` adapter

OpenAI's V4A diff format used by Codex CLI's primary edit tool.
Higher-fidelity than str_replace because the model is trained on it.

Format:
```
*** Begin Patch
*** Update File: path/to/file
@@ def hello():
- print("Hello")
+ print("Hello, World!")
*** End Patch
```

`daemon/executors/codex.py` translates between str_replace-style edits
and V4A envelopes. Activated when generator routes to a GPT-5-Codex
model (per `daemon/llms/registry.py` family classification). ~150 LOC,
doubles Forge's effective generator pool.

### 7.9 — Background / scheduled sprints

`forge schedule "every Mon: triage stale PRs"` writes to
`.forge/scheduled.toml`. The existing `daemon/scheduler.py` grows a
cron loop that polls and dispatches. Notifications via the WS event
stream + macOS `osascript`-based or Linux `notify-send` native
notification on completion. **Skip cloud execution** — local-only
matches Forge's threat model.

### 7.10 — Per-mode system-prompt overlays + refusal templates

Two small but high-leverage prompt-shape changes:

- **Per-mode overlay**: when mode is `ask` / `plan` / `bypass`, the
  generator's system prompt gets an additional paragraph baked in. Per
  `docs/PROMPTS_AND_GUARDRAILS.md` §C — already specified, just needs
  wiring.
- **Refusal template**: when `safety.is_destructive` matches, daemon
  responds to the agent (not just blocks silently) with a structured
  refusal the agent can recover from:

```
The previous tool call was refused because it matched destructive-op rule:
  pattern: \brm\s+-rf\s+/(?!\w)
  reason: rm -rf / — catastrophic
  severity: block

If you genuinely need to perform this operation, ask the user to switch
to bypass mode (⌘ M, then 5).
```

Makes the refusal an in-conversation event the agent can recover from.

---

## Sprint 8 — media layer (image / video / multimodal)

Research-informed plan. The architecture introduces a **third plugin
kind** (`media`) alongside `connector` and `llm`, declared in
`forge_plugin_api/media.py`. Media plugins surface as **MCP tools to
the agent** by default — generators call `generate_image(...)` exactly
like any other MCP tool, no special-casing. **Local-first** by default;
paid APIs flip the `$` meter to `metered` automatically (per Sprint 6.0.1).

| # | Task | Effort | Acceptance |
|---|---|---|---|
| 8.1 | Define `MediaProvider` plugin contract in `forge_plugin_api/media.py` | 1d | Protocol exported; `kind`, `capabilities`, `CostSpec`, `MediaRequest`, `MediaResult` dataclasses. `tests/test_media_contract.py` validates a stub provider |
| 8.2 | Asset storage + manifest under `.forge/media/<sprint-id>/` | 1d | `daemon/media/store.py`. Every generation writes blob + sibling JSON manifest (prompt, seed, model, sha256, c2pa, cost). `worktree.merge()` copies to project's `assets/`. `tests/test_media_store.py` covers naming collision + sha dedup |
| 8.3 | `forge-media-comfyui` provider (local-first, Apple Silicon MPS) | 3d | Detects local ComfyUI on `127.0.0.1:8188`; ships 3 workflow JSONs (txt2img-SDXL, img2img, inpaint); exposes `generate_image` MCP tool. Mocked-ComfyUI integration test passes |
| 8.4 | `forge-media-replicate` provider | 2d | Wraps Replicate API; supports Flux Schnell ($0.003/img), Flux Pro ($0.05/img), Veo 3.1 Lite ($0.15/s). Returns `local_path` after download (never base64). Cost reported per call |
| 8.5 | `forge-media-openai-image` provider | 1.5d | gpt-image-1 + gpt-image-1-mini, low/med/high quality. Cost from price book. Returns C2PA presence flag (OpenAI signs by default) |
| 8.6 | Extend `BudgetController` with MediaSpend register + price book | 2d | `daemon/budget_media.py` + `daemon/llms/pricing.py`. `media_costs.toml` shipped + `.forge/config.toml` override. `budget.can_afford(MediaRequest)` + `budget.downgrade(MediaRequest)` cascade (frontier→cheap→local→deny). Tests cover cascade |
| 8.7 | Multimodal input pipeline + vision-LM passthrough | 2d | Drag/drop in UI + `forge add --image=PATH` in CLI both stash to `.forge/media/in/`. LLM adapter gains `supports_vision: bool`; passthrough when true, **Mistral OCR → Tesseract → vision-LM** ladder when false |
| 8.8 | Safety: NSFW post-filter + provenance verification | 1.5d | `daemon/media/safety.py` runs `falcons-ai/nsfw_image_detection` on every output; failed outputs go to `.forge/media/quarantine/`. `c2pa-python` verifies manifests on ingest; SynthID flag set when present |
| 8.9 | WS events + UI MediaPanel | 2d | New events: `media_started`, `media_progress` (0–100), `media_complete`, `media_failed`. New `ui/components/MediaPanel.tsx` shows generation grid with cost meter and re-roll button |
| 8.10 | Docs + `forge doctor` integration | 1d | `docs/media-layer.md` covers architecture + provider matrix + cost tuning + local-first default. `forge doctor` lists detected media providers (ComfyUI URL, Replicate token, OpenAI key, MPS availability) |

**Sprint 8 total: ~17 days.**

### Why MCP-as-the-surface, not native-plugin

Per the research: every shipped agentic tool that supports image gen
(Cursor, Claude Code, Cline) reaches it via MCP servers, not via custom
plugin shapes. The convention is set; we should follow it. Forge's
MCP-bidirectional layer means a media plugin that exposes itself as
an MCP tool gets served to the generator with no extra wiring.

### Why local-first

A pure-Ollama Forge user gets a working image-generation pipeline
without ever entering a credit card. A paid-API user gets the
frontier-quality path. The cost-tracker stays mostly idle on free
tier (matching Sprint 6.0.1's `$`-meter conditional design).

### Three concrete first-tier integrations for v0.2.0

1. `forge-media-comfyui` — local ComfyUI / SDXL / Flux Schnell. Zero
   marginal cost. Default for Apple Silicon Macs.
2. `forge-media-replicate` — Flux Schnell ($0.003/img) +
   Flux Pro ($0.05/img) + Veo 3.1 Lite ($0.15/s). Single token covers
   many models; cheapest paid path.
3. `forge-media-openai-image` — gpt-image-1 family for highest-quality.
   Doubles as the moderation backend (OpenAI flags before generation).

**Skip in v0.2.0**: Sora ($0.10–0.50/s — too expensive for autonomous
loops). Frontier video stays opt-in via direct API calls.

---

## Sprint 9 — security layers (1–15)

Per [docs/SECURITY_AUDIT.md](SECURITY_AUDIT.md). Each layer is its
own task. Some already started (L12 plugin sandbox = Sprint 6.1).

| Layer | Description | Status after S6.1 |
|---|---|---|
| L1 | Provenance-tagged context (`trust: system\|user\|repo\|web\|mcp\|kb`) | planned |
| L2 | MCP manifest hash pinning + re-approval (Invariant Labs defense) | covered by S6.1.4 |
| L3 | Lethal-trifecta wiring at scheduler | function exists; needs hookup |
| L4 | Egress allow-list in worktree sandbox | covered by S7.7 |
| L5 | Unicode + bidi-override sanitizer (Pillar Security defense) | planned |
| L6 | Cross-family evaluator: deny tool access except read-only diff | partial — needs scope tightening |
| L7 | Confirm-token binding for destructive ops | planned |
| L8 | Per-project Anthropic prompt-cache key isolation | planned |
| L9 | KB quarantine: web-derived items low-confidence | partial |
| L10 | WebSocket Origin header check + CSRF token | partial |
| L11 | Strict CSP + no remote images in UI | planned |
| L12 | Plugin sandbox | covered by S6.1 |
| L13 | Pre-egress secret redaction at model-API boundary | planned |
| L14 | Compaction guardrails (re-inject system policy) | covered by S7.1 + S7.5 |
| L15 | Append-only tool-call audit log | covered by S6.1.3 |

After Sprint 6.1 + 7 + 9, all 15 layers ship.

---

## Sprint 10 — CI gates + tests

- Pip-audit on every PR (gated)
- Semgrep with `p/python p/security-audit p/owasp-top-ten`
- Bandit on `daemon/`
- Coverage gate ≥80% on `daemon/` core
- E2E test: full session from `forge plan` to merge gate
- Snapshot test: WS protocol stays stable
- Plugin sandbox escape test suite (path traversal, fork bomb, etc.)

---

## Sprint 11 — UI polish

- Collapsible OutputStream sections
- Agent-card layout
- Dark / light toggle
- Mobile responsive
- Playwright snapshot tests per component
- Demo GIF for README

---

## Sprint 12 — SWE-bench kill criterion

Per ADR-015. ≥30% on 50-task SWE-bench Verified subset using the
open-weight stack. If we miss → pivot or shut down.

---

## Sprint 13 — pre-release

- Mermaid diagrams for SECURITY_AUDIT
- Migration guides from Aider / OpenHands / Continue / opencode
- Cookbook: 5 worked examples
- External pen-test scoping
- Bug bounty rules

---

## Recommended execution order

If you want maximum visible progress per day:

1. ✅ **Sprint 6.0** (today, done) — `$` meter conditional + dev deps + Python error
2. **Sprint 7.1 + 7.4** in parallel (~4 days) — Hooks + AGENTS.md. Each adds visible Claude-Code parity surface
3. **Sprint 6.1** (~5 days) — Plugin runtime. Without this, every "we have skills/connectors" claim is half-true
4. **Sprint 7.2 + 7.3 + 7.5** in parallel (~5 days) — Subagents + custom slash commands + memory tool. Headline parity items
5. **Sprint 8** (~17 days) — Media layer. Differentiator vs every shipping product (no one ships a local-first multimodal coding orchestrator)
6. **Sprint 9** (~5 days) — All 15 security layers
7. **Sprint 12** — SWE-bench eval (go/no-go)
8. **Sprint 11 + 13** — UI polish + pre-release

---

## Research sources

The two background-agent investigations on 2026-05-01:

### Claude Code + Codex feature inventory

15 feature categories audited across both tools. Top 10 by
leverage-per-LOC fed Sprint 7. Sources:
- Claude Code docs (sub-agents, hooks, permission modes, memory tool, slash commands, skills, output styles, costs, data usage, vision, AGENTS.md adoption)
- Codex CLI docs (sandbox, hooks, subagents, custom prompts, configuration reference, apply_patch, image generation in v0.x)
- agents.md standard registry
- Anthropic Skills repo
- Community projects: codex-hooks, codex-subagents-mcp, ccusage, tokscale, CodexBar
- Notable issues: `Codex CLI Cost Tracking #5085`, `DISABLE_TELEMETRY side effects #47558`

### Image / video / multimodal integration

Field survey across Cursor, Claude Code, Codex, Cline, Continue, Aider,
OpenHands, Replit Agent. Convergent finding: **MCP servers are the
field's chosen surface for image gen**; never return base64 in MCP
responses (return file paths). Sources include:
- OpenAI gpt-image-1 launch + pricing
- Sora 2 / Veo 3.1 / Flux / Replicate / Fal pricing pages
- HuggingFace Diffusers MPS docs + Apple ml-stable-diffusion
- ComfyUI MCP servers: artokun/comfyui-mcp, joenorton/comfyui-mcp-server
- Replicate Flux MCP: GongRzhe/Image-Generation-MCP-Server
- Mistral OCR pricing + benchmark
- C2PA + SynthID provenance standards
- LiteLLM cost-tracking conventions
- `falcons-ai/nsfw_image_detection` for post-filter

Both research transcripts are appended to the session log if forensic
detail is needed.
