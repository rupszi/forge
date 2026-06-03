---
status: live
owner: pal.megyes
last_reviewed: 2026-06-04
---

# Forge Studio — Live Build Tracker

> **Single source of truth for build status.** Spec is in [FORGE_STUDIO_BUILD.md](FORGE_STUDIO_BUILD.md); engineering bar in [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md). This file is updated **every** time a task changes state. If it's not in here, it's not tracked.

**Goal:** local-first, free-by-default desktop app (Tauri) that opens a project, does coding + documents fully locally, with compounding memory. Images = Phase 2, Video = Phase 3.

---

## Status legend

| Mark | Meaning |
|---|---|
| ⬜ | Not started |
| 🟡 | In progress |
| 🔵 | In review / PR open |
| ✅ | Done — success gate met with evidence |
| ⛔ | Blocked (note the blocker) |
| ⏭️ | Deferred to a later phase |

**Update protocol:** when you start a task set it 🟡; when the PR is open set it 🔵; mark ✅ **only** when its success gate passes with linked evidence (test name, trace excerpt, or screenshot). Bump `last_reviewed` on every edit. Never mark a milestone ✅ until all its tasks **and** its exit gate are ✅.

**Post-M4 usability pass (2026-06-02):** `forge serve` now launches the daemon **and** the dashboard in one command (`--no-ui` for headless); default model lineup repointed to real pullable Ollama tags (qwen2.5 / llama3.1 / nomic-embed-text) so `forge models pull` + `forge run` work out of the box; **[docs/USER_GUIDE.md](USER_GUIDE.md)** written (install → models → start → connect models → orchestrate agents → documents) and README refreshed. Full suite 1044 passed.

**Audit remediation (2026-06-04):** the 2026-06-03 four-role audit's two High findings (evaluator-on-cloud, symlink escape) plus **all** remaining open findings F3–F15 are now closed, each with a regression test in `tests/test_audit_2026_06_04.py`. Highlights: scratchpad scoped per (project, session); `FORGE_REDACT_PROMPTS` implemented; injected context fenced as untrusted data; MLX weight cache; `num_ctx` snapshot per sprint; `scripts/check-schema-parity.py` built (caught a real `SprintContract.critical` TS drift); 4 weak tests rewritten; `pytest-randomly` + autouse reset fixtures added; `ENGINEERING_STANDARDS.md` reconciled (`src/forge/`→`daemon/`); `docs/WEBSOCKET_PROTOCOL.md` added. Full suite **1187 passed, 1 skipped**, stable across 3 randomized seeds. Fresh report: [docs/audits/2026-06-04-forge-studio/](audits/2026-06-04-forge-studio/REPORT.md). The SWE-bench kill gate remains **unrun** (needs models/GPU).

---

## Dashboard

| Phase | Milestone | Status | Exit gate |
|---|---|---|---|
| 0 | M0 — Foundation & guardrails harness | ✅ | Offline egress test + config-budget tests pass (38 tests) |
| 1 | M1 — Executor pivot (cloud → local default) | ✅ | Cloud gated behind opt-in; Ollama path egress-proven local; 953 tests green |
| 1 | M2 — Model Pool Manager | ✅ | Forced squeeze evicts LRU, pins survive, unfittable fails fast, large serialized |
| 1 | M3 — Memory upgrade (hybrid recall + reinforcement) | ✅ | Warm KB skips a revision + reinforces confidence; injection guard + research redaction live |
| 1 | M4 — CLI completion + audit fixes | ✅ | plan/run/add/merge/review registered + wired; cross-family invariant + path-guard fixes tested |
| 1 | M5 — UI completion (5 stub panels + onboarding) | 🟡 | Locality + pool meters wired + `pnpm build` clean; 5 legacy panels + onboarding remain |
| 2 | M6 — Tauri desktop shell + sidecar | ⛔ | Blocked: needs Rust toolchain + Apple Developer ID for signing/notarization |
| 2 | M7 — Document agent | ✅ | Brief → local Markdown via local model; export md/txt/html (+docx opt); `forge doc` |
| 2 | M8 — Release hardening (v1) | ⛔ | Depends on M5 finish + M6 signing |
| 3 | M9 — Image modality (ComfyUI) | ⏭️ | Prompt → local image with provenance + NSFW filter |
| 3 | M10 — Video modality (experimental) | ⏭️ | Prompt → local clip, labeled experimental, non-blocking |

**Overall v1 = M0–M8.** Phase 3 (M9–M10) is post-v1.

---

## Phase 0 — Foundation

### M0 — Foundation & guardrails harness  ✅
*Goal: stand up the safety nets before building features, so every later milestone is testable against them.*

