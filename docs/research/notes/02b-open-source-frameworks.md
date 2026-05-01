# Part 2B — Open-Source Multi-Agent Orchestration Frameworks

A comparative landscape review of 16+ open-source frameworks relevant to Forge's architecture decisions. Each section evaluates production-readiness, lock-in risk, agent-loop primitives, memory/state model, multi-agent topology, tool-use reliability with open-weight LLMs, observability, license, and activity.

The goal is twofold: (1) understand the design space so Forge's own primitives are informed, and (2) identify components that are clean enough to *lift* (i.e., copy ideas from, or depend on as a library) without violating Forge's "no LangChain, no CrewAI, no agent framework" rule.

---

## 1. OpenHands (formerly OpenDevin)

**Overview.** Generalist software-engineering agent built on the *CodeAct* architecture. Core agent emits Python/bash actions executed in a Docker-sandboxed runtime; web browsing is a Playwright-controlled Chromium inside that same sandbox. Now governed under Linux Foundation umbrella; ICLR 2025 paper documents the platform; an *SDK-V1* track (`software-agent-sdk`) splits the agent core out as a composable library.

- **Production-readiness:** *production*. 72.4k stars, enterprise self-hosted Kubernetes deployment, paid Cloud, ICLR 2025 publication.
- **Lock-in risk:** Medium-low. The SDK is explicitly composable; runtime, agent, tools are decoupled. Heavy dependency surface (Docker required for sandboxed runtime).
- **Agent-loop primitives:** *Action / Observation* event loop. `AgentController` drives the loop; `CodeActAgent` produces a single `CmdRunAction`, `IPythonRunCellAction`, `BrowseInteractiveAction`, or `MessageAction` per step; runtime returns matching observation. Loop terminates on `AgentFinishAction` or max-iterations.
- **Memory/state model:** Short-term event stream + history condensation. Memory condensation is research-backed (paper §5). Long-term: file-based "micro-agent" knowledge, plus user-supplied `.openhands/microagents/` files that activate on keyword triggers.
- **Multi-agent topology:** Generalist + delegation. CodeAct is the default generalist; *micro-agents* are specialized prompt overlays that re-use the generalist implementation. Browsing-specialist and editing-specialist agents exist. No true peer-to-peer swarm.
- **Tool-use with open-weight LLMs:** Strong — CodeAct emits *code* (Python/bash strings), not strict JSON tool-calls, so it works with models that don't function-call reliably. LiteLLM under the hood means 100+ providers supported.
- **Observability:** Built-in event-stream replay, trajectory logs (JSONL), Studio-style web UI, OpenTelemetry hooks in v1 SDK.
- **License:** MIT (core); enterprise/ subdir has separate terms.
- **Activity:** Very active. Daily commits, weekly releases through April 2026.

**Forge angle.** OpenHands' `Runtime` abstraction (Docker action-execution server with bash + Jupyter + browser pre-baked) is exactly what Forge would have to build for sandboxed evaluation. *Fork-able candidate.*

---

## 2. SWE-agent / SWE-agent Multimodal (Princeton)

**Overview.** NeurIPS 2024 paper that named and popularized the *Agent-Computer Interface* (ACI) concept — the insight that LM agents are a new class of end-user and benefit from interfaces designed for them, not for humans. Achieved 12.5% pass@1 on SWE-bench in 2024; later v1.1.0 (May 2025) ships "tens of thousands of training trajectories."

- **Production-readiness:** *research, production-adjacent*. Heavily cited; widely forked for SWE-bench leaderboard runs. Less polish than OpenHands but the cleanest reference implementation of ACI.
- **Lock-in risk:** Low. Single repo, Python, MIT.
- **Agent-loop primitives:** `AbstractAgent` → `DefaultAgent` → `RetryAgent`. `step()` returns a `StepOutput(action, observation, done)`. `RetryAgent` wraps multiple `DefaultAgent` configs and runs a review loop to pick the best attempt. Trajectories saved per attempt.
- **Memory/state model:** Per-task `history` (LLM messages) + `trajectory` (action/obs pairs) + `info` metadata. State derives from environment snapshots (`tools.get_state(env)`). No persistent cross-task memory.
- **Multi-agent topology:** Single-agent + retry/review meta-loop. Multimodal variant adds visual screenshot tool but is still single-agent.
- **Tool-use with open-weight LLMs:** Reasonable. Uses templated commands (Jinja2) — agent emits a textual command name + args; ToolHandler parses and executes via `tools.communicate()`. `should_block_action()` gate. Multiline-syntax guard prevents many parser failures, helping weaker models.
- **Observability:** Trajectory JSONL, full message history, Pytest+codecov+pre-commit CI infra.
- **License:** MIT.
- **Activity:** Active but slowing — last release v1.1.0 May 2025; recent commits exist but no major release in ~12 months. Flag for stagnation watch.

**Forge angle.** The ACI insight (design tools for LMs, not humans) is the *core lesson* behind Forge's evaluator-feedback contract. The `should_block_action` + multiline-guard pattern is worth lifting verbatim.

---

