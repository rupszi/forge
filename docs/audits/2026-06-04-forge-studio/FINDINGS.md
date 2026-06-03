---
status: live
owner: pal.megyes
last_reviewed: 2026-06-04
---

# Findings table — 2026-06-04 audit (remediation verification)

Severity: Critical > High > Medium > Low > Info. Confidence: proven (PoC) / suspected.
Status: ✅ closed (regression test) · 🟡 noted/best-effort · ⬜ open · ⏭️ deferred.

## Prior findings (2026-06-03) — verification

| ID | Sev | Title | Prior | Now | Proof |
|---|---|---|---|---|---|
| F1 | High | Evaluator ran on cloud `claude -p` on the default path | ✅ | ✅ | PoC re-run: dispatch `{claude:0, ollama:1}` with cloud off; `test_audit_2026_06_03.py` |
| F2 | High | Symlink escape in `_validate_init_path` | ✅ | ✅ | PoC re-run: `innocent.txt→/etc/passwd` → `False`; `test_audit_2026_06_03.py` |
| F3 | High | Scratchpad not session/project-scoped | ⬜ | ✅ | `test_audit_2026_06_04.py::TestScratchpadScoping` (4) + scheduler wiring assert |
| F4 | Medium | `FORGE_REDACT_PROMPTS` dead flag | ⬜ | ✅ | `::TestPromptRedaction` (on→redacted, off→byte-identical, evaluator diff) |
| F5 | Medium | KB injection guard bypassable | ⬜ | ✅/🟡 | `::TestUntrustedContextFencing` (fence + neutralized fence-break); guard documented best-effort |
| F6 | Medium | `chunk_text` overlap exceeds `max_chars` | ⬜ | ✅ | `::TestChunkOverlapBudget` (2) |
| F7 | Medium | MLX reloads weights every call | ⬜ | ✅ | `::TestMLXWeightCache` (load-once + LRU evict) |
| F8 | Medium | README stale | ✅ | ✅ | (closed 2026-06-03) |
| F9 | Medium | ENGINEERING_STANDARDS phantom paths/scripts | 🟡 | ✅ | `scripts/check-schema-parity.py` built; `::TestSchemaParityGate` (4); doc reconciled |
| F10 | Medium | num_ctx/KV/digest undocumented | ✅ | ✅ | (closed 2026-06-03) |
| F11 | Low | Dead `Researcher` cloud call + unrouted `batch` | ⬜ | ✅ | `::TestResearcherAndBatchRouting` (3) + `test_researcher.py` gate |
| F12 | Low | Context builders overshoot byte budget | ⬜ | ✅ | `::TestByteBudgets` (3) |
| F13 | Low | `context_window` globals mutate mid-session | ⬜ | ✅ | `::TestNumCtxSnapshot` (3) |
| F14 | Low | 4 weak tests | ⬜ | ✅ | rewritten in `test_audit_fixes.py`, `test_locality.py`, `test_ws_server.py` |
| F15 | Info | Singletons not reset; no `pytest-randomly` | ⬜ | ✅ | autouse reset fixtures + deps; `::TestGlobalSingletonIsolation`; 3 seeds stable |

**All 15 prior findings are closed.** No regressions in the two previously-fixed Highs.

## New findings (this pass)

| ID | Sev | Conf | Area | File:line | Title | Status |
|---|---|---|---|---|---|---|
| N1 | Low | proven | Security/Deps | (transitive) | `idna 3.13` advisory CVE-2026-45409 (fix 3.15), pulled via httpx | ⬜ open |
| N2 | Info | proven | Quality | daemon/ (db.py, budget.py, executors, …) | **~36 pre-existing pyright errors** (Optional handling, int\|None returns, optional-dep imports) — runtime-safe (suite green); pyright made advisory + tracked (M8). Earlier "3" undercounted (scanned only touched files). | 🟡 tracked |
| N3 | Info | proven | Security | daemon/agents/generator.py | Untrusted-data fencing is best-effort; only KB content passes `kb_guard` (attachments/research rely on the fence + neutralization) | 🟡 noted |

No new High/Medium defects were introduced by the F3–F15 fixes (adversarially
verified — see REPORT.md §"New-issue hunt").
