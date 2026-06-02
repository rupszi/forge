---
status: live
owner: pal.megyes
last_reviewed: 2026-06-02
---

# Forge Studio — Build Specification

> **What this is.** The canonical spec for turning the existing Forge orchestrator (a Python daemon + Next.js UI that drives the paid `claude -p` CLI) into **Forge Studio**: a double-clickable, **local-first, free-by-default** desktop app. You open it, point it at a project folder + git branch, and a local orchestrator model plans work and spawns specialist local models on demand — coding and documents in v1, images and video in later phases. All data stays on the machine.
>
> **Companion docs.** Live status lives in [FORGE_STUDIO_TRACKER.md](FORGE_STUDIO_TRACKER.md). General engineering bar lives in [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md) — this spec does **not** repeat it, only adds Studio-specific guardrails (§7). Architecture decisions are logged in [DECISIONS.md](DECISIONS.md) as ADRs.

---

## 0. Decisions locked (2026-06-02)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| D1 | Foundation | **Evolve Forge**, don't rewrite | Reuse harness, memory, scanner, scheduler, security (~13k LOC, 894 tests). Keep tests green throughout. |
| D2 | App shell | **Tauri v2** (Rust) wrapping the Next.js UI | Signed macOS `.app`, ~10 MB, Python daemon as a sidecar. |
| D3 | v1 scope | **Coding + Documents** | Images = Phase 2, Video = Phase 3, designed-in as plugins now, not built. |
| D4 | Locality | **Local-only by default, cloud opt-in** | Zero network inference out of the box; `claude -p` / cloud keys become an optional booster. |
| D5 | Target HW | **Apple Silicon (M4 Pro, 48 GB, Metal)** primary | No CUDA. All models/tools must run on Metal/MPS/MLX. Disk is the binding constraint. |

These five are the contract. Changing any of them is an ADR, not a side decision.

---

## 1. Mission & non-negotiables

**Mission.** A standalone product that, on first launch with **no API keys and the network off**, can: scan a project, plan work, generate code in isolated git worktrees, have a *different-model-family* evaluator grade it, let the user review diffs and merge — and remember what it learned for next time. Then write documents. Later, make images, then video — all with free local models.

**Non-negotiables** (violating any is a release blocker):

1. **Free & local by default.** Default path uses only **Ollama** (Metal) and locally-served weights (MLX / HuggingFace **weights**, never HF hosted inference). No outbound inference calls unless the user explicitly opts into cloud.
2. **Everything local.** All state in `<project>/.forge/` + the app data dir. SQLite only. No cloud memory service. No telemetry (carry over the existing anti-telemetry stance).
3. **Evolve, don't rewrite.** Reuse the tested modules (§3). Every PR keeps the suite green and respects [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md).
4. **Security posture is inherited, not relaxed.** 127.0.0.1-only IPC, no `shell=True`, worktree isolation, credential redaction, append-only audit log, schema-parity gate. Plus the new RAM-budget and local-only guardrails (§7).
5. **Honest surfaces.** No stub shipped as if complete. Experimental modalities (video) are labeled experimental. The "Local-only ●" indicator must be truthful.

---

## 2. Target architecture

```
Forge Studio.app  (Tauri v2 / Rust shell)
  ├─ WebView: existing Next.js UI
  └─ Sidecar: Python daemon (asyncio)         ⟷  127.0.0.1:9111 (WS, hardcoded)
        │
        ├─ Orchestrator (resident local model)  ── plans · classifies · routes · synthesizes
        ├─ Model Pool Manager (NEW: pool.py)     ── load/unload agent models under a RAM budget
        ├─ Agents: planner · generator · evaluator(cross-family) · reviewer · researcher · document(NEW)
        ├─ Executors: ollama(default) · mlx(NEW) · openai_compatible · claude_code(opt-in) · batch(opt-in)
        ├─ Memory: SQLite + sqlite-vec(NEW) + local embeddings  — episodic · KB · procedural · research
        ├─ Scanner · Scheduler · Budget(cost+RAM) · Worktree · Replay · Recovery · Security layers
        └─ Modality plugins:  [v1: code, document]   [P2: image]   [P3: video]

  All state: <project>/.forge/  +  ~/Library/Application Support/ForgeStudio/
  No cloud path active unless user opts in (then a visible indicator changes).
```

**Process model.** Tauri owns the window and lifecycle. On launch it spawns the Python daemon as a managed sidecar, waits for the WS healthcheck, then loads the UI. On quit (or crash), Tauri sends SIGTERM; the daemon's existing signal handlers flush WAL and clean worktrees. A `forge doctor` preflight runs before first session.

---

## 3. Reuse map (what we keep vs change)

