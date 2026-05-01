# Forge Build Plan & Tracker

A 14-week, week-by-week, checkbox-driven tracker for building Forge from current `develop` baseline → publicly launched `v0.1.0` running fully on open-weight LLMs on a M4 Pro 48 GB.

> **Hardware target**: Apple Silicon M4 Pro / 48 GB unified memory / 512 GB SSD
> **Architecture**: Option A (spec-hardened for open weights) — see [competitive-landscape-and-architecture.md](research/competitive-landscape-and-architecture.md) §3.1
> **Solo developer**, ~25–30 focused hours/week
> **Effort**: ~370 hours total
> **Cash spend**: ~$100–180 (LLM API credits for sanity checks + benchmark runs)

## Freshness-check deltas (2026-04-30)

The April-30 freshness check ([research/notes/05-competitive-freshness-2026-04-30.md](research/notes/05-competitive-freshness-2026-04-30.md)) and the head-to-head comparison ([COMPETITIVE_COMPARISON.md](COMPETITIVE_COMPARISON.md)) surfaced three modifications applied to this plan:

1. **Model defaults bumped** to reflect April-22/23 open-weight releases (see "Phase 0 → Pull baseline models" below):
   - Cheap-tier generator: ~~Qwen3-Coder-30B~~ → **`qwen3-coder-next`** (Feb 2026, 3B-active / 80B MoE)
   - Medium-tier generator: NEW → **`qwen3.6:27b`** (Apr 22, 2026; advertised as flagship-level agentic coding)
   - Premium-tier generator: ~~Devstral-Medium API~~ → **`deepseek-v4-flash`** (Apr 23, 2026; 13B active, MIT, ~79% SWE-bench Verified)
   - Planner: `gpt-oss:20b` retained
   - Evaluator: cross-family selection auto-enforced

2. **Composio-AO overlap trim**: Composio Agent Orchestrator (Feb 23, 2026, 6.7k stars) shipped basic worktree + spawn + PR + auto-CI-fix as table-stakes. Trim Phase 1 Week 1 work that overlaps and **reinvest those cycles in the KB / retriever / learner** where Forge is still uniquely positioned. Specifically: don't build a UX for "spawn worktree + show diff" — buy that pattern via inspiration. Spend the saved cycles on procedural memory feedback + KB confidence/decay tuning + evaluator-with-contracts hardening.

3. **Week-8 kill criterion bumped** from ≥25% to **≥30%** SWE-bench Verified on the 50-task subset. Justification: the open-weight ceiling moved from ~72% (Devstral-Medium) to ~80%+ (MiniMax M2.5, DeepSeek V4) in 60 days. Forge's harness should clear a meaningfully higher bar to justify the orchestration cost vs OpenHands SDK V1's 72% with Sonnet 4.5 + extended thinking.

4. **NEW Phase 3 stretch goal**: import from Anthropic Managed Agents memory (`/mnt/memory/`) so users on Anthropic enterprise get free knowledge-base seeding. Closes the loop with Anthropic's April 23 release.

5. **Time pressure call-out**: YC W26 had 41.5% of batch in agent infrastructure (demoed Mar 24, 2026). Several may pivot toward Forge's exact niche by H2 2026. **Consider opening the public WIP repo + Discord at Phase 1 Week 4** (instead of Week 12) to gather feedback early.

---

## How to use this tracker

- Tick `[x]` boxes as you complete tasks. The tracker is the single source of truth — keep it updated.
- **Exit criteria** at the end of each week must pass before moving on. If a week's exit criterion fails, do not advance — pause and triage.
- **Kill criterion at end of Week 8** is hard: SWE-bench Verified < 25% on the 50-task subset → pivot or shut down. Do not sink another month into a dead path.
- Effort estimates are budgets, not commitments. Track actual hours per task in a private notebook for calibration.
- Engineering standards (linting, types, CI, etc.) are documented in [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md). Adhere to them throughout.

---

