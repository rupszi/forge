# Changelog

All notable changes to Forge are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Code-review fixes (2026-05-01) — see `docs/EXECUTION_PLAN.md`

Sweep of issues surfaced by 3 rounds of critical code review (functionality / code quality / security). Baseline 588 tests → after this sweep **644 tests passing** (+56). Pre-push gate stays green.

#### Fixed
- **ADaPT recovery writeback** (Task 1.1, scheduler.py): when ADaPT decomposition flips a sprint from `failed` → `completed`, both the procedural store and episodic store now record it. Previously the writeback only ran on the original failure, so the procedural memory never learned that recovery succeeded for the task pattern. Added `sprint.recovered` event.
- **EpisodicStore agent_type via `routing.select_executor`** (Task 1.2, memory/episodic.py): the previous hardcoded `in ("opus", "sonnet")` check mislabeled haiku, every full-name Claude (`claude-sonnet-4-7`, …), every open-weight model (qwen, devstral, deepseek, gpt-oss), and every model routed via `OPENAI_BASE_URL`. Fixed by sharing the same dispatch logic the scheduler uses.
- **Database lifecycle** (Task 1.3, db.py): added `atexit` handler + `__del__` backstop so SIGKILL or unhandled-exception paths still flush the WAL. `close()` is now idempotent. Eliminates the "database is locked" race on restart after an unclean shutdown.
- **WebSocket DoS hardening** (Task 1.4, ws_server.py): per-client sliding-window rate limit (10 msg/sec), 1 MB per-message cap before `json.loads`, and `init` path validation (must be under home or cwd) prevent a misbehaving local client from OOMing the daemon.
- **Cross-family evaluator runtime assertion** (Task 1.9, evaluator.py): defense-in-depth assert against ADR-006 violation if a future refactor accidentally hardcodes the evaluator model.
- **Worktree creation race** (Task 2.1, worktree.py): `_active_worktrees` is now a `set` under an `asyncio.Lock`, eliminating the TOCTOU window where two concurrent `create()` calls for the same name double-registered.
- **Budget atomic across waves** (Task 2.2, budget.py + scheduler.py): new `BudgetController.reserve()` and `record_spend_async()` lock-protect the check-and-decrement so 100 concurrent $1 reservations against a $10 cap deliver exactly 10 successes (was: collective overshoot possible).
- **Subprocess kill on timeout** (Task 2.4, executors/claude_code.py): `proc.kill()` + `proc.wait()` on `asyncio.TimeoutError` so the claude subprocess doesn't linger as a zombie.

#### Added
- **9 new credential patterns** in `daemon/redact.py` (Task 1.5): Vercel, Cloudflare, npm, Hugging Face, SendGrid, Mailgun, Twilio, Discord bot, Telegram bot. All from gitleaks v8.20+ default rules.
- **8 new destructive-op rules** in `daemon/safety.py` (Task 1.8): `aws s3 rb/rm --force`, `gh repo delete`, `kubectl delete --all`, `terraform destroy`, `docker system prune -a`, `chmod -R 000`, `mkfs.*` (block), `dd of=/dev/<disk>` (block).
- **Graceful SIGTERM/SIGINT shutdown** (Task 1.7, cli.py + ws_server.py): `cmd_serve` now flips a `shutdown_event` that `start_server` awaits; existing connections close with code 1001 (going away), in-flight handlers drain, then `db.close()` flushes WAL.
- **WebSocket handler concurrency cap** (Task 2.3, ws_server.py): 10-handler semaphore prevents request fan-out from exhausting descriptors / DB connections.
- **`daemon/routing.py`** (Task 2.6): single source of truth for executor dispatch (`select_executor`), importable from both `agents/classifier` and `agents/generator` without forming a cycle. Both modules now consult the same function.
- **`daemon/events.py`** (Task 3.3): `EventType` enum registry — every trace event has a canonical entry. Catches typos at import time, makes the on-the-wire event-name contract explicit, and gives the UI / replay summarizer a single source of truth.
- **`critical: bool` field on `SprintContract`** (Task 3.2, models.py): structured replacement for the legacy `[critical]` description prefix; `recovery.is_critical` checks the field first and falls back to the prefix scan for backwards-compat.
- **Adversarial-input tests** (Task 4.3, tests/test_redact.py): 100k-char near-JWT input + repeated bearer fragments verify no regex catastrophic-backtracking (ReDoS) lurking in the catalog.
- **Quarterly-review checkbox** (Task 4.4, SECURITY.md): formal cadence for re-syncing the redaction catalog against gitleaks defaults and re-auditing the destructive-op classifier.
- **Captured-events test fixture** (Task 3.4, tests/test_recovery.py): replaces previous monkeypatched-to-no-op pattern. Tests now assert on emitted events instead of silently mocking them.
- **`tests/conftest.py`** (Task 2.5): consolidated `tmp_forge_dir` fixture; previously duplicated across `test_replay.py`, `test_integration_wiring.py`, `test_redact_integration.py`.

