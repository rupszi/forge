# Forge vs. the Field — Head-to-Head Competitive Comparison

**Date**: 2026-04-30 (with freshness-check deltas folded in from the same date)
**Status**: live
**Source research**: synthesized from [docs/research/notes/02a-closed-source-agents.md](research/notes/02a-closed-source-agents.md), [02b-open-source-frameworks.md](research/notes/02b-open-source-frameworks.md), [02d-open-weight-llms.md](research/notes/02d-open-weight-llms.md), the synthesis report at [research/competitive-landscape-and-architecture.md](research/competitive-landscape-and-architecture.md), and the **April-30 freshness check** at [05-competitive-freshness-2026-04-30.md](research/notes/05-competitive-freshness-2026-04-30.md).

> **Question this document answers**: How does Forge compare to what's currently shipping? Where does it win, tie, lose? Is there a market gap, or are we duplicating prior art?

## What changed in the last 60 days (folded in below)

The freshness check surfaced **five material deltas** that reshape the comparison:

1. **Composio Agent Orchestrator** open-sourced Feb 23, 2026 (6.7k stars by Apr 30) — now the closest direct analogue, displacing OpenClaw plugin. Worktrees + planner/worker + PRs + auto CI-fix. Default backend `claude-code`. **No published persistent SQLite KB** with confidence/decay.
2. **Open-weight SWE-bench Verified ceiling moved from ~72% → ~80%+** in 60 days. MiniMax M2.5 hits 80.2%; DeepSeek V4 / V4-Flash at ~79–83.7%; Qwen3.6-27B (Apr 22) advertises "flagship-level agentic coding". The "open-weight is good enough" thesis is materially stronger than 30 days ago.
3. **Tool-call reliability functionally solved upstream.** `--tool-call-parser qwen3_coder` landed in vLLM and SGLang. The historical objection "open-weight models can't reliably tool-call" is dead for Qwen3 family. Forge's "Ollama by default for planner / simple sprints" is now defensible, not hopeful.
4. **The pattern is mainstream.** Anthropic shipped sub-agent `worktree` isolation + Managed Agents memory (Apr 23) + Claude Cowork GA (Apr 9). Cognition shipped Manage Devins (Mar 19) with episodic learning. Cursor 3 + Composer 2 + Windsurf Wave 13 all added 8-parallel worktrees in early April. **Multi-agent + persistent memory + worktrees is now table stakes.** Forge cannot differentiate on the orchestrator pattern alone — only on **open-weight + local + KB**.
5. **YC W26 batch was 41.5% agent-infrastructure**, demoed Mar 24, 2026. Several may pivot toward Forge's exact niche by H2 2026. The window is real but not infinite.

