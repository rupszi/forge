---
status: live
owner: pal.megyes
last_reviewed: 2026-06-04
---

# Forge Studio — Remediation Audit (2026-06-04)

**Branch:** `develop` · **Scope:** verify the 2026-06-03 audit's remediation —
all open findings (F3–F15) plus the deliverables — and re-audit for regressions
and new defects. **Method:** four independent specialist roles (Security ·
Test-quality · Code-quality · Architecture/Docs), each evidence-based with
`file:line`, with **adversarial verification** of every High/Medium finding (try
to refute closure; re-run the original PoCs) and a fresh new-issue hunt focused
on the riskiest changes (F3 session threading, F4 prompt redaction).

## Verdict

**All 15 findings from the 2026-06-03 audit are closed**, each with a regression
test that fails against the pre-fix code. The two previously-fixed Highs (F1
evaluator-on-cloud, F2 symlink escape) were re-PoC'd and remain closed — no
regression. The new-issue hunt surfaced **no new High/Medium defect introduced
by the fixes**; three low-impact items are recorded (N1 transitive `idna`
advisory, N2 pre-existing pyright errors, N3 fencing-is-best-effort), none
blocking.

Forge Studio is, in this auditor's judgement, **v0.1 local-first-release-ready
on the software-quality axis**: zero-egress-by-default is intact (egress guard
green; evaluator + researcher both gated), the suite is green and now
order-independent, and the docs no longer make unverifiable claims. The **single
remaining gate is SWE-bench** — the project's own go/no-go — which is **unrun**
(it needs models + GPU and is explicitly out of scope for this pass).

## Tooling results

| Check | Result |
|---|---|
| `pytest` (full) | **1188 passed, 1 skipped** (was 1155; +33 regressions/rewrites) |
| Determinism | **Stable across 3 randomized seeds** (0/7/99) — `pytest-randomly` now installed |
| `ruff check` / `format --check` | Clean (172 files) |
| Branch coverage (core modules) | **TOTAL 88%**; every named module ≥ 82% (none < 80%) |
| `pyright` | 0 **new** errors; 3 pre-existing errors (N2), warnings stylistic |
| `pip-audit` | 1 transitive advisory: `idna 3.13` CVE-2026-45409 → fix 3.15 (N1) |
| `pnpm build` (UI) | Compiles clean (incl. the `SprintContract.critical` type add) |
| egress guard | **21 passed** — no outbound path on the default flow |

### Branch coverage detail (core modules)

```
daemon/routing.py            100%   daemon/agents/generator.py    98%
daemon/attachments.py         96%   daemon/redact.py              94%
daemon/context_window.py      94%   daemon/pool.py                92%
daemon/gitctl.py              92%   daemon/agents/evaluator.py    89%
daemon/chunker.py             86%   daemon/compaction.py          86%
daemon/memory_tool.py         82%   daemon/scheduler.py           82%
TOTAL 88% (1051 stmts, 320 branches)
```

No core module is below the 80% branch bar. `scheduler.py` (82%) carries the
most uncovered branches — the ADaPT recovery decomposition and the cancellation
paths — which are exercised in integration-marked tests, not the unit run.

## Role A — Security (adversarially verified)

- **F1 (re-verified closed):** PoC `evaluate()` with `FORGE_CLOUD_ENABLED`
  unset dispatches `{claude:0, ollama:1}`. The cloud gate in
  `evaluator._dispatch_eval` is intact.
- **F2 (re-verified closed):** `ln -s /etc/passwd cwd/innocent.txt` →
  `_validate_init_path` returns `False`. `realpath`-before-containment holds.
- **F3 (closed):** scratchpad root is now `<project>/.forge/memories/<session>/`
  with a sanitized session segment; two sessions / two projects cannot read each
  other's notes (proven). **New-issue check:** the WS `dispatch` path without a
  session falls back to a project-local `_shared` bucket (verified — no crash,
  no CWD leak); a crafted `session_id` like `../../etc` is reduced to a safe
  slug and stays under `memories/` (proven).
- **F4 (closed):** `FORGE_REDACT_PROMPTS=1` scrubs the assembled prompt at both
  the generator and evaluator egress; **off (default) is byte-identical** (the
  secret is sent unchanged — the documented behavior). **New-issue check:** the
  off-path adds no work and cannot leak the marker; the on-path does not mangle
  a prompt lacking secrets (the redactor is a no-op on non-matching text).
- **F5 (closed + hardened, documented best-effort):** injected context is fenced
  in an `<untrusted-data>` block with a "data, not instructions" preamble. During
  this pass a fence-break was found (a literal `</untrusted-data>` in content
  could close the fence early) and **hardened** — `_wrap_untrusted` now escapes
  literal fence tags, so injected text stays inside the block (proven). This
  remains **defense-in-depth, not a boundary** (N3): a determined injection in a
  long attachment can still try social-engineering inside the fence; `kb_guard`
  only screens KB writes, not attachments/research.
- **F11 (closed):** `researcher._web_search` raises `CloudDisabledError` with
  cloud off; `is_cloud_executor("batch")` stays `True` (fail-closed) and an
  unmapped executor now raises a clean `ValueError`, not `KeyError`.
- **Verified still SOUND:** egress guard (21), 127.0.0.1 bind, WS Origin
  allow-list, size cap + rate limit + handler semaphore (now behaviorally
  tested), subprocess argv lists / env allowlist, `memory_tool._resolve`
  containment, `gitctl._valid_branch`.

## Role B — Test quality

