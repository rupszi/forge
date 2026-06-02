---
status: live
owner: pal.megyes
last_reviewed: 2026-06-03
---

# Findings table — 2026-06-03 audit

Severity: Critical > High > Medium > Low > Info. Confidence: proven (PoC) / suspected.
Status: ✅ fixed · 🟡 reconciled/noted · ⬜ open.

| ID | Sev | Conf | Area | File:line | Title | Status |
|---|---|---|---|---|---|---|
| F1 | High | proven | Security/Arch | daemon/agents/evaluator.py:313 | Evaluator executed on cloud `claude -p` on the default path (G-LOC-1) | ✅ |
| F2 | High | proven | Security | daemon/ws_server.py:143 | Symlink escape in `_validate_init_path` → arbitrary file read | ✅ |
| F3 | High | proven | Correctness/Privacy | daemon/memory_tool.py:128; scheduler.py:282 | Scratchpad not session/project-scoped → cross-session/project leak | ⬜ |
| F4 | Medium | proven | Security | daemon/redact.py:36,360 | `FORGE_REDACT_PROMPTS` documented + allowlisted but never read | ⬜ |
| F5 | Medium | proven | Security | daemon/memory/kb_guard.py:17 | KB injection guard bypassable (English denylist) — best-effort only | ⬜ |
| F6 | Medium | proven | Correctness | daemon/chunker.py:62 | `chunk_text` overlap can exceed `max_chars` (latent; callers use overlap=0) | ⬜ |
| F7 | Medium | proven | Performance | daemon/executors/mlx.py:60 | MLX reloads model weights every call (no cache) | ⬜ |
| F8 | Medium | proven | Docs | README.md:7,144,231 | Stale model names, 3 conflicting test counts, 2 phantom CLI verbs | ✅ |
| F9 | Medium | proven | Docs | docs/ENGINEERING_STANDARDS.md:62,101,941 | References `src/forge/`, `schemas/`, schema-parity/sync-version scripts that don't exist | 🟡 |
| F10 | Medium | proven | Docs | docs/USER_GUIDE.md §7.5 | num_ctx presets, KV-quant, `forge digest` undocumented | ✅ |
| F11 | Low | proven | Quality | daemon/agents/researcher.py:45; routing.py:23 | Dead `Researcher` (unconditional cloud call) + unrouted `"batch"` string | ⬜ |
| F12 | Low | proven | Quality | daemon/compaction.py:34; attachments.py:62; memory_tool.py:106 | Context builders overshoot byte budget by suffix length | ⬜ |
| F13 | Low | suspected | Quality | daemon/context_window.py:57 | Live mid-session mutation of global ctx/kv settings (no per-sprint snapshot) | ⬜ |
| F14 | Low | proven | Tests | test_audit_fixes.py:44; test_locality.py:44; test_ws_server.py:107,113 | 4 genuinely weak tests | ⬜ |
| F15 | Info | proven | Tests | tests/conftest.py; attachments.py:90 | Singleton/global not reset between tests; `FORGE_DIR` relative leak; no `pytest-randomly` | ⬜ |
