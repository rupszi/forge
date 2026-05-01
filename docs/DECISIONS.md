# Forge — Locked Architectural & Project Decisions

This document is the **permanent record** of major decisions for Forge. ADR-style: each decision is dated, has a rationale, lists alternatives considered, and explicitly notes the trade-off accepted. Changes to a locked decision require a new ADR entry that supersedes the old one — never edit history in place.

> **Status of this document**: live. Append new ADRs at the bottom; never delete.
>
> **Linked from**: [BUILD_PLAN.md](BUILD_PLAN.md), [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md), [COMPETITIVE_COMPARISON.md](COMPETITIVE_COMPARISON.md), [CLAUDE.md](../CLAUDE.md).

---

## Table of decisions

| # | Date | Decision | Status |
|---|---|---|---|
| ADR-001 | 2026-04-30 | License: MIT, free, no monetization gates | **locked** |
| ADR-002 | 2026-04-30 | Architecture A — spec-hardened for open weights | **locked** |
| ADR-003 | 2026-04-30 | Open-weight model defaults (post Apr-22/23 releases) | **locked** |
| ADR-004 | 2026-04-30 | Pre-push > CI; conditional gate with `SKIP_*` escape hatches | **locked** |
| ADR-005 | 2026-04-30 | Schema parity rule across 5 surfaces | **locked** |
| ADR-006 | 2026-04-30 | Three-agent invariants (planner / generator / cross-family evaluator) | **locked** |
| ADR-007 | 2026-04-30 | Local-first; no telemetry; KB stays in `.forge/` | **locked** |
| ADR-008 | 2026-04-30 | Workflow tool: uv; build backend: hatchling; lockfile: `uv.lock` committed | **locked** |
| ADR-009 | 2026-04-30 | Lint+format: Ruff. Type: pyright (standard mode). | **locked** |
| ADR-010 | 2026-04-30 | Python floor: 3.10+ (3.11+ recommended); CI matrix 3.11/3.12/3.13 × ubuntu/macOS | **locked** |
| ADR-011 | 2026-04-30 | No agent frameworks (no LangChain/CrewAI/AutoGen/Letta/etc as runtime deps) | **locked** |
| ADR-012 | 2026-04-30 | KB design: SQLite with confidence/decay/dedup; no embeddings on KB; sqlite-vec optional on episodic | **locked** |
| ADR-013 | 2026-04-30 | Sandbox: git worktrees default; Docker as opt-in tier; skip macOS sandbox-exec; skip Windows | **locked** |
| ADR-014 | 2026-04-30 | Surface: browser dashboard for v1; ACP sidecar for v2; skip VS Code-specific extension | **locked** |
| ADR-015 | 2026-04-30 | Week-8 SWE-bench Verified ≥30% on 50-task subset = hard kill criterion | **locked** |
| ADR-016 | 2026-04-30 | Sustainability: GitHub Sponsors / Open Collective passive donation rail; no Pro tier in scope for v0.1.0 | **locked** |
| ADR-017 | 2026-05-01 | Outbound credential redaction at every persistence + subprocess boundary | **locked** |

---

## ADR-001 — License: MIT, free, no monetization gates

**Date**: 2026-04-30
**Status**: locked

**Decision**: Forge is licensed MIT. The end-user pays $0 to use it. There is no signup, no telemetry, no API key required to operate, no Forge-side service to gate. Future hosted/Pro tiers are explicitly out of scope for v0.1.0 (revisit only if community demand and sustainability needs justify it).

**Rationale**:
- MIT maximizes adoption and lets the project survive the maintainer's attention drift.
- Local-first means there's no operational tax (no cloud to run, no SLA to honor, no auth system to build).
- The competitive position requires this — every credible OSS coding agent (Aider, OpenHands, OpenCode, Cline, Continue, Goose, smolagents) is Apache/MIT. Closed competitors (Cursor, Devin, Claude Code) win on UX but lose on lock-in resistance, which is Forge's pitch.

