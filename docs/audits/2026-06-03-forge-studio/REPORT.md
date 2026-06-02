---
status: live
owner: pal.megyes
last_reviewed: 2026-06-03
---

# Forge Studio — Comprehensive Audit (2026-06-03)

**Branch:** `develop` · **Scope:** the local-first ("Forge Studio") pivot — daemon
+ UI + tests. **Method:** four independent specialist review roles
(Security · Test-quality · Code-quality · Architecture/Docs), each evidence-based
with `file:line`, followed by **adversarial verification** of every High finding
and a remediation pass. Tooling run on a clean tree.

## Verdict

The codebase is **disciplined and largely honest**, but the audit found **two
genuine High-severity defects** — both now **fixed and regression-tested** in this
pass:

1. **The evaluator ran on cloud `claude -p` on the default path** — breaking the
   project's central "local cross-family evaluator" promise and the G-LOC-1
   "zero-egress by default" guardrail. The integration suite missed it because it
   mocks `evaluator.evaluate` wholesale. **FIXED** — the evaluator now routes
   through the same executor selection + cloud gate as the generator (runs on the
   local cross-family model, e.g. `llama3.1:8b`, by default).
2. **Symlink escape in `_validate_init_path`** — a symlink planted inside cwd/home
   (`innocent.txt → /etc/passwd`) passed the lexical scope check, letting
   `file.fetch` / `attach.path` read arbitrary files into the agent context.
   **FIXED** — the guard now `realpath`s before the containment check, and
   attachments skip symlinks.

Test quality is **A−** (≈0.3% genuinely weak tests out of ~1150). Studio docs
(BUILD/TRACKER/USER_GUIDE) are honest about status; the **legacy README and
ENGINEERING_STANDARDS are stale** (reconciled in this pass / remediation plan).

**Is this production-grade for a v0.1 local-first release?** Not yet — but close.
The two Highs were the blockers and are fixed. Remaining work before a tag:
session/project-scope the working-memory scratchpad (High-open), wire or
gate the dead `Researcher` cloud call, implement-or-remove `FORGE_REDACT_PROMPTS`,
and run the SWE-bench kill gate (still unrun).

## Tooling results

| Check | Result |
|---|---|
| `pytest` (full) | **1155 passed, 1 skipped** (was 1150 pre-fix; +5 audit regressions) |
| Determinism (3 runs) | Stable; no flakes. ⚠ `pytest-randomly` not installed → order-coupling invisible |
| `ruff check` / `format --check` | Clean (168 files) |
| `pyright` | **Not installed** — no static type checker in the loop (gap) |
| `pip-audit` | available (8.30.1); **`bandit` / `gitleaks` not installed** in venv |
| `coverage` / `pytest-cov` | **Not installed** — numeric coverage unavailable this run |
| `pnpm build` (UI) | Compiles clean |

## Findings summary

| ID | Sev | Area | Title | Status |
|---|---|---|---|---|
| F1 | **High** | Security/Arch | Evaluator executes on cloud `claude -p` on the default path (G-LOC-1 violation) | ✅ Fixed |
| F2 | **High** | Security | Symlink escape in `_validate_init_path` → arbitrary file read | ✅ Fixed |
| F3 | **High** | Correctness/Privacy | Working-memory scratchpad not session/project-scoped → cross-session/project leak | ⬜ Open |
| F4 | Medium | Security | `FORGE_REDACT_PROMPTS` documented + allowlisted but never honored (dead flag) | ⬜ Open |
| F5 | Medium | Security | KB injection guard is a shallow English denylist (bypassable) — defense-in-depth only | ⬜ Open (document as best-effort) |
| F6 | Medium | Correctness | `chunk_text` overlap can push a chunk past `max_chars` (latent; callers pass overlap=0) | ⬜ Open |
| F7 | Medium | Performance | MLX executor reloads model weights on every call (no cache) | ⬜ Open |
| F8 | Medium | Docs | Legacy README stale: model names, 3 conflicting test counts, 2 phantom CLI verbs | ✅ Reconciled |
| F9 | Medium | Docs | ENGINEERING_STANDARDS references `src/forge/`, `schemas/`, schema-parity + sync-version scripts that don't exist | 🟡 Noted |
| F10 | Medium | Docs | Recent context features (num_ctx presets, KV-quant, `forge digest`) undocumented | ✅ Reconciled |
| F11 | Low | Quality | Dead code: `Researcher` agent + `"batch"` executor string never wired (latent cloud call / KeyError) | ⬜ Open |
| F12 | Low | Quality | Context builders overshoot byte budget by the truncation-suffix length | ⬜ Open |
| F13 | Low | Quality | `context_window` globals mutate live mid-session (no per-sprint snapshot) | ⬜ Open |
| F14 | Low | Tests | 4 genuinely weak tests (tautological `rc in (0,1)`, constant-equals-itself, Linux-branch vacuous) | ⬜ Open |
| F15 | Info | Tests | Attachments singleton not auto-cleared between sessions; `FORGE_DIR` relative leak in "isolated" tests | ⬜ Open |