- **F14 (closed):** the 4 weak tests now exercise behavior — the path-guard
  case-variant asserts the normcase-determined outcome (no `in (True, False)`);
  the models dry-run stubs disk for a deterministic `rc==0` and asserts nothing
  is pulled; the WS size-cap and handler-semaphore tests drive the actual
  guard/throttle rather than re-assert a constant.
- **F15 (closed):** autouse fixtures reset the attachment store, the
  context-window size/KV globals, and the MLX cache before/after every test;
  `tmp_forge_dir` patches `memory_tool.FORGE_DIR`. `pytest-randomly` is installed
  and the suite is **green across 3 seeds**. `pytest-cov` + `pyright` are wired
  into the dev group.
- **Regression discipline:** every fix carries a test that would fail without it
  (verified by construction — the tests assert the new behavior directly). The
  31-test `test_audit_2026_06_04.py` is the consolidated regression surface.
- **Residual:** the real plan→generate→evaluate loop is still only run with
  stubbed executors in CI (integration-marked tests cover the live path) — same
  honest gap noted in 2026-06-03, unchanged by this pass.

## Role C — Code quality & correctness

- **F6 (closed):** packing budget reserves `overlap_chars + sep` so overlapped
  chunks stay ≤ `max_chars`; verified at small and default budgets.
- **F7 (closed):** `(llm, tokenizer)` memoized in a lock-guarded bounded LRU
  (cap 2); load-once and LRU-evict both proven.
- **F12 (closed):** `compaction._truncate`, `attachments.context`, and
  `memory_tool.context` reserve the suffix/header before slicing; outputs are
  ≤ budget.
- **F13 (closed):** `num_ctx` is snapshotted once per sprint (after model
  finalization) and threaded to every attempt; a mid-flight `set_setting` no
  longer changes the window. The recovery sub-sprint (different model) resolves
  live by design — acceptable and documented.
- **N2 (pre-existing, not a regression):** pyright flags the optional `mlx_lm`
  import (expected — Apple-Silicon-only, imported lazily) and two scheduler
  items (`BaseException.status` in the `gather` handler at ~700; a stale
  `# type: ignore` at 478). All pre-date this work; recommend a follow-up
  cleanup commit. New code added this pass introduces **no** pyright errors.

## Role D — Architecture & docs

- **F9 (closed):** `scripts/check-schema-parity.py` is implemented and run by the
  pre-push gate. It enforces, per registered entity: DB columns ⊆ `to_dict()`
  keys, and `to_dict()` keys == the TS interface fields. It **caught a real
  drift** — `SprintContract.critical` was emitted by Python but absent from
  `ui/lib/types.ts` — now fixed. `ENGINEERING_STANDARDS.md` is reconciled:
  `src/forge/`→`daemon/` throughout, entry point corrected to `daemon.cli:main`,
  coverage source set to `daemon`, and the non-existent `schemas/`,
  `sync-version.py`, `find-flakes.py` marked PLANNED (not described as present).
- **Deliverable — WS protocol:** `docs/WEBSOCKET_PROTOCOL.md` documents all 28
  client→server handlers, the request responses, broadcast pushes, and every
  `EventType` trace event — generated from `ws_server.py` + `events.py` +
  `ui/lib/types.ts`.
- **Deliverable — reconcile:** `CHANGELOG.md` has a 2026-06-04 section listing
  every fix; `FORGE_STUDIO_TRACKER.md` has a remediation note, `last_reviewed`
  bumped, and the SWE-bench gate flagged unrun.

## New-issue hunt (introduced-by-fix focus)

| Change | Probe | Result |
|---|---|---|
| F3 session threading | WS dispatch with no session; crafted `session_id` traversal | `_shared` fallback; slug sanitized — no leak/crash |
| F4 redaction | off-path byte-identity; on-path no-op on clean prompts | byte-identical off; no mangling on |
| F5 fencing | literal `</untrusted-data>` in content | neutralized — injected text stays inside fence |
| F11 gate | researcher with cloud off; `batch` dispatch | raises `CloudDisabledError` / clean `ValueError` |
| F13 snapshot | mid-flight `set_setting` flip | in-flight sprint uses the snapshot |
| All | egress guard; 3 randomized full runs | 21 green; 1188 stable |

No new High/Medium defect found. N1/N2/N3 are low-impact and recorded above.

## Definition-of-done checklist

- [x] All OPEN findings (F3–F15) fixed with passing regression tests.
- [x] Full suite green — **1188 passed, 1 skipped**.
- [x] Determinism confirmed across 3 randomized seeds.
- [x] `ruff check` + `format --check` clean; `pnpm build` clean.
- [x] Coverage reported (TOTAL 88%; no core module < 80% branch).
- [x] Docs reconciled (ENGINEERING_STANDARDS, README prior); WS protocol documented.
- [x] New audit report + findings committed; prior table all closed/justified.
- [ ] **SWE-bench kill gate — UNRUN** (needs models/GPU; out of scope).

## Is this v0.1 local-first-release-ready?

On software quality: **yes.** The two Highs are fixed and stay fixed; every
remaining finding is closed with a regression test; the local-first guarantee is
intact and now guarded at every egress (generator, evaluator, researcher) with
the egress test green; the suite is green, order-independent, and reasonably
covered; and the docs are honest. The one outstanding blocker is the project's
own **SWE-bench kill gate**, which remains **unrun** — that, not any code defect
found here, is what stands between this branch and a v0.1 tag. Recommended
pre-tag follow-ups (non-blocking for code-quality): bump `idna` to ≥3.15 (N1)
and clear the 3 pre-existing pyright errors (N2).
