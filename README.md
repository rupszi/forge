# Forge

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](pyproject.toml)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()
[![No telemetry](https://img.shields.io/badge/telemetry-none-success.svg)](docs/DECISIONS.md)
[![Tests: passing](https://img.shields.io/badge/tests-passing-success.svg)]()

> **Status: v0.1, local-first.** Runs as a **local web dashboard in your browser**
> (`forge serve`) — OS-agnostic, no native app or installer to build. The
> SWE-bench thesis gate (the project's own go/no-go) is **unrun**: run it
> yourself and report results (see [eval/swebench/](eval/swebench/README.md)).
> A native desktop shell (Tauri) and a few UI panels are **WIP / open for
> contributors**. This is an honest pre-release, not finished-product polish.

> **Forge is the harness that doesn't trust its own work.**

The generator runs on one model. The evaluator runs on a **different model family** — automatically. Each `done_criterion` from the planner gets graded independently with PASS/FAIL + evidence. Local SQLite knowledge base compounds across sessions. **MIT, no telemetry, no signup, runs without an API key.**

Multi-agent harnesses are commodity in 2026 — every major coding tool ships some flavor of it. The problem the field hasn't solved is *who grades the work*. Self-evaluation fails on MT-Bench self-bias. Voting among same-family peers fails because correlated training distribution → correlated failure modes (Feb 2026 paper showed up to **37.6% performance loss**). Forge's bet is structural: the agent doing the work never grades the work, and the grader runs on a different model family from the writer. Default Ollama, optional Claude / OpenAI / vLLM.

→ **New user? Start here:** **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — install, pull models, start the app, connect models, orchestrate agents, generate documents. Local-first, free by default.

→ **Read more:** [docs/POSITIONING.md](docs/POSITIONING.md) (one-sentence story + research synthesis) · [docs/COMPETITIVE_COMPARISON.md](docs/COMPETITIVE_COMPARISON.md) (head-to-head with 18+ tools) · [docs/ROADMAP.md](docs/ROADMAP.md) (what's shipped + what's open for contributors)

---

## What's different about Forge

| | Forge | Aider | OpenHands | Cursor 3 | Claude Code | Composio AO | Devin v3 | OpenClaw |
|---|---|---|---|---|---|---|---|---|
| **Open-weight default** | ✅ | ⚠️ BYO | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Three-agent harness** (planner/generator/evaluator) | ✅ | ❌ | ⚠️ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ symmetric |
| **Cross-family evaluator** (different model from generator) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Persistent KB** with confidence/decay across sessions | ✅ | ❌ | ⚠️ | ⚠️ | ⚠️ | ❌ | ✅ | ❌ |
| **Procedural memory** (routing learns over time) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Done-criteria contracts** (each criterion graded with evidence) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠️ | ❌ vote-based |
| **MCP-bidirectional** (consume + expose KB) | ✅ | ❌ | ❌ | ⚠️ | ⚠️ | ❌ | ❌ | ⚠️ consume |
| **Local-first; no telemetry** | ✅ | ✅ | ⚠️ | ❌ | ✅ | ✅ | ❌ | ✅ |
| **MIT / Apache 2.0** | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ |
| **Skills sandbox** (per-skill capability scoping + isolation) | ✅ | ❌ | ⚠️ Docker | ❌ | ⚠️ permission-mode | ❌ | ❌ | ❌ |
| **Connector ecosystem** (MCP + native plugins) | ✅ | ❌ | ⚠️ | ⚠️ | ✅ via MCP | ❌ | ❌ | ⚠️ |

See [docs/COMPETITIVE_COMPARISON.md](docs/COMPETITIVE_COMPARISON.md) for the full head-to-head with 18+ competitors including a deep-dive on OpenClaw.

## How it works

Forge uses three agent roles inspired by [Anthropic's harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps):

- **Planner / orchestrator** — decomposes objectives into sprint-sized tasks with explicit `done_criteria`. Runs on `qwen2.5:7b` via Ollama (free) by default.
- **Generator** — writes code in an isolated git worktree, one per task. Cheap-tier `qwen2.5-coder:7b`, medium-tier `qwen2.5-coder:14b`, or premium `qwen2.5-coder:32b` — all open-weight, all pulled by `forge models pull`. Models spawn on demand under a RAM budget and evict when memory is tight.
- **Evaluator** — reviews the generator's work from outside, **on a different model family** (`llama3.1:8b` by default — cross-family enforced automatically). Grades each `done_criterion` independently with PASS/FAIL + evidence. Can fail a sprint and send specific feedback for revision.

Every session feeds a four-tier persistent memory (SQLite):

- **Knowledge base** — one-line imperative gotchas / patterns / solutions with confidence scoring
- **Episodic store** — every task execution, error, resolution
- **Procedural memory** — which model works for which task pattern (routing learns over time)
- **Research cache** — web search results with TTL

Memory injection is surgical — the retriever pulls the 3–5 most relevant items per task, capped at ~500 tokens. No context-window pollution.

## Hardware tiers

| Tier | What works |
|---|---|
| 8 GB RAM laptop | ❌ too small — try [OpenCode](https://github.com/sst/opencode) or [Continue](https://github.com/continuedev/continue) |
| 16 GB RAM | ⚠️ planner only on Ollama; BYO API key for generation |
| **24 GB RAM (M3 Pro / M4 Pro)** | ✅ **primary target** — full open-weight Architecture A locally |
| 32 GB+ M-series / RTX 4090 | ✅ comfortable with parallel sprints |
| Multi-GPU server | ✅ Qwen3-Coder-480B / DeepSeek V4 full for SOTA quality |

## Quickstart — one-shot install

```bash
# Inside your existing project directory:
cd ~/projects/my-webapp
bash install.sh             # interactive install + Ollama model pulls
# or
bash install.sh --check     # dry-run; verify environment, change nothing
bash install.sh --yes       # non-interactive (CI / Docker)
bash install.sh upgrade     # reuse existing .venv, pull latest
```

The installer:

1. Verifies OS (macOS / Linux / WSL), Python ≥3.10, ≥16 GB RAM, ≥120 GB disk
2. Prints the **anti-corruption contract** (Forge writes only to `.forge/`, appends one line to `.gitignore`, never edits your source)
3. Installs Ollama if missing; starts the daemon if not running
4. Lists required models with sizes; offers interactive download (resume-friendly)
5. Sets up `.venv` via `uv` (or pip fallback) and installs `forge`
6. Prompts for optional extras (`forge[robust|batch|vector|mcp]`)
7. Adds `.forge/` to `.gitignore`; symlinks `forge` to `~/.local/bin` if on PATH
8. Runs `forge doctor` to validate everything works

That's it. No Anthropic API key required. No signup. No telemetry. The KB lives in `.forge/forge.db` in your project; it never leaves your machine. See [INSTALL.md](INSTALL.md) for detailed install / troubleshooting.

To uninstall: `bash uninstall.sh` (KB preserved by default; pass `--with-data` to also remove `.forge/`).

## CLI commands

```
forge init                               Scan project, create .forge/, display context
forge plan "Build auth API with tests"   Decompose into sprints with contracts
forge run                                Execute all pending sprints
forge run sprint-a1f3                    Execute a specific sprint
forge add "Fix login bug" --model qwen2.5-coder:7b   Add a single task (skip planner)
forge status                             Show dashboard in terminal
forge doctor                             Check Claude Code, Ollama, git, MCP, models
forge models                             List the default local lineup + what's pulled
forge models pull                        Download the default models (disk-guarded)
forge doc "write a README" --format md   Generate a document locally
forge digest bigfile.md                  Map-reduce a large file into a digest
forge merge --approve                    Approve all clean merges
forge merge --show                       Show pending diffs
forge budget                             Show spend vs cap
forge memory                             Show knowledge base summary
forge memory search "supabase"           Search the knowledge base
forge memory add "gotcha" "supabase" "RLS requires service_role for testing"
forge memory import                      Import from Claude Code auto-memory
forge review sprint-a1f3                 Run multi-perspective review
forge replay session-abc123              Replay a session from its trace.jsonl
forge connectors list                    List configured tool connectors
forge connectors add github              Add a new connector via MCP or native plugin
forge skills list                        List installed skills
forge skills install <skill-name>        Install a skill (sandboxed, capability-scoped)
forge reset                              Clear tasks (keep knowledge base)
forge serve                              Start daemon + dashboard (one command)
```

→ Full walkthrough with model-connection and agent-orchestration details: **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**.

## Architecture

```
Browser (localhost:3000)
    │ WebSocket (127.0.0.1:9111)
    ▼
Forge Daemon (Python, asyncio)
    │
    ├── Project Scanner    reads .claude/, package.json, detects stack + MCP, builds repomap
    │
    ├── Memory System      SQLite (.forge/forge.db)
    │     ├── Knowledge base       gotchas / patterns / solutions, confidence scoring
    │     ├── Episodic store       every task ever executed (optional sqlite-vec)
    │     ├── Procedural memory    routing patterns; learns over time
    │     └── Research cache       web search results with TTL
    │
    ├── Planner Agent      decomposes objectives into sprints (qwen2.5:7b default)
    ├── Generator Agents   write code in git worktrees (Qwen3-Coder-Next / Devstral / Claude)
    ├── Evaluator Agent    reviews work externally on a DIFFERENT model family
    ├── Reviewer           multi-perspective review panel (security/perf/correctness)
    ├── Scheduler          parallel execution with dependency resolution
    ├── Budget Controller  spend cap + model downgrade cascade
    ├── Worktree Manager   git worktree lifecycle
    ├── Merge Gate         diff review + evaluator sign-off
    ├── KB-as-MCP Server   exposes Forge's KB as an MCP server to other tools
    ├── Connectors         MCP-first; native plugins for storage/email/git/CI/etc.
    ├── Skills Sandbox     subprocess-isolated, capability-scoped, signed manifest
    └── LLM Registry       pluggable model providers (Anthropic / OpenAI / Ollama / vLLM / custom)
```

Each generator runs as `claude -p "<prompt>"` (or `ollama run …` / `vllm` HTTP) inside an isolated git worktree, inheriting all MCP connections and CLAUDE.md instructions from the project.

## Connectors and plugins

Forge speaks **MCP first** — anything with an MCP server is one config line away. For tools that don't have an MCP server (or need richer integration), the **native plugin API** lets contributors ship Python connectors with declared capabilities.

Out-of-the-box connectors (see [docs/CONNECTORS.md](docs/CONNECTORS.md)):

- **Git/GitHub/GitLab** — PR creation, issue triage, CI status
- **Storage** — S3 / GCS / Cloudflare R2 / Supabase Storage
- **Email** — SendGrid / Resend / Postmark / AWS SES
- **Deployment** — Vercel / Netlify / Cloudflare Pages
- **Database** — Supabase / Neon / Postgres / SQLite
- **Comms** — Slack / Discord / Linear (via MCP)
- **Monitoring** — Sentry / Datadog / Posthog
- **Auth** — Clerk / Auth0 / Supabase Auth

Build your own: [docs/PLUGIN_DEVELOPMENT.md](docs/PLUGIN_DEVELOPMENT.md).

## Skills (Claude-Code-compatible, sandboxed)

Forge supports **Claude-Code-compatible skills** — markdown-based agent capabilities that ship as a directory with a manifest, scripts, and references. **Every skill runs in a sandbox**:

- Subprocess isolation (no shared Python interpreter)
- Capability declaration in `manifest.toml` (network / filesystem / exec scopes)
- Signed manifest verification before first run
- Per-skill resource limits (CPU / memory / wall time)
- All filesystem access scoped to the worktree
- Network egress allow-listed per skill

See [docs/SKILLS.md](docs/SKILLS.md) for the security model and [docs/PLUGIN_DEVELOPMENT.md](docs/PLUGIN_DEVELOPMENT.md) for authoring guides.

## Adding more LLMs

Forge ships with adapters for Anthropic, OpenAI-compatible (vLLM / SGLang / OpenRouter / Together), and Ollama. Adding a new provider is one file in `daemon/llms/` plus a registry entry. See [docs/LLMS.md](docs/LLMS.md).

## Dependencies

Runtime: `httpx`, `websockets`. That's it. Optional: `tree-sitter` (for AST repomap), `networkx` (PageRank in repomap), and the user's choice of model backend (Ollama, vLLM, claude-code).

Dev: `pytest`, `ruff`, `pyright`, `pre-commit`, `respx`, `hypothesis`, `syrupy`.

Optional extras: `forge[robust]` (BAML tolerant parsing), `forge[batch]` (Anthropic batch API), `forge[vector]` (sqlite-vec), `forge[mcp]` (KB-as-MCP).

No agent frameworks. No LangChain. No CrewAI. See [docs/DECISIONS.md ADR-011](docs/DECISIONS.md).

## Documentation

**Full index: [docs/README.md](docs/README.md)** — every doc, grouped (start-here · using · architecture · security · status · history · research).

**Start here:**
- **[docs/POSITIONING.md](docs/POSITIONING.md)** — what Forge is, what it isn't, OpenClaw / OpenHands / Cursor / Claude Code comparisons in one read
- **[docs/ROADMAP.md](docs/ROADMAP.md)** — what's shipped + what's open for contributors (every deferred feature has a contract + entry point + acceptance gates)
- **[INSTALL.md](INSTALL.md)** — detailed install + troubleshooting

**Deeper dives:**
- **[docs/CONNECTORS.md](docs/CONNECTORS.md)** — tool integrations (MCP + native plugins)
- **[docs/SKILLS.md](docs/SKILLS.md)** — skills system + security sandbox
- **[docs/PLUGIN_DEVELOPMENT.md](docs/PLUGIN_DEVELOPMENT.md)** — building your own connector or skill
- **[docs/LLMS.md](docs/LLMS.md)** — adding new model providers
- **[docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md)** — threat model + audit findings (12 attack classes covered)
- **[docs/GAP_ANALYSIS.md](docs/GAP_ANALYSIS.md)** — release gates + remaining work
- [docs/architecture.md](docs/architecture.md) — daemon structure, three-agent pattern
- [docs/memory-system.md](docs/memory-system.md) — four-tier KB design
- [docs/harness-design.md](docs/harness-design.md) — planner/generator/evaluator contracts
- [docs/configuration.md](docs/configuration.md) — env vars, paths
- [docs/COMPETITIVE_COMPARISON.md](docs/COMPETITIVE_COMPARISON.md) — full head-to-head with 18+ tools
- [docs/DECISIONS.md](docs/DECISIONS.md) — locked ADRs
- [docs/DELIVERY_PLAN.md](docs/DELIVERY_PLAN.md) — 16-week build plan to v0.1.0
- [docs/HANDOVER.md](docs/HANDOVER.md) — live state of the build for fresh contributors
- [docs/ENGINEERING_STANDARDS.md](docs/ENGINEERING_STANDARDS.md) — pre-push gate, schema parity, async patterns
- [docs/research/notes/](docs/research/notes/) — raw research notes

## Status

**v0.1, local-first pre-release.** The test suite is green (**1210 tests**); ruff + schema-parity + docs-audit clean; `pip-audit` clean; UI builds. The 2026-06-04 audit closed every finding (see [docs/audits/](docs/audits/2026-06-04-forge-studio/REPORT.md)).

Forge ships as the **OS-agnostic browser dashboard** (`forge serve`) — there is no native app or installer to build. A native desktop shell (Tauri) and a few UI panels are **WIP / open for contributors**. `pyright` is advisory for v0.1 (a tracked type-annotation backlog; the suite is green).

The central thesis is **not yet proven**: the SWE-bench kill gate is **unrun** (it needs Docker + GPU + local models). Run it on your own hardware and report — `forge bench --list-profiles`, then see [eval/swebench/](eval/swebench/README.md). What's shipped vs open for contributors lives in [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/FORGE_STUDIO_TRACKER.md](docs/FORGE_STUDIO_TRACKER.md).

Hard kill criterion: if Forge can't reach **≥30% on a 50-task SWE-bench Verified subset** with the open-weight stack, the open-weight thesis fails and the project pivots. See [docs/DECISIONS.md ADR-015](docs/DECISIONS.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Every PR runs the local pre-push gate before pushing — CI is intentionally light.

## Code of Conduct

[Contributor Covenant v2.1](CODE_OF_CONDUCT.md).

## Security

For security issues, see [SECURITY.md](SECURITY.md) — do not open a public GitHub issue. The full threat model and audit findings live in [docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md).

## Sustainability

Forge has no monetization gates. If you find it useful and want to help: ⭐ the repo, share it, file issues, send PRs. If you want to fund maintenance directly, GitHub Sponsors will be enabled at v0.1.0 launch.

## License

MIT — see [LICENSE](LICENSE). You can use Forge commercially, fork it, modify it, redistribute it. The only requirement is keeping the copyright notice.