## Role A — Security (adversarially verified)

- **F1 (High, FIXED):** `evaluator.py:313` called `claude_executor.execute()`
  unconditionally. **Proven** by running `evaluate()` with `FORGE_CLOUD_ENABLED`
  unset → `{'claude': 1, 'ollama': 0}`. Fix added `evaluator._dispatch_eval()`
  routing via `routing.select_executor` + `is_cloud_executor`/`cloud_enabled`
  gate; default cross-family model (`llama3.1:8b`) now runs on Ollama; cloud eval
  with cloud off raises `CloudDisabledError`. Regression: `test_audit_2026_06_03.py`.
- **F2 (High, FIXED):** **Proven** PoC — `ln -s /etc/passwd cwd/innocent.txt`;
  `_validate_init_path("innocent.txt") → True`; `read_file_text` leaked `root:`.
  Fix: `realpath` before containment + attachments skip symlinks. Regression added.
- **F4 (Medium, open):** `FORGE_REDACT_PROMPTS` is documented in `redact.py` and in
  `_SUBPROCESS_ENV_ALLOWLIST` but **no code reads it** — prompt-egress redaction is
  a dead promise. Trace-file redaction (`replay.py`) *is* correctly wired.
- **F5 (Medium, open):** `kb_guard.validate_kb_content` is bypassed by `Assistant:`
  headers, "developer mode", non-English (Cyrillic) injections. Treat as
  best-effort, not a boundary; document accordingly.
- **Verified SOUND:** `memory_tool._resolve` (traversal + symlink contained),
  `gitctl._valid_branch` (no git-arg injection), all subprocess calls (argv lists,
  no `shell=True`), WS Origin allow-list (no subdomain/userinfo bypass), 127.0.0.1
  bind, rate limit, size cap, subprocess env allowlist.

## Role B — Test quality (grade: A−)

- Genuinely weak tests: **4** (~0.3%): `test_audit_fixes.py` case-variant vacuous on
  Linux; `test_locality.py` `rc in (0,1)`; two `test_ws_server.py` constant==constant
  assertions (the file admits it). **No** tautological-mock-returns-its-own-mock,
  no `assert True` placeholders, no mocking-the-function-under-test.
- **Integration reality:** the real plan→generate→evaluate loop is never run with a
  real subprocess (every test stubs generator/evaluator — necessary in CI), **but
  wiring is genuinely proven** (repomap content reaches generator; DB rows written
  after recovery; pool lease held *during* generation; `test_ws_serve_live.py` runs
  a real WS client end-to-end). The suite even discloses its stubs (swebench runner
  raises `NotImplementedError`). This integration gap is exactly why F1 hid.
- **Hygiene gaps (F15):** `attachments.get_store()` and `context_window` module
  globals have no autouse reset; `tmp_forge_dir` doesn't patch `memory_tool.FORGE_DIR`,
  so "isolated" scheduler tests read the real `.forge/memories/`. Add `pytest-randomly`.

## Role C — Code quality & correctness

- **F3 (High, open):** `memory_tool.default_tool()` uses `MemoryTool(".forge/memories")`
  — relative to the daemon CWD, **no `<session>` subdir** (contradicts its own
  docstring), so every prior session's scratchpad re-injects into every future
  sprint, across projects. Fix: derive base from `ctx.path` + `session_id`.
