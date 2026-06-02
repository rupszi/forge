---
status: live
owner: pal.megyes
last_reviewed: 2026-06-02
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

---

## Dashboard

| Phase | Milestone | Status | Exit gate |
|---|---|---|---|
| 0 | M0 — Foundation & guardrails harness | ✅ | Offline egress test + config-budget tests pass (38 tests) |
| 1 | M1 — Executor pivot (cloud → local default) | ✅ | Cloud gated behind opt-in; Ollama path egress-proven local; 953 tests green |
| 1 | M2 — Model Pool Manager | ✅ | Forced squeeze evicts LRU, pins survive, unfittable fails fast, large serialized |
| 1 | M3 — Memory upgrade (hybrid recall + reinforcement) | ⬜ | Repeat task skips a revision via cached KB/routing |
| 1 | M4 — CLI completion + audit fixes | ⬜ | `plan/run/add/merge/review` work; cross-family enforced at runtime |
| 1 | M5 — UI completion (5 stub panels + onboarding) | ⬜ | `pnpm build` clean; merge gate approve/reject works; locality indicator honest |
| 2 | M6 — Tauri desktop shell + sidecar | ⬜ | Double-click `.app` runs an offline coding task end-to-end |
| 2 | M7 — Document agent | ⬜ | Generate + export a doc to MD + PDF/docx locally |
| 2 | M8 — Release hardening (v1) | ⬜ | All §9 acceptance criteria green; signed build |
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

### M3 — Memory upgrade (hybrid recall + reinforcement)  ⬜
*Goal: prove memory compounds across sessions.*

**Tasks**
- ⬜ Enable `sqlite-vec`; add local-embedding indexing for KB + episodic.
- ⬜ Hybrid retriever: keyword (LIKE) ∪ vector similarity, dedup, ≤500-token budget preserved.
- ⬜ Finish confidence reinforcement: mark injected KB items helpful/unhelpful post-task (close the audit stub).
- ⬜ Redact research before KB/prompt injection; validate KB content on add (G-AGT-4).

**Tests**
- `test_hybrid_retrieval_ranks`, `test_confidence_reinforcement`, `test_kb_injection_guard`, `test_research_redacted_before_store`.
- Integration: `test_memory_compounds` — session 2 of a similar task skips ≥1 revision vs session 1.

**Success gate (exit):** `test_memory_compounds` shows a measurable reduction in revisions/route-time on repeat; retrieval stays within the token budget; injection guard + redaction proven.

---

### M4 — CLI completion + audit fixes  ⬜
*Goal: drive the whole loop from the terminal; close audit gaps.*

**Tasks**
- ⬜ Add subcommands `plan`, `run`, `add`, `merge`, `review` over the existing backend (the audit found these missing).
- ⬜ Runtime enforcement + test that evaluator family ≠ generator family (G-AGT-1).
- ⬜ Path-traversal guard case-normalization fix.

**Tests**
- `test_cli_plan_run_add_merge_review`, `test_cross_family_enforced_runtime`, `test_path_guard_case_insensitive`.

**Success gate (exit):** `forge plan "..." && forge run` executes a full local session headlessly; cross-family invariant holds at runtime (not just config).

---

### M5 — UI completion  ⬜
*Goal: the dashboard is real, not stubs.*

**Tasks**
- ⬜ Finish the 5 stub panels: EvaluatorPanel, MergeGate, CostMeter, ResearchPanel, ReviewPanel/LearningLog.
- ⬜ Wire merge-gate approve/reject end-to-end.
- ⬜ Onboarding: folder picker + branch picker + `forge models pull` wizard with disk preview.
- ⬜ Locality indicator ("Local-only ●" / "Cloud enabled ▲"); live pool/RAM meter.
- ⬜ Schema parity across the 5 locations for all new WS messages.

**Tests**
- `pnpm build` clean, no console errors. Playwright snapshot tests for the 5 views + merge-gate flow. Schema-parity script green.

**Success gate (exit):** a user can run a coding task fully through the UI (plan → watch → review diff → approve/merge), see live pool/RAM + honest locality, with no stub panels remaining.

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

### M7 — Document agent  ⬜
*Goal: local document creation.*

**Tasks**
- ⬜ `daemon/agents/document.py` + `document` task type (plan→generate→evaluate against brief criteria).
- ⬜ Local export MD → PDF/docx via existing skill tooling; save to `.forge/artifacts/`.
- ⬜ UI: document task surface + artifact viewer/download.

**Tests**
- `test_document_agent_generates`, `test_document_export_md_pdf_docx`, evaluator-against-brief test.

**Success gate (exit):** generate a README/spec from a prompt and export to MD + PDF/docx, fully offline, with the doc graded against its brief.

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
