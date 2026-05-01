# Forge — Three-Round Code Review Synthesis

**Date**: 2026-05-01
**Reviewers**: 3 parallel review agents covering functionality, code quality, and security
**Source notes**: [06-review-r1-functionality.md](research/notes/06-review-r1-functionality.md) · [07-review-r2-code-quality.md](research/notes/07-review-r2-code-quality.md) · [08-review-r3-security.md](research/notes/08-review-r3-security.md)

---

## Executive summary

**No critical blockers**. The codebase is structurally sound, security-hardened for its stated threat model, and architecturally consistent. But there are **3 real bugs in scheduler integration** that silently break documented contracts, **3 high-severity production-readiness gaps** that should be closed before any public launch, **5 overengineered areas** that will hurt maintainability if left in, and **9 missing redaction patterns** that leave specific credential shapes unscrubbed.

Total fix effort: **~22 hours** across all three categories. The breakdown:

| Category | Effort | Issues |
|---|---|---|
| **P0 — functional bugs** (silently violate contracts) | ~3 hours | 3 |
| **P0 — security must-fix-for-launch** | ~7 hours | 3 |
| **P1 — production readiness** | ~5 hours | 4 |
| **P1 — overengineering / cleanup** | ~5 hours | 5 |
| **P2 — polish + tests** | ~2 hours | several |

**Status**: ship `v0.1.0` after the P0 fixes (~10 hours). The P1 / P2 items can land in `v0.1.x` patch releases.

---

## Cross-cutting findings (issues seen in multiple rounds)

These appeared in two or more reviews — meaning they're either important enough that two independent passes caught them, or they straddle the artificial round boundaries. Fix these first.

### CC-1 — Episodic store hardcodes agent type via model-name string match
**Round 1 BUG-3** (functional) + **Round 2 minor violation** (architecture)
**File**: `daemon/memory/episodic.py:27`

```python
agent_type="claude_code" if sprint.assigned_model in ("opus", "sonnet") else "ollama"
```

Misses `"haiku"` and any non-default Claude model (`claude-sonnet-4-7`, `opus-4.6`). Diverges from `classifier.select_executor()` which already handles this correctly via `model_family()`. Result: Haiku-tagged episodes are mislabeled as `"ollama"`, poisoning procedural memory training data.

**Fix**: replace with `select_executor(sprint.assigned_model)`. ~5 lines.

---

### CC-2 — Redaction catalog: simultaneously over-engineered AND incomplete
**Round 2** (overengineering) + **Round 3** (security gaps)
**File**: `daemon/redact.py`

Two complaints from different angles:

- **Over-engineered**: `_AUTH_BEARER_LOOSE` is a 2-alternation regex with lookbehind; the env-line negative lookahead `(?!\[REDACTED)` is a band-aid for rule-ordering issues; 14 rules with overlapping intent.
- **Incomplete**: missing 9 well-known credential shapes (Vercel, Cloudflare, npm, Hugging Face, SendGrid, Mailgun, Twilio, Discord, Telegram bot tokens). Gitleaks v8.20+ has all of these.

**Fix**: simplify the existing rules (drop `_AUTH_BEARER_LOOSE`, fix rule ordering to remove the lookahead) AND add the 9 missing patterns. ~3 hours total. The two changes net out near-LOC-neutral.

---

### CC-3 — Concurrency holes at every parallelism boundary
**Round 1 CONCURRENCY-1+2** (race conditions) + **Round 3 #7** (no semaphore on WS)
**Files**: `daemon/worktree.py:57–60`, `daemon/scheduler.py:380–407`, `daemon/ws_server.py:96–115`

Three independent concurrency issues:
1. Worktree creation has a TOCTOU race on `os.path.exists()` → duplicate entries in `_active_worktrees`.
2. Budget downgrade decisions are sequential, but the actual spends happen in parallel — the system can over-spend or over-downgrade.
3. WebSocket has no per-client or global handler semaphore — a misbehaving MCP client could spawn 100s of concurrent searches.

**Fix**: lock-protect `_active_worktrees`, move budget enforcement *into* `execute_sprint()` with a budget lock, add `Semaphore(10)` on WebSocket message handling. ~2 hours total.

