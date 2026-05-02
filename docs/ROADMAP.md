# Forge — Public Roadmap

> **For contributors.** This document is the contract between "what's shipped" and "what's open for community contribution." Every deferred sprint below has a scope, an entry point, a test shape, and a "where to plug in" pointer. **Pick one, open a draft PR, ask in the issue if unclear.** The maintainer will keep this current.

**Last updated**: 2026-05-01. Updated when a sprint moves between sections.

---

## How this roadmap is structured

Three sections, in order of priority for v0.1.0:

1. **Shipped** — code on `develop`, tests passing, in-tree.
2. **Next up (maintainer-led)** — work the maintainer is currently building. Comment on the linked issue if you want to coordinate.
3. **Open for contributors** — fully spec'd work the community can grab. Each entry has a stable contract, a one-paragraph rationale, and acceptance gates. Drop a comment on the linked issue and open a draft PR.

A fourth section (**Future / unscoped**) lists work that needs design discussion before code — open an issue if you want to lead the design.

---

## Shipped (Phase 1 + Phase 2 parity 5/10 + Phase 4 layers 5/10)

| # | Feature | Where it lives | Tests |
|---|---|---|---|
| Phase 1 | Scanner + planner / generator / evaluator harness | `daemon/scanner/`, `daemon/agents/` | `tests/test_scanner.py`, `tests/test_planner.py`, `tests/test_evaluator.py`, `tests/test_cross_family_evaluator.py` |
| Phase 1 | Four-tier SQLite KB (knowledge / episodic / procedural / research) | `daemon/db.py`, `daemon/memory/` | `tests/test_knowledge.py`, `tests/test_episodic.py`, `tests/test_retriever.py`, `tests/test_learner.py` |
| Phase 1 | Repomap + budget cap + worktrees + redaction at 5 boundaries | `daemon/scanner/repomap.py`, `daemon/budget.py`, `daemon/worktree.py`, `daemon/redact.py` | `tests/test_repomap.py`, `tests/test_budget.py`, `tests/test_worktree.py`, `tests/test_redact.py` |
| Phase 1 | Replay JSONL + WebSocket UI + KB-as-MCP server | `daemon/replay.py`, `daemon/ws_server.py`, `daemon/mcp_server.py` | `tests/test_replay.py`, `tests/test_ws_server.py`, `tests/test_mcp_server.py` |
| 6.1 | Plugin runtime (egress shim, audit log, lock, dispatcher, re-approval, CLI) | `daemon/skills/`, `daemon/connectors/`, `forge_plugin_api/` | `tests/test_plugin_*` |
| 6.2 | Mode picker enforcement (auto / accept_edits / plan / ask / bypass) | `daemon/mode.py` + scheduler hooks | `tests/test_mode_enforcement.py` |
| 6.3 | Daemon-side slash command handlers | `daemon/slash.py` | `tests/test_slash_handlers.py` |
| 6.4 | Reference connectors (git read-only + web_research) | `reference_plugins/` | `tests/test_reference_connectors.py` |
| 7.1 | Lifecycle hooks (PreToolUse / PostToolUse / SessionStart / SubagentStop / PreCompact) | `daemon/hooks.py` | `tests/test_hooks.py` |
| 7.3 | Custom slash commands from `.forge/commands/*.md` | `daemon/custom_commands.py` | `tests/test_custom_commands.py` |
| 7.4 | AGENTS.md root-to-leaf walk | `daemon/scanner/claude_code.py::read_agents_md` | `tests/test_agents_md.py` |
| 7.6 | Output styles registry | `daemon/output_styles.py` | `tests/test_output_styles.py` |
| 7.10 | Structured refusal templates | `daemon/refusal.py` | `tests/test_refusal_templates.py` |
| 9-L5 | Unicode + bidi-override sanitizer | `daemon/sanitize.py` | `tests/test_sanitize.py` |
| 9-L10 | WebSocket Origin allow-list | `daemon/ws_server.py::_origin_allowed` | `tests/test_ws_origin_check.py` |

