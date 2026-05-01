# Forge — Handover Brief

> **Purpose**: a fresh chat session can read this document and immediately pick up where we left off without context loss. Updated 2026-05-01 — Sprints 6.1–6.4 + 7.1/7.3/7.4/7.6/7.10 + Sprint 9 L5/L10 closed.

---

## In one paragraph

Forge is a multi-agent coding orchestrator (planner / generator / cross-family-evaluator) that runs locally on open-weight LLMs by default, with a persistent SQLite KB that compounds across sessions. We are at **Phase 1 Sprints 6.1–6.4 + Phase 2 (Claude Code parity) Sprints 7.1/7.3/7.4/7.6/7.10 + Phase 4 (security) layers 5 + 10 all complete** — plugin runtime wired end-to-end, mode picker actually changes daemon behavior, daemon-side slash handlers + custom slash commands from `.forge/commands/*.md`, AGENTS.md root-to-leaf walk, output styles registry, refusal templates, lifecycle hooks (PreToolUse / PostToolUse / SessionStart / SubagentStop / PreCompact), Unicode + bidi-override sanitizer, WebSocket Origin allow-list. The next code-side milestone is **Sprint 7.2 (Subagents) + 7.5 (Memory tool) + 7.8 (apply_patch adapter)**. The next external-infrastructure milestone is **v0.1.0 — Tauri v2 desktop wrapper + code signing + GitHub Releases pipeline + SWE-bench eval** (Phases 6/7/8 of `docs/DELIVERY_PLAN.md`).

---

## Verify state in 30 seconds

```bash
cd /Users/palmegyes/Development/forge

# 1. Tests must be green
PYTHONPATH=. .venv/bin/pytest tests/ --no-header -q | tail -3
# Expect: 894 passed, 1 skipped

# 2. Lint + format must be clean
.venv/bin/ruff check daemon tests forge_plugin_api | tail -3
.venv/bin/ruff format --check daemon tests forge_plugin_api | tail -3

# 3. Commit log
git log --oneline | head -15

# 4. Working tree clean
git status --short
# Expect: empty (Sprint 6.1 closed)

# 5. Sanity-import everything (incl. Sprint 6.1 surfaces)
PYTHONPATH=. .venv/bin/python -c "
from daemon import wizard, billing, scheduler, recovery, events
from daemon.connectors import ConnectorRegistry
from daemon.skills import is_blocked_combination, PluginsLock, SkillTampered, dispatch_plugin
from daemon.llms import list_llms
from forge_plugin_api import Connector, Tool, LLMAdapter, CapabilityViolation, make_http_client
from daemon.wizard import confirm_capability_changes
from daemon.cli import cmd_connectors, cmd_skills
print('all imports ok')
"
```

If any of those fail, troubleshoot before continuing.

---

## Where the work is

| Layer | Path | Lines | Status |
|---|---|---|---|
| Daemon (Python 3.12) | `daemon/` | ~13,500 | Functional — Phase-1 done + Phase-2 parity 5/10 + Phase-4 layers 5/10/12/15 |
| Plugin author API | `forge_plugin_api/` | ~700 | Adds `http.py` egress shim — `Connector`, `Tool`, `LLMAdapter`, `MockSandbox`, `FakeHttpClient`, `CapabilityViolation`, `GuardedAsyncClient`, `make_http_client` |
| Reference plugins | `reference_plugins/` | 2 plugins | `git/` (read-only worktree ops) + `web_research/` (allow-listed HTTP fetch); SKILL.md + manifest.toml + scripts/main.py each |
| UI (Next.js) | `ui/` | ~2,400 | Builds clean (`next build` ok); 12 components incl. ContextMeter / ModePicker / TranscriptView / AttachMenu / SlashCommandPalette / OutputStream / MetadataBar |
| Mockups | `mockups/` | 5 HTML files + index | Saved 2026-05-01; **the contract for Sprint 6.5 UI rebuild** |
| Install scripts | `install.sh`, `uninstall.sh` | ~700 | 9-phase interactive installer; `--check` / `--yes` / `upgrade` modes |
| Tests | `tests/` | 51 files | 894 passing, 1 skipped (mcp extra) |
| Docs | `docs/` | 14 files | All current — see Master Plan below |