The **decision** ([per the freshness recommendation §F](research/notes/05-competitive-freshness-2026-04-30.md#f-recommendation)): **proceed with the 14-week plan**, but trim weeks 1–4 surface that overlaps Composio AO and reinvest in the KB / retriever / learner where Forge is still uniquely positioned. Two model-default updates already applied to [BUILD_PLAN.md](BUILD_PLAN.md).

---

## TL;DR (one paragraph)

Forge occupies a specific seam in the market that no existing single product fills: **(1) open-weight LLM as the default backend, (2) three-agent harness with a cross-model evaluator on a different family, (3) persistent four-tier SQLite knowledge base with confidence/decay/dedup that compounds across sessions, (4) git-worktree isolation as a first-class concept, (5) MCP-bidirectional (consumes from Claude Code, exposes its KB to other agents), (6) browser dashboard mission-control surface, (7) MIT, local-first, anti-telemetry**. No competitor combines all seven. The closest analog is now **Composio Agent Orchestrator** (open-sourced Feb 23, 2026; 6.7k stars) which has worktrees + multi-agent + PRs + auto CI-fix, but defaults to Claude Code and lacks a persistent SQLite KB. **Devin v3 + Manage Devins** (Mar 19, 2026) is the closed-source mirror with episodic learning baked in, but it's $500/mo ACU-priced. **Aider** has the strongest single-agent coding-per-token but no orchestration. **OpenHands** reports 72% SWE-bench Verified with Sonnet 4.5 + extended thinking via their SDK but uses a single-agent topology. **Cursor 3 / Windsurf Wave 13** are now mainstream multi-agent IDEs but closed and IDE-locked. The gap is real but narrowing; the risk is that a YC W26 cohort agent-infra startup fills it before Forge ships, or that closed-source episodic learning (Manage Devins style) is good enough that the open-weight + local angle isn't worth the friction.

---

## The full comparison matrix

Read this with care: every cell is sourced from primary docs in the research notes; benchmark numbers move weekly so verify before quoting.

| Product | Open-weight default? | Topology | Persistent KB | Worktree isolation | Sandbox | License | Surface | Best public SWE-bench Verified |
|---|---|---|---|---|---|---|---|---|
| **Forge** *(target)* | **Yes** (`gpt-oss:20b` planner / `devstral-small-2507` cheap generator / `qwen3-coder-next` mid generator / `deepseek-v4-flash` premium / cross-family evaluator) | **Three-agent** (planner → generator → evaluator) cross-family | **Four-tier SQLite** (KB + episodic + procedural + research, confidence/decay/dedup) | **First-class, native** | git worktrees + optional Docker | MIT | Browser dashboard + KB-as-MCP server | **target ≥30%** on 50-task subset (Phase 2 W8 kill-criterion) |
| **Composio Agent Orchestrator** ⭐ NEW | No (default Claude Code; alts codex/aider/cursor/opencode) | **Planner + worker** | None published (KB story unclear) | **First-class** (per-agent worktree + branch + PR) | Inherits backend | MIT (Apache?) | CLI / SDK | unpublished |
| **Devin v3 + Manage Devins** ⭐ UPDATED (Mar 19, 2026) | No | **Coordinator + managed sub-Devins**, episodic learning from child trajectories | Devin Wiki + replay + Knowledge + memory | Cloud VM per managed Devin | Cloud VM per task | Proprietary, $500/mo+ ACU | Web + v3 API | high (closed; estimated 80%+ via Manage Devins) |
| **Claude Code** ⭐ UPDATED (v2.1.101 Apr 2026) | No (Claude-only) | Single + sub-agents with `isolation: worktree` + `background: true` | Auto-memory + `CLAUDE.md` + Managed Agents memory (`/mnt/memory/`, Apr 23) + memory tool | **Now first-class** via subagent `isolation: worktree` | Permission system + hooks | Proprietary | CLI + IDE plugins | unpublished (Opus 4.7 `xhigh` likely 87%+) |
| **OpenAI Codex CLI** ⭐ UPDATED (v0.116, Mar 19, 2026) | No (OpenAI-only) | Single + subagents (limited) | `AGENTS.md` | None | **OS-native** (Seatbelt / Bubblewrap+Landlock / WSandbox) | Apache 2.0 | CLI (Rust rewrite, 95.6% Rust) | unpublished |
| **Cursor 3 + Composer 2** ⭐ UPDATED (~Apr 2, 2026) | No | **Up to 8 parallel agents on worktrees**; `/multitask` async sub-agents | "Memories" + `.cursor/rules/` | **First-class** (worktrees or remote VMs) | Local (no OS sandbox) | Proprietary | IDE fork | unpublished (Composer 2: 61.3 CursorBench, 200 tok/s) |
| **Windsurf Wave 13** ⭐ UPDATED (Apr 2026; **owned by Cognition** since Dec 2025, $250M) | No | First-class parallel sessions + worktrees; SWE-1.5 + Codemaps; **Devin integration** | "Memories" + `.windsurfrules` | **First-class** | Local | Proprietary | IDE fork | unpublished |
| **Claude Cowork** ⭐ NEW (GA Apr 9, 2026) | No | Spawns parallel sub-agents inside Claude Desktop | Inherits Managed Agents memory | Cloud sub-agent | Cloud per session | Proprietary | Claude Desktop | unpublished (aimed at non-engineering users) |
| **Aider** | **Yes** (BYO model) | Single + Architect (2-model) | None across sessions | Git commits per change | None | Apache 2.0 | CLI | **71.4% via R1-0528** (Aider polyglot — different metric, but indicative of model ceiling) |
| **OpenHands SDK + Index** ⭐ UPDATED (V1 GA early 2026) | **Yes** | Single + delegation (microagents) | Microagents file system | None | **Docker runtime** (bash + Jupyter + Chromium) | MIT | Web + CLI + SDK | **72% with Sonnet 4.5 + extended thinking** (SDK V1) |
| **OpenCode (sst)** ⭐ UPDATED (v1.14.30, Apr 29, 2026) | **Yes** (BYO, 75+ providers) | Build + Plan agent split | Project context | None | Local | MIT | CLI (terminal-first) | unpublished |
| **Nano Claude Code** ⭐ NEW (~Apr 2026) | **Yes** (20+ closed and local open models) | Multi-agent + persistent memory + skills | Persistent memory (claimed) | None published | None | MIT | CLI (~5K LOC Python) | unpublished |
| **oh-my-codex** ⭐ NEW (~Apr 2026, 18.8k stars) | No (Codex CLI flavored) | **30 role-specialized subagents**, 40+ workflow skills | None | Worktree pattern | Inherits Codex | MIT | CLI | unpublished |
| **Cline** | Mostly Claude (computer-use) | Single | Project | None | Local | Apache 2.0 | VS Code extension | unpublished |
| **Continue.dev** | **Yes** (BYO) | Plan / Agent modes | `@codebase` + Hub blocks | None | None | Apache 2.0 | VS Code + JetBrains + CLI | unpublished |
| **Goose (Block)** ⭐ UPDATED (LF AAIF founding project) | **Yes** (15+ providers) | Single + extensions | Session-scoped | None | None | Apache 2.0 | Desktop app + CLI | unpublished |
| **Plandex v2.2+** ⭐ UPDATED | **Mixed** (built-in Ollama support added) | Single | Plan-as-data + branches | Custom diff sandbox | None | MIT | CLI | unpublished |
| **OpenClaw plugin** | No (Claude only) | **Multi-agent council** + voting | None | Worktrees | Inherits Claude Code | MIT | Plugin on Claude Code | unpublished (no fresh activity in 60-day window — flagged stagnant) |
| **smolagents** | **Yes** (HF) | Code-as-action | None (BYO) | E2B / Modal / Docker / WASM sandbox | First-class | Apache 2.0 | Library | n/a (library) |
| **SWE-agent** | **Yes** | Single + retry/review | Trajectory only | None | None | MIT | CLI/research | research benchmark vehicle |

---

## Forge's specific positioning vs. each peer

### vs. **Claude Code** (the most-feature-complete closed agent)

**What Forge does that Claude Code doesn't:**
- Open-weight default — runs without an Anthropic key
- Persistent four-tier KB that compounds across sessions across projects with confidence scoring (Claude Code's auto-memory is per-project file system; Anthropic's separate "memory tool" is closer but session-bound)
- Cross-model evaluator on a different family from the generator — Claude Code's sub-agents inherit one model
- Browser dashboard mission control across N parallel sprints

**What Claude Code does better than Forge:**
- Tool quality and selection — Anthropic's "writing tools for agents" discipline shows
- Hooks (`PreToolUse`, `PostToolUse`, `PreCompact`) — Forge has no equivalent yet
- Permission modes (`plan`, `acceptEdits`, `bypassPermissions`) — finer-grained than Forge's worktree gate
- Frontier model quality and prompt caching tuning out of the box

**Verdict**: Forge is *complementary*, not competitive. Forge runs on top of Claude Code (inherits its MCP, runs `claude -p` in worktrees by default) and adds orchestration + KB + open-weight fallback. The right framing: Forge is "Claude Code with a persistent brain and an open-weight escape hatch."

---

### vs. **OpenAI Codex CLI** (the best sandbox model)

**What Forge does that Codex doesn't:**
- Multi-agent harness (Codex is single-agent + limited subagents)
- Persistent KB
- Open-weight by default

**What Codex does better:**
- **OS-native sandboxing** is the most rigorous in the field (Seatbelt + Bubblewrap+Landlock + WSandbox). Forge's worktree-only sandbox is correct for "agent makes a mistake" threat model but Codex's is correct for "agent runs untrusted dependency".
- AGENTS.md is now a cross-vendor convention; Forge inherits it via Claude Code but doesn't author it.

**Verdict**: Forge should explicitly adopt Codex-style sandboxing as an opt-in tier (`--sandbox=docker`, `--sandbox=bwrap`) — already in [BUILD_PLAN.md Week 9](BUILD_PLAN.md#week-9--sandboxing--recovery-modes-25-h). Different products for different threat models.

---

### vs. **Cursor** (the most-mature multi-agent in production)

**What Forge does that Cursor doesn't:**
- Open-weight default
- MIT and local-first (Cursor is closed, cloud-hybrid)
- Persistent project-spanning KB
- Cross-model evaluator (Cursor's parallel agents share a model)

**What Cursor does better:**
- Full IDE integration with shadow workspace + LSP + tab model — nothing on the OSS side rivals this
- Up to 8 parallel agents on real worktrees, productized
- Codebase indexing with proprietary embeddings and Merkle-proof file possession
- Composer 1 native model is highly tuned for the tab-completion + agent-mode dual loop

**Verdict**: Cursor is the gold standard for *managed, all-in-one IDE-native* coding agents. Forge competes on a different axis — *self-hosted, open-weight, KB-compounding orchestrator on top of any IDE/CLI you already have*. Different markets; minimal direct overlap. The Cursor user who switches to Forge is the user who hates cloud lock-in or runs in environments where SaaS isn't viable.

---

### vs. **Devin** (the strongest closed multi-agent)

**What Forge does that Devin doesn't:**
- Local-first (Devin is cloud-only)
- Open-weight default
- MIT (Devin is proprietary, $500/mo+)
- **Multi-agent with structural separation** — Devin explicitly rejects multi-agent in their "Don't Build Multi-Agents" essay. Forge bets the opposite, with worktrees + cross-model evaluator as the structural answer to Cognition's critique.

**What Devin does better:**
- Cloud VM per task — heaviest sandbox of any product
- Devin Wiki (auto-indexed every few hours) + replay timeline
- Devin can manage Devins (parent spawns child VMs)
- Years of harness tuning under one company's roof

**Verdict**: Direct philosophical disagreement on multi-agent. Forge's worktree+evaluator design is *exactly* the structural mitigation Cognition says is missing in naive multi-agent systems. Whether the bet pays off is the Week-8 SWE-bench question. If Forge can't prove parallelism wins net of merge cost on coding, Cognition was right and we degrade to Architecture C (single strong agent).

---

### vs. **Aider** (the strongest single-agent on open weights)

**What Forge does that Aider doesn't:**
- Multi-agent harness with cross-model evaluator
- Persistent KB
- Web dashboard + multi-sprint dependency-wave execution
- KB-as-MCP server export

**What Aider does better:**
- Repo-map (tree-sitter + PageRank, ~500 LOC, MIT) — **Forge plans to lift this verbatim in Phase 1 Week 3**
- Edit-format taxonomy (whole / editblock / udiff / udiff-simple / patch / architect) — battle-tested per-model
- 71.4% on Aider polyglot via R1-0528 — currently the SOTA open-weight coding number for any harness
- Architect mode (reasoning model + fast-apply model) — pattern Forge could adopt internally on the generator side

**Verdict**: Aider is the **pacing baseline**. Forge's evaluator + KB + multi-agent should give better *long-running* results; Aider should give better *single-task* results because it's tightly tuned for that. If Forge isn't materially better than Aider on multi-sprint sessions, the orchestration overhead isn't justified.

---

### vs. **OpenHands** (the strongest open SWE-bench harness)

**What Forge does that OpenHands doesn't:**
- Multi-agent harness with explicit planner/generator/evaluator separation (OpenHands is generalist + delegation)
- Cross-family evaluator enforcement
- Persistent four-tier KB
- Git-worktree isolation as the primary unit (OpenHands uses Docker per task)

**What OpenHands does better:**
- **53.6% SWE-bench Verified with Devstral-Small-2507** — the reference open-weight number Forge will be measured against
- Docker runtime (bash + Jupyter + Chromium pre-baked) — cleaner sandbox story than worktrees alone
- ICLR 2025 paper backing the architecture
- 72.4k stars, Linux Foundation umbrella, paid Cloud
- CodeAct (code-as-action) — the right pattern for open-weight tool reliability

**Verdict**: OpenHands is the **target for the Week-8 kill criterion**. If Forge can hit ≥30% with the same Devstral-Small-2507 + Forge harness, the multi-agent overhead is paying for itself. If it can't, OpenHands's single-agent CodeAct pattern is winning and Forge should consider lifting the runtime container.

---

### vs. **OpenCode (sst/opencode)** (the leanest two-agent CLI)

**What Forge does that OpenCode doesn't:**
- Persistent KB across sessions
- Cross-family evaluator
- Worktree isolation
- Web dashboard

**What OpenCode does better:**
- 152k stars (hot OSS project; significant momentum)
- 75+ provider integrations out of the box
- Build/plan agent split is a leaner, simpler UX than Forge's planner/generator/evaluator
- TypeScript stack (lower contributor barrier on the JS side)
- Subscription piggybacking (use your existing Claude Pro/Max)

**Verdict**: OpenCode is the **UX baseline to benchmark against** in Phase 2 — if a developer prefers OpenCode's two-agent UX over Forge's three-agent dashboard, Forge's added structure isn't earning its complexity. The 152k stars are a market signal that lean wins.

---

### vs. **Cline** (the dominant VS Code extension)

**What Forge does that Cline doesn't:**
- Open-weight default (Cline leans Claude + computer-use)
- Multi-sprint orchestration
- Persistent KB
- Worktree isolation

**What Cline does better:**
- **VS Code extension is the right surface** for most developers — Forge's browser dashboard is a deliberate trade-off but loses developers who never leave their editor
- Computer-use integration via Claude
- Human-in-the-loop GUI is excellent
- 61k stars

**Verdict**: Different surfaces. Forge's [Phase 3 ACP sidecar](BUILD_PLAN.md#stretch-goals-not-on-the-critical-path) closes the IDE-surface gap if/when adoption demands it. For now Forge accepts losing the "I never leave VS Code" user.

---

### vs. **Continue.dev** (the configurable IDE assistant)

**What Forge does that Continue doesn't:**
- Multi-agent harness with cross-model evaluator
- Persistent KB across sessions
- Worktree isolation
- Sprint-based dependency execution

**What Continue does better:**
- Auto-detection of native vs prompted tool-calling per model — this is the single feature Forge should adopt verbatim for its open-weight executor
- Multi-IDE (VS Code + JetBrains + CLI)
- CI-style "checks" that run agents on PRs as GitHub status checks
- Hub for sharable agents/models/rules/prompts

**Verdict**: Continue's **per-model tool-call capability detection** is the pattern Forge should lift in Phase 1 Week 1. Continue is also a likely partner for the ACP sidecar work.

---

### vs. **Goose (Block)** (the MCP-native desktop)

**What Forge does that Goose doesn't:**
- Multi-agent harness
- Persistent KB
- Worktree isolation
- Sprint orchestration

**What Goose does better:**
- **MCP-native everywhere**, 70+ MCP extensions
- 15+ LLM provider integrations
- Native desktop app (Forge plans this for v2 only)
- Linux Foundation Agentic AI Foundation governance
- 43k stars, 132 releases

**Verdict**: Goose validates the bet on MCP. Forge's [planned KB-as-MCP server export](BUILD_PLAN.md#week-6--mcp-server-export--procedural-feedback-25-h) makes Forge a *Goose extension* in effect — Goose users can pull from Forge's KB through MCP.

---

### vs. **Plandex v2** (the cumulative-diff CLI)

**What Forge does that Plandex doesn't:**
- Multi-agent (Plandex is single-agent)
- Cross-model evaluator
- Persistent KB
- Web dashboard

**What Plandex does better:**
- **Cumulative diff sandbox with branches** — separates AI changes from working tree until accepted; Forge's worktrees serve a similar purpose but Plandex's branching plan-as-data is more refined
- 2M effective context window via context-selection-per-step
- Tree-sitter project mapping for 30+ languages

**Verdict**: Forge's worktree merge gate should adopt Plandex's "plan branches" framing. The cumulative-diff-with-explicit-accept pattern is a UX improvement worth lifting.

---

### vs. **Composio Agent Orchestrator** (the new closest prior art ⭐)

**The single most important comparison post-freshness-check.** Composio open-sourced AO on Feb 23, 2026 and it's now at 6.7k stars with 33 releases (latest Mar 29, 2026). It is the project most architecturally close to Forge.

**What Composio AO does** (per [freshness §A.1](research/notes/05-competitive-freshness-2026-04-30.md#a-top-5-deltas-that-could-change-forges-plan)):
- Planner + worker pattern with each agent in its own **git worktree + branch**
- Autonomous PR creation, CI-fix loop, merge-conflict resolution, review-comment handling
- Default backend `claude-code` with alternatives: `codex`, `aider`, `cursor`, `opencode`
- Open-source MIT
- Mature: 33 releases in two months, real adoption

**What Forge does that Composio AO doesn't:**
- **Open-weight first** routing (Composio defaults to Claude Code; Forge defaults to Ollama + Qwen3-Coder-Next + Devstral-Small)
- **Persistent four-tier SQLite KB** with confidence/decay/dedup/imperative-line discipline (Composio has no published KB story)
- **Cross-family evaluator** on a different model family from the generator (Composio's loop is closer to a CI-fix loop than a planner/generator/evaluator contract)
- **Sprint contracts with explicit `done_criteria`** graded independently per criterion (Composio reacts to CI signals, not contract verification)
- **Inherits Claude Code's `.claude/` settings + MCP + auto-memory** as a first-class concept (Composio uses claude-code as a *backend*, not as the host environment to inherit from)
- Cross-store retriever with token-budget injection
- Procedural memory that learns routing over time
- Browser dashboard mission-control surface

**What Composio AO does better:**
- **Ships and works today**; Forge is at Phase 0 with 14 weeks to go. **This is the most material risk to the build plan.**
- Validated in production (6.7k stars in two months, 33 releases)
- Lower setup friction (npm-installable agent SDK)
- Composio's broader connector ecosystem (their core business is integrations)

**Verdict**: **Composio AO has subsumed the "multi-agent + worktrees + PRs" pattern** that previously felt novel. Forge cannot win on the orchestrator pattern alone anymore — the differentiation has to be unambiguous on **(a) open-weight by default, (b) persistent SQLite KB with confidence/decay, (c) GAN-style separate evaluator with done-criteria contracts**. The marketing position must explicitly call out vs Composio: *"Composio AO orchestrates and reacts to CI; Forge plans, contracts, evaluates, and learns."*

**Action**: trim weeks 1–4 surface that overlaps Composio AO (basic worktree + spawn + PR is now table stakes — buy that pattern via inspiration) and reinvest those cycles in the SQLite KB + retriever + learner where Forge is still uniquely positioned. This is reflected in [BUILD_PLAN.md](BUILD_PLAN.md#freshness-check-deltas-2026-04-30).

---

### vs. **OpenClaw plugin** (formerly closest analogue, now superseded)

OpenClaw plugin (Claude Code multi-agent council with worktrees + voting, ~417 stars) had **no datable activity in the 60-day freshness window** and is flagged stagnant. Composio AO has filled this position. Forge's differentiation vs OpenClaw is moot since OpenClaw is no longer the active competitor — the same differentiation arguments apply more strongly to Composio AO above.

---

### vs. **Devin v3 + Manage Devins** ⭐ UPDATED (Mar 19, 2026)

The most important closed-source delta in the 60-day window.

**What Manage Devins does**:
- A Devin session can decompose a task and spawn **managed sub-Devins**, each in its own VM
- Coordinator monitors ACU, pauses, terminates, and **reads full child trajectories to improve next-task decomposition** — i.e. Cognition shipped procedural memory built into the coordinator
- v3 API is GA April 2026 as primary

**What Forge does that Manage Devins doesn't:**
- **Local-first** — Manage Devins is cloud-VM per managed agent at $500/mo+ ACU pricing
- **Open-weight** — Manage Devins is closed
- **MIT, no telemetry** — Manage Devins phones home to Cognition

**What Manage Devins does better:**
- **Already shipping with episodic learning baked in.** Cognition has a fully-featured planner-with-procedural-memory in production. Forge's procedural-memory writeback (planned for Phase 1 Week 6) has to demonstrably accumulate value to compete on the "I learn your codebase" axis.
- Years of harness tuning under one roof, ~50 engineers
- Heaviest sandbox of any product (full VM per sub-agent)

**Verdict**: Manage Devins is the **closed-source mirror of Forge's planner/generator pattern with episodic learning baked in**. Cognition was famously anti-multi-agent ("Don't Build Multi-Agents") — they reversed course in March. The category is validated, the bar is high. Forge's edge is open-weight + local + free; not the orchestrator pattern itself.

---

## Where the seam is — Forge's defensible niche (post-freshness-check)

Map every feature against every product. **Composio AO and Manage Devins are now in the matrix** (they weren't in the early-April research):

| Feature | Forge | Composio AO | Manage Devins | Aider | OpenHands SDK | Claude Code | Cursor 3 | Cline | OpenCode | Goose |
|---|---|---|---|---|---|---|---|---|---|---|
| Open-weight default | ✅ | ❌ | ❌ | ⚠️ (BYO) | ✅ | ❌ | ❌ | ❌ | ⚠️ (BYO) | ⚠️ (BYO) |
| Multi-agent topology | ✅ | ✅ | ✅ | ❌ | ⚠️ | ⚠️ (subagents) | ✅ | ❌ | ⚠️ | ❌ |
| **Cross-model evaluator** (different family) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Persistent KB across sessions** | ✅ | ❌ | ✅ | ❌ | ⚠️ (microagents) | ⚠️ (memory tool) | ⚠️ (Memories) | ❌ | ❌ | ⚠️ |
| **Confidence-scored gotcha learning** | ✅ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Procedural memory** (routing learns over time) | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Done-criteria contracts** (independent grading per criterion) | ✅ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Worktree isolation | ✅ | ✅ | n/a (VM) | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| MCP-bidirectional (consume + expose) | ✅ | ❌ | ❌ | ❌ | ❌ | ⚠️ (consume) | ⚠️ (consume) | ❌ | ❌ | ⚠️ (consume) |
| Browser dashboard | ✅ | ⚠️ | ✅ | ❌ | ✅ | ❌ | n/a (IDE) | ❌ | ❌ | ❌ |
| MIT / Apache 2.0 | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Local-first / no cloud requirement | ✅ | ✅ | ❌ | ✅ | ⚠️ | ✅ | ⚠️ | ✅ | ✅ | ✅ |

**The unique cell (updated April 30 post-freshness-check)**: Forge is the only project with **all five** of:
1. Open-weight default
2. Cross-model evaluator on a different family (none of the competitors have this)
3. Persistent KB across sessions with confidence-scored gotcha learning *and* procedural memory feedback
4. Done-criteria contracts graded independently per criterion
5. MCP-bidirectional (consume + expose KB to other agents)

**The narrowing**: Composio AO took "multi-agent + worktrees" off the unique list. Manage Devins took "persistent KB + procedural memory" off the unique list (but only in closed-source $500/mo form). The seam is still real but tighter than it was 60 days ago.

**The remaining defensible niche**: cross-family evaluator + done-criteria contracts + KB-as-MCP-out are the three features Forge alone offers. Whether that combo is *valuable enough to pay the engineering cost* is the Phase 2 SWE-bench question.

---

## Where Forge **loses** today

Honest list:

1. **Tool-call reliability on open weights** is unsolved upstream. Forge's three-layer defense (native parser + xgrammar + BAML) is the right mitigation but adds engineering surface that competitors don't carry.
2. **No frontier model on day 1.** Devstral-Small-2507 (53.6% SWE-bench) + Qwen3-Coder-30B is good, not great. Closed competitors run on Sonnet/Opus/GPT-5.
3. **No IDE plugin in v1.** Cursor users, Cline users, Continue.dev users live in their editor; Forge's browser dashboard is a context switch.
4. **Solo developer build.** Cursor has ~100 engineers; Cognition has ~50; Anthropic has Claude Code as a flagship product. Forge is one person building in evenings.
5. **No cloud / managed option.** Devin's $500/mo subscription model exists because some teams prefer not-self-hosted. Forge has no answer for that segment (intentional, but a market reality).
6. **Smaller community than Aider, Cline, OpenHands.** OSS coding agents need community velocity; Forge starts at zero.
7. **No fine-tuned models.** OpenHands has Devstral published with their scaffold; Aider has Architect-mode tuning per model. Forge accepts off-the-shelf for v1.

---

## Where Forge **wins**

1. **The seam from §"Where the seam is"**: only project with all six unique-cell features.
2. **Engineering bar**: pre-push gate + schema parity + frontmatter audit + structured CI is unusual for OSS coding agents. Most OSS coding agents are vibes-coded; Forge starts with discipline.
3. **Architecture is convergent with the published evidence** — cross-model evaluation > self-eval (MT-Bench self-bias quantified), Plan-and-Solve > one-shot, verbal feedback loops > single-pass. Architecture A is the literature's recommendation.
4. **MCP-bidirectional**: KB-as-MCP server is a one-day feature that immediately makes Forge useful inside *every* other MCP-aware tool (Claude Desktop, Cursor, Continue, Goose). High-leverage.
5. **Local-first by design**: KB stays in `.forge/`, no cloud, no telemetry. A real differentiator for security-conscious teams.
6. **MIT** with no commercial license traps in the model lineup (gpt-oss + Devstral-Small + Qwen3-Coder are all Apache 2.0; no Mistral Large 2 or Codestral research-only).

---

## Failure modes that would make Forge irrelevant (updated April 30 post-freshness-check)

If any of these happen during the build, Forge's positioning erodes:

| Scenario | Probability (was → now) | Status as of Apr 30 | Forge's response |
|---|---|---|---|
| Anthropic ships built-in multi-agent orchestration in Claude Agent SDK | 30% → **already happened** | Anthropic shipped sub-agent `worktree` isolation + Managed Agents memory + Claude Cowork in March–April. Pattern is mainstream, not novel. | Pivot fully to "the open-weight orchestrator" framing. Don't market on parallelism — market on local + open-weight + persistent KB. |
| Open-weight tool-call problem solved upstream | 40% → **already happened** | `qwen3_coder` parser landed in vLLM + SGLang; Qwen3-Coder-Next + Qwen3.6-27B + DeepSeek V4-Flash all reliable on agentic loops. | Good news. Forge's three-layer defense (native parser + xgrammar + BAML) is now belt-and-suspenders, not a hopeful bet. Keep BAML as opt-in. |
| Someone ships "open-weight Claude Code clone with persistent KB and worktrees" | 25% → **partially shipped** | Composio AO has worktrees + multi-agent (Feb 23, 2026, 6.7k stars). **No public SQLite KB story.** Nano Claude Code (~5K LOC) claims memory but no separate evaluator. | Differentiate explicitly on **cross-family evaluator + done-criteria contracts + four-tier KB with confidence/decay**. Trim weeks 1–4 surface that overlaps Composio. |
| Frontier closed models make orchestration overhead unjustifiable | 20% → 25% | Opus 4.7 + `xhigh` shipped Apr 16 (87.6% SWE-bench Verified); Mythos preview at 93.9%. Frontier still pulling ahead but not commoditized. | Forge's value is local + open + KB, not beating frontier. Reposition as "Claude Code with a persistent brain" if frontier closes the absolute gap. |
| Cursor / Codex CLI go open source | 10% → 10% | Codex remains Apache 2.0 but OpenAI-only; Cursor remains closed. No movement. | Existential — Forge would reposition entirely. Low-probability but watch. |
| Devstral / Qwen3-Coder progress stalls | 30% → **gone in opposite direction** | Open-weight ceiling moved 72% → 80%+ in 60 days. Qwen3.6-27B + DeepSeek V4-Flash announced. | Substrate is healthier than ever. Update model defaults in BUILD_PLAN.md to Qwen3-Coder-Next + DeepSeek V4-Flash. |
| YC W26 agent-infra cohort fills Forge's niche before launch | NEW 35% | YC W26 demoed Mar 24, 2026; 41.5% of batch was agent infra. Several may target Forge's exact niche by H2 2026. | Time pressure is real. The 14-week plan is borderline acceptable; don't slip. Consider a public WIP repo + Discord at Phase 1 Week 4 to start gathering feedback early. |
| Cognition extends Manage Devins to local / open-weight execution | NEW 15% | Cognition acquired Windsurf for $250M Dec 2025; integrating Devin into IDE; not yet open-weight or local. | Watch closely. If they ship "Devin Local on Devstral", Forge's open-weight + local angle erodes. |

---

## Decision: should Forge proceed? (post-freshness-check)

**Yes — proceed with the 14-week plan, with three modifications applied to BUILD_PLAN.md:**

1. **The Week-8 SWE-bench kill criterion is non-negotiable.** If the upgraded model lineup (Devstral-Small + Qwen3-Coder-Next + DeepSeek V4-Flash) + Forge harness can't reach **30%** on the 50-task subset, OpenHands SDK's single-agent approach (which hit 72% with Sonnet 4.5 + extended thinking) is winning and Forge's multi-agent overhead doesn't pay. Pivot or shut down. Don't iterate past Week 8.
2. **Trim weeks 1–4 surface that overlaps Composio AO.** Basic worktree + spawn + PR is now table stakes (Composio has shipped it; Cursor 3 has shipped it; Anthropic Claude Code has shipped it). Buy the pattern via inspiration, **invest the saved cycles in the SQLite KB + retriever + learner** where Forge is uniquely positioned. Specifically: cut any "build worktree-spawn UX" work and reinvest in the procedural memory feedback loop, KB confidence/decay tuning, and evaluator-with-contracts hardening.
3. **Bump default model lineup** to Qwen3-Coder-Next (cheap-tier generator) + Qwen3.6-27B (medium generator) + DeepSeek V4-Flash (premium generator) + gpt-oss:20b retained as planner default. The April-22-and-23 releases changed the open-weight ceiling materially; defaults should reflect that.
4. **Don't market on first-mover or on parallelism alone.** Composio AO + Manage Devins + Cursor 3 + Windsurf Wave 13 + Anthropic Cowork all shipped multi-agent + worktrees in the last 60 days. The pattern is mainstream. Position Forge as: *"the open-weight orchestrator with a brain that compounds across sessions, that runs locally with no telemetry."* Three differentiators: open-weight + local + KB. Marketing copy should test against this.
5. **Adopt Continue's per-model tool-call capability detection** in Phase 1 Week 1. Free win.
6. **Adopt Aider's repomap.py verbatim** in Phase 1 Week 3 (already in the plan). Free win.
7. **Lift smolagents' `LocalPythonInterpreter` AST sandbox** for the evaluator's "verify by running this assertion" step (already in Phase 0 standards). ~150 LOC.
8. **Ship the KB-as-MCP server in Phase 1 Week 6** (already in the plan). Highest-leverage UX move available — makes Forge useful in *every* other MCP-aware tool the user already runs.
9. **NEW: optionally add a Phase 3 Week 10 task** to import from Anthropic Managed Agents memory (`/mnt/memory/`) so users on Anthropic enterprise get free knowledge-base seeding. Closes the loop with Anthropic's April 23 release.
10. **Acknowledge the IDE-surface gap honestly** in the launch post. ACP sidecar is a v2 priority, not a v1 promise.

**Time pressure**: YC W26's 41.5% agent-infrastructure cohort demoed March 24, 2026. Several may pivot toward Forge's exact niche by H2 2026. The window is real but not yet closed. **Don't slip the 14-week plan.** Consider opening the public WIP repo + Discord at Phase 1 Week 4 (instead of Week 12) to gather feedback early.

---

## What this document is *not*

- It's not a feature roadmap (see [BUILD_PLAN.md](BUILD_PLAN.md))
- It's not a marketing pitch (the failure modes are real)
- It's not a freshness check ([05-competitive-freshness-2026-04-30.md](research/notes/05-competitive-freshness-2026-04-30.md) covers the last 60 days separately when that agent returns)

---

## Appendix: links to source research

- [02a-closed-source-agents.md](research/notes/02a-closed-source-agents.md) — Claude Code, Codex CLI, Cursor, Windsurf, Devin, Aider, Continue.dev, Sweep/Cody/Tabby/Plandex
- [02b-open-source-frameworks.md](research/notes/02b-open-source-frameworks.md) — 16 OSS frameworks including OpenHands, SWE-agent, smolagents, Letta, OpenCode, OpenClaw, Goose
- [02c-2g-swarm-and-decisions.md](research/notes/02c-2g-swarm-and-decisions.md) — multi-agent paradigms, Cognition's "Don't Build Multi-Agents" critique, MT-Bench self-bias
- [02d-open-weight-llms.md](research/notes/02d-open-weight-llms.md) — Devstral, Qwen3-Coder, gpt-oss, DeepSeek-R1, Llama 3.3/4 model evaluations
- [research/competitive-landscape-and-architecture.md](research/competitive-landscape-and-architecture.md) — the synthesis report (~9.6k words)

*Living document. Update when a competitor ships something material. Linked from [BUILD_PLAN.md](BUILD_PLAN.md).*