Total: **894 tests passing, 1 skipped (mcp extra), 0 lint errors, 0 format issues** at session end. See [HANDOVER.md](HANDOVER.md) for the live state.

---

## Next up (maintainer-led)

Two pieces of work that need to land before v0.1.0 can ship. Both have clearer-than-average scope and the maintainer wants direct authorship.

### 1. **Phase 8 — SWE-bench Verified evaluation** ⚠ HARD KILL GATE

Per [ADR-015](DECISIONS.md), if Forge cannot reach **≥30% on a 50-task SWE-bench Verified subset** with the open-weight stack, the open-weight thesis fails and the project pivots or shuts down. This is non-negotiable. It needs to happen before anyone invests further in feature work.

- **Scope**: SWE-bench harness adapter (`tests/test_swebench_adapter.py` exists; expand to a runnable evaluator); reproducible 50-task subset; published numbers; pivot decision documented.
- **External requirement**: SWE-bench-Verified harness install + GPU access for open-weight model serving (Qwen3-Coder-Next + Devstral-Small-2507 + DeepSeek V4-Flash).
- **Contributor angle**: out-of-scope for community — this is a high-stakes go/no-go gate the maintainer must own.

### 2. **Phase 6 + 7 — Tauri v2 desktop wrapper, code signing, GitHub Releases**

The v0.1.0 distribution story. Needs Apple Developer ID enrollment, signing certs, notarization, Homebrew tap, Windows EV cert (deferred to v0.1.1 per the [DELIVERY_PLAN.md](DELIVERY_PLAN.md)).

- **Scope**: Tauri shell + Python sidecar packaging + Next.js webview build + signing pipeline + GitHub Releases workflow + auto-updater.
- **External requirement**: ~$700 of one-time external infrastructure (Apple Developer Program, signing servers, domain, optional pen-test).
- **Contributor angle**: out-of-scope for community — this is solo-developer infrastructure work that the maintainer must own end-to-end with their credentials.

---

## Open for contributors

Every entry below is **fully spec'd**, **isolated**, and **shippable in 1–3 days of focused work**. Pick one, open a draft PR, ask if unclear.

### 6.5 — Next.js dashboard rebuild from mockups

> ~5 days · Frontend · 0 daemon changes · No external dependency.

The 5 HTML mockups at `mockups/` are the contract. The existing 12 components in `ui/components/` compile and the WebSocket protocol is stable; what's missing is the dashboard layout matching the mockup designs.

**Files**:
- `mockups/01-main-chat.html` — primary working surface
- `mockups/02-empty-state.html` — first-run / no-session state
- `mockups/03-merge-gate.html` — diff review + approve/reject
- `mockups/04-wizard.html` — connector setup wizard (browser-native variant)
- `mockups/05-knowledge-base.html` — KB browser with search + edit
- `mockups/index.html` — gallery index linking the above

**Acceptance gates**:
- [ ] `pnpm build` (or `npm run build`) succeeds with no console errors
- [ ] Visual match against mockups within reasonable fidelity (Tailwind utility classes, color tokens, spacing scale)
- [ ] All existing WebSocket message types still flow correctly (`ContextMeter`, `ModePicker`, `OutputStream`, `MergeGate`, etc.)
- [ ] Mobile-responsive (the mockups have responsive breakpoints — honor them)
- [ ] No new dependencies — Next.js 14 App Router + Tailwind + native WebSocket, that's it
- [ ] Component-level Playwright snapshot tests for the five top-level views

**Where to start**: `ui/app/page.tsx` (currently 230 lines) needs a layout rewrite. The component primitives in `ui/components/` are mostly correct; the composition isn't. `ui/hooks/useForgeSocket.ts` is the stable WS contract.

**Rationale**: pure frontend work. No daemon changes. Doable any time. The maintainer would do this but it's not on the critical path for the SWE-bench kill gate.