---

## Decisions locked

| ADR | Decision |
|---|---|
| ADR-001 | License: MIT, free, no monetization gates |
| ADR-002 | Architecture A — open-weight first, M-series Mac primary target |
| ADR-003 | Open-weight model defaults: gpt-oss:20b / qwen3-coder-next / qwen3.6:27b / deepseek-v4-flash |
| ADR-006 | Three-agent invariants — generator never self-evaluates; evaluator from different family |
| ADR-007 | Local-first; zero telemetry; KB stays in `.forge/` |
| ADR-013 | Sandbox: git worktrees default; Docker as opt-in tier |
| ADR-015 | **Hard kill: SWE-bench Verified ≥30% on 50-task subset by week 11** |
| ADR-017 | Outbound credential redaction at every persistence + subprocess boundary |

Plus 9 more — see `docs/DECISIONS.md`. **Don't reverse a locked ADR without writing a superseding ADR.**

---

## Recent decisions made this session (not yet ADRs)

| | Decision | Rationale |
|---|---|---|
| D-S6-1 | **Tauri v2 + Python sidecar + Next.js webview** is the v0.1.0 stack | Goose migrated this way 2026; 5 MB binary, signed updater, low risk, 95% code reuse |
| D-S6-2 | Skip full Rust rewrite of daemon | 12 weeks of risk for distribution gains a 5 MB Tauri shim delivers |
| D-S6-3 | Skip Electron | Goose's Discussion #7332 documents migration AWAY from Electron (150 MB → 5 MB) |
| D-S6-4 | Skip Textual TUI for v0.1.0 | User wants desktop app first; CLI / TUI is power-user mode |
| D-S6-5 | `$`-meter conditional via daemon-side tier detection | Per `daemon/billing.py` — pure-Ollama users see no `$` text; API-keyed users see live spend |
| D-S6-6 | Plugin runtime sandbox approach | Subprocess isolation + POSIX rlimit + filtered env + signed manifest hash pinning + lethal-trifecta gate at scheduler level |

If any of these become contentious, write them up as ADR-018+.

---

## Master plan (the contract)

**Read this in order if you're a fresh chat:**

1. **`docs/DELIVERY_PLAN.md`** — the master 16-week plan to v0.1.0 (776 lines). Contains: vision, architecture decision matrix, 10 phases, per-mockup component matrix, code-signing prerequisites, GitHub Releases workflow, Homebrew tap formula, pre-launch checklist (~80 items), risk register, resource estimate.
2. **`docs/SPRINT_6_PLAN.md`** — Sprint 6 / 7 / 8 detail (530 lines). Sprint 6.0 marked done; 6.1+ is the next concrete work.
3. **`mockups/index.html`** — the 5 designs the UI rebuild targets. Open in any browser; or `open -a Firefox mockups/`.
4. **`docs/GAP_ANALYSIS.md`** — release gates + 9-sprint roadmap; mostly subsumed by DELIVERY_PLAN but useful reference for risk register.
5. **`docs/SECURITY_AUDIT.md`** — 12 attack classes + 15-layer adoption plan (Phase 4 of DELIVERY_PLAN).
6. **`docs/PROMPTS_AND_GUARDRAILS.md`** — every system prompt + guardrail with file:line citations.
7. **`docs/CONNECTORS.md`** / **`docs/SKILLS.md`** / **`docs/PLUGIN_DEVELOPMENT.md`** / **`docs/LLMS.md`** — plugin ecosystem author guides.
8. **`docs/COMPETITIVE_COMPARISON.md`** — head-to-head with 18+ competitors incl. OpenClaw + Ruflo deep-dives.
9. **`docs/DECISIONS.md`** — 17 locked ADRs.
10. **`README.md`** — public-facing pitch.

---

## What's next, concretely