## Phase 0 — Pre-flight (Week 0, ~10 hours)

### Hardware / OS prep

- [ ] Install **Python 3.12** via Homebrew: `brew install python@3.12` (current system is 3.9, which is EOL). Add to PATH or use via `uv` (next bullet).
- [ ] Install **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh` (Forge will adopt uv as its workflow tool — see [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md) §1).
- [ ] Install **Ollama**: `brew install ollama && ollama serve` (run in background or via `brew services start ollama`).
- [ ] Pull baseline models (~80 GB SSD; updated for Apr-30 freshness check):
  - [ ] `ollama pull gpt-oss:20b` (~14 GB) — planner
  - [ ] `ollama pull qwen3-coder-next` (~50 GB MoE; 3B active) — **cheap-tier generator** (Feb 2026)
  - [ ] `ollama pull qwen3.6:27b` (~16 GB at Q4) — **medium-tier generator** (Apr 22, 2026)
  - [ ] `ollama pull deepseek-v4-flash` (~13 GB at Q4) — **premium-tier generator** (Apr 23, 2026; 13B active, MIT)
  - [ ] `ollama pull devstral-small-2507` (~15 GB) — secondary medium-tier (Apr 2025; OpenHands-validated 53.6% SWE-bench)
  - [ ] `ollama pull nomic-embed-text` (~270 MB) — for episodic vector recall (Phase 1, Week 4)
  - [ ] **Optional**: `ollama pull deepseek-r1-distill-qwen-32b` (~20 GB) — reasoner (no tools)
  - [ ] **Optional**: `ollama pull minimax-m2.5` if available — current open-weight SWE-bench leader (80.2%)
- [ ] Install **Docker Desktop** from docker.com; allocate 8 GB RAM, 60 GB disk in Settings.
- [ ] Install **Node 20 + pnpm**: `brew install node pnpm` (for the Next.js UI).
- [ ] Set Ollama env vars in `~/.zshrc`:
  ```
  export OLLAMA_MAX_LOADED_MODELS=1
  export OLLAMA_KEEP_ALIVE=5m
  ```
- [ ] Acquire API keys (cross-checks + premium-tier benchmark runs):
  - [ ] Anthropic console — load $20 credit
  - [ ] OpenRouter or Together AI — for Qwen3-Coder-480B / gpt-oss-120b benchmark runs

### Repo prep

- [ ] Confirm `develop` branch checked out, `pwd` is `/Users/palmegyes/Development/forge`.
- [ ] Run existing test suite: `./setup.sh && PYTHONPATH=. .venv/bin/pytest tests/` — must show 243/243 passing.
- [ ] First clean commit on `develop` so you have a baseline to diff against.
- [ ] Create GitHub project board with the 14-week milestones (one column per phase; one card per week).
- [ ] Create empty issues for each "Exit criterion" — close them as you complete weeks.

### Pre-flight smoke test

- [ ] `ollama run devstral-small-2507 "Write a Python function that reverses a list."` returns a response in <30 s.
- [ ] `pytest tests/` passes.
- [ ] Activity Monitor shows ~15 GB RAM used while a model is loaded; 5 min idle should unload it.

**Exit criterion (Week 0)**: All checkboxes above ticked. You can pull a model, hit it, get a response, and the existing Forge tests still pass.

---

## Phase 1 — Open-weight hardening (Weeks 1–4, ~100 hours)

By end of Week 4: Forge runs end-to-end on Ollama with no `ANTHROPIC_API_KEY`.

### Week 1 — Inference adapter + cross-family evaluator (~25 h)

**Goal**: A new `openai_compatible` executor and a generic `ollama` executor that both pass tool spec; classifier auto-enforces cross-family evaluator selection.

- [ ] **Mon–Tue (8 h)**: Build `daemon/executors/openai_compatible.py` — speaks OpenAI tool-calling API to any URL (vLLM, OpenRouter, Together). ~150 LOC.
- [ ] **Tue–Wed (5 h)**: Update `daemon/executors/ollama.py` — pass tool spec via `tools` array, parse `tool_calls` response, add `keep_alive: "30m"` per-call.
- [ ] **Wed–Thu (6 h)**: Auto-enforce `evaluator_family != generator_family` in `daemon/agents/classifier.py`. Maintain a `MODEL_FAMILY` registry (`qwen3*` → "qwen", `devstral*` → "mistral", `gpt-oss*` → "openai", `claude*` → "anthropic", `deepseek*` → "deepseek").
- [ ] **Thu–Fri (6 h)**: Tests for both new executors using `respx` to mock HTTP. Test classifier cross-family selection against all permutations.
- [ ] Replace hardcoded `eval_model = "sonnet"` at `daemon/agents/evaluator.py:120` with cross-family selector.

**Exit criterion (Week 1)**: `forge run` can execute a sprint via Ollama (cheap) or any OpenAI-compatible endpoint (premium fallback). All existing tests still pass plus 10+ new tests for the new executors.

### Week 2 — Constrained decoding + open-weight evaluator parser (~25 h)

**Goal**: Planner emits valid sprint-contract JSON ≥95% of the time on Qwen3 and Devstral; evaluator parses verdicts ≥90%.

- [ ] **Mon–Tue (8 h)**: Wire JSON-grammar enforcement into planner. For Ollama path, emit GBNF grammar inline (llama.cpp supports it). For OpenAI-compatible path, pass `response_format={"type":"json_schema","schema":...}`. Schema in new file `daemon/schemas/sprint_contract.json`.
- [ ] **Tue–Wed (5 h)**: Add **BAML** as opt-in extra (`pip install forge[robust]`). Use BAML's schema-aligned parsing as fallback when JSON parse fails. New file `daemon/parsing.py`.
- [ ] **Wed–Thu (5 h)**: Harden `daemon/agents/evaluator.py:44–82` — add regex variants for `✓/✗`, `[YES]/[NO]`, `**PASS**`, paragraph-style "criterion is satisfied".
- [ ] **Thu–Fri (7 h)**: Generate 50 real Qwen3 + Devstral evaluator outputs against fixtures; build a regression test suite from them. New file `tests/test_evaluator_open_weight.py` + `tests/fixtures/evaluator_outputs/`.

**Exit criterion (Week 2)**: Planner JSON valid ≥95% of the time on a 50-prompt benchmark; evaluator parses verdicts ≥90%.

### Week 3 — Repomap lift + context-window budgeting (~24 h)

**Goal**: Generators receive a deterministic, PageRank-ranked view of the repo + relevant KB items + recent failures, all within model window.

- [ ] **Mon–Tue (8 h)**: Fork `aider/repomap.py` into `daemon/scanner/repomap.py` under MIT attribution. Add `tree-sitter`, `tree-sitter-languages`, and `networkx` to `pyproject.toml` dependencies. Document the deliberate two-deps-rule violation in `CLAUDE.md`.
- [ ] **Tue–Wed (4 h)**: Wire repomap into `daemon/agents/generator.py` — inject 1500-token map alongside the 500-token memory context.
- [ ] **Wed–Thu (5 h)**: Add per-model context limits to `daemon/config.py`:
  ```python
  MODEL_CONTEXT_LIMITS = {
      "gpt-oss:20b": 32000,
      "qwen3-coder:30b": 256000,
      "devstral-small-2507": 128000,
      "claude-sonnet-*": 200000,
  }
  ```
  In generator prompt build, truncate memory + repomap if total > 80% of model window.
- [ ] **Thu–Fri (7 h)**: Tests — repomap on a real fixture project (clone a small Next.js repo); context-budget tests with synthetic large prompts. New files `tests/test_repomap.py`, `tests/test_context_budget.py`.

**Exit criterion (Week 3)**: A generator running against a fixture Next.js repo receives a non-empty repomap injected into its prompt, and the prompt never exceeds 80% of the target model's context window.

### Week 4 — Episodic vector recall + reviewer synthesis + cleanup (~25 h)

**Goal**: Forge KB has vector recall on the episodic store; reviewer panel synthesizes into a unified verdict; `forge doctor` validates the open-weight stack.

- [ ] **Mon (4 h)**: `pip install sqlite-vec`. Add gated extension to `daemon/db.py` — only loaded if `FORGE_VECTOR_EPISODES=1`. Index `task_description + error` columns.
- [ ] **Mon–Tue (5 h)**: Backfill embeddings via `nomic-embed-text` through Ollama. New file `daemon/memory/embeddings.py`.
- [ ] **Tue–Wed (6 h)**: Finish reviewer synthesis stub at `daemon/agents/reviewer.py:148`. Implement 2/5 quorum for `critical`; aggregated action list.
- [ ] **Wed–Thu (4 h)**: Extend `forge doctor` — validate Ollama running, recommended models pulled, MCP servers reachable, sqlite-vec loadable, Python ≥3.10, git ≥2.30.
- [ ] **Thu–Fri (6 h)**: End-to-end smoke test on a fresh fixture: `forge init` → `forge plan "Add a /health endpoint"` → `forge run` → verify worktree created, generator ran, evaluator approved, merge gate appeared, all without an `ANTHROPIC_API_KEY`.

**Exit criterion (Phase 1)**: `forge serve` with no `ANTHROPIC_API_KEY` set; planner uses `gpt-oss:20b`, generator uses `devstral-small-2507`, evaluator uses `qwen3-coder:30b` (cross-family enforced), and a toy task completes end-to-end in a worktree with a clean diff.

🎉 **Take the weekend off after Week 4. Phase 1 is the hard part.**

---

## Phase 2 — Reference tasks + benchmark (Weeks 5–8, ~100 hours)

By end of Week 8 you know whether the open-weight thesis is real.

### Week 5 — Three reference tasks (~25 h)

Build three real fixture projects under `tests/fixtures/` and prove Forge handles them end-to-end. For each: log timing, token counts, evaluator pass rate, number of revisions, total cost. Document failures in `docs/known-issues.md`.

- [ ] **Task 1 (Mon–Tue, 10 h)**: "Add an auth endpoint with tests" on a Next.js + Supabase fixture. Path: `tests/fixtures/nextjs-auth/`. Forge plans 3 sprints, runs them, evaluator approves, merges.
- [ ] **Task 2 (Wed, 5 h)**: "Fix this failing test" — a regression scenario, single sprint. Path: `tests/fixtures/regression/`.
- [ ] **Task 3 (Thu–Fri, 10 h)**: "Refactor module X" — non-trivial multi-file refactor, 3+ sprints with dependencies. Path: `tests/fixtures/refactor/`.

**Exit criterion (Week 5)**: All three fixtures pass at least once with the open-weight default lineup. Document any tasks that required Anthropic API fallback.

### Week 6 — MCP server export + procedural feedback (~25 h)

**Goal**: Forge KB queryable as MCP server from Claude Desktop; procedural memory updates automatically on every evaluator verdict.

- [ ] **Mon–Tue (8 h)**: Implement `daemon/mcp_server.py` using `modelcontextprotocol/python-sdk` (FastMCP). Expose `forge_kb_search`, `forge_kb_add`, `forge_episode_search`, `forge_research_lookup` tools + `forge://stats`, `forge://session/{id}/summary` resources + `review_with_forge_kb` prompt. ~80 LOC. Reference: [04-anthropic-best-practices.md §B](research/notes/04-anthropic-best-practices.md).
- [ ] **Wed (3 h)**: Test in Claude Desktop. Configure Forge MCP server in `~/Library/Application Support/Claude/claude_desktop_config.json`. Query "what gotchas does Forge know about Supabase?" and verify it returns real KB items.
- [ ] **Wed–Thu (6 h)**: Procedural memory writeback loop. Every evaluator verdict updates `procedures` table automatically (`task_pattern → recommended_model + success_rate + avg_duration`). Add metrics endpoint for routing accuracy over time.
- [ ] **Thu–Fri (8 h)**: UI polish round 1 — fix any WebSocket race conditions surfaced during reference-task runs. Validate live updates for sprint state transitions.