- **F6/F7/F12/F13/F11** as in the table. Notably the async primitives audited
  hardest — the **pool `Condition` wait/notify and event-loop binding — are
  correct** (no lost wakeup / spin / OOM-before-evict reproducible); compaction +
  map_reduce terminate; `_reinforce` fires exactly once per path. Schema parity for
  the *typed* WS messages (`PoolState`/`LocalityState`/`ContextOptions`) is OK.

## Role D — Architecture & docs

- **F1** also surfaced here (evaluator docstring asserts local cross-family
  execution; code did not). Fixed.
- **F8/F10 (reconciled):** README model names corrected to `qwen2.5*`; test-count
  badge de-numbered; phantom `forge research` / `forge llms` removed; USER_GUIDE
  §7.5 extended with num_ctx presets + KV-quant + `forge digest`.
- **F9 (noted):** ENGINEERING_STANDARDS describes `src/forge/`, a `schemas/` dir,
  and `scripts/check-schema-parity.py` / `sync-version.py` that **don't exist**
  (package is `daemon/`; `scripts/` has only `audit-docs.py` + `pre-push.sh`). The
  "single biggest incident preventer" gate is documented but unimplemented.
- **Tracker is honest:** M2/M3/M4/M7 spot-checked real; M5 🟡 accurate; M6/M8/SWE
  honestly blocked.

### Architecture map (verified)

```
Forge daemon (asyncio) — package: daemon/   (docs say src/forge/ — wrong)
  ws_server.py     127.0.0.1:9111 WS; ~28 client message types (de-facto protocol source)
  config.py        cloud_enabled(), RAM/disk/ctx budgets, model lineup + family registry
  routing.py       select_executor → {mlx | claude_code(cloud) | openai_compatible | ollama}
  agents/ planner · generator(cloud-gated) · evaluator(NOW cloud-gated too) ·
          classifier(cross-family pick) · reviewer · researcher(dead) · document(local)
  executors/ ollama(default) · mlx · openai_compatible · claude_code(cloud) · batch(unrouted)
  pool.py          RAM budget, LRU evict-before-load, pin orchestrator+embeddings
  memory/ knowledge(+kb_guard) · episodic · procedural · research · retriever(hybrid) · learner
  scheduler.py     plan→generate→evaluate→revise(≤2)→merge; one pool/session; reinforce + learn
  context stack    attachments · memory_tool(scratchpad) · compaction(auto) ·
                   context_window(num_ctx + KV-quant) · chunker+filefetch (forge digest)
```
Data flow: `folder → scan(stack+MCP+repomap) → branch → plan → [per sprint: worktree →
retrieve(KB hybrid) + attachments + scratchpad → (auto-compact) → generate(local) →
diff → evaluate(local cross-family) → revise≤2 → APPROVED] → merge gate → learn`.

## Fixes applied in this audit
- F1 evaluator local routing + cloud gate (`evaluator._dispatch_eval`).
- F2 symlink-escape close (`_validate_init_path` realpath; attachments skip symlinks).
- F8/F10 README + USER_GUIDE reconciliation.
- 5 regression tests (`test_audit_2026_06_03.py`) + updated `test_evaluator.py`.

## Remediation plan (prioritized)
1. **F3 (High):** session/project-scope the scratchpad (`ctx.path` + `session_id`). ~1h.
2. **F4 (Medium):** implement `FORGE_REDACT_PROMPTS` at the prompt-egress boundary, or remove the documented option. ~30m.
3. **F11 (Low):** gate `Researcher._web_search` behind the cloud check, or mark experimental; drop `"batch"` from `_CLOUD_EXECUTORS` or add to `_EXECUTOR_MAP`. ~30m.
4. **F6/F12/F13 (Low):** chunk overlap clamp; reserve suffix in truncation; snapshot ctx setting per sprint. ~1h.
5. **F7 (Medium):** memoize MLX model loads. ~30m.
6. **F9/F15 + tooling:** correct ENGINEERING_STANDARDS paths / implement schema-parity gate; add autouse reset fixtures + `pytest-randomly` + `pytest-cov` + `pyright` to dev deps. ~2h.
7. **SWE-bench kill gate** — still unrun (the project's own go/no-go).

See `FINDINGS.md` for the sortable table.