**Sprints 6.1 → 6.4 all DONE.** Plugin runtime, mode enforcement, slash handlers, and reference connectors — every acceptance gate verified end-to-end (many with real-subprocess tests).

| # | Task | What landed | Test file |
|---|---|---|---|
| 6.1.1 | Plugin dispatcher wired into scheduler | `daemon/skills/dispatch.py::dispatch_plugin` ties hash verify + trifecta + sandbox + audit; re-exported from `daemon.scheduler` | `tests/test_plugin_dispatch.py` (7 tests, 2 real subprocess) |
| 6.1.2 | Egress filter shim wrapping `httpx.AsyncClient` | `forge_plugin_api/http.py` — `GuardedAsyncClient`, `make_http_client`, `CapabilityViolation`; `Connector` / `LLMAdapter` defaults updated | `tests/test_plugin_http.py` (16 tests) |
| 6.1.3 | Append-only `skill_invocations` table + write-once trigger | `daemon/db.py` schema + `record_invocation_start` / `record_invocation_finish` / `list_invocations`; UPDATE/DELETE refused by trigger | `tests/test_skill_invocations_audit.py` (10 tests) |
| 6.1.4 | Manifest hash pinning via `.forge/plugins.lock` | `daemon/skills/lock.py` — `PluginsLock`, `LockEntry`, `SkillTampered`, `default_lock_path`; TOML format, schema-versioned | `tests/test_plugins_lock.py` (17 tests) |
| 6.1.5 | Capability-change re-approval prompt | `daemon/wizard.py::confirm_capability_changes` + `find_widened_capabilities`; pure narrowing auto-approves; widening prompts default-N | `tests/test_capability_reapproval.py` (12 tests) |
| 6.1.6 | `forge connectors/skills test <name>` CLI healthchecks | `daemon/cli.py::cmd_connectors` / `cmd_skills` with `add` / `install` / `list` / `test` / `remove` actions | `tests/test_cli_plugin_commands.py` (13 tests) |
| 6.2 | UI mode picker actually changes daemon behavior | `daemon/mode.py` — `ModeState` + `mode_prompt_addendum`; scheduler `plan` skips wave loop; `bypass` logs WARNING; `ask` injects prompt addendum | `tests/test_mode_enforcement.py` (16 tests) |
| 6.3 | Real daemon-side slash command handlers | `daemon/slash.py` — 11-command registry (`/help`, `/clear`, `/quit`, `/mode`, `/model`, `/memory`, `/budget`, `/connectors`, `/skills`, `/llms`, `/wizard`); `dispatch_slash` re-exported via WS | `tests/test_slash_handlers.py` (21 tests) |
| 6.4 | Reference connectors (git + web_research) | `reference_plugins/git/` (read-only worktree ops with op + flag allow-lists) and `reference_plugins/web_research/` (allow-listed HTTP fetch via egress shim) | `tests/test_reference_connectors.py` (8 tests, 6 real subprocess) |

**Acceptance gates verified:**
- ✓ A tampered plugin file refuses to run with `SkillTampered` (test: `test_tampered_plugin_refuses_to_run`)
- ✓ A plugin trying to fetch a non-allowlisted URL raises `CapabilityViolation` (test: `test_egress_to_non_allowlisted_host_raises_capability_violation` — real subprocess; also the `web_research` reference connector via `test_web_research_refuses_non_allowlisted_url`)
- ✓ The audit log shows every invocation (test: `test_every_invocation_writes_two_rows`)
- ✓ Five-mode picker actually branches daemon behavior — plan halts after planning, ask injects an instructional preamble, bypass emits an audit warning, auto/accept_edits run end-to-end (test: `test_scheduler_skips_wave_execution_in_plan_mode`)
- ✓ Slash commands typed in TUI / web command bar reach real daemon handlers (test: `test_ws_server_routes_slash_through_dispatcher`)
- ✓ Reference plugins demonstrate the contract end-to-end — git read-only ops + narrow-allow-list egress

### Sprint 7 (Phase 2 parity) — what landed