#### Changed
- **EpisodicStore type hint**: `eval_result: EvaluatorResult | None` (Task 4.1) (was: `EvaluatorResult = None`).
- **Phantom dep removed**: `forge[repomap]` extra no longer pulls `tree-sitter` / `tree-sitter-languages` (Task 1.10) — the current `daemon/scanner/repomap.py` is regex-only. Reserved for a future `forge[repomap-precise]` extra.

#### Deferred (documented in `docs/EXECUTION_PLAN.md`)
- **Task 1.6** (drop `_AUTH_BEARER_LOOSE`; remove env-line negative lookahead): reverted after empirical test failure — both halves are load-bearing for security-critical integration tests. Re-file once the env-line rule is redesigned with a two-pass scheme that detects already-redacted markers.
- **Task 3.1** (extract `HTTPExecutor` base for ollama + openai_compatible): 6-8h refactor saving ~60 LOC; deferred per the plan's own "Sprint 3+4 can land incrementally" note. Re-file when a third HTTP executor lands.

#### Test count
- Before review sweep: 588 passing, 1 skipped
- After Sprint 1: ~621 passing
- After Sprint 2: ~635 passing
- After Sprint 3: ~640 passing
- After Sprint 4: **644 passing**, 1 skipped (+56 net)

### Added — Outbound credential redaction (2026-05-01, ADR-017)
- **`daemon/redact.py`** — regex-based redaction utility with three public surfaces: `redact(text)` (replace credentials with `[REDACTED:<TYPE>]` markers), `contains_secret(text)` (fast yes/no for write-gate use), `redact_value(value)` (recursive into dicts/lists), `filtered_subprocess_env()` (allowlisted env for subprocess spawning), and `RedactionFilter` (a `logging.Filter` for log-config wiring).
- Pattern catalog covers: Anthropic (`sk-ant-…`), OpenAI (`sk-…`/`sk-proj-…`/`sk-svcacct-…`), GitHub (`ghp_`/`ghs_`/`gho_`/`github_pat_`), AWS access key IDs (AKIA/ASIA/AGPA/AROA/AIDA/AIPA/ANPA/ANVA/ABIA/ACCA), AWS secret keys (`aws_secret_access_key=…`), Slack (`xox[a-r]-…`), Stripe (`sk_live_…`/`sk_test_…`), Google (`AIza…`), JWT (3-segment base64url), `Authorization: Bearer …` headers (strict + loose for nested-JSON cases), `.env`-line patterns where LHS contains SECRET/TOKEN/PASSWORD/API_KEY/CREDENTIAL/PRIVATE_KEY, PEM private-key blocks, DB connection URLs (`postgres://user:password@…`).
- **Wired at five outbound boundaries**:
  - Trace JSONL writer (`replay.append_event`) — recursive scrub of every event's `data` payload before write
  - KB writes (`db.add_knowledge`) — **refuses** to persist content matching any credential pattern (returns `None`, logs warning)
  - Episodic store (`db.save_episode`) — redacts `error`/`resolution`/`result`/`evaluator_feedback`/`task_description` at write time
  - Subprocess env (`executors/claude_code.execute`) — `filtered_subprocess_env()` allowlist drops unrelated env vars (AWS, GH PAT for unrelated repos, custom CI tokens)
  - Daemon log via `RedactionFilter` (helper available; wired in by `daemon/log.py`)
- **52 new tests** in `tests/test_redact.py` (38 unit) + `tests/test_redact_integration.py` (14 end-to-end through every wired layer).
- **ADR-017** added to `docs/DECISIONS.md` with full rationale, alternatives, trade-offs.
- **SECURITY.md** updated with the redaction matrix + threat-model entries 14 + 15.