**Tasks**
- ✅ Add `tests/` egress assertion harness: `tests/egress_guard.py` with `assert_no_external_egress()` + `ExternalEgressError`, patches the socket layer (loopback + AF_UNIX pass, all else blocked).
- ✅ Add `FORGE_CLOUD_ENABLED`, `FORGE_LOCAL_RAM_BUDGET_GB`, `FORGE_MODEL_DISK_HEADROOM_GB` to `config.py` (defaults: `False`, `36.0`, `10.0`) + live reader helpers `cloud_enabled()`, `local_ram_budget_gb()`, `model_disk_headroom_gb()`.
- ⬜ Extend schema-parity script awareness for new WS messages (`pool.state`, `locality.state`, `document.*`) — deferred to M1/M5 when those messages land.
- ⬜ ADR for `sqlite-vec` + `mlx` dependency additions — deferred to M3 (`sqlite-vec` extra already exists) / M1 (`mlx`).

**Tests**
- `tests/test_egress_guard.py` — 21 tests: local/external classification, blocks external connect/connect_ex, allows loopback, restores originals (incl. on exception).
- `tests/test_config_studio.py` — 17 tests: cloud disabled by default, truthy/falsy parsing, RAM budget + disk headroom defaults & overrides.

**Success gate (exit):** ✅ both suites pass (38 tests); `cloud_enabled()` defaults False; full suite 932 passed / 1 skipped. RAM-budget *enforcement* test lands with the pool (M2); the config knob it reads exists now.

---

## Phase 1 — Local-first core

### M1 — Executor pivot (cloud → local default)  ✅
*Goal: the default everything runs on local models; cloud is opt-in only.*

**Tasks**
- ✅ `routing`: `is_cloud_executor()` + `CloudDisabledError`; generator dispatch raises when a cloud executor is selected with cloud off (G-LOC-2). `select_executor()` defaults to `ollama` (was already local-weighted).
- ✅ `executors/mlx.py` — Apple-Silicon MLX executor (lazy `mlx_lm` import; `mlx:`/`mlx-` models route here). Runs in a worker thread with timeout.
- ✅ Locality indicator: `daemon/locality.py::locality_state()`; emitted in `init`/`status` and a `locality` WS handler (daemon = source of truth).
- ✅ `forge models` CLI: `list` + `pull [--dry-run]` with `model_setup.plan_pull()` disk-headroom guard (G-RAM-2).

**Tests**
- `test_executor_pivot.py` (string routing, MLX routing, `is_cloud_executor`, dispatch cloud-gate on/off, Ollama path egress assertion).
- `test_model_setup.py` (pull planner allow/refuse/boundary/skip-present, free-disk).
- `test_locality.py` (local/cloud state + `forge models` list/dry-run CLI).
- Updated `test_generator_context_budget.py` to the new gated contract (+ a blocked-when-disabled test).

**Success gate (exit):** ✅ the real Ollama executor makes no external connection under `assert_no_external_egress()`; cloud executors only dispatch when `FORGE_CLOUD_ENABLED` is set. Full suite 953 passed / 1 skipped, lint + format clean.

---

### M2 — Model Pool Manager (`daemon/pool.py`)  ✅
*Goal: spawn agent models on demand, evict under a RAM budget, never OOM.*

**Tasks**
- ✅ `pool.py` — `ModelPool` with `acquire`/`release`/`lease`/`pin`; LRU eviction *before* load (no transient overrun); orchestrator + embeddings pinned; `PoolCapacityError` for unfittable; large+large *serialized* via an `asyncio.Condition` (in-use models never evicted, waiters wake on release).
- ✅ Scheduler wiring: `_generate_with_pool` leases the generator model; `execute_sprint`/`_run_one_attempt` take an optional `pool`; `execute_session` builds one pool per session (loop-bound) and pins `LOCAL_PLAN_MODEL` + `LOCAL_EMBED_MODEL`.
- ✅ `model_setup.estimate_size_gb()` (table → embed → param-count → default) sizes leases.
- ✅ `pool_state` pushed via `on_change=_broadcast`; pull path via `pool` WS handler + `active_pool_state()`.
- ⬜ 2-D budget merge into `budget.py` — deferred; the pool owns RAM, `budget.py` owns $; kept separate intentionally (simpler, both enforced).

**Tests**
- `test_pool.py` (14): residency/reuse, LRU eviction, budget-never-exceeded, eviction-before-load, pin (ctor + runtime), unfittable raises fast (no hang), large-model serialization, state payload + on_change callback.
- `test_scheduler_pool.py` (3): generator model resident during generation, pool emits state, no-pool back-comp.
- `test_model_setup.py` estimator tests (4).