| # | Task | What landed | Test file |
|---|---|---|---|
| 7.1 | Hooks system (PreToolUse / PostToolUse / SessionStart / SubagentStop / PreCompact) | `daemon/hooks.py` — Claude-Code-compatible JSON-on-stdin / JSON-on-stdout contract; SessionStart wired into `scheduler.execute_session`; remaining call sites land alongside the per-event use cases | `tests/test_hooks.py` (18 tests) |
| 7.3 | Custom slash commands from `.forge/commands/*.md` | `daemon/custom_commands.py` — minimal YAML-frontmatter parser, `discover_commands(project)` walking both `.forge/` and `.claude/` (Forge overrides Claude); slash dispatcher resolution chain extended | `tests/test_custom_commands.py` (22 tests) |
| 7.4 | AGENTS.md root-to-leaf walk in scanner | `daemon/scanner/claude_code.py::read_agents_md` walking project root → cwd, AGENTS.override.md > AGENTS.md per level, populated into `ProjectContext.agents_md` | `tests/test_agents_md.py` (10 tests) |
| 7.6 | Output styles registry | `daemon/output_styles.py` — five built-ins (default / terse / explanatory / strict-reviewer / pr-bot) + user overrides at `.forge/output-styles/*.md`; `style_addendum(name)` returns the system-prompt addendum | `tests/test_output_styles.py` (14 tests) |
| 7.10 | Refusal templates | `daemon/refusal.py` — Claude-Code-shaped structured refusals for destructive-op blocks, hook blocks (PreToolUse / PostToolUse), egress capability violations, and SkillTampered hash mismatches | `tests/test_refusal_templates.py` (12 tests) |

### Sprint 9 (Phase 4 security layers) — what landed in this run

| Layer | Description | Status |
|---|---|---|
| L5 | Unicode + bidi-override sanitizer | `daemon/sanitize.py` — Pillar Security 2025 defense; covers bidi controls, ZWSP, tag chars, BOM, variation selectors. Idempotent. `tests/test_sanitize.py` (19 tests) |
| L10 | WebSocket Origin allow-list | `daemon/ws_server.py::_origin_allowed` — rejects cross-site WS hijack with code 4403 before any message handler runs; CLI/TUI (no Origin) unaffected. `tests/test_ws_origin_check.py` (11 tests) |

### What's NOT yet done — and why

**Sprint 7.2 (Subagents)** — `.forge/agents/<name>.md` registry + planner auto-delegation. Architecturally larger; needs planner-side semantic match against agent descriptions. Defer to next session. ~3 days of focused work.

**Sprint 7.5 (Memory tool)** — Anthropic's view/create/str_replace/insert/delete/rename tool over `.forge/memories/<session>/`. Requires generator-tool-call wiring + compaction-event flush. ~2 days. Plumbing depends on 7.2.

**Sprint 7.7 (Sandbox profiles)** — `sandbox-exec` / `bwrap` profile generation per sprint. OS-specific; needs runtime testing on each platform. ~3 days.

**Sprint 7.8 (apply_patch adapter)** — V4A diff format adapter for Codex CLI. ~150 LOC but needs a Codex-family LLM adapter to test against. ~1 day once the LLM is wired.

**Sprint 7.9 (Background / scheduled sprints)** — cron loop in scheduler + native notifications. ~3 days.

**Sprint 8 (Media layer)** — image / video / multimodal MCP plugins. 17 days; requires ComfyUI / Replicate / OpenAI provider integrations and a real GPU for `forge-media-comfyui` integration tests.

**Sprint 9 layers L1, L7, L8, L11, L13** — provenance tagging, confirm-token binding, prompt-cache key isolation, strict CSP, pre-egress secret redaction. Each needs its own session of focused work. L13 is partially in place (`daemon/redact.py` redacts at persistence boundaries; pre-LLM-prompt redaction is the missing piece).

**Sprint 6.5 (UI rebuild from mockups)** — Next.js components need to be re-laid-out to match the 5 HTML mockups. ~5 days of frontend work; the existing 12 components compile and the WS protocol is stable, so this is design-implementation, not architecture.