---

## Top 15 issues — prioritized

### P0 — Must fix before launch (silently broken or critical security)

#### 1. ADaPT recovery doesn't write back to procedural or episodic memory
**Round 1 BUG-1 + BUG-2** · `daemon/scheduler.py:305–307`
When ADaPT recovery flips a sprint from "failed" to "completed", neither `_writeback_procedural()` nor `episodic.store()` fires. The procedural memory never learns from successful recovery; the learner is blind to recovery wins. **Violates the documented contract** in the scheduler docstring ("Procedural memory writeback after every evaluator verdict"). **Fix**: 5 lines after line 305. **Effort**: 30 min.

#### 2. WebSocket DoS — no rate limit, no message-size cap, no path validation
**Round 3 #1 + #5** · `daemon/ws_server.py:23–93`
A misbehaving 127.0.0.1 client (a buggy UI tab, a hostile MCP server, a future cross-machine exposure if the bind ever changes) can OOM the daemon with `{"query": "x" * 10_000_000}` or trigger path-traversal scans via `{"path": "../../etc"}`. Three sub-fixes: per-client rate limiter (10 msg/sec sliding window), 1 MB message cap, normalize+validate `path` against project root. **Effort**: 2h.

#### 3. Database connection has no shutdown discipline
**Round 3 #2** · `daemon/db.py:117–125`
`ForgeDB.__init__` opens a SQLite connection but the only close path is an explicit `db.close()` call. SIGKILL or unhandled exception → WAL journal in inconsistent state → next session may hit "database is locked". **Fix**: add `__del__` + `atexit.register(self.close)` in `__init__`. ~10 lines. **Effort**: 1h.

#### 4. Redaction catalog missing 9 high-traffic credential patterns
**Round 3 #3** · `daemon/redact.py:62–200`
Vercel, Cloudflare, npm, Hugging Face, SendGrid, Mailgun, Twilio, Discord bot, Telegram bot. All in gitleaks default. **Fix**: add 9 `_Rule()` entries; cross-reference gitleaks v8.20+. **Effort**: 2h including tests.

#### 5. No graceful shutdown on SIGTERM
**Round 3 #6** · `daemon/cli.py` + `daemon/ws_server.py:110–115`
Kubernetes eviction / systemd stop / `kill <pid>` orphans pending `ws.send()` futures, kills connections without close frames, may lose in-flight DB transactions and trace events. **Fix**: register asyncio signal handler in `cmd_serve`; close clients with code=1001; await server.wait_closed(); flush DB. **Effort**: 1.5h.

#### 6. Episodic store agent-type misclassification (CC-1 above)
**Effort**: 30 min.

---

### P1 — Should fix soon (production readiness, correctness gaps)

#### 7. Safety command catalog missing cloud-destructive ops
**Round 3 #4** · `daemon/safety.py:64–161`
Missing: `aws s3 rb --force`, `aws s3 rm --recursive`, `gh repo delete`, `kubectl delete namespace --all`, `terraform destroy`, `docker system prune -af`, `chmod -R 000`, `mkfs.*`. **Fix**: add 7 `DestructiveOp` entries. **Effort**: 1h.

#### 8. Worktree creation race condition
**Round 1 CONCURRENCY-1** · `daemon/worktree.py:57–60`
TOCTOU between `os.path.exists()` and `_active_worktrees.append()`. Switch the global from `list` → `set`, lock-protect the create path. **Effort**: 30 min.