**Success gate (exit):** ✅ forced squeeze evicts LRU, pins survive, `resident_gb` never exceeds budget on acquire, unfittable fails fast with an actionable message, competing large models serialize. UI can pull (`pool`) and receives pushes (`pool_state`). Full suite 974 passed / 1 skipped.

---

### M3 — Memory upgrade (hybrid recall + reinforcement)  ✅
*Goal: prove memory compounds across sessions.*

**Tasks**
- ✅ Hybrid retriever merge: `retriever.merge_hybrid()` (keyword ∪ vector, dedup-by-id keeping best score, ranked, limit). Live vector pass activates under `FORGE_VECTOR_EPISODES`.
- ✅ Confidence reinforcement: `Retriever.get_context_and_ids()` + `KnowledgeBase.reinforce()`; scheduler reinforces up/down after each verdict (normal, self-consistency, ADaPT). Closes the audit stub.
- ✅ KB injection guard: `memory/kb_guard.validate_kb_content()` (fences, front-matter, chat markers, "ignore previous", fake SYSTEM, null bytes, over-length); wired into `KnowledgeBase.add` + ws `add_knowledge`.
- ✅ Research redaction: `researcher._extract_relevant_content` `redact()`s before store/inject.
- ⬜ sqlite-vec live KB indexing — kept opt-in (ADR-012); merge layer ready.

**Tests**
- `test_hybrid_retrieval.py` (5), `test_confidence_reinforcement.py` (6), `test_kb_guard.py` (12), `test_research_redaction.py` (1).
- Integration `test_memory_compounds.py`: cold KB needs a revision; warm KB approves first attempt **and** confidence rises. Added shared `tmp_db` fixture.

**Success gate (exit):** ✅ warm KB cuts a revision + reinforces; token budget honored; injection guard + redaction proven. Full suite 1000 passed / 1 skipped, lint + format clean.

---

### M4 — CLI completion + audit fixes  ✅
*Goal: drive the whole loop from the terminal; close audit gaps.*

**Tasks**
- ✅ Subcommands `plan` / `run` / `add` / `merge` / `review` registered in `build_parser` + dispatch table, wired over the existing backend (planner, scheduler.execute_sprint, reviewer.review, worktree). `add` defaults to the local coder (not the old "sonnet" default). `_sprint_from_row` reconstructs persisted sprints for `run`.
- ✅ Cross-family invariant test (`pick_evaluator_model` returns a different family for every default-lineup generator + Claude + Qwen + DeepSeek).
- ✅ Path-traversal guard case-normalized via `os.path.normcase` (audit LOW fix).

**Tests**
- `test_cli_verbs.py` (parser registration for all verbs, `add` persists pending, `plan` invokes planner+saves, `run` executes via scheduler / returns 1 with nothing pending, `review` runs the panel, `merge --show` lists worktrees).
- `test_audit_fixes.py` (path guard cwd/external/case-variant; cross-family invariant across 7 generators).

**Success gate (exit):** ✅ all verbs registered + dispatched (`python -m daemon.main` help shows them); `forge run` reconstructs and executes pending sprints; cross-family invariant holds at runtime. Full suite 1024 passed / 1 skipped.

---

### M5 — UI completion  🟡 (partial)
*Goal: the dashboard is real, not stubs.*

**Tasks**
- ✅ Locality indicator (`LocalityIndicator.tsx`, "● Local-only" / "▲ Cloud enabled") + live pool/RAM meter (`PoolMeter.tsx`) wired to the new `locality` + `pool_state` WS messages; requested on connect, updated on push.
- ✅ Schema parity for the new messages: `daemon/locality.py` + `daemon/pool.py` ↔ `ui/lib/types.ts` (`LocalityState`, `PoolState`, `PoolModel`) ↔ `useForgeSocket` handlers.
- ✅ `pnpm build` clean (Next typecheck passes).
- ⬜ Flesh out the 5 legacy stub panels (EvaluatorPanel, MergeGate, CostMeter, ResearchPanel, ReviewPanel/LearningLog).
- ⬜ Merge-gate approve/reject UI; onboarding folder/branch picker + `forge models pull` wizard.
- ⬜ Playwright snapshot tests (no Playwright harness configured yet).

**Success gate (exit):** PARTIAL — new local-first surfaces (locality + pool) shipped and build-verified; the legacy-panel rebuild + onboarding remain. Best done interactively with the daemon running.

---

## Phase 2 — Product

### M6 — Tauri desktop shell + Python sidecar  ⬜
*Goal: a double-clickable app.*