**Exit criterion (Week 6)**: Claude Desktop can `forge_kb_search` and get real results; running 5 sprints in a row demonstrably improves the procedural memory routing accuracy.

### Week 7 — SWE-bench harness setup (~25 h)

- [ ] **Mon–Tue (8 h)**: Fork SWE-bench Docker harness from `SWE-bench/SWE-bench`. Run their Docker image to confirm test infra works locally. Beware: Docker disk usage will climb fast on M4 Pro 512 GB — monitor with `docker system df`.
- [ ] **Wed (2 h)**: Pick the 50-task subset. Recommend the **django subset** (well-isolated, fast tests, representative). Document selection criteria in `eval/swebench/README.md`.
- [ ] **Wed–Thu (10 h)**: Build adapter — take a SWE-bench task → run Forge against the cloned repo → capture the resulting diff → submit to SWE-bench scaffold for verification. New file `eval/swebench/adapter.py` (~300 LOC).
- [ ] **Fri (5 h)**: First baseline run. Expect 10–20% your first attempt. Log everything to `eval/swebench/runs/<timestamp>/`.

**Exit criterion (Week 7)**: First baseline number recorded. You know your starting point.

### Week 8 — Iterate to ≥30% (~30 h)

Pure tuning week. Each weekday morning: pick the worst-performing failure mode from yesterday's run, fix it, re-run.