**Keep & extend (no behavioral change required):**
`daemon/memory/*`, `daemon/db.py`, `daemon/scanner/*`, `daemon/scheduler.py`, `daemon/agents/{planner,generator,evaluator,reviewer,classifier,researcher}.py`, `daemon/worktree.py`, `daemon/budget.py`, `daemon/recovery.py`, `daemon/replay.py`, `daemon/safety.py`, `daemon/redact.py`, `daemon/sanitize.py`, `daemon/refusal.py`, `daemon/hooks.py`, `daemon/mode.py`, `daemon/ws_server.py`, `daemon/mcp_server.py`, the whole `ui/`.

**Pivot (default flips from cloud → local):**
- `daemon/routing.py` + `daemon/agents/classifier.py` — default model lineup becomes local (§4). `select_executor()` defaults to `ollama`.
- `daemon/executors/claude_code.py`, `daemon/executors/batch.py` — gated behind a **cloud-opt-in flag**; never on the default path.
- `daemon/executors/ollama.py`, `daemon/executors/openai_compatible.py` — primary paths.

**Add (new modules):**
- `daemon/pool.py` — Model Pool Manager (§5).
- `daemon/executors/mlx.py` — MLX-served models for anything Ollama can't host (e.g. some HF weights, embeddings).
- `daemon/agents/document.py` — Document agent (§6.2).
- `daemon/modalities/` — plugin contract for image/video (§8), with `code` + `document` as the first two registered modalities.
- Memory: enable `sqlite-vec` + a local embedding model for hybrid retrieval (§6.3); finish the stubbed confidence-reinforcement loop.

**Fix while here (from the 2026-06-02 audit):**
- Add missing CLI verbs `plan / run / add / merge / review` over the existing backend.
- Verify `pick_evaluator_model()` enforces a *different model family* at runtime (the thesis depends on it).
- Validate KB content on add (prompt-injection guard); `redact()` research before KB/prompt injection; case-normalize the path-traversal guard.

---

## 4. Local model lineup (defaults for 48 GB / Metal)

All free, all Apple-Silicon-friendly, all overridable in settings. Sizes are approximate Q4 quants.

| Role | Default model | ~Size | Residency |
|---|---|---|---|
| **Orchestrator** (plans, routes, classifies, synthesizes) | `qwen2.5:7b-instruct` (alt `llama3.1:8b`) | ~4.7 GB | **Pinned** (always loaded) |
| **Coder** (generator) | `qwen2.5-coder:14b` (opt-up `:32b` ~20 GB if disk allows; fallback `:7b`) | ~9 GB | Spawned per task, LRU-evicted |
| **Evaluator** (must be a DIFFERENT family than the generator) | `llama3.1:8b` or `deepseek-coder-v2:16b` | ~5–10 GB | Spawned per evaluation |
| **Embeddings** (memory recall) | `nomic-embed-text` (alt `bge-small`) | ~0.3 GB | Pinned (tiny) |
| **Document writer** | reuses orchestrator/coder + writer style | — | Reuses loaded model |

**Cross-family rule (load-bearing).** The generator and evaluator must never be the same family. `pick_evaluator_model()` enforces this and a test asserts it (Generator=Qwen ⇒ Evaluator ∈ {Llama, DeepSeek, …}).

**Disk reality.** ~39 GB free at audit time. The default set (orchestrator + coder-14b + evaluator-8b + embeddings) is ~19 GB — fits, but tight. `forge models pull` reports cumulative size and **refuses** to exceed a configurable disk ceiling (`FORGE_MODEL_DISK_CEILING_GB`, default leaves 10 GB headroom). Document an external-model-dir option (`OLLAMA_MODELS=/Volumes/...`).

---

## 5. Model Pool Manager (`daemon/pool.py`) — the "spawn when needed" core

The single new subsystem that makes local orchestration safe on a 48 GB shared-memory machine.

**Responsibilities:**
- Track resident models and their real memory footprint.
- Enforce a **RAM budget** (`FORGE_LOCAL_RAM_BUDGET_GB`, default ~36 of 48 — leaves headroom for the OS, the daemon, ComfyUI later).
- On dispatch: ensure the required model is loaded (Ollama `keep_alive`); if loading it would exceed the budget, **evict the LRU non-pinned model first**. Never co-resident two large models that don't fit.
- Pin the orchestrator and embeddings; everything else is evictable.
- Serialize "large + large" so two 14B+ models never run concurrently unless they fit.
- Surface live state to the UI (loaded models, RAM used, what's pinned, what's about to evict).

**Integration.** Extend `daemon/budget.py` so "budget" is two-dimensional: **$ cost** (only meaningful when cloud opt-in is on) **and** **local RAM residency**. The scheduler asks the pool for a model handle before each generate/evaluate; the pool blocks/evicts as needed.