**Alternatives considered**:
- Apache 2.0 (compatible; MIT chosen for brevity and zero patent-grant ambiguity)
- AGPL (rejected — incompatible with the "lift Aider's repomap" plan; Aider is Apache 2.0)
- Source-available / BSL with a future Apache transition (rejected — adds operational complexity, signals "we'll commercialize later," undermines the local-first ethos)
- Closed source with paid tier (rejected — out of character for Forge's positioning and would compete head-on with Cursor/Devin which are far better resourced)

**Trade-off accepted**: no direct revenue from end users. Sustainability via passive donations + sponsor-funded features + (eventually, optionally) hosted Pro tier.

**Required to operate (user-side, all $0 by default)**:
- Hardware (≥16 GB RAM minimum; 24 GB+ recommended; primary target M-series Mac 48 GB)
- Their electricity
- ~10 minutes setup time
- **Optional**: API credits for frontier models if they BYO key (Anthropic / OpenRouter / Together) — payment goes to those providers, never to Forge.

**Implication**: see [README.md](../README.md) for the public-facing version of this commitment.

---

## ADR-002 — Architecture A: spec-hardened for open weights

**Date**: 2026-04-30
**Status**: locked

**Decision**: Forge ships Architecture A from the [competitive landscape and architecture report §3.1](research/competitive-landscape-and-architecture.md#311-architecture-a--forge-as-specified-hardened-for-open-weights) — keep planner/generator/evaluator + worktrees + SQLite + cross-family evaluator. Add three-layer tool-call defense (native parser + xgrammar + BAML). Add Aider's `repomap.py` (MIT). Hardware target: M4 Pro 48 GB. **Architecture B (swarm-first) and Architecture C (single strong agent) are explicitly rejected for v0.1.0.**

**Rationale**:
- Cross-model evaluation > self-evaluation is the strongest published finding (MT-Bench self-bias quantified at +25% for Claude-v1, +10% for GPT-4)
- Plan-and-Solve > one-shot is the well-established baseline (Wang et al. arxiv 2305.04091)
- Verbal feedback loops > single-pass is well-supported (Reflexion, Self-Refine ~20% gain)
- Architecture B's coding gains don't justify 3-5× token cost; Anthropic explicitly carves out coding as a domain where multi-agent fan-out underperforms; M4 Pro 48 GB cannot run 3 parallel 20+ GB models simultaneously
- Architecture C throws away ~95% of existing 3 K LOC; no thank you

**Alternatives considered**:
- Architecture B (swarm-first, N=3 parallel generators with voting evaluator) — rejected as default; reserved as opt-in *Self-Consistency-on-`critical`* mode
- Architecture C (single SWE-agent-style strong agent with CodeAct) — rejected; would require throwing out existing code

**Trade-off accepted**: orchestration overhead must demonstrably pay (Week-8 SWE-bench ≥30%) or kill criterion fires.

**Reference**: [research/competitive-landscape-and-architecture.md §3.1.4](research/competitive-landscape-and-architecture.md).

---

## ADR-003 — Open-weight model defaults (post Apr-22/23 releases)

**Date**: 2026-04-30
**Status**: locked
**Supersedes**: prior tentative defaults from early-April research (Devstral-Small + Qwen3-Coder-30B + gpt-oss:20b)

**Decision**: Forge's default model lineup as of 2026-04-30 is:

| Role | Model | License | Footprint |
|---|---|---|---|
| Planner | `gpt-oss:20b` | Apache 2.0 | ~14 GB |
| Cheap-tier generator | `qwen3-coder-next` (3B-active / 80B MoE) | Apache 2.0 | ~50 GB MoE; 3B active |
| Medium-tier generator | `qwen3.6:27b` | Apache 2.0 | ~16 GB Q4 |
| Premium-tier generator | `deepseek-v4-flash` (13B active) | MIT | ~13 GB Q4 |
| Backup medium-tier | `devstral-small-2507` (24B) | Apache 2.0 | ~15 GB Q4 |
| Reasoner (no tools) | `deepseek-r1-distill-qwen-32b` | MIT | ~20 GB |
| Embeddings | `nomic-embed-text` | Apache 2.0 | ~270 MB |

**Rationale**: the open-weight SWE-bench Verified ceiling moved from ~72% to ~80%+ between early March and end of April 2026 ([freshness check](research/notes/05-competitive-freshness-2026-04-30.md)). Qwen3-Coder-Next + Qwen3.6-27B (Apr 22) + DeepSeek V4-Flash (Apr 23) reflect that ceiling. All defaults are Apache 2.0 / MIT — no commercial-license traps.

**Cross-family enforcement**: the classifier auto-picks an evaluator from a different model family than the generator. Family registry: `qwen3*`/`qwen2.5*` → "qwen", `devstral*` → "mistral", `gpt-oss*` → "openai", `claude-*` → "anthropic", `deepseek*` → "deepseek". Implemented in `daemon/agents/classifier.py`.

**Alternatives considered**:
- Llama 3.3 70B (commercial license <700M MAU is fine but 70B at Q4 leaves ~6 GB on M4 Pro 48 GB; too tight)
- Mistral Large 2 / Codestral (research-only license — disqualified)
- DeepSeek-V3 / R1 (tool-call reliability flaky in production; vLLM has parsers but practical reports describe loops/empty calls)
- Qwen3-Coder-480B (server-class only; for hosted-endpoint users, not laptop default)

**Trade-off accepted**: defaults will need refreshing every 60–90 days as the open-weight leaderboard moves. Procedural memory writeback (Phase 1 Week 6) helps the classifier auto-route to whatever empirically performs best per task pattern.

**Configuration**: env vars in `daemon/config.py` allow override. See [BUILD_PLAN.md → Phase 0 → Pull baseline models](BUILD_PLAN.md#phase-0--pre-flight-week-0-10-hours).

---

## ADR-004 — Pre-push > CI; conditional gate with `SKIP_*` escape hatches

**Date**: 2026-04-30
**Status**: locked

**Decision**: The full quality gate (lint + format + typecheck + tests) runs in **pre-push locally**, not in CI. CI is reserved for things pre-push *cannot* do: security audit on a fresh runner, scheduled CodeQL, cross-OS/Python matrix validation, and (eventually) OIDC PyPI publishing.

**Rationale**: CI minutes are scarce; developer machines are not. Push the slow gate left. Conditional checks (only run what the diff touches) make the heavy gate tolerable. Documented `SKIP_SCHEMA_PARITY=1` / `SKIP_DOCS_AUDIT=1` / `RUN_INTEGRATION=1` / `RUN_SWEBENCH_SMOKE=1` env vars give controlled escape hatches.

**Inherited from**: a private TS/RN reference monorepo (Fittssy) where this pattern is the single biggest engineering opinion. Adapted to Python.

**Alternatives considered**:
- All-CI (rejected — slow feedback, expensive)
- Pre-commit only (rejected — too slow for every commit; we use commit-stage for fast hooks only)
- No quality gate (rejected — engineering bar matters)

**Trade-off accepted**: contributors must run hooks locally. CI catches bypass attempts via the security audit job + OS matrix. See [docs/ENGINEERING_STANDARDS.md §6–7](ENGINEERING_STANDARDS.md#6-cicd) and [scripts/pre-push.sh](../scripts/pre-push.sh).

---

## ADR-005 — Schema parity rule across 5 surfaces

**Date**: 2026-04-30
**Status**: locked

**Decision**: Forge has five surfaces that describe the same data shapes and must be kept in sync via a scripted check (`scripts/check-schema-parity.py`, slated for Phase 1 Week 4). When any of the five files changes, pre-push runs the parity check (skippable with `SKIP_SCHEMA_PARITY=1` only with PR justification):

| Surface | File | Owns |
|---|---|---|
| 1 | `daemon/db.py` | SQLite `CREATE TABLE` statements |
| 2 | `daemon/models.py` | Python dataclasses |
| 3 | `daemon/ws_server.py` | WebSocket event JSON shapes |
| 4 | `ui/lib/types.ts` | TypeScript types for the WS protocol |
| 5 | `daemon/schemas/` | JSON schemas for sprint contracts and evaluator verdicts |

**Rationale**: this is the single biggest production-incident preventer in the reference repo's playbook. Dual-store drift (server schema vs client cache) is a common, expensive class of bug. Encoding it as a script makes it impossible to forget.

**Trade-off accepted**: a small amount of duplicated schema work per change. Worth it.

**Reference**: [docs/ENGINEERING_STANDARDS.md §11 → Schema parity rule](ENGINEERING_STANDARDS.md#schema-parity-rule-the-reference-repos-killer-pattern).

---

## ADR-006 — Three-agent invariants (planner / generator / cross-family evaluator)

**Date**: 2026-04-30
**Status**: locked

**Decision**: Forge maintains four hard invariants that govern all agent code:

1. **Generator never self-evaluates.** The evaluator is a different process.
2. **Evaluator runs on a different model family than the generator.** Cross-family enforced automatically by the classifier (after Phase 1 Week 1). Family registry per ADR-003.
3. **Each evaluator criterion is graded independently** (PASS/FAIL + evidence). No holistic averaging.
4. **Max 2 revision cycles per sprint**, then escalate to user (or trigger ADaPT-style recursive decomposition).

**Rationale**: directly grounded in Anthropic's harness research ("Separating the agent doing the work from the agent judging it proves to be a strong lever") and the MT-Bench self-enhancement-bias paper (Claude-v1 favors itself +25%, GPT-4 +10%).

**Alternatives considered**:
- Same-model evaluator with skeptical prompting (rejected; bias persists per published evidence)
- Holistic averaging of criterion scores (rejected; harness research recommends hard-threshold per criterion)
- Unlimited revisions (rejected; non-converging; ADaPT-style recursive decomposition is the recovery path)

**Trade-off accepted**: cross-family evaluator costs an extra LLM call. Worth it.

---

## ADR-007 — Local-first; no telemetry; KB stays in `.forge/`

**Date**: 2026-04-30
**Status**: locked

**Decision**: All Forge data — KB, episodic store, procedural memory, research cache, session traces — stays in the user's `.forge/` directory. Forge phones home for nothing. No analytics. No crash reporting (no Sentry). No update checks. The WebSocket server binds 127.0.0.1 only and is hardcoded (not configurable).

**Rationale**: Forge's pitch is "Claude Code with a persistent brain that you own and runs locally." Telemetry undermines that. A local-first daemon doesn't need Sentry; a JSONL audit log per session at `.forge/sessions/<id>/trace.jsonl` is the right observability layer.

**Alternatives considered**:
- Optional opt-in telemetry (rejected; opt-in telemetry has historically meant ~3% participation and creates compliance overhead)
- Sentry for error reporting (rejected; out of scope for local-first)
- Auto-update checks (rejected; users update via `git pull` or `pip install --upgrade`)

**Trade-off accepted**: you don't know how many people use Forge. Stars + Discord activity + PyPI download counts are the only signals.

**Implication**: the launch post must explicitly call out "no telemetry, no signup, no signup, no API key required." It's a feature.

---

## ADR-008 — Workflow tool: uv; build backend: hatchling; lockfile: `uv.lock` committed

**Date**: 2026-04-30
**Status**: locked

**Decision**: `uv` (Astral) is the workflow tool (`uv sync`, `uv run`, `uv lock`). `hatchling` is the build backend. `uv.lock` is committed. Setup script falls back to legacy pip + venv for users who haven't installed uv yet.

**Rationale**: uv is 10–100× faster than pip/Poetry/PDM, manages CPython natively, and produces a universal cross-platform lockfile. Astral's acquisition by OpenAI in 2026 introduces some long-term steward uncertainty, but the tool itself is mature and the lockfile format is documented.

**Alternatives considered**: Poetry (slower, doesn't manage CPython), PDM (smaller community), pip directly (no lockfile semantics).

**Trade-off accepted**: contributors need uv installed (one-line install: `curl -LsSf https://astral.sh/uv/install.sh | sh`). Setup script handles the legacy path during transition.

---

## ADR-009 — Lint+format: Ruff. Type: pyright (standard mode).

**Date**: 2026-04-30
**Status**: locked

**Decision**: Ruff handles lint (`ruff check`), format (`ruff format`), import sort, modernization, and security lint. pyright in `standard` mode handles type checking. ty (Astral's new type checker) is on the watch list — revisit Q3 2026 once spec conformance is >70%.

**Rationale**: Ruff is the entire linter+formatter stack now (>99.9% Black-compatible, 30× faster). pyright has the best editor DX (Pylance) and is fast enough for 3 K LOC. mypy is fine but slower with weaker editor support.

**Alternatives**: Black + flake8 + isort + pyupgrade (rejected — Ruff replaces all four). mypy (rejected — pyright preferred). ty/pyrefly (deferred).

---

## ADR-010 — Python floor: 3.10+ (3.11+ recommended); CI matrix

**Date**: 2026-04-30
**Status**: locked

**Decision**: `requires-python = ">=3.10"` in `pyproject.toml`. CI matrix is 3.11 / 3.12 / 3.13 × ubuntu-latest / macos-latest. Python 3.9 (EOL October 2025) and Python 3.10 (EOL October 2026) are not in CI. Windows is skipped (subprocess + path + permission model differences make it a sustained tax for ~5% of users; document "WSL is supported").

**Rationale**: Python 3.11+ unlocks `asyncio.TaskGroup`, `asyncio.timeout()`, `ExceptionGroup`, `tomllib`, `match` statements, and 10–60% startup speedup. Forge's scheduler benefits from TaskGroup directly.

**Trade-off accepted**: until the user's local Python is upgraded to 3.10+, the existing test suite uses `from __future__ import annotations` shims to make `X | None` syntax work on 3.9. Those shims should be removed once the upgrade lands.

---

## ADR-011 — No agent frameworks (no LangChain/CrewAI/AutoGen/Letta/etc as runtime deps)

**Date**: 2026-04-30
**Status**: locked

**Decision**: Forge does not depend on any agent framework as a runtime dependency. Specifically rejected: LangChain / LangGraph (dep gravity), CrewAI (logging gap, lock-in, scales only to ~5 agents), AutoGen (Microsoft put it into maintenance mode), Letta / Mem0 / Zep (server dependencies, wrong abstraction for Forge's KB scale), R2R (vector RAG that Forge doesn't want), smolagents (Apache 2.0 and well-designed; lift the *idea* — code-as-action, `LocalPythonInterpreter` AST sandbox — without taking the dep).

**Rationale**: every framework is a long-term liability. Forge's planner→generator→evaluator pipeline is ~3 K LOC; an agent framework would invert the dependency relationship.

**Alternatives considered**: LangGraph as a clean DAG runtime (rejected — pulls LangChain transitive deps; Forge's DAG is shallow and reimplementable in ~50 LOC).

**Trade-off accepted**: more code to maintain in `daemon/scheduler.py`. Worth it.

**Lift candidates** (copy idea, not lib): Aider's `repomap.py` (MIT, ~500 LOC), smolagents' `LocalPythonInterpreter` (Apache 2.0, ~150 LOC), SWE-agent's `should_block_action` + multiline guard (~30 LOC). All permissively licensed for forking.

---

## ADR-012 — KB design: SQLite with confidence/decay/dedup; no embeddings on KB; sqlite-vec optional on episodic

**Date**: 2026-04-30
**Status**: locked

**Decision**: Knowledge base is SQLite-only with topic-filter + LIKE search. Knowledge items are one-line imperative statements, capped at 200 per project, with confidence scoring (reinforced on success, decayed on failure, pruned at <0.2 or >90 days unused). **No embeddings on the KB.** The episodic store *may* opt-in to sqlite-vec for vector recall on past failures (gated by `FORGE_VECTOR_EPISODES=1`) — sqlite-vec ships as a Python wheel so the dep is minimal.

**Rationale**: at the 200-item KB cap, SQLite LIKE on a topic-filtered subset runs in microseconds. Embeddings would add a model dependency, a vector store, and 768–1536 floats per item with no measurable retrieval-quality gain. The 200-item cap is the design feature — it forces curation quality (the learner) to be the bottleneck.

**Alternatives considered**: Letta (three-tier core/recall/archival; lift the *idea*, not the dep), Mem0 (chat memory, wrong abstraction), Zep / Graphiti (graph DB; heavy), LanceDB (overkill at 200 items), Turbopuffer (managed cloud, violates ADR-007).

**Trade-off accepted**: cross-project KB queries are limited to keyword. Acceptable for v0.1.0; revisit only if users complain.

---

## ADR-013 — Sandbox: git worktrees default; Docker as opt-in tier; skip macOS sandbox-exec; skip Windows

**Date**: 2026-04-30
**Status**: locked

**Decision**: Default isolation is git worktrees (zero startup cost, no security boundary, fine for "agent makes a mistake" threat model). Optional `--sandbox=docker` tier for users who want container isolation (Phase 1 Week 9). `--sandbox=bwrap` opt-in on Linux. **Skip macOS `sandbox-exec`** — Apple deprecated it on 15.4 and field reports describe brittle behavior. **Skip Windows entirely.**

**Rationale**: Forge's threat model is "agent makes a mistake," not "agent is malicious." Worktrees are the correct default. Docker is the correct escalation for users running untrusted dependency installs. macOS native sandboxing is dead; recommend Docker on macOS.

**Trade-off accepted**: macOS users get worktree-only isolation by default (or Docker if they opt in). Windows users use WSL.

---

## ADR-014 — Surface: browser dashboard for v1; ACP sidecar for v2; skip VS Code-specific extension

**Date**: 2026-04-30
**Status**: locked

**Decision**: v0.1.0 ships a Next.js browser dashboard at `localhost:3000` as the only UI. v0.2.0 may add an ACP (Zed Agent Client Protocol) sidecar that lets any ACP-aware editor (Zed today) integrate with Forge. **Skip a VS Code-specific extension** unless adoption demands it.

**Rationale**: browser dashboard is the right shape for *mission control* (multi-worktree visualization, sprint dependency-wave display, KB browser, cost meter). ACP is the open standard for editor↔agent integration; betting on it scales across editors. VS Code Language Model API is for extensions that *consume* a model, not for *being* an agent.

**Alternatives considered**: VS Code extension first (rejected — locks Forge into one editor), JetBrains plugin (rejected — heavy investment), full desktop app via Electron/Tauri (rejected — premature scope).

**Trade-off accepted**: editor-resident developers (Cursor users, Cline users, Continue users) will not switch to a browser dashboard. Acceptable for v0.1.0; ACP closes the gap if adoption demands.

---

## ADR-015 — Week-8 SWE-bench Verified ≥30% on 50-task subset = hard kill criterion

**Date**: 2026-04-30
**Status**: locked
**Supersedes**: prior ≥25% threshold (raised after Apr-30 freshness check)

**Decision**: At the end of Phase 2 Week 8 of [BUILD_PLAN.md](BUILD_PLAN.md), Forge must score ≥30% on a 50-task SWE-bench Verified subset (recommended: the django subset) using the full open-weight stack (Devstral-Small + Qwen3-Coder-Next + DeepSeek V4-Flash + cross-family evaluator). Below 30%, the open-weight thesis fails for self-host and the project pivots or shuts down. Do not iterate past Week 8.

**Rationale**: OpenHands SDK V1 hits 72% with Sonnet 4.5 + extended thinking. Forge's multi-agent overhead must demonstrably pay something to justify the engineering cost. The open-weight ceiling moved from ~72% to ~80%+ in 60 days, so the bar moved from 25% to 30%.

**Pivot options if <30%**:
1. Make Anthropic API the default; keep open-weight as opt-in
2. Reposition as "the open-weight harness for SOTA open models" and re-run with MiniMax M2.5 / DeepSeek V4 full
3. Shut down

**Trade-off accepted**: hard commitment to fail fast. No iteration past Week 8.

---

## ADR-016 — Sustainability: passive donation rail; no Pro tier in v0.1.0 scope

**Date**: 2026-04-30
**Status**: locked

**Decision**: For v0.1.0, the only sustainability lever is **GitHub Sponsors / Open Collective** as a passive donation rail. No paid features. No hosted tier. No SLA. No support contract.

If post-launch the project gains traction (target: 1,000+ GitHub stars, active Discord, sponsor-funded feature requests), revisit at month 6 with options:
1. **Sponsor-funded features** (Linux Foundation Agentic AI Foundation model — Goose, MCP, AGENTS.md): companies fund specific features that ship in OSS for everyone
2. **Optional hosted Forge Pro tier**: multi-user team mode (shared KB across a company, audit log compliance, SSO) as paid SaaS while OSS stays unmodified
3. **Drop maintenance and let the community fork** (MIT enforces this is always an option)

**Rationale**: a solo maintainer cannot operate a managed service while building. The OSS path is sustainable at ~10 hours/week post-launch with zero infrastructure. Premature monetization risks the local-first ethos.

**Trade-off accepted**: zero direct revenue from v0.1.0. Fine — the project pays for itself in engineering experience and the artifact.

**Implication**: launch comms should not promise a Pro tier or imply commercial intent. The open-source promise is the product.

---

## ADR-017 — Outbound credential redaction at every persistence + subprocess boundary

**Date**: 2026-05-01
**Status**: locked

**Decision**: Forge applies regex-based credential redaction at every outbound boundary — anywhere data leaves the agent's working memory and lands in storage, logs, or a subprocess environment. The implementation is ``daemon/redact.py``; the wiring covers:

| Boundary | Mechanism | Purpose |
|---|---|---|
| Trace JSONL (`.forge/sessions/<id>/trace.jsonl`) | `redact_value()` recurses into event `data` payloads in `replay.append_event` | Audit log on disk never sees raw secrets even if the runtime did |
| Daemon log (`.forge/forge.log`) | `RedactionFilter` log filter (opt-in via `daemon.log` config) | Exception messages and `logger.warning(...)` carrying provider 401 bodies are scrubbed |
| KB writes via `db.add_knowledge` | `contains_secret()` gate — refuses to persist content that matches any rule | Agents calling `forge_kb_add` over MCP can't poison the KB with leaked tokens |
| Episodic store (`error`, `resolution`, `result`, `evaluator_feedback`) | `redact()` applied at `db.save_episode` write time | Subprocess stderr containing keys is scrubbed before SQLite |
| Subprocess env (`claude -p`, future `ollama serve`, `git`, etc.) | `filtered_subprocess_env()` allowlist | Unrelated env vars (AWS, GH PAT for unrelated repos, custom CI tokens) don't leak into the child process |

**Patterns covered (high-confidence, low false-positive)**: Anthropic keys (`sk-ant-…`), OpenAI keys (`sk-…`, `sk-proj-…`, `sk-svcacct-…`), GitHub tokens (`ghp_`, `ghs_`, `gho_`, `github_pat_`), AWS access key IDs (AKIA/ASIA/etc.), AWS secret keys after `aws_secret_access_key=`, Slack tokens (`xox[a-r]-…`), Stripe live/test keys (`sk_live_…`, `rk_live_…`), Google API keys (`AIza…`), JWT tokens (three base64url segments), `Authorization: Bearer …` headers, `.env`-line patterns where LHS contains SECRET/TOKEN/PASSWORD/API_KEY, PEM private-key blocks, DB connection URLs (`postgres://user:password@…`).

**What this is NOT**:
- A complete defense — high-entropy random strings without recognizable structure (custom internal tokens) will slip through.
- An LLM-prompt scrubber — by default we *do* send prompt content (which might contain credentials the user pasted) to the model unredacted, because aggressive prompt redaction would mangle legitimate code and break agent loops. Users can opt in via `FORGE_REDACT_PROMPTS=1` if their threat model warrants it.
- A replacement for `gitleaks` at commit time — gitleaks gates *inbound* (preventing commits); this ADR gates *outbound* (preventing persistence + leakage).

**Rationale**: Forge is local-first (ADR-007), so the runtime and the user share a trust boundary at the OS level. But the audit log is durable, the KB is shared via MCP with other agents, and the episodic store is a candidate for future cross-project sharing — all of which extend the trust boundary. Defense in depth: every persistence layer scrubs.

**Alternatives considered**:
- Trust the user to not paste secrets (rejected — humans paste secrets routinely; gateways exist precisely because you can't eliminate user error)
- Encrypt-at-rest for the audit log (rejected — adds key-management surface; doesn't help the `forge_kb_search` MCP-out path or the WebSocket stream to the UI)
- ML-based PII/secret detector (rejected — adds an inference dep; regex catches the common shapes at zero marginal cost)

**Trade-off accepted**: regex catches ~95% of credential shapes by structure. The remaining ~5% (high-entropy custom tokens) require user vigilance + the fallback `silent_catch()` audit. Documented in SECURITY.md known-limitations.

**Reference**: `daemon/redact.py`, `tests/test_redact.py`, [SECURITY.md](../SECURITY.md).

---

## How to add a new ADR

1. Append a new section to this file with the next ADR number.
2. Date it ISO-8601 (`2026-MM-DD`).
3. Status: `proposed` → `accepted` → `locked`. (Once `locked`, only a superseding ADR can change it.)
4. Include: Decision, Rationale, Alternatives considered, Trade-off accepted, Reference links.
5. If superseding an old ADR, mark the old one as `superseded by ADR-XXX` and link.
6. Update the table at the top.

ADRs may be revisited but not deleted. The history matters.

---

*Last updated: 2026-04-30. Linked from [BUILD_PLAN.md](BUILD_PLAN.md) and [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md).*