**Tasks**
- ⬜ Tauri v2 shell embedding the Next.js build; spawn + supervise the Python daemon sidecar; WS healthcheck gate before UI load.
- ⬜ `forge doctor` preflight on first launch (Ollama present, models pulled, git ok, disk ok).
- ⬜ Graceful quit → SIGTERM → WAL flush + worktree cleanup (verify existing handlers fire under Tauri).
- ⬜ Signing + notarization pipeline (Apple Developer ID) → `.app` / `.dmg`. *(External: Apple enrollment.)*

**Tests / checks**
- Manual: cold launch on a clean machine; offline coding task completes; quit leaves no orphan worktrees/processes.
- `test_sidecar_lifecycle` (daemon start/stop contract), `test_doctor_preflight`.

**Success gate (exit):** double-click the signed `.app`, network off, complete an end-to-end coding task; clean shutdown verified.

---

### M7 — Document agent  ✅
*Goal: local document creation.*

**Tasks**
- ✅ `daemon/agents/document.py` — `write_document(brief, criteria, model)` via the local Ollama executor (free/offline; default model is local, not cloud), returns Markdown; `save_document()` persists it.
- ✅ `daemon/artifacts.py` — `save_artifact()` writes under `.forge/artifacts/` with slugified (traversal-safe) names; export `md`/`txt`/`html` (stdlib `markdown_to_html`, HTML-escaped) + best-effort `docx` (optional `python-docx`, degrades to `.md`).
- ✅ `forge doc "<brief>" --name --format` CLI command.
- ⬜ UI document surface + viewer — deferred to M5 (frontend).
- ⬜ PDF export — deferred (would add a heavy runtime dep; html→PDF can be done in the UI/print path).

**Tests**
- `test_artifacts.py` (9): save md/txt/html, slugify/traversal-safety, markdown→html headings/lists/escaping, unknown-format raises.
- `test_document_agent.py` (5): brief→markdown, failure surfaces, local-model default is not cloud, write-and-save.

**Success gate (exit):** ✅ generate a doc from a brief fully offline via a local model and export to md/txt/html locally; default writer model routes through a non-cloud executor. Full suite 1036 passed / 1 skipped.

---

### M8 — Release hardening (v1)  ⬜
*Goal: ship v1.*

**Tasks**
- ⬜ Run full acceptance suite (BUILD §9, all 8 criteria).
- ⬜ Coverage ≥80% on touched core; pre-push gate green; schema parity green.
- ⬜ CHANGELOG + version sync (`scripts/sync-version.py`); signed tag.
- ⬜ Modality contract (`daemon/modalities/base.py`) + `code`/`document` registered; image/video documented stubs.

**Success gate (exit):** every §9 acceptance criterion is ✅ with evidence; signed build produced; Phases 2/3 exist as documented contracts.

---

## Phase 3 — Multi-modal (post-v1)

### M9 — Image modality (ComfyUI on Metal)  ⏭️
**Gate:** prompt → local SDXL/Flux image with NSFW post-filter + provenance tag; cost/RAM/disk estimate shown before run; never blocks coding.

### M10 — Video modality (experimental)  ⏭️
**Gate:** prompt → short local clip (Wan/LTX-Video on Metal), clearly labeled experimental, time/RAM estimate first, fully optional and non-blocking.

---

## Cross-cutting success gates (apply to every milestone)

1. **Offline by default** — `assert_no_external_egress()` holds on the default path after the change (G-LOC-1).
2. **Tests green locally** — pre-push passes; coverage ≥80% on touched core.
3. **Schema parity** — if the WS protocol changed, all 5 locations moved together.
4. **Trace truthful** — new agent/pool actions appear in `.forge/sessions/<id>/trace.jsonl`.
5. **No relaxed security** — no `shell=True`, 127.0.0.1-only, redaction intact, worktree isolation intact.
6. **Honest UI** — no stub shipped as complete; locality indicator matches reality.

---

## Risk register (live)

| ID | Risk | Status | Mitigation / owner |
|---|---|---|---|
| R1 | Disk exhaustion from models | Open | Disk ceiling guard (M1) + external-dir doc |
| R2 | Local quality → revision blow-up | Open | Cross-family eval + cap + cloud booster; smoke-set measurement (M3) |
| R3 | RAM thrash on 48 GB | Open | Pool budget + LRU (M2) |
| R4 | Tauri signing/notarization friction | Open | Isolated to M6; needs Apple Developer ID |
| R5 | Video-on-Metal immaturity | Open | Keep M10 experimental, non-blocking |
| R6 | Scope creep to all modalities | Open | D3 locks v1 = code+docs |

---

*Update this file on every task state change. Bump `last_reviewed`. Evidence (test name / trace / screenshot) is required to mark anything ✅.*