**Phases 6–10 (Tauri v2 wrapper, code signing, distribution, SWE-bench eval, launch)** — needs external infrastructure (Apple Developer ID, Tauri toolchain, GitHub Releases CI, SWE-bench harness, signing servers). Not buildable in a code-only chat session; requires the user's involvement for sign-up flows and credential provisioning.

---

## Pending sign-off from the user

The DELIVERY_PLAN.md ends with a sign-off section asking for 4 explicit confirmations before Phase 1 begins:

1. Acknowledge the scope — 16 weeks of focused single-developer work + ~$700 out-of-pocket
2. Confirm the kill criterion — SWE-bench <30% at week 11 = halt
3. Approve the architecture — Tauri v2 + Python sidecar + Next.js webview
4. Greenlight Phase 1 start — Sprint 6.1 plugin runtime

**As of session end the user has NOT explicitly signed off all four**, but the working assumption (auto mode active throughout) is they'll greenlight when ready. Default in auto mode if user doesn't object: **start Phase 1 / Sprint 6.1 next session**.

---

## Open questions left for the user

1. **Domain**: do they own `forge.dev` or want a different name? The plan assumes that domain throughout.
2. **GitHub org**: where will the repo live publicly? Plan uses `yourorg/forge` placeholder.
3. **Apple Developer ID**: do they already have one, or should the plan factor in 1–7 days enrollment lead time?
4. **Windows EV cert**: do they want native Windows from day one, or ship Mac+Linux first and add Windows in v0.1.1?
5. **Pen-test budget**: $5k–15k optional — sign off pre-launch or defer to post-launch with rapid-response SLA?
6. **Discord / community**: priority for launch or post-launch?
7. **Bug bounty pool**: starting amount?

None of these block Phase 1. They become relevant at Phase 7 (sign + distribute) and Phase 10 (launch).

---

## Auto-mode behavior contract

The user has been operating in **auto mode** throughout the session. That means:

- Execute immediately, prefer action over planning
- Make reasonable assumptions for routine decisions
- Don't ask permission for low-risk work (lint fixes, tests, doc updates, refactors)
- Confirm only for high-risk work (destructive ops, third-party services, irreversible changes)
- Treat course-corrections from the user as normal input

**Inferred preferences from session behavior:**

- User likes per-task atomic commits with detailed bodies (see `git log` for the cadence)
- User likes mockups + diagrams to ground decisions (5 HTML mockups committed)
- User wants research-informed decisions (we ran 4 background research agents this session)
- User pushes back when the plan is incomplete — when in doubt, plan more thoroughly
- User wants pragmatic recommendations, not menu-of-options ad nauseam — "what would work best for me" got a direct answer

---

## Recent significant commits (last 12)

```
40fa041 docs(delivery): comprehensive 16-week delivery plan to v0.1.0
[mockups] docs(mockups): 5 dark-themed HTML mockups + gallery index
9cdfaa2 docs(plan): full Sprint 6+ task list to v0.1.0 (research-informed)
e2cd23b chore(install): forge[dev] extra + clearer Python <3.10 error
60d3201 feat(billing): daemon-side tier detection — $-meter shows only when paid
d3d4fd0 docs(prompts): full prompts + guardrails audit (planner/generator/evaluator)
cfc210f feat(ui): wire new components into page.tsx + extend useForgeSocket
187ccb1 feat(ui): Claude-Code-style components — mode picker, slash palette, output stream, …
860ab98 feat(ws_server): handlers for mode picker / slash commands / connectors API
d708ea3 feat(wizard): first-run connector setup wizard + auto-trigger hooks
cb6d9d9 docs(changelog): install + plugin ecosystem + security audit entry
c66f57f test(plugins): manifest gates + lethal trifecta + registry + public API
```

For the full history: `git log --oneline | wc -l` → ~50 commits since session start.

---

## Background research agents fired this session (results in conversation transcript)