Levers in priority order (estimated gain per lever):

- [ ] Tighten evaluator skepticism prompt — "fail on doubt" + few-shot calibration block (+2–4%). See [04-anthropic-best-practices.md §A](research/notes/04-anthropic-best-practices.md) `evaluator.py` recommendations.
- [ ] Increase repomap budget from 1500 → 2500 tokens (+2–3%).
- [ ] Add ADaPT-style recovery: when sprint fails after `MAX_REVISIONS=2`, recursively decompose rather than escalating (+3–6%).
- [ ] Switch primary generator to Qwen3-Coder-30B for Python-heavy tasks vs Devstral for Java/Rust (+1–4%).
- [ ] For the hardest 10 tasks, escalate to remote Qwen3-Coder-480B via OpenRouter (counts as fully open weights since model is open) (+5–10%).
- [ ] Better sprint contract templates with explicit test-runner instructions in done_criteria (+2–4%).
- [ ] Replace `memory += ...` revision append in `scheduler.py:89,112` with structured context reset (+1–3%).

**Exit criterion (Phase 2 — KILL CHECKPOINT, updated post-freshness-check)**:

| Week-8 result | Action |
|---|---|
| ≥40% | ✅ Strong. Ship full launch in Phase 3 with a real claim ("X% SWE-bench Verified, fully local, Apache 2.0"). |
| 30–39% | ✅ You have a product. Ship full launch in Phase 3. |
| **<30%** | 🛑 **Open-weight thesis fails for self-host.** OpenHands SDK V1 hits 72% with Sonnet 4.5 + extended thinking; Forge's multi-agent overhead must demonstrably pay something to justify the engineering cost. Pivot: (1) make Anthropic API the default and keep open-weight as opt-in; (2) reposition as "the open-weight harness for SOTA open models" and re-run with MiniMax M2.5 / DeepSeek V4 if available; (3) shut down. Do not sink another month into a dead path. |