### Added — Scheduler integration + CLI completion (2026-05-01)
- **Scheduler wiring**: `daemon/scheduler.py` now emits trace events at every phase via `replay.append_event`, builds and injects the repomap into generator prompts (`scanner/repomap.build_repomap`), writes back to procedural memory after every evaluator verdict (online RouteLLM-style routing learning), invokes ADaPT recovery on `MAX_REVISIONS` exhaustion, and routes `[critical]` sprints through Self-Consistency.
- **`forge replay <session-id>` CLI subcommand** — reads a session's trace JSONL and pretty-prints (or `--raw` for JSONL passthrough). Lists sessions when invoked without args.
- **`forge mcp-serve` CLI subcommand** — spawns the FastMCP server over stdio, ready to register in any Claude Code / Cursor / Continue / Goose `.claude/settings.json`.
- **`daemon/log.py`** — concrete `setup_logging()` helper that applies the JSON formatter + `RedactionFilter` to both stderr and the rotating file handler.
- **sqlite-vec wiring** in `db.save_episode` (gated by `FORGE_VECTOR_EPISODES=1`) — embeds episode text via the Ollama embeddings endpoint and stores the vector for later cosine-similarity recall.

### Added — Phase 1 Day 1 (2026-04-30 → 2026-05-01)
- **`daemon/executors/openai_compatible.py`** — OpenAI-compatible HTTP executor for vLLM / SGLang / OpenRouter / Together / any endpoint speaking the OpenAI Chat Completions protocol. Heavy comments explaining tool-calling reliability strategy, prefix-cache prompt structuring, cancellation semantics, and the sentinel-prefixed tool-call serialization pattern.
- **Cross-family evaluator enforcement** in `daemon/agents/classifier.py` via new `pick_evaluator_model()` function. Implements ADR-006 — the evaluator must run on a model from a different family than the generator, to avoid the +25% same-family self-bias documented in MT-Bench.
- **Model family registry** in `daemon/config.py` (`MODEL_FAMILIES` dict + `model_family()` helper). Covers Anthropic / OpenAI / Qwen / Mistral / DeepSeek / Llama / Granite / Zhipu / MiniMax / Moonshot lineages with case-insensitive longest-prefix matching.
- **`docs/DECISIONS.md`** — locked ADR-style decisions doc with 16 ADRs covering license, architecture, model defaults, pre-push-heavy philosophy, schema-parity rule, three-agent invariants, local-first telemetry stance, packaging, lint/type stack, Python floor, framework-ban, KB design, sandboxing, surface, kill criterion, and sustainability model.
- **OSS launch hygiene**: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1 by reference), `SECURITY.md` with vuln-disclosure flow + threat model + hardened defaults.
- **README.md refresh** — leads with the free/MIT/local-first positioning and a head-to-head feature matrix vs Aider / OpenHands / Cursor / Claude Code / Composio AO / Devin.
- **62 new tests** across `tests/test_openai_compatible.py` (13 tests covering happy path, tool calls, HTTP errors, network errors, malformed responses, missing-base-url guard, request-shape verification) and `tests/test_cross_family_evaluator.py` (49 tests covering family registry parametrization, cross-family invariant per generator, determinism, candidate ordering, edge cases). All passing.
- **Phase 3 Week 12 launch-hygiene checklist** added to `BUILD_PLAN.md` (Sponsors, Discord, Discussions, domain, email aliases, issue/PR templates).

### Changed
- **Default model lineup updated** for the April-22/23 open-weight releases:
  - Cheap-tier generator: `qwen3-coder:30b` → `qwen3-coder-next` (Feb 2026, 3B-active / 80B MoE)
  - Medium-tier generator: NEW `qwen3.6:27b` (Apr 22, 2026)
  - Premium-tier generator: NEW `deepseek-v4-flash` (Apr 23, 2026; 13B active, MIT, ~79% SWE-bench Verified)
  - Planner: `gpt-oss:20b` retained
  - Backup mid-tier: `devstral-small-2507` retained