---

### 7.2 — Subagents (`.forge/agents/<name>.md` registry + planner auto-delegation)

> ~3 days · Daemon + planner · No external dependency.

Claude Code-compatible subagent format: a Markdown file with YAML frontmatter declaring name, description, allowed tools, model, and `disable-model-invocation`. The planner reads the registry and auto-delegates by matching task description against `description` field (semantic match, not exact).

**Format** (compatible with Claude Code):

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
...
```

**Files to add**:
- `daemon/subagents.py` — `Subagent` dataclass + `discover_subagents(project_path)` walking `.forge/agents/*.md` (with `.claude/agents/*.md` fallback). Reuse `daemon/custom_commands._parse_frontmatter` for the YAML.
- `daemon/agents/planner.py` — extend the planner prompt to list registered subagents in the system prompt and emit a `subagent` field in each sprint contract. Auto-delegation logic: if a sprint's description semantically matches a subagent's `description` (start with substring + topic-overlap match; vector embeddings are a follow-up), set `sprint.subagent = name`.
- `daemon/scheduler.py` — when `sprint.subagent` is set, override `sprint.assigned_model` from the subagent's `model` and inject the subagent body as a system-prompt addendum (alongside `mode_prompt_addendum` and `output_styles.style_addendum`).
- New `/agents` slash command in `daemon/slash.py` to list / show / explicitly invoke a subagent.

**Acceptance gates**:
- [ ] A user can drop `security-reviewer.md` in `.forge/agents/` and `forge plan "audit the auth changes"` auto-delegates to it
- [ ] `forge agents list` shows registered subagents with their descriptions
- [ ] `forge agents test <name>` runs the subagent against a synthetic input
- [ ] `disable-model-invocation: true` makes the subagent invokable only via explicit `/agents <name>` (not auto-delegated)
- [ ] Tests cover: registry round-trip, frontmatter parsing edge cases, auto-delegation match logic, model override applies, integration through scheduler

**Where to start**: copy the shape of `daemon/custom_commands.py` — it's the same pattern (Markdown + frontmatter, `.forge/` overrides `.claude/`, registry resolution).

**Rationale**: subagents are the second-most-requested Claude Code parity feature behind hooks (already shipped). Single biggest unlock for the planner — the planner stops trying to be a generalist and starts dispatching work to specialists.

---

### 7.5 — Memory tool (`.forge/memories/<session>/`)

> ~2 days · Daemon + tool wiring · Depends on 7.2 for clean integration.

Anthropic's [memory tool](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/memory-tool) gives the model `view` / `create` / `str_replace` / `insert` / `delete` / `rename` commands operating on a virtual filesystem. **Distinct from** the auto-extracted KB — this is the *model's working scratchpad* during a session.

**Files to add**:
- `daemon/memory_tool.py` — six functions matching the Anthropic tool schema, operating on `.forge/memories/<session-id>/` with path scoping (no `..`, no absolute paths).
- `daemon/agents/generator.py` — when `sprint.allowed_tools` includes `Memory`, expose the six methods as MCP tools the model can call.
- `daemon/memory/learner.py` — on session end, optionally promote relevant memory entries to the persistent KB via the existing `extract_gotcha` pipeline. Confidence starts at 0.5; user can promote / discard via the UI.

**Acceptance gates**:
- [ ] Path-traversal safe: `view ../../etc/passwd` raises `MemoryViolation`, never reads outside `.forge/memories/<session>/`
- [ ] Round-trip: model creates a file, reads it back, edits via `str_replace`, deletes it
- [ ] Compaction event in `daemon/memory/learner.py::compact_session` triggers promotion-to-KB pass; user-rejected entries get `superseded_by` set and don't re-appear
- [ ] Memory survives only for the session by default; persistent promotion is explicit
- [ ] Tests cover: path scoping, all six commands, learner promotion, compaction

**Where to start**: `daemon/memory_tool.py` is greenfield. Constraints come from `daemon/sanitize.py` (clean Unicode) and `daemon/redact.py` (no secrets in stored memories).

**Rationale**: closes the gap between "ephemeral context" and "long-term KB." The planner / generator can scratch-pad during a sprint without polluting the KB; only learnings the user keeps survive.

---

### 7.7 — OS-native sandbox profiles (`sandbox-exec` / `bwrap` / WSandbox)

> ~3 days · Per-OS shell + Python wrapper · No external dependency.

Wrap the generator subprocess in OS-level sandbox layers (in addition to the existing git worktree). Three profiles mirroring Codex CLI:

- `read-only` — generator can read project, write nothing
- `workspace-write` (default) — read project, write only worktree + `.forge/`; optional `network_access = false`
- `danger-full-access` — disabled by default; admin opt-in via `FORGE_SANDBOX=full` env

Per-OS implementations:
- **macOS**: `sandbox-exec` with a `.sb` profile derived from worktree path + `.forge/`. Profile generated per-sprint.
- **Linux**: `bwrap` (Bubblewrap) with bind-mounts for the same scope.
- **Windows / WSL**: documented as not-supported in v0.1.0; falls back to worktree-only with a WARNING.

**Files to add**:
- `daemon/sandbox/macos.py` — generates the `.sb` profile, wraps `claude -p` / `ollama run` in `sandbox-exec -f profile.sb -- <cmd>`
- `daemon/sandbox/linux.py` — generates `bwrap` argv list with the right `--ro-bind` / `--bind` / `--unshare-net`
- `daemon/sandbox/__init__.py` — `wrap_command(cmd, sandbox_profile, worktree_path) -> list[str]` dispatches by OS
- `daemon/scheduler.py` — read `sprint.sandbox_profile` (default `workspace-write`), pass through to executor

**Acceptance gates**:
- [ ] `read-only` mode actually prevents `echo "x" > worktree/file.txt` (subprocess gets EROFS / EACCES)
- [ ] `workspace-write` allows writing to the worktree and `.forge/` but not to `~/.bashrc` / `/etc/`
- [ ] `network_access = false` blocks `curl https://example.com` (DNS resolution + socket connect both fail)
- [ ] Per-sprint configurable in the planner contract (`sprint.sandbox`)
- [ ] Tests on macOS + Linux CI runners; Windows skipped with a WARN message
- [ ] `forge doctor` reports which sandbox is available

**Where to start**: Codex CLI's open-source sandbox profiles are the reference (Apache 2.0). [github.com/openai/codex](https://github.com/openai/codex) — see their `sandbox-exec.sb` and `bwrap` invocations.

**Rationale**: worktree isolation is correct for "agent makes a mistake" threat model but doesn't defend against "agent runs untrusted dependency that escapes the worktree." OS sandboxing closes that gap. Codex's sandbox is "the most rigorous in the field" per the competitive comparison; lifting the pattern is a free win.

---

### 7.8 — `apply_patch` adapter for Codex-family models

> ~1 day · LLM adapter · Depends on someone wiring a GPT-5-Codex LLM adapter first (see "Future / unscoped" below).

OpenAI's V4A diff format used by Codex CLI's primary edit tool. Higher-fidelity than `str_replace` because the model is trained on it.

**Format**:
```
*** Begin Patch
*** Update File: path/to/file
@@ def hello():
- print("Hello")
+ print("Hello, World!")
*** End Patch
```

**Files to add**:
- `daemon/executors/codex.py` — translates between str_replace-style edits and V4A envelopes. Activated when generator routes to a GPT-5-Codex model (per `daemon/llms/registry.py` family classification).

**Acceptance gates**:
- [ ] Round-trip: V4A → AST changes → V4A produces the same envelope
- [ ] Fuzz against the Codex CLI's golden test cases if available
- [ ] When a GPT-5-Codex adapter is registered in the LLM registry, generator routing picks `codex` executor automatically
- [ ] Tests cover: simple update, file create, file delete, multi-hunk update, merge-conflict resolution

**Where to start**: ~150 LOC in `daemon/executors/codex.py`. Reference: OpenAI Codex CLI source (Apache 2.0) for the V4A grammar.

**Rationale**: doubles Forge's effective generator pool when GPT-5-Codex is in scope. Low-risk adapter work.

---

### 7.9 — Background / scheduled sprints

> ~3 days · Scheduler + cron loop + native notifications.

`forge schedule "every Mon: triage stale PRs"` writes to `.forge/scheduled.toml`. The scheduler grows a cron loop that polls and dispatches. Notifications via the WebSocket event stream + native (`osascript` on macOS, `notify-send` on Linux).

**Files to add**:
- `daemon/scheduled.py` — TOML parser for `.forge/scheduled.toml` + cron expression evaluator (vendor [croniter](https://github.com/kiorky/croniter) or similar; tiny, MIT)
- `daemon/scheduler.py` — background task loop (started alongside `start_server`) that polls for due schedules
- `daemon/notify.py` — `notify(title, body)` dispatching to `osascript -e 'display notification ...'` / `notify-send` / WS-only fallback
- New CLI command: `forge schedule add / list / remove / run-now`

**Acceptance gates**:
- [ ] Schedule survives daemon restart (state on disk, not in memory)
- [ ] Misfire policy: if the daemon was offline at the scheduled time, run on next start with a "missed" event
- [ ] Cron expression parsing handles standard 5-field syntax + `@daily` / `@weekly` aliases
- [ ] Tests cover: cron evaluation, persistence, misfire, run-now
- [ ] Skip cloud execution — local-only matches Forge's threat model

**Where to start**: `daemon/scheduler.py::execute_session` is the entry. The cron loop calls it with the schedule's saved `objective` field.

**Rationale**: enables "every Monday, run the maintenance plan" workflows that are currently impossible. Especially valuable for teams running Forge on a dev box / lab server.

---

### 9-L1 — Provenance-tagged context (`trust: system|user|repo|web|mcp|kb`)

> ~2 days · Memory layer change + planner injection update.

Every context block injected into a prompt gets a trust tag. Untrusted blocks (`web`, low-confidence `kb`, raw `repo`) run through `daemon/sanitize.py::sanitize_strict` automatically; trusted blocks (`system`, `user`) skip sanitization.

**Files to change**:
- `daemon/memory/retriever.py` — output blocks become `(trust, content)` pairs
- `daemon/agents/planner.py`, `generator.py`, `evaluator.py` — accept tagged blocks, sanitize accordingly
- `daemon/scanner/repomap.py` — emit `repo` trust tag

**Acceptance gates**:
- [ ] Untrusted blocks run through sanitizer; trusted skip
- [ ] Tests cover: round trip with mixed trust levels; bidi-override in untrusted block gets stripped; benign Unicode in trusted block passes through

**Rationale**: the prerequisite for safely auto-injecting web research and MCP-server output into prompts. Today the sanitizer exists but call sites don't know which blocks are untrusted.

---

### 9-L7 — Confirm-token binding for destructive ops

> ~1 day · Refusal + agent-tool-use plumbing.

When a destructive op is matched (e.g. `rm -rf` on absolute path), the daemon issues a one-time confirm token that the agent must echo in its retry. Defeats the "model jailbreaks itself into bypass" failure mode by making confirmation a structured handshake the agent can't fake.

**Files to add**:
- `daemon/confirm_tokens.py` — generate / verify tokens (HMAC-SHA256, 5-minute TTL, scoped to `(session_id, command_hash)`)
- `daemon/refusal.py` — extend `from_destructive_op` to embed a confirm token in `extra` so the agent's retry includes it
- `daemon/safety.py` — the destructive-op classifier accepts an optional `confirm_token` arg and passes the op through if it verifies

**Acceptance gates**:
- [ ] Without token: destructive op refused
- [ ] With valid token: destructive op proceeds
- [ ] Token bound to specific `(session, command)`: token from session A doesn't unblock session B
- [ ] Token expires after 5 minutes
- [ ] Tests cover: token round-trip, scope binding, expiry, malformed token

**Rationale**: the gap between `bypass mode` (user-mediated, all-or-nothing) and `auto mode` (no per-op confirmation). Confirm tokens give the user a per-op opt-in without flipping the whole session into bypass.

---

### 9-L8 — Per-project Anthropic prompt-cache key isolation

> ~0.5 day · Adapter change.

Today all Anthropic API calls share a global prompt cache key. Means a sprint in project A could (in theory) hit a cache entry seeded by project B. Per-project key fixes that.

**Files to change**:
- `daemon/executors/claude_code.py` (and any direct Anthropic adapter) — inject `anthropic-cache-key` header derived from `hashlib.sha256(project_path).hexdigest()[:16]`
- Document in [DECISIONS.md](DECISIONS.md) as a small follow-up to ADR-007

**Acceptance gates**:
- [ ] Two projects produce different cache keys
- [ ] Same project across runs produces the same key (cache stays warm)
- [ ] Tests cover: derivation, header presence

**Rationale**: defense in depth against cross-project prompt-cache leakage. Probably not exploitable today but trivial to fix and aligns with local-first ethos.

---

### 9-L11 — Strict CSP + no remote images in UI

> ~0.5 day · Next.js config.

Add a strict Content Security Policy header to the Next.js dashboard and a `next.config.js` rule blocking remote image domains. Closes the "malicious page injects an `<img src=evil>` to leak a CSRF cookie" class of attacks.

**Files to change**:
- `ui/next.config.js` — `images.domains = []` (no remote images), CSP middleware
- `ui/middleware.ts` — `Content-Security-Policy: default-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self' ws://127.0.0.1:9111;`

**Acceptance gates**:
- [ ] Browser DevTools shows CSP header on every response
- [ ] An external image URL in a markdown KB item renders as broken (intended)
- [ ] WebSocket to `127.0.0.1:9111` still works (connect-src allow)

**Rationale**: belt-and-suspenders given the Origin check (Layer 10). Pure frontend config; trivial.

---

### 9-L13 — Pre-egress secret redaction at model-API boundary

> ~1 day · Adapter change.

Today `daemon/redact.py` redacts at persistence boundaries (DB, JSONL, log). It does NOT redact at the LLM-API egress boundary by default — the rationale was "users may legitimately want to send secrets they're debugging." Layer 13 makes that opt-in: `FORGE_REDACT_PROMPTS=1` activates pre-egress redaction so a stray `.env` in the diff doesn't reach Anthropic / OpenAI.

**Files to change**:
- `daemon/agents/generator.py::_build_prompt` — when `os.environ.get("FORGE_REDACT_PROMPTS") == "1"`, run the assembled prompt through `daemon.redact.redact` before dispatch
- `daemon/agents/evaluator.py` — same for the diff sent to the evaluator
- Document in `docs/SECURITY_AUDIT.md` and `docs/configuration.md`

**Acceptance gates**:
- [ ] With `FORGE_REDACT_PROMPTS=1`: a sprint that prints an Anthropic key in the diff sends `[REDACTED:ANTHROPIC]` to the model API, not the key
- [ ] Without the env var: behavior unchanged (default off, opt-in)
- [ ] Tests cover: prompt redaction on / off, evaluator diff redaction

**Rationale**: defense in depth for users who don't want to think about it. Default-off because aggressive prompt redaction can break legitimate "debug this OAuth flow" prompts.

---

## Future / unscoped (needs design discussion)

These are big enough that an issue + design discussion comes before code. Open one if you want to lead.

### Sprint 8 — Media layer (image / video / multimodal)

The plan lives in [SPRINT_6_PLAN.md](SPRINT_6_PLAN.md#sprint-8). Three reference providers:
- `forge-media-comfyui` (local SDXL / Flux Schnell on Apple Silicon MPS)
- `forge-media-replicate` (Flux Schnell $0.003/img + Flux Pro + Veo 3.1 Lite)
- `forge-media-openai-image` (gpt-image-1 family)

Plus the `MediaProvider` plugin contract, asset storage, multimodal input pipeline, NSFW post-filter, C2PA verification, MediaPanel UI.

Total: ~17 days. Needs ComfyUI install + GPU access + paid-API credentials for testing. **Best done as a sub-project with its own contributor team.**

### Frontier-model LLM adapters

Cohere, Mistral, Groq, Cerebras, Fireworks — each is one file in `daemon/llms/` plus a registry entry. Pick one, follow the existing Anthropic / OpenAI-compatible / Ollama shape in `daemon/llms/registry.py`, add a manifest at `~/.forge/llms/<provider>/manifest.toml`, ship.

### IDE plugins

ACP sidecar enables Continue.dev / Cline / Zed integration. Open question: do we ship a VS Code extension natively, or rely on ACP? Discussion needed.

### Cloud / managed mode

Devin's $500/mo segment exists because some teams prefer not-self-hosted. Forge has no plan to ship a managed cloud, but a "BYO server" mode (run the daemon on a VPS, point the dashboard at it) is a small change to the WS bind config (already on the table for v0.2.0).

### Fine-tuned Forge models

OpenHands publishes Devstral-tuned-for-OpenHands. Forge could publish "Qwen3-Coder-tuned-for-Forge-evaluator." High effort, high payoff if the harness pattern reaches enough adoption to justify the training cost. v0.3.0+ topic.

### Python 3.13 free-threaded performance pass

Once free-threading stabilizes, run a benchmark pass — Forge's worktree-per-sprint model maps cleanly to nogil if asyncio isn't the bottleneck. Profile-guided.

---

## How to contribute

1. **Pick an item from "Open for contributors."** Comment on the linked GitHub issue (one per sprint will be filed at v0.1.0 launch). Or open a fresh issue if there isn't one yet.
2. **Read the entry's "Where to start" pointer.** Most items reuse an existing module shape — don't reinvent.
3. **Run the local pre-push gate before pushing.** `pre-commit run --all-files` covers lint, format, secret scan, large-file check. CI is intentionally light; we trust the local gate.
4. **Open a draft PR early.** Describe the contract first, code second. The maintainer will review for shape before you sink days into implementation.
5. **Tests are mandatory but the bar is "every public symbol has a happy-path test + every error path has a test."** Aim for the discipline you see in `tests/test_plugin_dispatch.py` (real subprocess where the contract requires it; mocks where it doesn't). Coverage gate is ≥80% on `daemon/` core.
6. **No CLA, no DCO, no copyright assignment.** MIT means MIT. Sign your commits if your platform requires it; otherwise ship.

---

## What this roadmap is NOT

- **Not a marketing pitch.** The acceptance gates are real; the open / shipped split is honest.
- **Not exhaustive.** A long tail of polish work (better error messages, doc fixes, CI cleanup) lives in GitHub Issues, not here. This roadmap is for *coherent feature work that needs spec to start*.
- **Not a deadline.** v0.1.0 ships when Phase 8's SWE-bench gate passes. No earlier; no later. If the gate doesn't pass, the project pivots or shuts down per [ADR-015](DECISIONS.md). That's the contract.
- **Not the planner's input.** [SPRINT_6_PLAN.md](SPRINT_6_PLAN.md), [DELIVERY_PLAN.md](DELIVERY_PLAN.md), and [HANDOVER.md](HANDOVER.md) are the maintainer's planning surfaces. ROADMAP.md is the *contributor* surface — what's open, what's shippable, what's spec'd.
