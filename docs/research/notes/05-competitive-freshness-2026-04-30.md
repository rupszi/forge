# Competitive freshness check — 2026-04-30

**Scope:** what shipped in the last ~60 days (March 1 – April 30, 2026) that materially affects Forge's 14-week build plan. Not a re-do of the prior research (notes 01–04 in this directory). Every claim cited with URL + date.

---

## A. Top 5 deltas that could change Forge's plan

1. **Composio open-sourced "Agent Orchestrator" (Feb 23, 2026; now 6.7k stars, 33 releases, latest Mar 29, 2026).** This is the single closest analogue to Forge in the open-source landscape: planner + worker pattern, each agent in its own git worktree + branch + PR, autonomous CI fix / merge-conflict / review-comment handling. Default backend is `claude-code` with alternatives `codex, aider, cursor, opencode`. **Forge implication:** Forge's "I/O is git worktrees + branches + PRs" hook is no longer differentiated by itself. Forge must double down on (a) open-weight-first routing via Ollama/vLLM, (b) the persistent SQLite KB + cross-store retriever, and (c) the GAN-style separate evaluator with done-criteria contracts — Composio AO's loop is closer to a CI-fix loop than a planner/generator/evaluator contract. ([repo](https://github.com/ComposioHQ/agent-orchestrator), [MarkTechPost 2026-02-23](https://www.marktechpost.com/2026/02/23/composio-open-sources-agent-orchestrator-to-help-ai-developers-build-scalable-multi-agent-workflows-beyond-the-traditional-react-loops/))

2. **Cognition shipped "Devin can now Manage Devins" on Mar 19, 2026.** A Devin session can decompose, spawn managed sub-Devins each in their own VM, monitor ACU, pause/terminate, and **read full child trajectories to improve next-task decomposition** — i.e. they shipped procedural memory built into the coordinator. This is essentially the planner/generator pattern with built-in episodic learning. **Forge implication:** the multi-agent orchestrator pattern is now table-stakes for the closed-source frontier. Forge's edge has to be open-weight + local + free-tier, not "we have multi-agent." Don't bother marketing on parallelism alone. ([Cognition blog 2026-03-19](https://cognition.ai/blog/devin-can-now-manage-devins))

3. **Cursor 3 + Composer 2 launched ~Apr 2, 2026, with up to 8 parallel agents on git worktrees (Composer 2 model post dated 2026-03-19).** Cursor now natively does worktree-based multi-agent with their own 200-tok/s frontier coding model (61.3 CursorBench). Windsurf Wave 13 followed in the same window with first-class parallel sessions and worktrees. **Forge implication:** the "8 parallel agents on worktrees in a polished UI" pattern is mainstream as of April. Forge cannot differentiate on UX vs Cursor; differentiation has to be: free local models, persistent KB across sessions/projects, and works inside any project (no IDE lock-in). ([Cursor 2.0 blog](https://cursor.com/blog/2-0), [Composer 2 blog 2026-03-19](https://cursor.com/blog/composer-2), [Nimbalyst Apr 2026](https://nimbalyst.com/blog/best-multi-agent-coding-tools-2026/))

4. **Claude Opus 4.7 released Apr 16, 2026 with `xhigh` effort tier; Anthropic Managed Agents added persistent memory on Apr 23, 2026 (`/mnt/memory/` directory mounted into the agent container).** Anthropic also shipped sub-agent isolation `worktree` mode and `background: true` agent definitions in Claude Code's daily-cadence April releases. **Forge implication:** Anthropic is officially in the "persistent memory + isolated worktrees + sub-agents" space — but only for users on Anthropic infra. Forge's bet (use these patterns with **open-weight** models on local hardware) is now validated by Anthropic itself building exactly that internally. The KB design in Forge stays right; just track Anthropic's memory-store API in case there's a useful interop pattern. ([Claude Opus 4.7](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7), [Managed Agents memory Apr 2026](https://opentools.ai/news/anthropic-managed-agents-add-memory-persistent-state-for-ai-that-actually-ships), [Claude Code changelog Apr 2026](https://help.apiyi.com/en/claude-code-changelog-2026-april-updates-en.html))

5. **Open-weight tool-call reliability is now genuinely solved on the substrate Forge targets.** vLLM and SGLang both ship a `qwen3_coder` tool-call parser; Qwen3-Coder-Next (3B-active / 80B MoE, Feb 2026) and Qwen3.6-27B (Apr 22, 2026) advertise "flagship-level agentic coding" and run on consumer hardware. DeepSeek V4-Flash (Apr 23, 2026, 13B active, MIT, ~79% SWE-bench Verified) is poised to land on Ollama. **Forge implication:** the historical "open-weight models can't reliably do tool calls" objection is dead for the Qwen3-Coder family. Forge's local-first routing (Ollama default for planner + simple sprints) is now defensibly viable, not a hopeful bet. ([vLLM tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/), [Qwen3-Coder-Next on Ollama](https://ollama.com/library/qwen3-coder-next), [AkitaOnRails benchmark Apr 2026](https://akitaonrails.com/en/2026/04/24/llm-benchmarks-parte-3-deepseek-kimi-mimo/))

---

## B. Per-product update table

| Product | Last release date | Key change in last 60 days | Forge implication |
|---|---|---|---|
| **Claude Code** | Daily cadence; v2.1.69→v2.1.101 in April | Opus 4.7 + `xhigh` effort, sub-agent `worktree` isolation, `background: true` agents, `/team-onboarding`, named sub-agents | Forge's `claude -p` executor model still works; track new sub-agent flags for executor; Auto Mode is now baseline UX |
| **OpenAI Codex CLI** | v0.116.0 on Mar 19, 2026; active April | Rust rewrite (95.6% Rust now), expanded permission profiles, sandbox CLI profile selection, network proxy policies | Forge's sandbox model is fine; Codex is converging on similar primitives but not orchestrating multi-agent |
| **Cursor** | Cursor 3 + Composer 2 ~Apr 2, 2026 | 8 parallel agents on worktrees, Composer 2 (61.3 CursorBench, 200 tok/s), `/multitask` async sub-agents | Don't try to out-IDE Cursor. Forge stays terminal-first + works inside any project |
| **Windsurf / Codeium** | Wave 13, April 2026 | Owned by Cognition since Dec 2025 ($250M); SWE-1.5 + Codemaps; first-class parallel + worktrees; Devin integration | The "Cascade dual-agent" thesis the prior research relied on is now subsumed under Cognition's roadmap |
| **Devin / Cognition** | Manage Devins Mar 19, 2026; v3 API GA April 2026 | Coordinator + managed sub-Devins in isolated VMs with trajectory-based learning loop; v3 API as primary | Closed-source mirror of Forge's planner/generator pattern with episodic learning. Forge must lean on open-weight + local |
| **Aider** | v0.86.0 (Apr 2026 evidence indirect) | Added GPT-5 model support, Grok-4, Gemini 2.5 Flash Lite | Aider remains a single-agent pair-programmer; not encroaching on Forge's territory |
| **OpenHands** | Software Agent SDK + V1 GA early 2026; OpenHands Index Jan 28, 2026 | 72% SWE-bench Verified with Sonnet 4.5 + extended thinking (SDK); Index is multi-eval (issue resolve / greenfield / frontend / tests) | Strong direct competitor on the open-source side. Forge differentiates on KB + planner-evaluator contracts, not raw SWE-bench % |
| **OpenCode (sst)** | v1.14.30 on Apr 29, 2026 | Mistral Medium 3.5 reasoning support, Moonshot/Kimi tool-schema sanitization, MCP OAuth fixes; 2026.4 release brought Ollama streaming v2 (-40% TTFT), Windows ARM64 GA | Same TUI-coding-agent niche, but no orchestration / worktrees / persistent KB. Not an existential overlap |
| **Cline** | Active April 2026 | GPT-5.5 support for Codex-subscription users, computer-use through Claude Sonnet 4 capability | Same VS Code single-agent pattern; not orchestrator-class |
| **Continue.dev** | Active 2026 | Hub-blocks model (`anthropic/claude-4-sonnet`), `baseAgentSystemMessage`, Plan/Chat/Agent tool gating | Hub-blocks is a useful pattern to mimic for Forge's KB-as-shareable artifact, optional |
| **Goose (Block)** | Active 2026 | Joined Linux Foundation's Agentic AI Foundation (AAIF) alongside MCP and AGENTS.md as founding projects; MCP Apps (interactive UIs in Desktop); 70+ extensions, 29k stars | Goose is now governance-blessed. Forge should stay a thin layer on top of MCP rather than building parallel infra |
| **Plandex v2** | v2.2 (built-in Ollama support, JSON model config); v2.3 references seen | Built-in Ollama support, gemini-planner pack | Plandex has `--yes` automation but no separate evaluator role; Forge's contract-based eval still differentiates |
| **OpenClaw plugin** | (could not confirm fresh activity in 60-day window — flagged) | Not surfaced in any April 2026 reporting | Likely stagnant; not an immediate threat |

---

## C. Benchmark snapshot — April 30, 2026

### SWE-bench Verified — top 5 (closed)
1. **Claude Mythos Preview** — 93.9% (research/preview tier; not GA) ([leaderboard](https://www.marc0.dev/en/leaderboard))
2. **Claude Opus 4.7 (Adaptive)** — 87.6%
3. **GPT-5.3 Codex** — 85%
4. (multiple in the 80–85 band — Sonnet 4.6, Opus 4.5)
5. (mixed)

### SWE-bench Verified — top 5 (open-weight)
1. **MiniMax M2.5** — 80.2% (top-10 overall, open-weight) ([benchlm](https://benchlm.ai/benchmarks/sweVerified))
2. **DeepSeek V4 / V4-Flash** — ~79–83.7% depending on full vs Flash variant ([AkitaOnRails Apr 24](https://akitaonrails.com/en/2026/04/24/llm-benchmarks-parte-3-deepseek-kimi-mimo/))
3. **MiMo-V2-Pro (Xiaomi)** — 78.0%
4. **GLM-5 (Zhipu)** — 77.8%
5. **Devstral 2 (123B)** — ~72.2% (Mistral, Dec 2025)

**Best open-weight as of late April 2026: ~80% (MiniMax M2.5) on raw Verified, ~83.7% if you accept DeepSeek V4 full.** This is a **major flip vs the prior research** which had Devstral-Medium at ~72% as the open-weight ceiling. The open ceiling moved up roughly 8–11 points in 60 days.

### Aider polyglot — top 5
1. **Claude Opus 4.5** — 89.4% ([llm-stats](https://llm-stats.com/benchmarks/aider-polyglot))
2. **GPT-5 (high)** — 88.0%
3. (the rest of the closed-source frontier)
4. **MiniMax M2.5** — best open-weight, ~80% range
5. **DeepSeek V3.2-Exp Chat** — 70.2% (best cost-adjusted)

**Best open-weight on polyglot: still gapped vs closed (≈8–10 points) but DeepSeek V4 not yet on this leaderboard at time of writing.**

### TerminalBench / BFCL v4
No major flips surfaced in 60-day window in the searches; not a primary deciding axis.

---

## D. New entrants worth watching (didn't exist in prior research, early April compile)

1. **Composio Agent Orchestrator** — open-sourced Feb 23, 2026; 6.7k stars by Apr 30. The closest direct analogue. ([repo](https://github.com/ComposioHQ/agent-orchestrator))
2. **oh-my-codex** — Show-HN'd around Apr 2026; "30 role-specialized subagents, 40+ workflow skills"; 18,807 stars by mid-April. Codex-CLI flavored. ([particula.tech](https://particula.tech/blog/parallel-coding-agents-worktree-pattern-oh-my-codex))
3. **Broccoli** — cloud-sandbox per task, end-to-end PR. Show HN. ([HN 47865642](https://news.ycombinator.com/item?id=47865642))
4. **Agent-worktree** — the "snap mode" tool (`wt new -s claude` → worktree + agent + merge prompt). Show HN. ([HN 46901380](https://news.ycombinator.com/item?id=46901380))
5. **Nano Claude Code** — ~5k LOC Python reimplementation supporting 20+ closed and local open models, multi-agent + persistent memory + skills. (As referenced in [augmentcode review](https://www.augmentcode.com/tools/open-source-agent-orchestrators).)
6. **Synthetic Sciences (YC W26)** — "Claude Code for Science" with ~$1.9M raised; vertical adjacent. ([YC W26 breakdown](https://www.thevccorner.com/p/yc-w26-batch-complete-company-database))
7. **Claude Cowork** — Anthropic; GA Apr 9, 2026; spawns parallel sub-agents inside Claude Desktop. Aimed at non-engineering users primarily, but the architecture overlaps. ([anthropic.com/product/claude-cowork](https://www.anthropic.com/product/claude-cowork), [blockchain.news Apr 2026](https://blockchain.news/news/anthropic-claude-cowork-enterprise-rollout-april-2026))

---

## E. Existential risks specific to Forge's positioning

**Q1: Has anyone shipped "open-weight Claude Code clone with persistent KB and worktrees"?**
Closest: **Composio Agent Orchestrator** (worktrees ✔, multi-agent ✔, but Claude-Code-default and **no published persistent SQLite KB** with confidence/decay/dedup; KB story unclear from README). **Nano Claude Code** (claims multi-agent + persistent memory + skills + open-weight support, ~5k LOC Python, but no separate evaluator). No project publicly combines all four of: (1) **open-weight first**, (2) **planner / generator / evaluator with done-criteria contracts**, (3) **SQLite KB with confidence/decay/imperatives**, (4) **inherits Claude Code's `.claude/` MCP + auto-memory**. Forge's quad is still unique as of Apr 30, 2026.

Differentiation message stays the same as the prior research, **but** it must now explicitly call out vs Composio AO ("we plan, contract, eval — they execute and react") and vs Devin Manage Devins ("they're closed-source, ACU-priced; we're local + Ollama-free").

**Q2: Has the open-weight tool-call reliability problem been solved upstream?**
Yes, mostly. vLLM and SGLang both ship `--tool-call-parser qwen3_coder`. Qwen3-Coder-Next (Feb 2026) and Qwen3.6-27B (Apr 22, 2026) are reliable enough for agentic loops; DeepSeek V4-Flash (Apr 23, 2026) is on track. Forge's "Ollama-by-default for planner / simple sprints" is now reasonable, not optimistic. ([vLLM docs](https://docs.vllm.ai/en/latest/features/tool_calling/), [qwen3-coder-next on Ollama](https://ollama.com/library/qwen3-coder-next))

**Q3: Has Anthropic/OpenAI shipped something that obsoletes the multi-agent orchestrator pattern?**
No — the opposite. Anthropic shipped sub-agent worktree isolation, Managed Agent persistent memory, and Cowork sub-agent spawning in March–April 2026. OpenAI Codex CLI is still single-session per invocation (Rust rewrite was about robustness, not multi-agent). The category is clearly validated. The risk is not obsolescence — it's commoditization. Forge has to win on the open-weight + local + persistent-KB combo, not on the orchestrator pattern alone.

**Q4: Where's the new pressure?**
- **Cursor 3 / Windsurf Wave 13** are the polished commercial competitors. Forge cannot beat them on UX inside an IDE. Forge's anchor is "runs inside any project, talks to your existing `.claude/` setup, no IDE migration." Reaffirm.
- **Devin v3 + Manage Devins** is the high-end closed-source competitor with episodic learning baked in. Forge's KB must demonstrably accumulate value across sessions to compete on the "I learn your codebase" axis.
- **YC W26 had 41.5% of the batch building agent infrastructure.** Several may pivot toward Forge's exact niche by H2 2026. Time-to-MVP matters; the 14-week plan is borderline acceptable.

---

## F. Recommendation

**Proceed with the 14-week plan, with two tightening modifications, and start now.** The freshness check did not surface a project that occupies all four of Forge's quadrants (open-weight-first + planner/generator/evaluator with contracts + SQLite KB with confidence/decay + Claude Code `.claude/` inheritance). Composio AO is the closest, and it's deliberately Claude-Code-coupled and lacks a separate KB; Devin Manage Devins is the closest in spirit, but it's closed-source and ACU-billed. The substrate Forge depends on (Ollama tool-calls reliable on Qwen3-Coder-Next / Qwen3.6, DeepSeek V4 about to land) is more solid than it was in early April. Anthropic shipping sub-agent + memory primitives in Claude Code/Managed Agents is a *validation*, not a threat — it confirms the pattern matters.

**Modifications:** (1) **Cut anything in weeks 1–4 that overlaps Composio AO's existing surface** (basic worktree + spawn + PR); buy that pattern via comparison/inspiration and spend the saved cycles on the SQLite KB + retriever + learner, since that's where Forge is still unique. (2) **Bump open-weight model defaults to Qwen3-Coder-Next and DeepSeek V4-Flash explicitly** in the procedural store seeds and in the routing classifier — the "best local" answer changed in the last 30 days and the prior research's defaults are stale. (3) Optional but recommended: in week ~10 add an explicit "import from Anthropic Managed Agents memory directory" path so users on Anthropic enterprise get free knowledge-base seeding.

The window to ship is real and not infinite — YC W26's agent-infra cohort is iterating fast. Don't pause.

---

## Sources cited (chronological, Mar–Apr 2026)

- Composio Agent Orchestrator open-sourced — MarkTechPost, 2026-02-23: <https://www.marktechpost.com/2026/02/23/composio-open-sources-agent-orchestrator-to-help-ai-developers-build-scalable-multi-agent-workflows-beyond-the-traditional-react-loops/>
- Composio Agent Orchestrator repo (6.7k stars, latest release 2026-03-29): <https://github.com/ComposioHQ/agent-orchestrator>
- Cursor Composer 2 announcement, 2026-03-19: <https://cursor.com/blog/composer-2>
- Cursor 2.0 / Cursor 3 — worktree multi-agent: <https://cursor.com/blog/2-0>
- Cognition: Devin can now Manage Devins, 2026-03-19: <https://cognition.ai/blog/devin-can-now-manage-devins>
- OpenAI Codex CLI v0.116.0, 2026-03-19: <https://github.com/openai/codex/releases>, <https://www.augmentcode.com/learn/openai-codex-cli-enterprise>
- Y Combinator W26 breakdown (Demo Day 2026-03-24, 41.5% agent infra): <https://www.thevccorner.com/p/yc-w26-batch-complete-company-database>, <https://www.buildmvpfast.com/blog/yc-w26-batch-agent-infrastructure-boom>
- Multi-agent / worktree convergence (April 2026): <https://nimbalyst.com/blog/best-multi-agent-coding-tools-2026/>
- Claude Cowork GA, 2026-04-09: <https://www.anthropic.com/product/claude-cowork>, <https://blockchain.news/news/anthropic-claude-cowork-enterprise-rollout-april-2026>
- Claude Opus 4.7 release, 2026-04-16: <https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7>, <https://www.anthropic.com/claude/opus>
- Claude Code April changelog (v2.1.69 → 2.1.101): <https://help.apiyi.com/en/claude-code-changelog-2026-april-updates-en.html>
- Anthropic Managed Agents memory beta, 2026-04-23: <https://opentools.ai/news/anthropic-managed-agents-add-memory-persistent-state-for-ai-that-actually-ships>
- Qwen3.6-27B release, 2026-04-22: <https://huggingface.co/Qwen/Qwen3.6-27B>, <https://www.amd.com/en/developer/resources/technical-articles/2026/day-0-support-for-qwen3-6-on-amd-instinct-gpus.html>
- DeepSeek V4-Flash release, 2026-04-23: <https://akitaonrails.com/en/2026/04/24/llm-benchmarks-parte-3-deepseek-kimi-mimo/>
- vLLM tool-calling parser docs (qwen3_coder): <https://docs.vllm.ai/en/latest/features/tool_calling/>
- Qwen3-Coder-Next on Ollama: <https://ollama.com/library/qwen3-coder-next>
- OpenCode 1.14.30 release, 2026-04-29: <https://opencode.ai/changelog>
- OpenHands SDK / V1 + Index, Jan–Feb 2026: <https://openhands.dev/blog/openhands-index>, <https://github.com/OpenHands/software-agent-sdk/releases>
- SWE-bench Verified leaderboard (April 2026 snapshot): <https://www.marc0.dev/en/leaderboard>, <https://benchlm.ai/benchmarks/sweVerified>
- Aider polyglot leaderboard: <https://aider.chat/docs/leaderboards/>, <https://llm-stats.com/benchmarks/aider-polyglot>
- Plandex v2 / Ollama support: <https://github.com/plandex-ai/plandex/releases>
- Goose / AAIF (Linux Foundation), 2026: <https://www.paperclipped.de/en/blog/goose-block-open-source-ai-agent/>
- Devstral 2 (Dec 2025) and Mistral Small 4 (Mar 2026): <https://mistral.ai/news/devstral-2-vibe-cli>
- Show HN — Agent-worktree: <https://news.ycombinator.com/item?id=46901380>
- Show HN — Broccoli: <https://news.ycombinator.com/item?id=47865642>
- Open-source agent orchestrators landscape (Apr 2026): <https://www.augmentcode.com/tools/open-source-agent-orchestrators>