#### 9. Budget enforcement is not atomic across parallel waves
**Round 1 CONCURRENCY-2** · `daemon/scheduler.py:380–407`
Sequential downgrade decisions before parallel execution → over-spend possible. Move budget enforcement *into* `execute_sprint()` with a `BudgetController` lock; reject (don't downgrade after the fact) when `can_afford()` returns False mid-wave. **Effort**: 1h.

#### 10. WebSocket has no concurrency semaphore
**Round 3 #7** · `daemon/ws_server.py:96–115`
Add `_message_semaphore = asyncio.Semaphore(10)` and wrap `_handle_message`. **Effort**: 30 min.

#### 11. Cross-family evaluator invariant has no runtime assertion
**Round 1 INTEGRATION-1** · `daemon/agents/evaluator.py:269` + `classifier.py:pick_evaluator_model()`
The invariant ("evaluator family ≠ generator family") is documented in ADR-006 but there's no `assert` at the wire that catches an accidental refactor that hardcodes `eval_model="sonnet"`. **Fix**: 1-line assert in `evaluate()`. **Effort**: 5 min.

#### 12. Phantom `tree-sitter` dependency
**Round 2 #2.7** · `pyproject.toml:41–42`
`forge[repomap]` lists `tree-sitter` + `tree-sitter-languages` (~30MB of binary wheels), but `daemon/scanner/repomap.py` uses **only** regex extraction — never imports tree-sitter. Users opting into the extras get bloat for code that doesn't run. **Fix**: delete the deps from the `repomap` extra (keep the extra empty as a forward-compatible placeholder, or delete it entirely). **Effort**: 5 min.

---

### P1 — Overengineering / refactor opportunities

#### 13. Executor duplication: `openai_compatible.py` and `ollama.py` share 60%+ shape
**Round 2 #1.1** · `daemon/executors/`
Both files implement the same shape: parse env, build body, POST, parse response, handle tool_calls, return `ExecutionResult`. ~250 LOC each, 60%+ shared. **Fix**: extract `daemon/executors/_http_base.py` with `http_chat_execute(..., build_body_fn, extract_response_fn)`. Net **−40 LOC**, plus the next HTTP executor (Anthropic batch, Together, etc.) costs +50 instead of +200 LOC. **Effort**: 6–8h, but big payoff.

#### 14. Redaction over-engineering (CC-2 above)
Drop `_AUTH_BEARER_LOOSE`. Reorder rules so capturing-group rules come first; remove the env-line `(?!\[REDACTED)` lookahead — it's solving a problem caused by bad rule ordering, not a real ambiguity. Result: simpler regex catalog, fewer false positives, the same security floor. **Effort**: 1h.

#### 15. Recovery's two isomorphic dataclasses + `is_critical()` string-prefix hack
**Round 2 #1.3 + comment-quality #2** · `daemon/recovery.py`
- `DecompositionResult` and `SelfConsistencyResult` solve the same shape (run N attempts, pick winner, record verdict). Extract `AttemptResult` base. **Effort**: 2h.
- `is_critical(sprint)` checks if description starts with `[critical]` — too cute. Add a real `critical: bool` field to `SprintContract` (one-line dataclass change). **Effort**: 30 min.

---

### P2 — Polish, tests, comments

#### Tests that monkeypatch `append_event` instead of asserting on it
**Round 2 #4.1** · `tests/test_recovery.py:101, 127, 147`
The tests verify the algorithm but never assert that the right trace events were emitted. Replace `monkeypatch.setattr(... lambda *a, **kw: None)` with a capture function that appends events to a list, then assert the list. **Effort**: 30 min.

#### Missing test coverage
- ADaPT integration in scheduler (R1 UNTESTED-1) — 20 LOC test
- Self-Consistency early-exit budget accounting (R1 UNTESTED-2) — 15 LOC test
- ReDoS adversarial inputs against redact.py (R3 test gap) — 10 LOC test
- Path-traversal attempts against `replay._trace_path` and `worktree.create` (R3) — 15 LOC test

**Effort**: 1.5h total.

#### Type-hint hygiene
**Round 2 #1.6** · multiple files
- `db.py` returns bare `dict` — should be `dict[str, int]` etc.
- `episodic.py` `eval_result = None` should be `EvaluatorResult | None = None`
- `models.py` `to_dict()` methods should declare TypedDict
**Effort**: 1.5h.

#### Move `tmp_forge_dir` to `tests/conftest.py`
**Round 2 #2.2** · 3 test files duplicate the fixture. **Effort**: 15 min.

#### Comments to delete (say-what-not-why)
**Round 2 comment quality** · scheduler.py:176, redact.py:220, recovery.py:165, parsing.py:184. ~10 lines of noise to remove. **Effort**: 10 min.

---

## What's NOT broken (positives — for balance)

The reviews surfaced what was missing, but these things are explicitly **good** and should not be touched:

- ✅ **No critical security holes.** Subprocess hardening (no `shell=True`), env allowlist, parameterized SQL, hardcoded localhost binding, redact-at-every-boundary all hold.
- ✅ **No circular imports.** Module graph is clean. The one duplication (generator's `_select_executor` vs classifier's `select_executor`) is an *intentional* trade-off to avoid a cycle.
- ✅ **No module boundary violations.** Memory, agents, executors, scheduler each own their concerns cleanly.
- ✅ **The Memory module architecture is good.** Episodic / procedural / research / retriever / learner are properly separated.
- ✅ **Comments in `recovery.py` are exemplary.** Per Round 2: "explains both mechanisms, references papers, and justifies every design choice."
- ✅ **License compatibility is clean.** All deps are MIT/Apache/BSD; Forge is MIT.
- ✅ **`uv.lock` committed.** Reproducible builds.
- ✅ **Async patterns mostly sound.** No `time.sleep` in async, no blocking httpx, proper `await proc.communicate()`. The remaining concurrency holes are about coordination primitives, not async correctness.
- ✅ **Test foundation is strong.** 588 passing in 1.36s. The gaps identified are about coverage of *new* integration paths, not broken existing tests.
- ✅ **Documentation discipline is real.** ADRs locked, CHANGELOG up to date, every new module has a top-of-file docstring explaining the why.

---

## Cross-cutting recommendations

### A. Stop adding regex rules; cross-reference gitleaks instead
The redaction catalog will keep growing forever if every new credential shape requires a hand-written rule. **Adopt a quarterly sync** with gitleaks v8.20+ default rule set. Either:
1. Write a small script that fetches gitleaks rules and generates `_Rule()` entries (best long-term).
2. Manually audit gitleaks every quarter and add missed patterns (acceptable v0.1).

Fix all 9 known gaps now (P0 #4); set a calendar reminder for the next sync.

### B. Establish an event-type registry
**Round 2 #3.3**: event names like `"worktree.created"`, `"sprint.attempt"`, `"recovery.consistency.start"` are scattered as string literals through `scheduler.py`. Add `daemon/events.py`:

```python
class EventType(StrEnum):
    WORKTREE_CREATED = "worktree.created"
    SPRINT_ATTEMPT = "sprint.attempt"
    SPRINT_EVALUATED = "sprint.evaluated"
    SPRINT_APPROVED = "sprint.approved"
    SPRINT_REVISING = "sprint.revising"
    RECOVERY_ADAPT_START = "recovery.adapt.start"
    RECOVERY_ADAPT_COMPLETE = "recovery.adapt.complete"
    RECOVERY_CONSISTENCY_START = "recovery.consistency.start"
    RECOVERY_CONSISTENCY_COMPLETE = "recovery.consistency.complete"
    BUDGET_DOWNGRADE = "budget.downgrade"
    SESSION_START = "session.start"
    SESSION_COMPLETE = "session.complete"
    # ...
```

Catches typos at import time. Makes UI-side event handling discoverable. Documents the protocol. **Effort**: 4–5h including updating call sites and adding to `docs/`.

### C. Tighten the "documented contract vs. actual code" loop
Two contracts in current docs are subtly false:
- *"Trace events at every phase transition"* — yes, except `sprint.recovered` doesn't exist when ADaPT flips status (R1 DOCSTRING-1)
- *"Procedural memory writeback after every evaluator verdict"* — no, missing on ADaPT recovery success (R1 BUG-1)

**Fix the code, not the docs.** Add `_emit("sprint.recovered", ...)`. Add the `_writeback_procedural()` call. The docs are aspirationally correct; make the code match.

### D. Add a SECURITY.md quarterly review checkbox
Things that drift over 90 days even if nothing else changes:
- Gitleaks rule catalog (new credential providers ship)
- Safety command catalog (new dangerous CLI subcommands)
- Dependency advisories (`pip-audit` may surface late-disclosed CVEs)
- WebSocket / IDE protocol versions

Add to `SECURITY.md`: *"Quarterly review (Mar/Jun/Sep/Dec): re-sync `daemon/redact.py` against gitleaks default rules; re-audit `daemon/safety.py` for new cloud CLIs; run `pip-audit --strict`; bump dep floors."*

### E. The two `select_executor` functions
**Round 1 INTEGRATION-2**: `generator._select_executor()` and `classifier.select_executor()` have very similar logic. Currently this duplication is *intentional* to avoid a circular import. Audit: is the cycle real? If we move `select_executor` to a leaf module like `daemon/routing.py`, both can import it. **Effort**: 1h. **Benefit**: removes a known divergence risk.

---

## Action plan (in priority order with effort estimates)

### Sprint 1 — pre-launch P0 (~10 hours)

| # | Task | Effort | Source |
|---|---|---|---|
| 1 | ADaPT writeback to procedural + episodic | 30m | R1 BUG-1+2 |
| 2 | DB connection __del__ + atexit | 1h | R3 #2 |
| 3 | WebSocket rate limit + size cap + path validation | 2h | R3 #1+#5 |
| 4 | Redaction catalog +9 patterns | 2h | R3 #3 |
| 5 | Graceful shutdown on SIGTERM | 1.5h | R3 #6 |
| 6 | Safety catalog +7 cloud commands | 1h | R3 #4 |
| 7 | EpisodicStore agent-type fix (CC-1) | 30m | R1 BUG-3 |
| 8 | Cross-family evaluator runtime assertion | 5m | R1 INT-1 |
| 9 | Delete tree-sitter phantom dep | 5m | R2 #2.7 |
| 10 | Drop AUTH_BEARER_LOOSE; reorder redact rules | 1h | R2 #1.1 |
| 11 | Tests for above (parametrize new patterns; rate-limit; shutdown) | 1.5h | — |

### Sprint 2 — reliability + concurrency (~5 hours)

| # | Task | Effort | Source |
|---|---|---|---|
| 12 | Worktree creation lock + set-based tracking | 30m | R1 CONC-1 |
| 13 | Budget enforcement inside execute_sprint with lock | 1h | R1 CONC-2 |
| 14 | WS message handler semaphore | 30m | R3 #7 |
| 15 | Subprocess.kill on timeout in claude_code | 30m | R3 lifecycle |
| 16 | tmp_forge_dir → conftest.py | 15m | R2 #2.2 |
| 17 | Unify `_select_executor` between generator + classifier | 1h | R1 INT-2 |
| 18 | EventType StrEnum registry + replace string literals | 1.5h | R2 #3.3 |

### Sprint 3 — overengineering cleanup (~6 hours)

| # | Task | Effort | Source |
|---|---|---|---|
| 19 | Extract HTTPExecutor base class (ollama + openai_compatible) | 6h | R2 #1.1 |
| 20 | `is_critical()` string-prefix → `critical: bool` field on SprintContract | 30m | R2 comment-#2 |
| 21 | AttemptResult base class for recovery | 2h | R2 #1.3 |
| 22 | Type-hint cleanup (bare dict / Optional / TypedDict) | 1.5h | R2 #1.6 |

### Continuous — polish + docs

- Comments to delete (~10 min)
- Test event-emission assertions (~30 min)
- Adversarial-input tests (ReDoS, Unicode tricks, path traversal) (~1h)
- Add quarterly review checkbox to SECURITY.md (~5 min)

---

## Final word

Forge is in **shipping shape modulo the 10-hour P0 sprint**. The bugs found in R1 are real but narrow — none of them produce wrong code or wrong evaluator verdicts; they cause silent gaps in *learning loops* (procedural / episodic memory) that take dozens of sessions to manifest. The security findings in R3 are real production-readiness gaps — none are zero-day exploits, but all are the kind of "we should have caught this in v0.1.0 review" items that bite at scale. The R2 quality issues are low-stakes refactor work that won't bite until the codebase grows another 2x.

Ship `v0.1.0` after Sprint 1. Land Sprint 2+3 across `v0.1.x` patch releases as they fit in available bandwidth.

---

*Living document. Re-run a 3-round review at `v0.2.0` and again at `v1.0.0`. Append findings; never delete.*
