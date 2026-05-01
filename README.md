# Forge

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](pyproject.toml)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()
[![No telemetry](https://img.shields.io/badge/telemetry-none-success.svg)](docs/DECISIONS.md)

> **Free. MIT. Local-first. No telemetry. No signup. No API key required.**

Forge is a multi-agent coding orchestrator that runs inside your existing project folder. It discovers your `.claude/` configuration and MCP servers, then orchestrates parallel coding agents (open-weight via Ollama, or Claude Code) against git-worktree-isolated copies of your repo. Every session feeds a persistent SQLite knowledge base that compounds across projects — Forge gets smarter the more you use it.

Think of it as **"Claude Code with a persistent brain that runs locally on open weights."**

---

## What's different about Forge

| | Forge | Aider | OpenHands | Cursor | Claude Code | Composio AO | Devin |
|---|---|---|---|---|---|---|---|
| **Runs on open-weight LLMs by default** | ✅ | ⚠️ BYO | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Three-agent harness** (planner/generator/evaluator) | ✅ | ❌ | ⚠️ | ✅ | ⚠️ | ✅ | ✅ |
| **Cross-family evaluator** (different model from generator) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Persistent KB across sessions** with confidence/decay | ✅ | ❌ | ⚠️ | ⚠️ | ⚠️ | ❌ | ✅ |
| **Procedural memory** (routing learns over time) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Done-criteria contracts** (each criterion graded independently) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠️ |
| **MCP-bidirectional** (consume + expose KB) | ✅ | ❌ | ❌ | ⚠️ | ⚠️ | ❌ | ❌ |
| **Local-first; no telemetry** | ✅ | ✅ | ⚠️ | ❌ | ✅ | ✅ | ❌ |
| **MIT / Apache 2.0** | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |

See [docs/COMPETITIVE_COMPARISON.md](docs/COMPETITIVE_COMPARISON.md) for the full head-to-head with 18 competitors.

## How it works

Forge uses three agent roles inspired by [Anthropic's harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps):

- **Planner** — decomposes objectives into sprint-sized tasks with explicit `done_criteria`. Runs on `gpt-oss:20b` via Ollama (free) by default.
- **Generator** — writes code in an isolated git worktree, one per task. Cheap-tier `qwen3-coder-next`, medium-tier `qwen3.6:27b`, or premium `deepseek-v4-flash` — all open-weight, all Apache 2.0 / MIT.
- **Evaluator** — reviews the generator's work from outside, **on a different model family** (cross-family enforced automatically). Grades each `done_criterion` independently with PASS/FAIL + evidence. Can fail a sprint and send specific feedback for revision.

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

## Quickstart

```bash
# 1. Install uv (the workflow tool — fast, manages Python)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install Ollama and pull the default models
brew install ollama && ollama serve   # in one terminal
ollama pull gpt-oss:20b               # ~14 GB — planner
ollama pull qwen3-coder-next          # ~50 GB MoE — cheap-tier generator
ollama pull qwen3.6:27b               # ~16 GB — medium-tier generator
ollama pull deepseek-v4-flash         # ~13 GB — premium-tier generator
ollama pull nomic-embed-text          # ~270 MB — episodic vector recall

# 3. Clone Forge and set up
git clone https://github.com/<your-org>/forge.git
cd forge
./setup.sh

# 4. Initialize in your existing project
cd ~/projects/my-webapp
forge init    # scans .claude/, package.json, detects stack + MCP

# 5. Start the dashboard
forge serve   # → http://localhost:3000
```

That's it. No Anthropic API key required. No signup. No telemetry. The KB lives in `.forge/forge.db` in your project; it never leaves your machine.

## CLI commands

```
forge init                               Scan project, create .forge/, display context
forge plan "Build auth API with tests"   Decompose into sprints with contracts
forge run                                Execute all pending sprints
forge run sprint-a1f3                    Execute a specific sprint
forge add "Fix login bug" --claude       Add a single task (skip planner)
forge status                             Show dashboard in terminal
forge doctor                             Check Claude Code, Ollama, git, MCP
forge models                             List available Ollama models
forge merge --approve                    Approve all clean merges
forge merge --show                       Show pending diffs
forge budget                             Show spend vs cap
forge memory                             Show knowledge base summary
forge memory search "supabase"           Search the knowledge base
forge memory add "gotcha" "supabase" "RLS requires service_role for testing"
forge memory import                      Import from Claude Code auto-memory
forge research "next.js middleware auth" Manual web research
forge review sprint-a1f3                 Run multi-perspective review
forge replay session-abc123              Replay a session from its trace.jsonl
forge reset                              Clear tasks (keep knowledge base)
forge serve                              Start daemon + open browser dashboard
```

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
    ├── Planner Agent      decomposes objectives into sprints (gpt-oss:20b default)
    ├── Generator Agents   write code in git worktrees (Qwen3-Coder-Next / Devstral / Claude)
    ├── Evaluator Agent    reviews work externally on a DIFFERENT model family
    ├── Reviewer           multi-perspective review panel (security/perf/correctness)
    ├── Scheduler          parallel execution with dependency resolution
    ├── Budget Controller  spend cap + model downgrade cascade
    ├── Worktree Manager   git worktree lifecycle
    ├── Merge Gate         diff review + evaluator sign-off
    └── KB-as-MCP Server   exposes Forge's KB as an MCP server to other tools
```

Each generator runs as `claude -p "<prompt>"` (or `ollama run …` / `vllm` HTTP) inside an isolated git worktree, inheriting all MCP connections and CLAUDE.md instructions from the project.

## Dependencies

Runtime: `httpx`, `websockets`, `tree-sitter` (for repomap), `networkx` (PageRank in repomap), and the user's choice of model backend (Ollama, vLLM, claude-code).
Dev: `pytest`, `ruff`, `pyright`, `pre-commit`, `respx`, `hypothesis`, `syrupy`.
Optional extras: `forge[robust]` (BAML tolerant parsing), `forge[batch]` (Anthropic batch API), `forge[vector]` (sqlite-vec), `forge[mcp]` (KB-as-MCP).

No agent frameworks. No LangChain. No CrewAI. See [docs/DECISIONS.md ADR-011](docs/DECISIONS.md).

## Documentation

- [BUILD_PLAN.md](docs/BUILD_PLAN.md) — 14-week tracker (currently in Phase 1)
- [ENGINEERING_STANDARDS.md](docs/ENGINEERING_STANDARDS.md) — pre-push gate, schema parity, async patterns
- [DECISIONS.md](docs/DECISIONS.md) — locked ADRs
- [COMPETITIVE_COMPARISON.md](docs/COMPETITIVE_COMPARISON.md) — head-to-head with 18 competitors
- [Architecture](docs/architecture.md), [Memory System](docs/memory-system.md), [Harness Design](docs/harness-design.md), [Security](docs/security.md), [Configuration](docs/configuration.md)
- [Research notes](docs/research/notes/) — six raw research notes + April-30 freshness check

## Status

Forge is currently **alpha** — Phase 1 of a 14-week build plan. The existing 243-test suite is green; engineering perimeter (pre-push gate, CI, lint, types, schema-parity script) is in place. The first launchable release is `v0.1.0` targeting end of Phase 3 (~12 weeks out).

Hard kill criterion: if Forge can't reach **≥30% on a 50-task SWE-bench Verified subset** using the open-weight stack by Phase 2 Week 8, the open-weight thesis fails and we pivot or shut down. See [docs/DECISIONS.md ADR-015](docs/DECISIONS.md#adr-015--week-8-swe-bench-verified-30-on-50-task-subset--hard-kill-criterion).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Every PR runs the local pre-push gate before pushing — CI is intentionally light.

## Code of Conduct

[Contributor Covenant v2.1](CODE_OF_CONDUCT.md).

## Security

For security issues, see [SECURITY.md](SECURITY.md) — do not open a public GitHub issue.

## Sustainability

Forge has no monetization gates. If you find it useful and want to help: ⭐ the repo, share it, file issues, send PRs. If you want to fund maintenance directly, GitHub Sponsors will be enabled at v0.1.0 launch.

## License

MIT — see [LICENSE](LICENSE). You can use Forge commercially, fork it, modify it, redistribute it. The only requirement is keeping the copyright notice.