**Hard rules:** no OOM (eviction must happen *before* load, not after); the orchestrator is never evicted; eviction is logged to the trace JSONL.

---

## 6. v1 capabilities

### 6.1 Coding (the core loop, already mostly built)
Open folder → scanner → pick/create branch → prompt → planner decomposes into sprints with `done_criteria` → generator works in a **git worktree** → cross-family evaluator grades each criterion PASS/FAIL with evidence → up to 2 revisions → merge gate (diff review + approve/reject) → learner extracts gotchas. **Work to do:** flip executors to local, wire the pool, finish the 5 stub UI panels, add CLI verbs.

### 6.2 Documents (new, lightweight)
A `document` task type and `daemon/agents/document.py`. Produces Markdown by default; exports to **docx / PDF locally** via the existing skill tooling (the repo already lists `docx` / `pdf` skills). Reuses `output_styles.py` for voice/format. Outputs saved under `<project>/.forge/artifacts/` (or a user-chosen path). No cloud. Same plan→generate→evaluate discipline (evaluator checks the doc against the brief's criteria), but no worktree needed for pure-doc tasks.

### 6.3 Memory (good, local, small DB)
Keep the four-tier SQLite store. **Add hybrid retrieval**: `sqlite-vec` + the local embedding model so recall is keyword (LIKE) **+** vector similarity — still one small local file. **Finish confidence reinforcement** (the audit found it stubbed): after a task, mark injected KB items helpful/unhelpful so the KB self-corrects. **Acceptance:** a repeated task demonstrably hits cached KB/procedural routing and skips a revision cycle (proves compounding).

---

## 7. Guardrails (Studio-specific) + industry best practices

> These **add to** [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md) (which already covers ruff/pyright/pytest/pre-push/CI/SemVer/security hygiene). Below are only the guardrails this pivot introduces.

### 7.1 Locality guardrails (the product promise)
- **G-LOC-1 — Default offline.** With no cloud opt-in, the daemon makes **zero** outbound network connections for inference. Enforce with an egress assertion in tests: mock the socket layer and assert no connection leaves `127.0.0.1` / `localhost` on the default path.
- **G-LOC-2 — Cloud is explicit & visible.** Cloud executors (`claude_code`, `batch`, any API key path) activate **only** when the user sets a setting/flag, and the UI's locality indicator must switch from "Local-only ●" to "Cloud enabled ▲". No silent fallback to cloud, ever.
- **G-LOC-3 — Data residency.** No code path writes project data, prompts, diffs, or memory off-machine. CI grep-gate forbids new outbound URLs in `daemon/` outside the opt-in executors and the (existing) researcher, which itself is opt-in.

### 7.2 Resource guardrails (48 GB shared memory)
- **G-RAM-1 — No OOM.** The pool evicts before loading. A test simulates a budget squeeze and asserts eviction order (LRU, never the orchestrator).
- **G-RAM-2 — Disk ceiling.** `forge models pull` refuses to cross `FORGE_MODEL_DISK_CEILING_GB`; surfaces cumulative size before downloading.
- **G-RAM-3 — Graceful degradation.** If a model can't fit even after eviction, fail the sprint with a clear, actionable error (suggest a smaller model / freeing RAM) — never hang, never thrash.

### 7.3 Agent safety guardrails (autonomy)
- **G-AGT-1 — Cross-family evaluation enforced** (runtime check + test). The generator never grades its own work; evaluator family ≠ generator family.
- **G-AGT-2 — Worktree isolation** for all code edits; evaluator is read-only against the diff (inherited).
- **G-AGT-3 — Mode honored.** `ask / plan / auto / bypass / accept_edits` actually gate scheduler behavior (inherited from `mode.py`); destructive ops route through `refusal.py`.
- **G-AGT-4 — Prompt-injection hygiene.** Untrusted context (web research, raw repo, low-confidence KB) runs through `sanitize.py`; KB content is validated on add; research is `redact()`-ed before injection. (This realizes audit fix + roadmap L1/L13.)
- **G-AGT-5 — Revision cap.** Max 2 revisions then escalate to the user (inherited) — no infinite generate↔evaluate loops.

### 7.4 Engineering best practices carried in (pointers, not repeats)
- **Pre-push > CI**, conditional `SKIP_*` gates — [STANDARDS §6–7](ENGINEERING_STANDARDS.md#6-cicd).
- **Schema-parity gate** across `db.py` ↔ `models.py` ↔ `ws_server.py` ↔ `ui/lib/types.ts` ↔ `schemas/` — any Studio change touching the WS protocol (pool state, locality indicator, document tasks) **must** move all five together. This is the single biggest incident preventer.
- **Tests: unit (no binaries) + integration (`@pytest.mark.integration`, needs Ollama)**, ≥80% branch coverage on core — [STANDARDS §5](ENGINEERING_STANDARDS.md#5-testing). The pool, hybrid retrieval, executor routing, and CLI verbs each get unit + integration tests.
- **`asyncio.TaskGroup` + `asyncio.timeout`**, mandatory timeouts on every external call, `silent_catch` over bare `except` — [STANDARDS §8, §10](ENGINEERING_STANDARDS.md#8-async-concurrency-performance-patterns).
- **Per-session JSONL trace** for every agent action incl. pool load/evict events — [STANDARDS §9, §16](ENGINEERING_STANDARDS.md#9-logging-tracing-observability).
- **No new runtime deps without justification.** `sqlite-vec` (vector recall) and `mlx`/`mlx-lm` (Apple-Silicon serving) are the only expected additions; each gets an ADR + a Dependency-tracker row. Tauri/Rust deps live in the `ui`/shell side, not Python runtime.
- **Branch strategy:** feature branches off `develop` → `main` via PR; no direct push to `main`; squash to `develop`, merge commit to `main`.

### 7.5 Definition of Done (every Studio task)
A task is done only when: code + tests green locally (pre-push passes), coverage holds ≥80% on touched core, schema-parity holds if the WS protocol changed, the relevant **success gate** in the tracker is met with evidence, the trace shows the new events, docs/CHANGELOG updated, and **the default path stays offline** (G-LOC-1 re-verified).

---

## 8. Later phases — designed in now, built later

These ship as **modality plugins** behind a stable contract so they're drop-in, not forklift changes. v1 builds **only the contract + `code`/`document` modalities**; image/video are stubs with documented interfaces.

**`MediaProvider` / modality contract (`daemon/modalities/base.py`):** `name`, `capabilities`, `plan(brief)`, `generate(spec) -> Asset`, `evaluate(asset, criteria)`, `estimate_cost(spec)` (RAM/disk/time), asset storage under `<project>/.forge/artifacts/`.

- **Phase 2 — Images.** `daemon/modalities/image_comfyui.py`: local **ComfyUI** on Metal (SDXL / Flux Schnell via MPS/MLX). Prompt → image, with NSFW post-filter and C2PA-style provenance tag. Needs disk cleanup first.
- **Phase 3 — Video.** `daemon/modalities/video_local.py`: local **Wan / LTX-Video** on Metal — explicitly **experimental, slow, optional**, never on the critical path. Clear "experimental" labeling and a time/RAM estimate before run.

---

## 9. Acceptance criteria (v1 release)

1. **Offline coding task.** Double-click the `.app`; with no API keys and **network disabled**, complete a real task on a sample repo: plan → generate-in-worktree → cross-family evaluate → review diff → merge. 100% local.
2. **Document task.** Generate a README/spec locally and export to Markdown + PDF/docx.
3. **Memory compounds.** Re-running a similar task uses cached KB/routing and needs fewer/zero revisions (measured, in the trace).
4. **Pool behaves.** Coder spawns on demand and is evicted after; RAM never exceeds the budget; UI shows it live; no OOM under a forced squeeze.
5. **Tests green + gates hold.** All existing tests pass + new tests for pool, hybrid retrieval, executor routing, CLI verbs, and the locality egress assertion. Coverage ≥80% on touched core.
6. **Locality honest.** Indicator reflects reality; cloud only activates on explicit opt-in.
7. **App lifecycle.** Tauri launches/supervises/cleans up the daemon; `forge doctor` preflight passes; graceful quit flushes WAL + worktrees.
8. **Phases 2 & 3 exist as documented contracts**, not half-built features.

---

## 10. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Disk exhaustion from models | High | Disk ceiling guard + external-dir option + size preview before pull |
| Local model quality < cloud (revisions balloon) | Med | Cross-family eval + revision cap + cloud opt-in as a booster; measure on a smoke set |
| RAM thrash on 48 GB | Med | Pool budget + LRU eviction + serialize large models |
| Tauri ↔ Python sidecar packaging/signing pain | Med | Treat as its own milestone (M6); reuse the deferred Phase 6/7 work; notarization needs Apple Developer ID |
| Video-on-Metal immaturity | High | Keep Phase 3, experimental, non-blocking |
| Scope creep into all-modalities-at-once | Med | D3 locks v1 = code+docs; modality contract absorbs the rest later |

---

*Living document. Status and task-level progress are tracked in [FORGE_STUDIO_TRACKER.md](FORGE_STUDIO_TRACKER.md). Update this spec only when a §0 decision or an architectural contract changes (and log it in [DECISIONS.md](DECISIONS.md)).*