## 3. AutoGen / AutoGen Studio (Microsoft)

**Overview.** Conversational multi-agent framework that catalyzed the "agents talking to agents" wave. v0.4 was a ground-up redesign (event-driven, distributed runtime); core API in Python and C#. *Important:* repo is now in **maintenance mode**; users are pushed toward Microsoft Agent Framework.

- **Production-readiness:** v0.4 *production* but on a downgrade path. v0.2 was research-grade. Microsoft's migration messaging is unambiguous: "AutoGen is in maintenance mode."
- **Lock-in risk:** Medium-high — once you adopt AutoGen's `GroupChat` / `ConversableAgent` abstractions, porting away is non-trivial; Microsoft pushing you toward their successor framework adds re-platforming risk.
- **Agent-loop primitives:** Event-driven message-passing actor model. `ConversableAgent.on_messages()` is the unit; `GroupChatManager` orchestrates speaker selection.
- **Memory/state model:** Per-agent message log, optional `AbstractMemory` extension. No first-class persistent KB.
- **Multi-agent topology:** Conversational — two-agent chat, group chat, hub-and-spoke via manager. v0.4 supports *distributed runtime* (agents on different processes/hosts).
- **Tool-use with open-weight LLMs:** Moderate. Default tool-use is JSON function calls (OpenAI-style). Group-chat consensus scales poorly: each extra agent multiplies LLM turns.
- **Observability:** AgentChat Studio (no-code GUI), AutoGenBench benchmark harness, OpenTelemetry traces.
- **License:** MIT (CC-BY-4.0 for docs); Magentic-One subdir has `LICENSE-CODE` (MIT-CODE-style).
- **Activity:** Maintenance mode (acknowledged by Microsoft). Last meaningful release Q1 2026.

**Forge angle.** The lesson is the inverse: AutoGen's conversational pattern is *expensive* and *non-deterministic*. Forge's planner→generator→evaluator pipeline is the antidote. Skip AutoGen as a dependency; study its event-driven core for Forge's WebSocket dispatch.

---

## 4. CrewAI

**Overview.** Role-based crews — "agent" = role + goal + backstory in YAML. Sequential and hierarchical processes. Built-in planning. Notably, CrewAI is "completely independent from LangChain" since v0.30+.

- **Production-readiness:** *production-claimed* but team retention concerns. 50.4k stars, enterprise SaaS, 100k "certified developers." But...
- **Lock-in risk:** **High.** YAML-driven role definitions and Crew/Task abstractions are pervasive — extracting business logic out is rewrite-grade work.
- **Agent-loop primitives:** `Crew.kickoff()` runs Tasks sequentially or hierarchically. Tasks bind to `Agent`s. Hierarchical mode auto-spawns a manager LLM (one extra LLM call per delegation).
- **Memory/state model:** Built-in short-term, long-term (vector), entity memory. Custom storage backends.
- **Multi-agent topology:** Sequential pipeline OR hierarchical (manager + workers). No DAG. No swarm.
- **Tool-use with open-weight LLMs:** Mediocre. Defaults to OpenAI-style JSON function calls; Ollama works but tool reliability degrades on smaller models. No code-as-action mode.
- **Observability:** "Logging is a huge pain" per multiple production reports — `print` and `log` inside Tasks misbehave. Limited tracing.
- **License:** MIT.
- **Activity:** Very active. v1.14.3 April 24 2026.

**Why Forge bans CrewAI.** Three reasons, all correct:

1. **Restrictive scaling.** Role-based orchestration scales smoothly to ~5 agents; beyond that, inter-agent coordination overhead grows fast (per multiple production engineers' reports). Forge expects to fan out 10–20 worktrees in parallel — wrong shape.
2. **Logging/observability gap.** Forge needs deterministic per-sprint trajectories streamed to a UI WebSocket. CrewAI's documented logging issues are a non-starter.
3. **Lock-in.** Forge's commitment to "raw Python + httpx + websockets" exists precisely because frameworks like CrewAI tend to absorb your domain logic into their abstractions. The CLAUDE.md "no CrewAI" rule is the *right* call.

---

## 5. LangGraph (LangChain)

**Overview.** Low-level orchestration framework for stateful agents — directed graphs of nodes (`State -> Partial<State>`), edges, conditional routes. Checkpointing, durable execution, human-in-the-loop, time-travel debugging.

- **Production-readiness:** *production*. The most battle-tested stateful-agent runtime; Klarna and Replit cited as production users. 30.9k stars.
- **Lock-in risk:** Low-medium. Core LangGraph is independent of LangChain LLM wrappers — you can use it with raw API clients. But LangChain ecosystem gravity is real; tutorials assume LangChain primitives.
- **Agent-loop primitives:** `StateGraph` builder → `compile()` → executable graph. Nodes: `State -> Partial<State>`. Edges: simple, conditional. Reducers aggregate multi-source updates per state key. Retry policies, error handlers, cache policies, deferred execution.
- **Memory/state model:** Pluggable checkpointer. In-memory (default), SQLite, Redis, Postgres backends. Short-term: graph state. Long-term: store API for cross-session memory.
- **Multi-agent topology:** Graph (DAG / cyclic). Supports hierarchical, swarm, supervisor patterns by graph construction.
- **Tool-use with open-weight LLMs:** Strong primitives but no built-in fallback for non-tool-calling models. You ship that yourself.
- **Observability:** LangSmith integration (commercial); also OpenTelemetry. Time-travel replay via checkpoints is excellent.
- **License:** MIT.
- **Activity:** Very active. Daily commits.

**Why Forge bans LangChain.** Forge's CLAUDE.md says "no LangChain" — but that ban is most accurate when read as *no LangChain wrappers around LLM calls.* LangGraph proper, if used in isolation, is a respectable graph runtime. The argument for not depending on it:

1. **Two-dependency policy.** Forge's `httpx + websockets` rule is partly aesthetic, partly philosophical: every dep is a long-term liability. LangGraph drags Pydantic, LangChain-core, and a thousand transitive deps.
2. **Forge's actual graph is shallow.** Planner → generators (parallel) → evaluator → merge gate. Three hand-rolled stages. A `StateGraph` is overkill.
3. **Lift the *idea*, not the *library*.** Forge's scheduler implements dependency-wave execution — that's a small DAG executor, ~50 lines. The lock-in cost of LangGraph is not worth the savings.

The "no LangChain" rule is correct for Forge's scope.

---

## 6. MetaGPT

**Overview.** "Code = SOP(Team)" — codifies real software-company SOPs (standard operating procedures) into agent roles: Product Manager, Architect, Project Manager, Engineer. From a one-line requirement, produces user stories, competitive analysis, data structures, APIs, and code.

- **Production-readiness:** *research-grade*. ICLR 2025 (AFlow paper). Demoware-strong; brittle on novel domains. MGX (commercial follow-on) February 2025.
- **Lock-in risk:** Medium. Heavy on YAML workflow definitions.
- **Agent-loop primitives:** `Role.run()` consumes messages, executes `Action`s, publishes new messages on a shared `MessageQueue`. Pub-sub topology.
- **Memory/state model:** Per-role memory + shared environment. Vector RAG plug-ins.
- **Multi-agent topology:** Hierarchical company-org chart. Each role has fixed input/output schemas (the SOP).
- **Tool-use with open-weight LLMs:** Configurable LLM provider (OpenAI, Azure, Ollama, Groq). SOP-driven structured outputs help weaker models — they fill in templates rather than invent JSON.
- **Observability:** Run logs, file artifacts per stage. No first-class trace UI.
- **License:** MIT.
- **Activity:** Active. 67.6k stars.

**Forge angle.** Conceptually adjacent to Forge's planner→generator→evaluator: MetaGPT proves that *SOP-driven specialization* outperforms generic group chat. Forge's sprint-contract-with-done-criteria is essentially an SOP for one task. Don't depend on MetaGPT, but the SOP framing is sound research backing.

---

## 7. ChatDev (OpenBMB)

**Overview.** "Communicative agents for software development" — waterfall-style multi-agent dev. v2.x (March 2026) shifted to a zero-code orchestration platform with DAG topology via *MacNet* (supports 1000+ agents).

- **Production-readiness:** *research → light production*. Apache-2.0 licensed; v2.2.0 March 2026.
- **Lock-in risk:** Medium. Zero-code config files are portable but the orchestration model is opinionated.
- **Agent-loop primitives:** Phased prompt-chaining. Each phase: instructor agent + assistant agent dialogue → artifact → next phase. Experiential Co-Learning Module: instructor and assistant accumulate "shortcut-oriented experiences" — a primitive memory system.
- **Memory/state model:** Per-phase artifacts; cross-session experiential learning.
- **Multi-agent topology:** v1: chain. v2: DAG via MacNet, scales to 1000+ agents.
- **Tool-use with open-weight LLMs:** Configurable BASE_URL/API_KEY — works with any OpenAI-compatible endpoint. MCP support added in v2.
- **Observability:** Visualization tooling (described in v1 paper); v2 has dashboards.
- **License:** Apache-2.0.
- **Activity:** Steady. v2.2.0 March 23 2026 latest.

**Forge angle.** Useful as a *case study* — proves that waterfall-style multi-agent dev works on small toy problems but degrades on novel real codebases. Forge's "evaluator on a different model than generator" is a sharper version of ChatDev's instructor/assistant pattern.

---

## 8. CAMEL-AI / OWL

**Overview.** Two related projects. **CAMEL** is a research framework for "communicative agents" with a `RolePlayingSession` core; claims to scale to 1M agents for emergent-behavior research. **OWL** is built on CAMEL, focused on *workforce* orchestration of mixed-skill agents.

- **Production-readiness:** *research*. CAMEL is a living lab; OWL is more of a coordination layer.
- **Lock-in risk:** Medium.
- **Agent-loop primitives:** Iterative `step()` per agent — input → tool execution → response. Stateful memory per agent.
- **Memory/state model:** Per-agent stateful memory; chat history maintained across role-play turns.
- **Multi-agent topology:** Society / role-play (CAMEL); workforce orchestration (OWL).
- **Tool-use with open-weight LLMs:** Multi-provider — OpenAI, Claude, Gemini, Qwen, DeepSeek, Azure, Ollama. *But* documentation explicitly notes "GPT-4 or later" recommended; weaker models "show significantly lower performance."
- **Observability:** Chat history logs; OWL adds workforce dashboards.
- **License:** Apache-2.0.
- **Activity:** Very active for CAMEL (2,184 commits). OWL: 639 commits, no formal releases (continuous-development pattern, less mature).

**Forge angle.** Skip as a dependency. The role-play pattern is interesting but Forge's planner/generator/evaluator achieves similar division of cognitive labor with less ceremony.

---

## 9. smolagents (Hugging Face)

**Overview.** Deliberately barebones library — main code in `agents.py` is <1000 LOC. Killer feature: **CodeAgent**, where the agent emits Python code snippets (executed in a sandbox) instead of JSON tool-calls. Multiple sandbox backends (E2B, Modal, Docker, WebAssembly) are pluggable.

- **Production-readiness:** *research → light production*. ~27k stars, Apache-2.0. Hugging Face maintains it actively. Used in production by some teams; main risk is the small abstraction surface.
- **Lock-in risk:** **Very low.** The author *encourages* hacking on the source. Component extraction is the design intent.
- **Agent-loop primitives:** `MultiStepAgent` (abstract) → `CodeAgent` (code-as-action) and `ToolCallingAgent` (JSON). `run()` loops `_step_stream()`. Optional planning steps every N iterations.
- **Memory/state model:** Per-run `Memory` with step tracking. No persistent cross-run memory (intentional — bring your own).
- **Multi-agent topology:** Managed agents — one agent can be a "tool" of another, enabling tree topology.
- **Tool-use with open-weight LLMs:** **Best-in-class.** Code-as-action wins because (a) Python is the native action language for most LLM training data and (b) it sidesteps JSON tool-call format-fragility on smaller open-weight models. Reported ~30% fewer steps and LLM calls vs. JSON agents on benchmarks. Smolagents-with-open-models matches closed-model performance in their evals.
- **Observability:** Step logs, callback hooks, OpenTelemetry traces.
- **License:** Apache-2.0.
- **Activity:** Very active.

**Forge angle.** **Highest-priority lift candidate.** Forge already runs a sandboxed Python environment via `claude -p` in worktrees, so the *concept* is parallel — but smolagents' `LocalPythonInterpreter` and `E2BSandbox` are well-tested implementations of code-as-action. Specifically lift:

1. The `LocalPythonInterpreter` AST-walking sandbox (whitelisted imports, no `eval`/`exec`) — Forge could use this for its evaluator's "verify by running this assertion" step.
2. The `Tool` base class is ~50 lines and clean.
3. The `MultiStepAgent` skeleton is a textbook implementation of the ReAct loop with planning.

This is the one open-source agent library Forge can probably ship as a dep without violating its own minimalism — but even better, the sub-1000-LOC scope means Forge could re-implement the bits it needs in 200 lines.

---

## 10. Letta (formerly MemGPT)

**Overview.** The MemGPT paper ("LLMs as Operating Systems") productized. Stateful agents with self-edited memory blocks — agents call tools to modify their own memory.

- **Production-readiness:** *production*. v0.16.7 March 31 2026, 22.4k stars, 100+ contributors.
- **Lock-in risk:** Medium. Memory APIs are pervasive in agent code.
- **Agent-loop primitives:** `Agent` extends `BaseAgent`. `inner_step()` is one tool-calling iteration; *heartbeat* mechanism chains steps when a tool requests follow-up. Sandboxed tool execution (`ToolExecutionSandbox`). `return_char_limit` prevents context overflow.
- **Memory/state model:** **The reason to study Letta.** Three-tier hierarchy:
  - **Core memory** — in-context blocks (RAM analog), labeled `human` / `persona` / etc., editable by agent tools.
  - **Recall memory** — full message history, searchable (`text_search`, `date_search` tools).
  - **Archival memory** — vector DB for long-running facts and external data sources.
  - Self-editing: agent decides what to write/read using normal tool calls.
- **Multi-agent topology:** Multi-agent supported in v0.x; agents share or isolate memory blocks.
- **Tool-use with open-weight LLMs:** Tool-call-based — JSON function calls. Recommends Opus 4.5 / GPT-5.2; weaker models suffer.
- **Observability:** Per-step trace, message log, web UI.
- **License:** Apache-2.0.
- **Activity:** Very active.

**Forge angle.** Letta's three-tier memory model is *exactly* the gradient Forge's KB needs to grow into. Forge currently has episodic + semantic + procedural + research, all SQLite. Letta validates that the working/recall/archival split is real and works. Don't depend on Letta — its read-only-block validation and self-editing tools are elegant patterns Forge can copy.

---

## 11. Magentic-One (Microsoft Research)

**Overview.** Generalist multi-agent team for open-ended web/file tasks. Now part of `autogen-agentchat`. Architecture: an **Orchestrator** agent maintains a *task ledger* (facts, hypotheses, plan) and a *progress ledger* (per-step status), and dispatches to specialist agents: MultimodalWebSurfer, FileSurfer, Coder, ComputerTerminal.

- **Production-readiness:** *research*, but with serious benchmark numbers. GAIA / AssistantBench / WebArena competitive results.
- **Lock-in risk:** Medium-high — depends on AutoGen v0.4 stack which is itself in maintenance mode.
- **Agent-loop primitives:** Orchestrator loop: (1) update task ledger with facts, (2) update plan, (3) pick next agent, (4) verify progress, (5) repeat. Re-plans on failure.
- **Memory/state model:** Task ledger + progress ledger (in-context).
- **Multi-agent topology:** Hub-and-spoke — Orchestrator at center, specialists as spokes. Specialists are added/removed without prompt re-tuning.
- **Tool-use with open-weight LLMs:** JSON function calls; web/file specialists rely on tool-call reliability of GPT-4o-class models.
- **Observability:** Task-ledger transcripts; AutoGenBench harness (designed for repeatable agent benchmarks with isolation).
- **License:** MIT (LICENSE-CODE).
- **Activity:** Frozen as standalone package; ported into AgentChat which is itself in maintenance mode. **Flag for stagnation.**

**Forge angle.** The *task ledger / progress ledger* split is precisely what Forge calls the *sprint contract* + *evaluator verdict*. Magentic-One validates the architectural choice. Don't depend on Magentic-One; its parent AutoGen is downgrading.

---

## 12. Open-source Claude Code clones

A 2025–2026 cottage industry. Claude Code's UX (terminal-first, full-repo agent, MCP-native) sparked a wave of clones using different LLMs.

| Project | Stars | License | Languages | Notable |
|---|---|---|---|---|
| **OpenCode** (`sst/opencode`) | ~152k | MIT | TypeScript | 75+ providers, client/server arch, build & plan agents, terminal-first, subscription piggybacking |
| **Cline** (VSCode ext) | ~61k | Apache-2.0 | TypeScript | Human-in-the-loop GUI; uses Claude's Computer Use; MCP-native |
| **Aider** | ~44k | Apache-2.0 | Python | Repo-map; multiple edit formats (whole/diff/udiff); auto-commits; Claude 3.7 Sonnet recommended |
| **OpenClaude** (`Gitlawb`) | ~25k | MIT | TypeScript | OpenAI/Gemini/DeepSeek/Ollama/200+ providers; gRPC server; bash/file tools/grep/glob/agents/tasks |
| **OpenClaw plugin** (`Enderfga/openclaw-claude-code`) | ~417 | MIT | TypeScript | Headless Claude Code; multi-agent council with git-worktree isolation; consensus voting |
| **ClaudeClaw** (`moazbuilds`) | ~1k | MIT | TypeScript | Lightweight daemon on top of Claude Code; cron jobs; Telegram/Discord bridges |
| **OpenWork** (`different-ai`) | ~14.5k | MIT | TS/Rust | Open-source Claude Cowork clone; powered by opencode; local-first desktop |
| **Open CoDesign** (`OpenCoworkAI`) | small | MIT | TypeScript | Claude Design alternative; Electron+React |

**Pattern observations.**

- **Every credible clone is MIT or Apache-2.0** — important for Forge, which sits as a layer *on top of* Claude Code rather than replacing it.
- **MCP support is table stakes** — every serious project wires up MCP because Claude Code did.
- **Terminal-first wins.** Browser GUIs (Open CoDesign, OpenWork) are niche; the heavy users want CLIs.
- **Multi-agent council pattern** (OpenClaw plugin: multiple agents on the same codebase with git-worktree isolation + consensus voting) is the closest existing analog to Forge's planner→generators→evaluator. Worth reading their `skills/references/` for prior art.
- **OpenCode's "build" + "plan" agent split** is a leaner version of Forge's planner/generator separation. Forge should test against OpenCode UX as a baseline.

---

## 13. Goose (Block, now under Linux Foundation's Agentic AI Foundation)

**Overview.** Rust-core extensible agent with first-class MCP. Native desktop app, CLI, API. 70+ MCP extensions. 15+ LLM providers.

- **Production-readiness:** *production*. 43.6k stars, 132 releases, Linux Foundation-hosted. Block (Square's parent) operates it.
- **Lock-in risk:** Low. MCP-native means tools are portable in/out.
- **Agent-loop primitives:** Rust core (`crates/goose`), MCP-bridge for tool execution. Session-scoped agent loop. Specific loop primitives not surfaced in README but ACP-style schemas (`acp-meta.json`, `acp-schema.json`) suggest Agent Communication Protocol roots.
- **Memory/state model:** Session-scoped; persisted across runs; details minimal in public docs.
- **Multi-agent topology:** Single-agent with extensions (no advertised multi-agent topology).
- **Tool-use with open-weight LLMs:** Strong — 15+ providers including Ollama. MCP tools execute out-of-process so providers' tool-call quirks are bounded.
- **Observability:** Session logs.
- **License:** Apache-2.0.
- **Activity:** Very active. 4,331 commits.

**Forge angle.** Most architecturally aligned with Forge's own constraints (MCP-native, multi-LLM, extensible). Goose validates Forge's bet on inheriting MCP from the host environment. **Watch closely; do not depend on it** — Forge runs on top of Claude Code which already speaks MCP, so Goose's MCP layer is redundant.

---

## 14. Plandex v2

**Overview.** Terminal coding agent for large multi-file tasks. Pet feature: **cumulative diff review sandbox** — keeps generated changes separate from project files until ready, with full version control (branches for exploring multiple paths).

- **Production-readiness:** *production-claimed*. Hosted Cloud + self-host.
- **Lock-in risk:** Low-medium. Terminal-first, MIT.
- **Agent-loop primitives:** Configurable autonomy — full-auto to step-confirm. Tree-sitter-based project mapping (30+ languages) for context selection.
- **Memory/state model:** 2M-token effective context window via context-selection-per-step. Plan-as-data with branching version control.
- **Multi-agent topology:** Single-agent.
- **Tool-use with open-weight LLMs:** "Best models from Anthropic, OpenAI, Google, and open source." OpenRouter-friendly.
- **Observability:** Plan branches as observable artifacts; per-step diff review.
- **License:** MIT.
- **Activity:** Active.

**Forge angle.** Plandex's *cumulative diff sandbox* maps almost 1:1 onto Forge's *git worktree* pattern. Plandex implements it without true git worktrees (its own diff layer). Forge's worktree approach is cleaner and more native. Lift the *plan-with-branches* concept for Forge's MergeGate.

---

## 15. R2R (SciPhi)

**Overview.** "RAG-as-a-platform." Multimodal ingestion, hybrid search (semantic + keyword), automatic entity/relationship extraction (knowledge graph), Deep Research agentic API.

- **Production-readiness:** *production*. v3.6.5 June 2025. (Last release older than ideal — flag for slowing activity.)
- **Lock-in risk:** Medium. Adopting R2R as your retrieval layer is sticky.
- **Agent-loop primitives:** Deep Research API does multi-step retrieval reasoning, not general agentry.
- **Memory/state model:** Vector + hybrid + KG; auth & multi-tenant collections.
- **Multi-agent topology:** N/A — single-agent retrieval.
- **Tool-use with open-weight LLMs:** Configurable LLM endpoint.
- **Observability:** Standard logs.
- **License:** MIT.
- **Activity:** Slowing — last release ~10 months pre-current date. **Flag.**

**Forge angle.** Forge's CLAUDE.md explicitly says "no vector embeddings — SQLite LIKE is enough" and "no external memory services." R2R is the negative example: a sophisticated RAG platform that Forge correctly avoids. Useful only as a reference for *if* Forge ever needs hybrid search; until then, don't add the complexity.

---

## 16. Codel

**Overview.** Lightweight autonomous coder. Docker-sandboxed. PostgreSQL for command history. Built-in browser + editor tools.

- **Production-readiness:** *toy / research*. v0.2.2 from April 2024, no recent releases.
- **Lock-in risk:** Low (small codebase).
- **Agent-loop primitives:** Auto-determines next steps; no human in the loop between actions.
- **Memory/state model:** PostgreSQL-backed command history.
- **Multi-agent topology:** Single-agent.
- **Tool-use with open-weight LLMs:** OpenAI + Ollama + OpenAI-compatible.
- **Observability:** PostgreSQL log.
- **License:** **AGPL-3.0** — copyleft. Risky for projects that want to ship closed-source alongside.
- **Activity:** **Stagnant** — last release April 2024. **Flag, do not depend.**

**Forge angle.** Skip. AGPL alone disqualifies it from Forge's MIT context.

---

## Cross-cutting observations

### Tool-use reliability with open-weight LLMs

Three patterns dominate:

1. **JSON function calls** — AutoGen, CrewAI, Letta, Magentic-One. Brittle on Llama-3-8B, Qwen-7B, etc. Most frameworks accept this and recommend GPT-4-class models.
2. **Code-as-action** — OpenHands (CodeAct), smolagents (CodeAgent). Strong with open-weights because Python is in the training distribution.
3. **Templated commands with parser guards** — SWE-agent's ACI. The `should_block_action` + `guard_multiline_input` style salvages weaker models.

**For Forge:** because every generator agent is `claude -p`, Forge dodges the open-weight tool-call problem entirely *for Claude calls*. The pain surfaces only for the local-Ollama planner and learner. Smolagents-style code-as-action is the cleanest fix if those break.

### Observability

The frameworks split into:

- **Trace-first** (LangGraph, OpenHands SDK v1, Letta, AutoGen): structured event streams, replay-able.
- **Log-first** (CrewAI, MetaGPT, ChatDev, OWL): print/log driven, hard to debug at scale.

**For Forge:** the WebSocket event protocol is already trace-first. Match LangGraph's level of structure (typed events, replay).

### Activity / stagnation flags

| Project | Status | Reason |
|---|---|---|
| AutoGen | maintenance mode | Microsoft pushing migration to Microsoft Agent Framework |
| Magentic-One | frozen → ported | Now part of AutoGen, which is itself in maintenance |
| SWE-agent | slowing | Last release v1.1.0 May 2025 |
| R2R | slowing | Last release v3.6.5 June 2025 |
| Codel | **stagnant** | Last release April 2024 |
| OWL | continuous-no-release | No formal versioning; risky for production |

---

## Summary table — frameworks × criteria

| Framework | Prod | Lock-in | Loop primitive | Memory | Topology | Open-LLM tool-use | License | Activity |
|---|---|---|---|---|---|---|---|---|
| OpenHands | prod | med-low | action/obs | event stream + microagents | generalist + delegation | code-as-action | MIT | very active |
| SWE-agent | research | low | step()→StepOutput | trajectory only | single + retry | templated cmds | MIT | slowing |
| AutoGen | maint | high | event-driven actor | per-agent log | conversational graph | JSON | MIT | maintenance |
| CrewAI | prod | high | Crew.kickoff + Tasks | short/long/entity | sequential / hier | JSON | MIT | very active |
| LangGraph | prod | low-med | StateGraph nodes | pluggable checkpoint | DAG / cyclic | bring-your-own | MIT | very active |
| MetaGPT | research | med | Role.run + msg queue | per-role + RAG | hierarchical org | SOP-templated | MIT | active |
| ChatDev | research | med | phased dialogue | experiential | chain (v1) / DAG (v2) | OpenAI-compat | Apache-2.0 | steady |
| CAMEL/OWL | research | med | step() per agent | stateful per-agent | role-play / workforce | needs GPT-4-class | Apache-2.0 | active / no-rel |
| smolagents | light prod | very low | MultiStepAgent.run | per-run only | managed agents tree | code-as-action | Apache-2.0 | very active |
| Letta | prod | med | inner_step + heartbeat | core/recall/archival | multi-agent shared mem | JSON | Apache-2.0 | very active |
| Magentic-One | research | med-high | orchestrator + ledgers | task/progress ledger | hub-and-spoke | JSON | MIT | frozen |
| OpenCode | prod | low | build/plan agents | session | single + plan/build | multi (75+) | MIT | very active |
| Cline | prod | low | VSCode loop | AST-aware ctx mgmt | single | multi | Apache-2.0 | very active |
| Aider | prod | low | repo-map + edit fmts | repo map | single | multi | Apache-2.0 | active |
| Goose | prod | low | session loop + MCP | session-scoped | single + extensions | multi (15+) | Apache-2.0 | very active |
| Plandex | prod | low-med | configurable autonomy | 2M ctx + plan branches | single | multi | MIT | active |
| R2R | prod | med | Deep Research agent | vector + KG + hybrid | retrieval-only | configurable | MIT | slowing |
| Codel | toy | low | auto-step | Postgres history | single | OpenAI/Ollama | **AGPL-3.0** | **stagnant** |

---

## What to lift into Forge

| Component | From | What it gives Forge | Lift mode |
|---|---|---|---|
| Docker action-execution runtime | OpenHands `runtime/` | Sandboxed bash/Jupyter/Chromium for evaluator's "verify by running" | **Fork** (or vendor concept) |
| Agent-Computer Interface design | SWE-agent (paper) | The principle that tool design matters more than agent prompting | **Idea** |
| `should_block_action` + multiline guard | SWE-agent | Pre-execution safety on agent-emitted commands | **Copy** ~30 LOC |
| `LocalPythonInterpreter` AST sandbox | smolagents | Safe Python eval for evaluator assertions | **Copy** ~150 LOC |
| `MultiStepAgent` skeleton | smolagents | Reference ReAct loop with optional planning | **Idea** (re-implement in 200 LOC) |
| Code-as-action pattern | smolagents / OpenHands CodeAct | Robust tool-use for open-weight Ollama planner | **Pattern** |
| Three-tier memory (core / recall / archival) | Letta | Validated upgrade path for Forge's KB beyond flat SQLite | **Idea** |
| Self-editing memory tool pattern | Letta | Agents call tools to mutate their own memory blocks | **Pattern** |
| Task ledger / progress ledger split | Magentic-One | Validates Forge's sprint-contract + evaluator-verdict design | **Idea (validation)** |
| Multi-agent council with git-worktree isolation | OpenClaw plugin | Direct prior art for Forge's parallel-generator pattern | **Study** |
| `build` + `plan` agent split | OpenCode | Lean two-agent UX worth benchmarking against | **Study / UX baseline** |
| Cumulative diff sandbox | Plandex | Plan-as-data with branches; complements MergeGate | **Idea** |
| StateGraph / dependency-wave concept | LangGraph | DAG executor for sprint dependencies (~50 LOC reimplementation) | **Idea, NOT dep** |
| Trajectory JSONL + replay | OpenHands SDK / LangGraph | Structured per-sprint event stream | **Pattern** for ws_server.py |
| MCP-native everywhere | Goose | Confirms Forge's "inherit MCP from Claude Code" bet | **Validation** |
| Repo-map context loading | Aider | Full-codebase awareness without dumping | **Pattern** for retriever.py |

**Frameworks Forge should NOT depend on (even though tempting):**

- **CrewAI** — logging/observability gap, lock-in. CLAUDE.md ban is correct.
- **LangChain core** — gravity, transitive deps. CLAUDE.md ban is correct.
- **LangGraph** — overkill for Forge's shallow DAG; would violate two-dep rule. Use the *idea* not the lib.
- **AutoGen** — maintenance mode; Microsoft pushing migration.
- **Letta** — beautiful memory model but adds a server dependency; Forge's SQLite path is right for now.
- **R2R** — vector search Forge explicitly doesn't want.
- **Codel** — AGPL + stagnant.

**Frameworks Forge could fork/study source from (no runtime dep):**

- **smolagents** — sub-1000-LOC, Apache-2.0, extraction-friendly by design.
- **SWE-agent** — clean reference of ACI patterns.
- **OpenHands** — runtime container is genuinely useful and modular.
- **OpenClaw plugin / OpenCode** — closest existing UX prior art.

---

## Citations

Primary sources (GitHub repos and source files):

- [OpenHands repo](https://github.com/All-Hands-AI/OpenHands)
- [OpenHands SDK docs](https://docs.openhands.dev/sdk)
- [OpenHands Runtime Architecture](https://docs.openhands.dev/openhands/usage/architecture/runtime)
- [OpenHands ICLR 2025 paper](https://openreview.net/pdf/95990590797cff8b93c33af989ecf4ac58bde9bb.pdf)
- [OpenHands SDK paper (arXiv 2511.03690)](https://arxiv.org/pdf/2511.03690)
- [SWE-agent repo](https://github.com/SWE-agent/SWE-agent)
- [SWE-agent NeurIPS 2024 paper (arXiv 2405.15793)](https://arxiv.org/abs/2405.15793)
- [SWE-agent agents.py source](https://github.com/SWE-agent/SWE-agent/blob/main/sweagent/agent/agents.py)
- [AutoGen repo](https://github.com/microsoft/autogen)
- [Magentic-One package](https://github.com/microsoft/autogen/tree/main/python/packages/autogen-magentic-one)
- [Magentic-One paper (arXiv 2411.04468)](https://arxiv.org/abs/2411.04468)
- [CrewAI repo](https://github.com/crewAIInc/crewAI)
- [LangGraph repo](https://github.com/langchain-ai/langgraph)
- [LangGraph StateGraph source](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/graph/state.py)
- [MetaGPT repo](https://github.com/geekan/MetaGPT)
- [ChatDev repo](https://github.com/OpenBMB/ChatDev)
- [CAMEL repo](https://github.com/camel-ai/camel)
- [OWL repo](https://github.com/camel-ai/owl)
- [smolagents repo](https://github.com/huggingface/smolagents)
- [smolagents agents.py source](https://github.com/huggingface/smolagents/blob/main/src/smolagents/agents.py)
- [smolagents launch blog post](https://huggingface.co/blog/smolagents)
- [Letta repo](https://github.com/letta-ai/letta)
- [Letta agent.py source](https://github.com/letta-ai/letta/blob/main/letta/agent.py)
- [Letta memory management docs](https://docs.letta.com/advanced/memory-management/)
- [Goose repo](https://github.com/block/goose)
- [Plandex repo](https://github.com/plandex-ai/plandex)
- [R2R repo](https://github.com/SciPhi-AI/R2R)
- [Codel repo](https://github.com/semanser/codel)

Secondary sources (clones and comparison posts):

- [OpenCode (sst)](https://github.com/sst/opencode)
- [Cline](https://github.com/cline/cline)
- [Aider](https://github.com/Aider-AI/aider)
- [OpenClaude (Gitlawb)](https://github.com/Gitlawb/openclaude)
- [OpenClaw plugin (Enderfga)](https://github.com/Enderfga/openclaw-claude-code)
- [ClaudeClaw (moazbuilds)](https://github.com/moazbuilds/claudeclaw)
- [OpenWork (different-ai)](https://github.com/different-ai/openwork)
- [Open CoDesign (OpenCoworkAI)](https://github.com/OpenCoworkAI/open-codesign)
- [5 Claude Code Alternatives in 2026 (Builder.io)](https://www.builder.io/blog/claude-code-alternatives)
- [DataCamp: CrewAI vs LangGraph vs AutoGen](https://www.datacamp.com/tutorial/crewai-vs-langgraph-vs-autogen)
- [Production Engineer's Honest Comparison (Plain English)](https://python.plainenglish.io/autogen-vs-langgraph-vs-crewai-a-production-engineers-honest-comparison-d557b3b9262c)
- [LangChain vs CrewAI vs AutoGen: Which One Breaks in Production (Cordum)](https://cordum.io/blog/ai-agent-frameworks-comparison)
- [Smolagents vs LangGraph (ZenML)](https://www.zenml.io/blog/smolagents-vs-langgraph)
- [Writing actions as code vs JSON (HF Agents course)](https://huggingface.co/learn/agents-course/en/unit2/smolagents/tool_calling_agents)