1. **Code-review fix sweep** — 24 tasks across 4 sprints; all but 2 deferred ones landed
2. **Agentic-tool exploits 2024–2026** — 12 attack classes + 15 prioritized Forge mitigations (now in SECURITY_AUDIT.md)
3. **OpenClaw deep-dive** — Enderfga/openclaw-claude-code differentiation matrix (now in COMPETITIVE_COMPARISON.md)
4. **Ruflo + top-5 GitHub field** — OpenHands / opencode / Cline / Goose / Aider comparisons (now in COMPETITIVE_COMPARISON.md)
5. **Claude Code + Codex feature inventory** — top 10 features Forge should adopt (Sprint 7 plan in SPRINT_6_PLAN.md)
6. **Image / video / multimodal integration** — MCP-as-the-surface convention; 3 reference providers planned (Sprint 8 plan in SPRINT_6_PLAN.md)
7. **Codex desktop architecture** — Tauri v2 vs Electron decision matrix (folded into DELIVERY_PLAN.md Part 2)

**Don't re-run these unless they're genuinely stale.** The findings are committed and stay valid for at least Q3 2026.

---

## Things NOT to do (footguns)

1. **Don't run `--no-verify` on git commits.** Pre-commit hooks (gitleaks, ruff, format, detect-private-key) are load-bearing.
2. **Don't `git rebase -i` published commits.** This branch hasn't been pushed yet but if anyone else has cloned it, force-push is destructive.
3. **Don't add telemetry of any kind.** ADR-007 is locked. Even "anonymized usage stats" requires a superseding ADR.
4. **Don't put `print()` in `daemon/`.** Lint rule blocks it. Use `logging`.
5. **Don't use `shell=True` in subprocess calls.** Forbidden by lint + security rule.
6. **Don't bind WebSocket server to `0.0.0.0`.** Hardcoded `127.0.0.1` is required (ADR-013).
7. **Don't store credentials anywhere.** The wizard explicitly does NOT write secrets to disk; env vars or `.env` only.
8. **Don't skip the SWE-bench eval at Phase 8.** ADR-015 hard kill is the contract; <30% means halt, not "ship anyway and fix later."
9. **Don't change the agent system prompts without a regression test.** Files at `daemon/agents/{planner,generator,evaluator}.py`; behavior is tested in `tests/test_planner.py` / `test_evaluator.py`.
10. **Don't use UI strings without typed message contracts.** WebSocket message envelope is intentionally open (`{type: string; ...}`) for forward compat, but new event types should land in `daemon/events.py::EventType` enum first.

---

## Environment

| | Value |
|---|---|
| OS | macOS 25.4.0 (Darwin) |
| Python | 3.12.13 (homebrew); rebuilt venv 2026-05-01 |
| Node | npm + next.js 14 in `ui/` (deps installed) |
| Working dir | `/Users/palmegyes/Development/forge` |
| Git branch | `develop` (no remote pushed yet) |
| Git user | Pal Megyes <pal.megyes@ift.xyz> |
| Shell | zsh |
| Editor of record | (user does manual edits between turns; verify with `git status` first) |

**The user manually edits files between turns.** Several `<system-reminder>` notes during the session noted modifications to `daemon/wizard.py`, `forge_plugin_api/llm.py`, `forge_plugin_api/connector.py`, etc. **Always check `git status` and read the current file before editing.**

---

## TL;DR for a fresh chat

> "We're building a desktop coding-agent app. Plan is locked at `docs/DELIVERY_PLAN.md` — 16 weeks, Tauri v2 + Python sidecar, ~$700 out-of-pocket. **Sprints 6.1–6.4 + Sprint 7 parity (7.1/7.3/7.4/7.6/7.10) + Sprint 9 layers 5/10 all done** — plugin runtime, mode picker, slash handlers + custom slash commands, AGENTS.md walk, output styles, refusal templates, lifecycle hooks, Unicode sanitizer, WS Origin check. Tests at 894 passing, lint+format clean. Next code-side: Sprint 7.2 Subagents, 7.5 Memory tool, 7.8 apply_patch. External-infrastructure work (Tauri wrapper / code signing / SWE-bench eval) needs the user's involvement and isn't buildable in a code-only chat. The user is in auto mode."

Welcome to Forge.