**Why the bar moved from 25% → 30%**: the open-weight SWE-bench Verified ceiling moved from ~72% (Devstral-Medium, prior research's number) to ~80%+ (MiniMax M2.5; DeepSeek V4 ~83.7%) in 60 days. Forge's harness must clear a meaningfully higher bar to justify the orchestration cost vs OpenHands SDK V1's published 72%.

---

## Phase 3 — Polish + launch (Weeks 9–12, ~100 hours)

### Week 9 — Sandboxing + recovery modes (~25 h)

- [ ] **Mon–Tue (8 h)**: Add `--sandbox=docker` flag — thin wrapper running generator inside `forge-runtime:latest` image with worktree mounted. Default image: `python:3.12-slim` + `node:20` + `git`.
- [ ] **Wed (2 h)**: Skip `--sandbox=bwrap` (Linux-only) and `sandbox-exec` (deprecated by Apple on macOS 15.4). Document why in `docs/security.md`.
- [ ] **Wed–Thu (5 h)**: Implement ADaPT recovery (if not already done in Week 8): after `MAX_REVISIONS=2`, recursively decompose into smaller sprints rather than escalating to user.
- [ ] **Thu–Fri (6 h)**: Implement Self-Consistency-on-`critical` (sequential N=3 since M4 Pro can't run 3 in parallel; pick the best-scoring evaluator verdict). Mark via `critical: true` in sprint contract.

**Exit criterion (Week 9)**: Docker tier works; ADaPT decomposition lands; `critical` sprints get N=3 attempts.

### Week 10 — Docs site (~25 h)

- [ ] **Mon (5 h)**: Set up MkDocs Material under `docs-site/` (or VitePress if you prefer). Pull existing `docs/*.md` as initial content. Configure `mkdocstrings-python` for API reference.
- [ ] **Tue–Wed (8 h)**: Write the **"Forge in 5 minutes"** quickstart — walkthrough on M4 Pro / 4090 / Linux server.
- [ ] **Wed–Thu (6 h)**: Architecture deep-dive (lift from `docs/research/competitive-landscape-and-architecture.md`).
- [ ] **Thu–Fri (6 h)**: Model-lineup recommendations + hardware tiers; "Forge on Apple Silicon" guide; "Forge on a 4090" guide; "Forge on a server" guide.

**Exit criterion (Week 10)**: Docs site live (locally at `mkdocs serve`); a fresh user can read the quickstart and get Forge running on their machine.

### Week 11 — Hardening + observability (~25 h)

- [ ] **Mon–Tue (8 h)**: Trace-replay — every WebSocket event written to `~/.forge/sessions/<id>/trace.jsonl`; CLI `forge replay <session-id>` re-renders to UI for debugging. The OpenHands pattern.
- [ ] **Wed (4 h)**: Per-tool-call approval allow/deny list in config (block `rm -rf`, `git push --force`, schema migrations on prod, etc. even in full-auto). New file `daemon/safety.py`.
- [ ] **Wed–Thu (5 h)**: Cost meter accuracy pass — real token counts via Ollama's `prompt_eval_count` / `eval_count` (not the naive `len/4`).
- [ ] **Thu–Fri (8 h)**: Performance pass — profile a long session with `py-spy` or `austin`; fix any obvious N+1s in scheduler / WebSocket dispatch.

**Exit criterion (Week 11)**: Trace replay works; cost meter accurate; one-hour session profile shows no obvious bottlenecks.

### Week 12 — Launch (~28 h)

#### Launch hygiene (~3 h, do these before the launch post)

- [x] `LICENSE` (MIT, already present)
- [x] `CONTRIBUTING.md` — quality bar, ADR process, schema-parity rule
- [x] `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1 by reference
- [x] `SECURITY.md` — vuln-disclosure flow, threat model, hardened defaults
- [x] `docs/DECISIONS.md` — locked ADRs
- [x] `README.md` refresh with current state, free/MIT positioning, hardware tiers
- [ ] GitHub Sponsors profile — enable at https://github.com/sponsors
- [ ] Discord server — create + post invite link in README + post pinned welcome
- [ ] GitHub Discussions — enable; seed with `architecture`, `q-and-a`, `show-and-tell` categories
- [ ] `forge.dev` (or alt) domain — purchase + 301-redirect to GitHub for now
- [ ] Email aliases: `conduct@forge.dev`, `security@forge.dev` — set up forwarding to maintainer
- [ ] Issue templates: `bug_report.yml`, `feature_request.yml`, `architecture_proposal.yml` under `.github/ISSUE_TEMPLATE/`
- [ ] PR template: `.github/pull_request_template.md` matching the Summary + Test plan format from CONTRIBUTING.md

#### Launch sequence (~25 h)

- [ ] **Mon (4 h)**: Write the launch post — Show HN style: "Forge: Self-hosted multi-agent coding orchestrator on open weights." Lead with: "X% SWE-bench, no API key, Apache 2.0, runs on your laptop. Free forever."
- [ ] **Mon (2 h)**: Cut `v0.1.0` release on GitHub via signed git tag. Push to PyPI via OIDC trusted publishing (no API tokens). Sigstore signing automatic.
- [ ] **Tue (4 h)**: Record a 3-minute YouTube demo: install on M4 Pro, run a 3-sprint task, show evaluator catching a real bug, merge to main.
- [ ] **Wed (6 h)**: **Launch**: HN Show post 9 am Pacific Tuesday or Wednesday (best slots). Twitter thread. Discord opened. r/LocalLLaMA + Hugging Face Discord cross-post.
- [ ] **Thu–Fri (12 h)**: Triage incoming issues; respond fast; first patch release within 48 h if needed.

**Exit criterion (Phase 3)**: Public release that a developer can `git clone && ./setup.sh && forge serve` and have a working open-weight coding agent within 10 minutes.

---

## Phase 4 — Post-launch buffer (Weeks 13–14)

Reserve two weeks of pure reactive work — bug fixes, install issues, port to Linux/Windows users who try it, model bumps if Qwen4 or Devstral 3 drops.

- [ ] **Week 13**: First patch release `v0.1.1` based on launch feedback. Triage GitHub issues. Respond to every Discord thread within 24 h.
- [ ] **Week 14**: Plan `v0.2.0` roadmap publicly. Top candidates: ACP sidecar (Zed integration), larger SWE-bench (200 tasks), Linux/Windows hardening, Devstral fine-tune on Forge harness traces.

---

## Stretch goals (not on the critical path)

- ACP sidecar (Week 13–14, if launch goes well).
- Devstral-Small fine-tune on Forge-harness evaluator-format traces (Weeks 14–16, only if base evaluator parsing is the dominant failure mode at Week 12).
- Claude API batch executor wired into the post-session learner (Weeks 12–13, not blocking; saves 50% on cost-insensitive paths).
- `.claude/agents/forge-evaluator.md`, `.claude/agents/forge-reviewer.md`, `.claude/agents/forge-research.md` shipped under `.claude-templates/agents/` so `forge init` can copy them into user projects on confirmation. See [04-anthropic-best-practices.md §C](research/notes/04-anthropic-best-practices.md).

---

## Cost tracker

| Item | Estimated | Actual |
|---|---|---|
| Anthropic API credits | $20 | _(fill in)_ |
| OpenRouter / Together AI credits (premium-tier benchmark runs) | $50–80 | _(fill in)_ |
| Domain (forge.dev or similar) | $15/yr | _(fill in)_ |
| Mintlify/MkDocs hosting | $0–60 | _(fill in)_ |
| **Total** | **$100–180** | _(fill in)_ |

---

## Dependency tracker

Started with `httpx + websockets`. By end of build:

| Package | Why | License | Phase added |
|---|---|---|---|
| `httpx` | Original — HTTP client | BSD | baseline |
| `websockets` | Original — WS server | BSD | baseline |
| `tree-sitter` + `tree-sitter-languages` | Repomap | MIT | Week 3 |
| `networkx` | PageRank in repomap | BSD | Week 3 |
| `sqlite-vec` (gated) | Episodic vector recall | Apache/MIT | Week 4 |
| `mcp` (FastMCP python-sdk) | KB-as-MCP server | MIT | Week 6 |
| `respx` (test only) | Mock HTTP in tests | BSD | Week 1 |
| `baml-py` (extras only) | Tolerant JSON parsing | Apache 2.0 | Week 2 |
| `pytest`, `pytest-asyncio`, `pytest-cov` (dev) | Tests | MIT | Phase 0 |
| `ruff`, `pyright`, `pre-commit` (dev) | Lint, types, hooks | MIT/MIT/MIT | Phase 0 |

→ Going from **2 → 6 hard deps + 2 dev/test deps + 1 extras dep**. Document the deliberate post-research deviation from the original two-deps rule in `CLAUDE.md`.

---

## Risks specific to this plan

| Risk | Probability | Mitigation |
|---|---|---|
| Week-8 SWE-bench < 25% | **30%** | Kill criterion fires; pivot or shut down |
| Ollama tool-call regressions on a model upgrade mid-build | **40%** | Pin model versions in `daemon/config.py`; test before `ollama pull` |
| MLX overhead vs llama.cpp on Apple Silicon underdelivers | **20%** | Default to Ollama (llama.cpp under the hood); MLX as opt-in only |
| Solo burnout | **50%** | Hard cap 30 h/week; take weekends; the plan has buffer |
| Repomap regressions on monorepos > 50 K files | **40%** | Default `--map-tokens=1500`; full-monorepo support is a v0.2 problem |
| HN launch flops | **35%** | Pre-warm: r/LocalLLaMA + HF Discord 1 week before; line up 3–5 design partners |

---

## Success vs failure scenarios at Week 14

### Success looks like
- Forge `v0.1.0` shipped on GitHub, MIT-licensed
- ≥35% on 50-task SWE-bench Verified subset, fully open-weight
- 100+ stars, 5+ external contributors, Discord with 50+ active users
- 1–2 design partners using it weekly on real projects
- KB-as-MCP working in Claude Desktop and Cursor
- Clear v0.2 roadmap (ACP sidecar, larger SWE-bench, Linux/Windows hardening)

### Failure looks like (and is OK)
- Week-8 kill criterion fires at 18% SWE-bench
- You learn the hard limits of open-weight tool-calling firsthand
- You write a postmortem blog post
- The research report and codebase remain valuable artifacts
- ~$200 spent, 10 weeks invested, real lessons learned, no shame

---

## Weekly cadence summary

| Week | Focus | Hours | Exit criterion |
|---|---|---|---|
| 0 | Pre-flight | 10 | Models pulled, tests pass, Docker working |
| 1 | Inference adapter + cross-family eval | 25 | `forge run` works on Ollama with no Anthropic key |
| 2 | Constrained decoding + open-weight evaluator | 25 | Planner JSON valid ≥95%, evaluator parses ≥90% |
| 3 | Repomap + context budget | 24 | Generator gets PageRank repo map within model window |
| 4 | sqlite-vec + reviewer synthesis + doctor | 25 | End-to-end toy task completes fully on Ollama |
| 5 | Three reference tasks | 25 | All three fixtures pass at least once |
| 6 | MCP export + procedural feedback | 25 | KB queryable from Claude Desktop |
| 7 | SWE-bench harness | 25 | First baseline number recorded |
| 8 | **Iterate to ≥30%** | 30 | **KILL CRITERION CHECKPOINT** |
| 9 | Sandbox + recovery modes | 25 | Docker tier works; ADaPT lands |
| 10 | Docs site | 25 | Quickstart + architecture deep-dive published |
| 11 | Observability + hardening | 25 | Trace replay works; cost meter accurate |
| 12 | Launch week | 28 | HN post live; v0.1.0 tagged |
| 13–14 | Post-launch reactive | 30 | First patch release; design-partner feedback loop |
| **Total** | | **~370 h** | |

---

*Tracker last updated: 2026-04-30. Update this file as you complete tasks. Commit with message `track: week N progress`.*