- **Classifier `ROUTING` table** updated to dispatch all default complexity tiers via the `ollama` executor on the new model lineup. Users with `OPENAI_BASE_URL` set automatically dispatch through the new `openai_compatible` executor.
- **Evaluator hardcoded `eval_model = "sonnet"`** at `daemon/agents/evaluator.py:120` will be removed in Phase 1 Week 1 follow-up — `pick_evaluator_model()` is the replacement.
- **Week-8 kill-criterion bar raised**: ≥25% → ≥30% SWE-bench Verified on the 50-task subset.
- Documented relaxation of the original "two pip deps" rule to ~6 hard deps + 2 dev/test + 1 extras, with rationale per dep in [BUILD_PLAN.md → Dependency tracker](docs/BUILD_PLAN.md#dependency-tracker).

### Notes
- Test suite: 305 passed in 1.05 s (was 244; +61 new tests).
- Lint: clean (`ruff check`).
- Format: clean (`ruff format --check`).
- Pre-push gate: passes end-to-end.

### Added — Engineering perimeter (initial)
- Comprehensive engineering standards: `docs/ENGINEERING_STANDARDS.md` aligned to a reference TS/RN monorepo's pre-push-heavy philosophy.
- 14-week build plan with weekly checkboxes, exit criteria, and a Week 8 kill-criterion checkpoint: `docs/BUILD_PLAN.md`.
- Competitive landscape and architecture report (~9.6 K words) plus seven raw research notes under `docs/research/` (six original + Apr-30 freshness check).
- **Head-to-head competitive comparison** at `docs/COMPETITIVE_COMPARISON.md` — Forge vs 18 competitors with side-by-side feature matrix, unique-cell analysis, per-product positioning notes, failure modes, and explicit decision rationale.
- **April-30 freshness check** at `docs/research/notes/05-competitive-freshness-2026-04-30.md` — last-60-day deltas with ~25 primary sources from Mar–Apr 2026.
- `pyproject.toml` (PEP 621) with hatchling build backend, ruff/pyright/pytest/coverage/bandit config, optional extras (`robust`, `batch`, `repomap`, `vector`, `mcp`).
- `.pre-commit-config.yaml` (fast hooks: gitleaks + std + Ruff) wired to also run `scripts/pre-push.sh` on push.
- `scripts/pre-push.sh` — heavy quality gate with conditional checks based on diff and `SKIP_*` / `RUN_*` env vars.
- `scripts/audit-docs.py` — frontmatter validator for `docs/active/` and `docs/reference/`.
- `.gitleaks.toml`, `.gitignore`, `.github/workflows/{ci,codeql}.yml`, `.github/dependabot.yml`.

### Changed
- Documented relaxation of the original "two pip deps" rule to ~6 hard deps + 2 dev/test + 1 extras, with rationale per dep in [BUILD_PLAN.md → Dependency tracker](docs/BUILD_PLAN.md#dependency-tracker).
- **Default model lineup updated** for the April-22/23 open-weight releases:
  - Cheap-tier generator: `qwen3-coder:30b` → `qwen3-coder-next` (Feb 2026, 3B-active / 80B MoE)
  - Medium-tier generator: NEW `qwen3.6:27b` (Apr 22, 2026)
  - Premium-tier generator: NEW `deepseek-v4-flash` (Apr 23, 2026; 13B active, MIT, ~79% SWE-bench Verified)
  - Planner: `gpt-oss:20b` retained
- **Week-8 kill-criterion bar raised**: ≥25% → ≥30% SWE-bench Verified on the 50-task subset. Justification: the open-weight ceiling moved from ~72% (Devstral-Medium) to ~80%+ (MiniMax M2.5, DeepSeek V4) in 60 days; Forge must clear a meaningfully higher bar to justify orchestration overhead vs OpenHands SDK V1's published 72%.

### Notes
- Existing test suite (243 tests, 0.87 s) remains green throughout.
- No code changes to `daemon/` in this slice — all engineering perimeter and competitive analysis only.
- **Composio Agent Orchestrator** (Feb 23, 2026; 6.7k stars) is now the closest direct analogue (replacing OpenClaw plugin which had no datable activity in the freshness window). Differentiation reframed accordingly in COMPETITIVE_COMPARISON.md.

## [0.0.1] – 2026-04-30 — initial baseline

### Added
- Forge daemon (~3 K LOC across 17 modules): planner / generator / evaluator / scheduler / memory / executors / scanner.
- Forge UI (Next.js dashboard, ~1 K LOC across 12 components).
- Test suite (1.9 K LOC, 243 tests).
- `CLAUDE.md` specification (~47 KB).
- Initial documentation under `docs/` (`architecture.md`, `memory-system.md`, `harness-design.md`, `security.md`, `configuration.md`).
