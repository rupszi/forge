# Forge — Positioning

> **Updated 2026-05-01 with primary-source research from OpenClaw, OpenHands, opencode, Cline, Goose, Aider, Crush, Composio AO, Devin v3, Cursor, Claude Code, and the minimalist-agent canon.**
>
> This document answers three questions: (1) **What is Forge in one sentence?** (2) **What is OpenClaw and how is it different?** (3) **Where is the open positioning space and which feature wins it?** It is the canonical reference the README, blog post, launch tweet, and `forge --help` all derive from.

---

## In one sentence

> **Forge is the harness that doesn't trust its own work.**

Long form for the README:

> Forge is a multi-agent coding orchestrator with a **cross-family evaluator** — your generator runs on one model (Claude, Ollama, whatever you have), your evaluator runs on a *different model family*, and grades each `done_criterion` from the planner with PASS/FAIL + evidence. Everything else (worktrees, hooks, slash commands, MCP) is plumbing. Local SQLite knowledge base compounds across sessions. MIT, no telemetry, no signup, runs without an API key.

The single feature that defines the product is the **evaluator-from-a-different-family invariant** combined with **done-criteria contracts that get graded independently**. Every other tool either self-evaluates (fails on MT-Bench self-bias), votes among same-family peers (fails because correlated training distribution → correlated failure modes), or has no evaluator at all (the agent charges off in the wrong direction — the #1 friction across every coding agent in 2026 user research).

---

## What we are NOT

Naming what Forge is *not* is as important as what it is, because the field is crowded with adjacent products.

- **Not a Claude Code replacement.** Forge runs *inside* a Claude Code project. It reads `.claude/settings.json`, `CLAUDE.md`, `.claude/rules/`, MCP server configs, and Claude Code auto-memory. It calls `claude -p` in worktrees as one of its executors. Claude Code users keep using Claude Code; Forge adds a planner / evaluator / KB on top.
- **Not an IDE.** No Cursor / Cline / Continue.dev rivalry. Forge does not ship a tab-completion model, an LSP, a shadow workspace, or a VS Code extension. The CLI + browser dashboard surface targets the developer who *also* uses an IDE — Forge is the headless orchestrator running in a side terminal.
- **Not a SaaS.** No cloud, no signup, no telemetry, no rate-limit pool, no $500/mo subscription. Local SQLite KB in `.forge/forge.db`, never leaves the machine. (See [ADR-007](DECISIONS.md).)
- **Not a framework.** Two pip dependencies (`httpx`, `websockets`). No LangChain, no CrewAI, no LlamaIndex. (See [ADR-011](DECISIONS.md).) Plugins are subprocess-isolated, capability-scoped, hash-pinned — not Python-imported.
- **Not a multi-agent swarm.** Three roles (planner, generator, evaluator), not 60+ specialized agents. Ruflo / Crush / oh-my-codex go the swarm direction; Forge bets on **structural separation** over **specialization**. Three-agent harness, asymmetric roles, cross-family invariant. The harness paper (Anthropic) and the Feb 2026 multi-agent failure paper (arxiv 2603.25773) both point at this same answer: the bottleneck is *what grades the work*, not *how many agents do the work*.

---

## What Forge IS — the five-feature seam

| | Forge | Closest peer | Gap |
|---|---|---|---|
| Cross-family evaluator (different model from generator, mandated) | ✅ | nobody | unique |
| Done-criteria contracts graded independently per criterion | ✅ | nobody | unique |
| Persistent four-tier SQLite KB with confidence + decay across sessions across projects | ✅ | Devin v3 (closed, $500/mo) / Goose (session-scoped, not 4-tier) | open-weight + free differentiator |
| Open-weight default routing (Ollama by default; Claude / OpenAI optional) | ✅ | Aider BYO / OpenHands / opencode BYO / Goose BYO | Forge is the only one with a *default* tier and procedural memory that learns routing |
| MCP-bidirectional (consume from `.claude/`, expose KB-as-MCP-server) | ✅ | nobody (Goose and Claude Code consume; nobody exposes their KB) | unique |

**These five together** are the seam. No competitor — including the new entrants from the 2026 freshness check (Composio AO, Manage Devins, Claude Cowork, Crush, oh-my-codex, Nano Claude Code) — combines all five.

The single most defensible cell is the **cross-family evaluator**: every multi-agent product that has shipped in 2026 either self-evaluates, uses voting among same-family peers (OpenClaw council, Ruflo swarm), or has same-family architect (Aider). The literature says this is the wrong choice — the Feb 2026 paper showed *up to 37.6% performance loss* from correlated failures in same-family multi-agent teams. Forge's mandate ("evaluator from a different family") is the literal mitigation.

---

## OpenClaw — what it is, and where it differs

> Source: [Enderfga/openclaw-claude-code](https://github.com/Enderfga/openclaw-claude-code) v2.14.1, 422 stars, 65 forks, MIT, TypeScript / Node ≥22, last push 2026-04-29.

### What OpenClaw is

OpenClaw (the plugin form — distinct from the unrelated `openclaw/openclaw` personal-AI gateway) is a **TypeScript plugin that wraps coding CLIs behind a unified `ISession` interface** and exposes them via:

1. **27 programmable tools** for session lifecycle, council, ultraplan, ultrareview, inbox.
2. An **OpenAI-compatible HTTP server** at `:18796` so any frontend (Open WebUI, LobeChat, custom chat UI) can drive Claude Code / Codex / Gemini CLI / Cursor Agent through one endpoint.
3. A **multi-agent council mode** — N agents (default 3) work in parallel, each in its own git worktree (`council/Architect`, `council/Engineer`, `council/Reviewer`), with a `[CONSENSUS: YES/NO]` voting protocol after each round, looping until consensus or max-rounds.

The pitch is "**turn Claude Code CLI into a programmable, headless coding engine with plenty of tools, agent teams, and multi-model proxy.**" Targets developers who already use Claude Code (or Codex, Gemini, Cursor) and want to drive it programmatically from another orchestrator.

### Where Forge and OpenClaw differ

| Dimension | Forge | OpenClaw |
|---|---|---|
| **Topology** | Asymmetric: planner → generator → **external** evaluator. Three roles, distinct responsibilities. | Symmetric: N peers each in their own worktree, vote `[CONSENSUS: YES/NO]`. |
| **Verification model** | Cross-family evaluator on a *different* model family from the generator. Each `done_criterion` graded independently with evidence. | Voting among council members. Members may share model family; consensus = majority approval. |
| **Why this matters** | The Feb 2026 multi-agent paper showed same-family voting fails by up to 37.6% due to correlated training distribution. Cross-family is the literature's mitigation. | Voting depends on agents disagreeing. If they share family, they share blind spots. |
| **Persistent memory** | Four-tier SQLite (knowledge / episodic / procedural / research) with confidence/decay/dedup across sessions across projects. | None documented. 7-day on-disk session TTL only. |
| **Open-weight default** | Yes — Ollama (gpt-oss / qwen3-coder-next / deepseek-v4-flash) by default. Procedural memory learns routing over time. | No — Claude / Codex / Gemini / Cursor (all hosted). |
| **MCP** | Bidirectional: consumes `.claude/settings.json` AND exposes Forge's KB as an MCP server (so Claude Desktop, Cursor, Continue, Goose can pull from it). | One-way: it *is* consumed via Claude Code's plugin protocol. |
| **Sandbox** | 5-layer credential redaction; destructive-op classifier; no `shell=True`; signed-manifest hash pinning for plugins; egress allow-list. | `bypassPermissions` is the documented default; per-agent overrides. Weaker default safety posture. |
| **Surface** | Browser dashboard at `localhost:3000` + CLI + (optional) Textual TUI. | 27 programmatic tools + OpenAI-compat HTTP server. No first-party UI; bring your own chat frontend. |
| **Engine breadth** | Claude Code + Ollama + OpenAI-compatible (vLLM / SGLang / OpenRouter / Together). | Claude / Codex / Gemini / Cursor + custom. |
| **Maturity** | Pre-v1 (alpha). 894 tests passing. | v2.14.x, ~weekly releases, 6 contributors. |
| **License** | MIT | MIT |

### Coexistence

These products are largely **orthogonal, not competitive**. OpenClaw is a plugin / programmable surface; Forge is a daemon + dashboard with its own learning loop. They can run in the same project simultaneously:

- Namespace worktrees (`forge-<id>` vs `council/<role>`) to avoid collisions.
- Forge can call OpenClaw's HTTP endpoint as one of its LLM adapters (route a sprint to "OpenClaw council" via the LLM registry).
- A user wanting "drive Claude Code from a chat UI" picks OpenClaw; a user wanting "compounding KB + cross-family evaluator + open-weight default" picks Forge; a user wanting both runs both.

The right framing for the README: *"Forge is not OpenClaw. OpenClaw makes Claude Code programmable; Forge makes the harness that grades Claude Code's output skeptical."*

---

## How Forge compares to the broader field (2026-05-01 snapshot)

| Tool | Tagline | Where it wins | Where it loses |
|---|---|---|---|
| **Claude Code** | Anthropic's flagship coding agent | Tool quality, hooks, frontier model access | Closed; rate-limited; "engineering missteps" admitted Apr 2026; loses on persistent KB |
| **Codex CLI** | OpenAI's terminal agent | Best OS-native sandbox (Seatbelt / bwrap+Landlock); 65.3% of devs prefer over Claude Code per 500-dev survey | Single-agent; OpenAI-only; no KB |
| **Cursor 3** | Multi-agent IDE fork | Tab autocomplete; 8 parallel agents; Composer 2 | Closed; cloud-hybrid; IDE-locked; expensive |
| **Cline** | VS Code agent with per-step approval | Best in-IDE UX; per-step gates; 30+ providers | Single-agent; no cross-session memory beyond `.clinerules/` |
| **opencode** (sst) | Terminal-first AI coding agent | Polished TUI; mobile companion; 152k stars | Single-agent; no persistent KB; provider-delegated safety |
| **Aider** | Git-native pair programming | Repomap (Forge inherits this); architect mode; battle-tested | Single-agent; no evaluator; no learning across sessions |
| **OpenHands** | Open platform for SWE agents | 53–72% SWE-bench Verified; ICLR 2025 paper; Docker sandbox | Heavyweight; "Docker-in-Docker setup hell"; 70+ pip deps |
| **Goose** (Block / LF) | Local extensible agent | MCP-native; Linux Foundation governance; Rust core; Apache 2.0 | Single-agent; session-scoped memory only |
| **Crush** (Charm) | Glamourous TUI agent | Best-looking TUI; LSP context; per-project permissions | Single-agent; FSL license blocks commercial fork-and-host |
| **Devin v3 + Manage Devins** | Cognition's coordinator + sub-Devins | Cloud VM per agent; episodic learning baked in; full procedural memory | Closed; $500/mo+ ACU; phones home |
| **Composio AO** | Open-source multi-agent orchestrator | Worktrees + PRs + auto CI-fix; 6.7k stars in 2 months | No KB; Claude-Code-default; reactive (CI) not contractual (done-criteria) |
| **Ruflo** (formerly Claude Flow) | 60+ agent swarm orchestrator | 314 MCP tools; 31k stars; federated multi-machine swarms | Heavyweight; voting-based (correlated-failure risk); 84.8% SWE-bench self-reported, not audited |
| **OpenClaw plugin** | Programmable coding-CLI proxy | OpenAI-compat HTTP; 4 hosted CLIs; council voting | No persistent KB; voting-based (same family-failure risk); `bypassPermissions` default |

### What's saturated and what's open

- **Saturated**: multi-agent + worktrees + parallel sprints. Composio AO, Cursor 3, Anthropic Cowork, Windsurf Wave 13, Ruflo, OpenClaw all ship this. Forge cannot differentiate here.
- **Saturated**: MCP integration. Goose / Cline / Cursor / Continue / Crush / opencode all support it.
- **Saturated**: hooks, slash commands, custom commands, output styles, AGENTS.md. Claude Code and Codex CLI both shipped these; Forge has parity but it's table stakes.
- **Open**: cross-family evaluator with done-criteria contracts. **Nobody else ships this.**
- **Open**: persistent four-tier KB with confidence/decay/dedup that compounds across sessions across projects. Devin v3 has the closest version, but it's closed and $500/mo.
- **Open**: open-weight + local + free + KB simultaneously. Goose comes closest, but no harness.
- **Open**: "runs *inside* your existing Claude Code project" — inheriting `.claude/`, MCP, auto-memory. Tools either replace Claude Code or wrap it as a subprocess; nobody treats it as substrate.

---

## The minimalist canon — and why Forge isn't there

The "100 lines of Python" coding-agent canon (mini-SWE-agent, PocketFlow, smolagents at ~1000 LOC) has a simple thesis: *the loop is small; everything else is your problem*. Aider stands above this canon at ~25K LOC of Python, deliberately disciplined ("very large context windows aren't useful in practice" — Paul Gauthier), and it's still the gold standard for terminal pair-programming.

Forge is at ~13K LOC of daemon Python with 894 tests. It is **not** in the minimalist canon and shouldn't try to be. It is, however, **disciplined** in the same sense Aider is: every line is there because of a documented architectural decision, every feature has a test, and the runtime dependency surface is two pip packages.

But the research is sharp on this: **"13K LOC and 894 tests is a liability, not an asset, until the product story is one sentence."** This document is that one sentence. Everything in `daemon/` should be readable as supporting *the harness that doesn't trust its own work* or it should be questioned.

---

## What this means for what we ship

The full code-side roadmap is in [ROADMAP.md](ROADMAP.md). The high-leverage takeaway:

- **v0.1.0 must surface the cross-family evaluator as the headline.** README, install screen, `forge doctor`, first-run output, blog post — all lead with the evaluator-from-a-different-family invariant. Today the README leads with "multi-agent coding orchestrator," which is generic.
- **Defer everything that doesn't directly support the headline.** Feature flags exist; behind-flags is fine. Code that's already shipped is shipped. But the *pitch* should be one sentence and the *first 10 minutes of using Forge* should be the evaluator-grading-a-sprint experience, not the wizard, not the plugin runtime, not the slash commands.
- **The community can build the rest.** ROADMAP.md is contribution-ready: every deferred sprint has a contract, an entry point, a test shape, and a "where to plug in" pointer. People can grab a sprint and ship it without reading the entire codebase.

---

## What this means for marketing copy

The launch tweet, blog post, and `forge --help` should converge on one of these three lines (test which lands):

1. *"Forge is the harness that doesn't trust its own work. Cross-family evaluator. Done-criteria contracts. Local SQLite KB that compounds. MIT, no signup, no API key."*
2. *"Multi-agent is everywhere now. Forge's bet: the agent doing the work should never grade the work. So the evaluator runs on a different model family from the generator. Default Ollama, optional Claude/OpenAI. MIT."*
3. *"What if your coding agent's reviewer ran on a different model family from its writer? That's Forge."*

Don't lead with "multi-agent" — that's generic in 2026. Don't lead with "open-weight" — every BYO-key tool checks that box. Lead with the *invariant* nobody else has.

---

## Sources

- Primary research from May 2026 on OpenClaw, OpenHands, opencode, Cline, Goose, Aider, Crush, Composio AO, Devin v3, Cursor, Claude Code (in `docs/research/notes/`).
- The Anthropic GAN-inspired harness essay (https://www.anthropic.com/engineering/harness-design-long-running-apps).
- The Feb 2026 multi-agent failure paper (arxiv 2603.25773) — same-family teams lose up to 37.6%.
- The Sonar 2026 State of Code survey + Anthropic 2026 Agentic Coding Trends Report — what users actually use day-to-day.
- The 500-dev Reddit Claude-Code-vs-Codex survey — real friction signal (rate limits, "agents charge off in the wrong direction").
- [COMPETITIVE_COMPARISON.md](COMPETITIVE_COMPARISON.md) — full head-to-head with 18+ tools.
- [DECISIONS.md](DECISIONS.md) — locked ADRs.
