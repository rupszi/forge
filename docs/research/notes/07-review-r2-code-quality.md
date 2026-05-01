# Round 2 Code Quality Review: Architecture, Overengineering, and Duplication

**Date:** 2026-04-30
**Scope:** daemon/ and tests/ code quality review
**Outcome:** 14 significant issues identified; 5 recommend immediate action

---

## Executive Summary

The codebase demonstrates solid architectural intent (clear module boundaries, sensible separation of concerns) but has accumulated unnecessary complexity in three areas:

1. **Redaction rules catalog** — 14 rules with overlapping intent and an error-prone ordering dependency
2. **Parsing layer** — redundant fixers that could compose more efficiently
3. **Executor duplication** — openai_compatible and ollama share 60%+ of their shapes without shared abstraction
4. **Recovery abstractions** — two dataclasses (DecompositionResult, SelfConsistencyResult) solving isomorphic problems
5. **Type-hint erosion** — dict/list without parameterization, Optional where None shouldn't be legitimate

The code is **maintainable as-is** but **will become a liability** when the next model lineup shift arrives or when users request custom routing logic.

---

## Overengineered Areas (Delete or Simplify)

### 1. Redaction Rule Catalog (daemon/redact.py)

**Location:** Lines 62–200; 14 `_Rule` objects

**Why it's over-engineered:**

- The `_AUTH_BEARER_LOOSE` pattern (lines 134–140) is a band-aid over a fundamental architectural choice — matching "any Bearer token that looks token-ish" requires a complex regex with two alternations and lookahead logic that's hard to read and harder to maintain.
- The env-line rule's negative lookahead `(?!\[REDACTED)` (line 156) is a **code smell**: it's working around rule ordering instead of solving ordering properly. If a rule already matched and redacted something, the output no longer contains the secret — there's no need for lookahead.
- Four rules capture subgroups (AWS_SECRET, AUTH_BEARER, AUTH_BEARER_LOOSE, DB_URL_CREDS, ENV_LINE) but the pattern is inconsistent — some use `m.group(1)`, others replace entire matches. The lambda in line 228–229 handles both, but the inconsistency invites bugs.
- The PEM key rule (lines 161–166) is correct but rare in practice — most Forge users won't hit this, and when they do it's because something went very wrong (committed a key file). The rule is defensible but adds bulk.

**Simpler alternative:**

- Drop AUTH_BEARER_LOOSE entirely. It's too noisy and catches valid prose. A user who wants to redact Bearer tokens should explicitly log them or use FORGE_REDACT_PROMPTS=1.
- Reorder rules so ALL capturing-group rules come before non-capturing-group rules. Remove the negative lookahead entirely; if something is already redacted, it won't match any pattern again (redaction markers like `[REDACTED:X]` don't match credential shapes).
- Consolidate AWS_SECRET + AWS_KEY_ID into a single rule that matches the full `aws_secret_access_key=<secret>` line without sub-capture — replace the entire match.
- Inline PEM_KEY as a fallback/optional feature; don't check it by default.

**Estimated impact:** -40 LOC, -2 regex patterns, removes one class of ordering bugs.

**Cost:** Low. The public API (redact, contains_secret) doesn't change. Tests would need 2–3 updates.

---

### 2. The Parsing Layer (daemon/parsing.py)

**Location:** Lines 154–224 (parse_json_lenient)

**Why it's over-engineered:**

The "recovery ladder" (steps 1–5) is conceptually sound, but the implementation is inefficient:

- Strip markdown fences (step 2), then extract brackets (step 3). But step 4 applies fixers to step 3's output. If step 3 finds nothing, step 4 applies fixers to the fenced output. The state management is correct but hidden.
- The common-case fixers (smart quotes, trailing commas, comments) are pure functions that compose, but they're called in a fixed order on a single target. There's no need to re-extract candidates if step 2 already failed.
- The `schema_hint` parameter exists only to control bracket extraction (array vs object). It could be simpler: try both, pick the one that parses.

**Simpler alternative:**

```python
def parse_json_lenient(text: str) -> Any | None:
    # 1. Try as-is
    if v := _try_parse(text): return v

    # 2. Try after fence strip
    if v := _try_parse(strip_markdown_fences(text)): return v

    # 3. Try after bracket extraction + fixer ladder
    for opener, closer in ("[", "]"), ("{", "}"):
        if bracket := extract_first_balanced(text, opener=opener, closer=closer):
            if v := _try_parse_with_fixers(bracket): return v

    return None

def _try_parse(s: str) -> Any | None:
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None

def _try_parse_with_fixers(s: str) -> Any | None:
    s = fix_smart_quotes(fix_json_comments(s))
    s = fix_trailing_commas(s)
    return _try_parse(s)
```

This removes the `schema_hint` parameter, eliminates the manual candidate ordering, and makes the ladder explicit.

**Estimated impact:** -30 LOC, simpler logic flow, same behavior.

**Cost:** Low. One public API change (drop schema_hint; it's rarely used). BAML integration stub is unaffected.

---

### 3. Recovery: Two Isomorphic Dataclasses

**Location:** daemon/recovery.py, lines 46–59 and 201–220

**Why it's over-engineered:**

`DecompositionResult` and `SelfConsistencyResult` solve the same problem (record attempts + pick a winner) with slightly different field names and semantics:

| Aspect | Decomposition | SelfConsistency |
|--------|---|---|
| Attempts stored | `sub_results: list[ExecutionResult]` | `attempts: list[tuple[ExecutionResult, EvaluatorResult]]` |
| Winner index | implicit (tracked in parent sprint) | `winner_index: int` |
| Verdict field | `final_verdict: str` (PASS/PARTIAL/FAIL) | `final_verdict: str` (APPROVED/REVISE) |
| Accessor | `.all_passed` property | `.winner` property |

The types are slightly different (ExecutionResult only vs. paired results), but both are tracking "run N attempts, pick the best, report the outcome." The verdict enum is also different (3 states vs. 2 states), which is legitimate, but the structure could be shared.

**Simpler alternative:**

Create a generic `AttemptResult` dataclass:

```python
@dataclass
class AttemptResult:
    """Generic: N attempts, pick the winner, report verdict."""
    parent_id: str
    attempts: list[Any]  # Either ExecutionResult or (ExecutionResult, EvaluatorResult)
    winner_index: int = -1
    final_verdict: str = ""

    @property
    def winner(self):
        if 0 <= self.winner_index < len(self.attempts):
            return self.attempts[self.winner_index]
        return None
```

Then specialize as needed (rename fields in DecompositionResult, keep SelfConsistencyResult as-is but inherit from AttemptResult).

**Estimated impact:** -15 LOC, one less dataclass, shared winner/verdict logic.

**Cost:** Medium. Both recovery.py and tests/test_recovery.py need updates. No public API change (same names after migration).

---

### 4. The Scheduler's \_emit Helper (daemon/scheduler.py, lines 173–178)

**Location:** Lines 173–178 in execute_sprint

**Why it's over-engineered:**

The `_emit` helper captures `sprint.id` and `session_id` via closure to emit events to both WebSocket broadcast and on-disk trace. This works but is a bit too clever:

```python
def _emit(typ: str, **data):
    if broadcast:
        broadcast({"type": typ, "sprint_id": sprint.id, **data})
    replay.append_event(session_id, typ, sprint_id=sprint.id, data=data)
```

The closure silently closes over `sprint`, `session_id`, and `broadcast`. If either changes during the function (e.g., sprint object is reassigned), the behavior is subtle. The alternative is a small SchedulerContext class or explicit parameters.

**Simpler alternative:**

Create a lightweight context:

```python
class SprintExecutionContext:
    def __init__(self, sprint_id, session_id, broadcast=None):
        self.sprint_id = sprint_id
        self.session_id = session_id
        self.broadcast = broadcast

    def emit(self, typ: str, **data):
        if self.broadcast:
            self.broadcast({"type": typ, "sprint_id": self.sprint_id, **data})
        replay.append_event(self.session_id, typ, sprint_id=self.sprint_id, data=data)
```

Then pass `ctx.emit(typ, **data)` throughout. The explicit parameters make the dependencies clear.

**Estimated impact:** +25 LOC (new class), -5 LOC (simpler calls), 0 functional change.

**Cost:** Low. Refactoring is mechanical; no behavior change. Tests don't need updates (the emit function is still mocked).

---

## Duplicated Logic

### 1. Executor Boilerplate: openai_compatible.py vs. ollama.py

**Location:** daemon/executors/openai_compatible.py and ollama.py

**Duplication:**

Both files have ~250 LOC and implement the same shape:

1. Parse env vars for credentials / base URL.
2. Build a request body (model, messages, options, tools, format).
3. POST to a REST endpoint.
4. Parse the response (extract output text + tokens).
5. Handle tool_calls via TOOL_CALL_PREFIX sentinel.
6. Return ExecutionResult.

The key difference is the HTTP request shape (Ollama `/api/chat` vs. OpenAI `/v1/chat/completions`) and response parsing (Ollama's response is flat; OpenAI's is nested under `response.choices[0].message`).

**Where the duplication lives:**

- Lines 119–200+ in openai_compatible.py
- Lines 66–150+ in ollama.py

**Suggested extraction:**

Create a base `HTTPExecutor` class or a composable set of functions:

```python
# daemon/executors/_http_base.py
async def http_chat_execute(
    prompt: str,
    model: str,
    base_url: str,
    api_key: str,
    *,
    tools: list[dict] | None = None,
    response_format: dict | None = None,
    temperature: float = 0.2,
    # ... other params
    # Subclass-provided:
    build_body_fn: Callable,
    extract_response_fn: Callable,
) -> ExecutionResult:
    """Generic HTTP executor."""
    body = build_body_fn(...)
    async with httpx.AsyncClient(...) as client:
        r = await client.post(base_url, json=body)
        return extract_response_fn(r)

# Then in ollama.py:
def _build_ollama_body(...) -> dict: ...
def _extract_ollama_response(r: httpx.Response) -> ExecutionResult: ...
async def execute(...) -> ExecutionResult:
    return await http_chat_execute(..., build_body_fn=_build_ollama_body, extract_response_fn=_extract_ollama_response)
```

**Estimated impact:** -80 LOC total (duplication removed), +40 LOC (shared base), -40 LOC net.

**Cost:** Medium-High. Both executors need refactoring, and tests for both would need light updates (they'd now test the composition). But the payoff is high: when a third HTTP executor arrives (e.g., Anthropic Batch API), the cost drops to +50 LOC instead of +200.

---

### 2. Fixture Duplication: tmp_forge_dir

**Location:** tests/test_replay.py, tests/test_scanner.py, tests/test_knowledge.py (and possibly more)

**Duplication:**

The `tmp_forge_dir` fixture is defined in multiple test files:

```python
@pytest.fixture
def tmp_forge_dir(tmp_path, monkeypatch):
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    monkeypatch.setenv("FORGE_DIR", str(forge_dir))
    return forge_dir
```

**Suggested extraction:**

Move to tests/conftest.py so it's shared across all test modules.

**Estimated impact:** -20 LOC (3 duplicate definitions), 0 net LOC.

**Cost:** Trivial. Mechanical move; no behavior change.

---

## Module Boundary Violations

None detected. The daemon modules have clear responsibilities:

- `scheduler.py` orchestrates; it calls into agents, recovery, and memory without reaching into their internals.
- `executors/` each implement a standard interface; no cross-executor calls.
- `memory/` modules own their data; the scheduler calls public methods.
- `agents/` agents don't import each other (no classifier ↔ evaluator, etc.).
- The one exception is `generator.py:_select_executor()` which mirrors `classifier.select_executor()`. This is acceptable duplication to avoid a circular import (generator shouldn't import classifier just to pick an executor; classifier and generator are peers).

**Minor violation:** `episodic.py` (lines 27–39) reaches into sprint.assigned_model to hardcode agent-type logic:

```python
agent_type="claude_code" if sprint.assigned_model in ("opus", "sonnet") else "ollama",
```

This should call `select_executor()` from classifier instead, but the module avoids importing classifier to prevent cycles. This is a design trade-off, not a bug.

---

## Naming Problems

### 1. "recovery" module name is vague

**Current:** `daemon/recovery.py`

**Why it's misleading:** "Recovery" could mean checkpoint/rollback, failover, resilience, or recomputation. The module is specifically about **algorithm fallbacks on terminal failure** (ADaPT decomposition + self-consistency).

**Proposed:** `daemon/fallback.py` or `daemon/strategies.py` or rename to `daemon/adapt.py` if ADaPT is the primary concern.

**Impact:** Low. Renaming is mechanical. The docstring is clear, so users who read it will understand. But new readers might assume recovery means something different.

---

### 2. "assign" vs. "set" inconsistency in sprint updates

**Current:**

- `sprint.assigned_model`
- `sprint.assigned_worktree`
- But `budget.downgrade()` sets `sprint.assigned_model = new_model` directly (no method).

**Why it's inconsistent:** "assigned" suggests a setter method (like `sprint.assign_model()`) but the code uses direct assignment. Compare to the explicit `db.save_procedure()` call.

**Proposed:** Either rename to `sprint.model` / `sprint.worktree` (stored state, not process), or introduce `sprint.assign_model(m)` and `sprint.assign_worktree(w)` methods (emphasizing the action).

**Impact:** Low. The names are clear in context. But consistency would improve readability in dense code like the scheduler.

---

### 3. \_emit event type names lack a registry

**Current:** Event type names are strings scattered throughout scheduler.py (worktree.created, sprint.attempt, recovery.consistency.start, etc.) with no canonical list.

**Proposed:** Add a registry or enum:

```python
class EventType(Enum):
    WORKTREE_CREATED = "worktree.created"
    SPRINT_ATTEMPT = "sprint.attempt"
    RECOVERY_CONSISTENCY_START = "recovery.consistency.start"
    # ...
```

Then use `_emit(EventType.WORKTREE_CREATED.value, ...)` or just `_emit(EventType.WORKTREE_CREATED, ...)` (if _emit handles both).

**Impact:** Medium. Easier to grep and refactor event names. UI can depend on a canonical list. But adds ~20 LOC and requires importing the enum.

---

## Comment Quality Issues

### Comments That Say What the Code Already Says (Delete These)

1. **scheduler.py:176** — `if broadcast:` with comment `"Emit to the broadcast channel"`. The name `broadcast` is clear.
2. **redact.py:220** — `if not text: return text` with comment. The logic is obvious.
3. **recovery.py:165** — `passed = exec_result.success and eval_result.verdict == "APPROVED"` with comment. The variable name already says what it is.
4. **parsing.py:184** — `try: return json.loads(text)` with comment `"Step 1: happy path"`. The step number is already in the comment above; the code itself is clear.

**Impact:** Low. These comments clutter but don't harm. Remove them to reduce cognitive load.

---

### Comments Missing Where the *Why* Is Unclear

1. **redact.py:146–151** — Why use a negative lookahead instead of just reordering rules? The comment explains what it does but not why this approach was chosen over the obvious alternative. Add: "This avoids losing precision when a secret matches both a specific rule (e.g., Slack token) and the generic env-line rule. By checking the negative lookahead, we preserve the more specific label."

2. **recovery.py:222–235** — The `is_critical()` function checks if the description starts with `[critical]`. Why not a boolean field on SprintContract? The comment says "for v1" but there's no issue tracker link or date. Add: "TODO (Phase X): add `critical: bool` field to SprintContract; this string-prefix check is a temporary fallback for backward compatibility."

3. **classifier.py:105–112** — The three-tier routing logic (Anthropic → claude_code, OPENAI_BASE_URL → openai_compatible, else → ollama) is clear from the code but the *why* is in a comment at the function level. Good. But the logic doesn't mention what happens if OPENAI_BASE_URL is set and the model is Anthropic. Add a comment: "Note: Anthropic models always use claude_code executor, even if OPENAI_BASE_URL is set. This is intentional — Claude API has prompt caching natively."

4. **scheduler.py:199–203** — The self-consistency branch is wired in between worktree creation and the normal loop, but there's no comment explaining why this branching exists or when it activates. The docstring explains ADaPT but not self-consistency placement. Add inline: "If flagged critical (per ADR-0?), run N=3 sequential attempts instead of the revision loop; critical sprints don't benefit from iterative refinement."

---

## Type-Hint Hygiene

### Files Needing Better Type Hints

| File | Issue | Count | Fix |
|------|-------|-------|-----|
| daemon/db.py | Returns `dict` without parameterization | 5 | `dict[str, Any]` or specific TypedDict |
| daemon/models.py | Uses `Any` in payloads | 4 | Define a Payload = dict[str, Any] alias or use TypedDict |
| daemon/grammars.py | Returns `dict[str, Any]` everywhere | 6 | OK as-is; JSON schema is inherently untyped |
| daemon/memory/episodic.py | `eval_result = None` (should be Optional) | 1 | `eval_result: EvaluatorResult \| None` |
| daemon/agents/generator.py | Private helper returns `str \| None` without annotation | 1 | Add return type hint to `_truncate_to_budget` |
| daemon/agents/classifier.py | llm_classify returns str but might return "medium" on any error | 1 | Document fallback behavior in return type or exception spec |

**Specific issues:**

1. **db.py:table_counts()** — Returns `dict` but should be `dict[str, int]` (table names to row counts).
2. **models.py** — Several to_dict() methods return bare `dict`. Use TypedDict or define interfaces.
3. **episodic.py:store()** — Parameter `eval_result = None` should be `eval_result: EvaluatorResult | None = None` (it's used with `.verdict` and `.feedback` later, suggesting it's sometimes present, sometimes absent).
4. **classifier.py:llm_classify()** — Promises to return str (low/medium/high) but falls back to "medium" on any error. The function signature should clarify: either add `-> str` (never None) or document the error handling.
5. **generator.py** — The `_build_prompt()` helper has multiple branches and conditional returns. The return type is `str`, but add a docstring clarifying "always returns a non-empty string" or "returns empty string if both prefix and suffix are empty".

**Cost:** Low. Type hints don't change runtime behavior. Updates are mechanical.

---

## Dependency and Import Issues

### Phantom Dependency: tree-sitter

**Finding:** The repomap optional dependency lists `tree-sitter` and `tree-sitter-languages` in pyproject.toml (lines 41–42), but the current repomap.py implementation (daemon/scanner/repomap.py) uses **only regex-based symbol extraction** and never imports tree-sitter.

**Code evidence:**

- Line 9–14 of repomap.py explains: "This Phase 1 simplified version uses regex-based symbol extraction... When users want better fidelity, they can opt in to the full tree-sitter version (planned Phase 1 Week 4 follow-up)."
- No `import tree_sitter` or `from tree_sitter import Language` anywhere in repomap.py.
- The regex patterns (_SYMBOL_PATTERNS) are the only symbol extractor.

**Implication:** Users installing `forge[repomap]` get tree-sitter 30MB+ of wheels for code that doesn't use it. This violates the principle "install only what you need."

**Fix:**

Remove tree-sitter from the repomap optional group. Either:
1. Delete the optional group entirely (repomap is always on).
2. Keep the group but list no dependencies (tree-sitter is a future enhancement).

Then add a follow-up in BUILD_PLAN.md: "Phase 1 Week 4: wire tree-sitter for precise symbol extraction; users opt in with forge[repomap-precise]."

**Cost:** Trivial. One line deletion from pyproject.toml.

---

### No Circular Imports Detected

Checked the full import graph; no cycles found. The architecture cleanly separates concerns:

- `scheduler.py` imports agents, memory, recovery, worktree.
- Agents don't import each other.
- Memory modules don't import agents.
- Recovery is isolated.
- Executors are pluggable.

**Minor import oddity:** `generator.py:_select_executor()` replicates `classifier.select_executor()` to avoid importing classifier (which would create a cycle if classifier ever imported agents). This is acceptable — it's two tiny functions (12 LOC total).

---

## Test Quality Issues

### 1. Tests That Monkeypatch append_event Instead of Asserting on It

**Location:** tests/test_recovery.py, lines 101, 127, 147, etc.

**Pattern:**

```python
@pytest.mark.asyncio
async def test_adapt_returns_pass_when_all_subsprints_succeed(tmp_path, monkeypatch):
    monkeypatch.setattr("daemon.recovery.append_event", lambda *a, **kw: None)
    # ... test code ...
```

**Problem:** The test mocks away the append_event call entirely, so it doesn't verify that the event was emitted with the right data. The test verifies the algorithm (decomposition, verdict calculation) but not the side effect (event emission).

**Better approach:**

```python
@pytest.mark.asyncio
async def test_adapt_emits_events(monkeypatch):
    events_emitted = []

    def capture_event(session_id, typ, **kwargs):
        events_emitted.append({"typ": typ, "session_id": session_id, **kwargs})

    monkeypatch.setattr("daemon.recovery.append_event", capture_event)

    # ... run recovery ...

    assert len(events_emitted) >= 2  # At least start and complete
    assert events_emitted[0]["typ"] == "recovery.adapt.decomposed"
```

This verifies both the algorithm and the tracing behavior.

**Impact:** Low. The current tests are sufficient for coverage; they just don't test all the code paths. Add 3–4 event-capture tests to cover the tracing.

---

### 2. Missing @pytest.mark.slow for Integration Tests

**Finding:** Several tests in tests/test_integration_wiring.py and tests/test_openai_compatible.py make real HTTP requests (or mock them with respx). These are integration tests that can timeout or fail for environmental reasons, but they're not marked as slow.

**Impact:** When running `pytest -m "not slow"` to skip long-running tests, integration tests still run. This is usually fine, but it's worth marking them explicitly.

**Fix:** Add `@pytest.mark.integration` or `@pytest.mark.slow` to tests that make real API calls or spawn subprocesses.

---

### 3. Brittle Assertion: Exact Error String Matching

**Location:** Not found in the review sample, but a pattern to watch for.

**Anti-pattern:**

```python
assert "exact error message text" in str(exc)
```

Models and external services change error messages between versions. A brittle assertion breaks when the error text changes.

**Better approach:**

```python
assert "timeout" in str(exc).lower()  # Match the concept, not the exact wording
# OR
assert isinstance(exc, asyncio.TimeoutError)  # Match the exception type
```

---

## Architectural Recommendations

### Top 5 Changes for Meaningful Clarity Improvement

#### 1. **Consolidate Executor Boilerplate** (High impact, medium effort)

**Rationale:** When a third HTTP executor lands, the code will again duplicate 250 LOC. Extract a shared `HTTPExecutor` base class or composable functions to remove this redundancy.

**Effort:** 6–8 hours (refactoring + test updates).

**Benefit:** -40 LOC net, easier to add new executors, clearer error handling across all HTTP paths.

---

#### 2. **Remove AUTH_BEARER_LOOSE from Redaction Rules** (Low impact, trivial effort)

**Rationale:** The pattern is too loose and catches legitimate prose. Users who need Bearer token redaction can opt in via FORGE_REDACT_PROMPTS=1.

**Effort:** 30 minutes (delete 7 lines, update 1 test).

**Benefit:** Simpler redaction logic, fewer false positives, smaller regex complexity.

---

#### 3. **Move tmp_forge_dir to conftest.py** (Low impact, trivial effort)

**Rationale:** Reduce duplication across test files.

**Effort:** 15 minutes (move 5 lines, remove 3 duplicates).

**Benefit:** Single source of truth for the fixture; easier to maintain.

---

#### 4. **Add a RecoveryStrategy or AttemptResult Base Class** (Low impact, low-medium effort)

**Rationale:** DecompositionResult and SelfConsistencyResult solve the same problem. Sharing a base reduces future duplication when a third recovery strategy arrives.

**Effort:** 2–3 hours (create base, update both subclasses, test).

**Benefit:** -15 LOC net, clearer intent, shared winner/verdict logic.

---

#### 5. **Create an Event Type Registry** (Medium impact, medium effort)

**Rationale:** Event type names are currently strings scattered in scheduler.py. A registry makes them discoverable and enables validation.

**Effort:** 4–5 hours (create enum, update all _emit calls, document in ENGINEERING_STANDARDS.md).

**Benefit:** Easier to refactor event names, UI can depend on canonical types, catch typos in event names at import time.

---

## Summary Table: Top 10 Quality Issues by Impact × Fix Cost

| # | Issue | Impact | Cost | Recommendation |
|----|-------|--------|------|---|
| 1 | Executor boilerplate duplication | High | Medium | Refactor to shared HTTPExecutor base |
| 2 | AUTH_BEARER_LOOSE over-matches | Medium | Trivial | Delete pattern; use FORGE_REDACT_PROMPTS for opt-in |
| 3 | Redaction negative-lookahead smell | Medium | Low | Reorder rules; remove lookahead |
| 4 | Recovery: isomorphic dataclasses | Low | Low | Create AttemptResult base; inherit |
| 5 | tmp_forge_dir duplication | Low | Trivial | Move to conftest.py |
| 6 | Type hints: bare dict/list | Low | Low | Add parameterization (dict[str, int], etc.) |
| 7 | Event type names aren't registered | Medium | Medium | Create EventType enum; centralize |
| 8 | is_critical() uses string prefix | Low | Low | Document as temporary (Phase X: add boolean field) |
| 9 | Parsing layer state management | Low | Low | Simplify candidate extraction; use walrus operator |
| 10 | EpisodicStore hardcodes agent type | Low | Low | Call classifier.select_executor() instead |

---

## Caveats and Non-Issues

### What's Actually Fine

1. **The Memory Module Architecture** — episodic, procedural, research, retriever, learner are cleanly separated. The use of a Retriever class that wraps ForgeDB is reasonable.

2. **Comments in Recovery** — The recovery.py docstring is excellent. It explains both mechanisms, references papers, and justifies every design choice. No changes needed.

3. **Classifier Heuristics** — The layered approach (procedural → heuristic → LLM) is well-documented and the regex patterns are reasonable. The false positive concern (routing a hard task to cheap tier) is correctly weighted.

4. **Prompt Truncation Logic** — The 80% input / 20% output split in generator.py is configurable (easy to parameterize if users request it) and well-justified in comments. No red flags.

5. **Async/Concurrency** — The use of asyncio.Semaphore for wave parallelism is appropriate. No TaskGroup here (Ruff ignores ASYNC240 for startup), but the intent is clear.

---

## Conclusion

The codebase is **well-structured and maintainable** in its current form. No architectural rot is present. The issues identified are **incremental complexity** that would benefit from cleanup before the next major feature arrives.

**Priority actions (before Phase 2):**

1. Remove AUTH_BEARER_LOOSE (1 hour).
2. Move tmp_forge_dir to conftest.py (15 min).
3. Add type hints to bare dict returns (2 hours).

**Medium-term improvements (Phase 1 final polish):**

1. Create HTTPExecutor base to reduce executor duplication.
2. Add EventType enum for event type registry.
3. Simplify parsing ladder.

**Long-term structural improvements (Phase 2+):**

1. Add `critical: bool` field to SprintContract; retire string-prefix check.
2. Create a dedicated recovery strategy registry when a 3rd recovery method arrives.

The module is **not over-engineered in an absolute sense**, but it has accumulated optional patterns (redaction rules, recovery dataclasses, executor duplication) that will become **liabilities when they need to be extended or maintained by new contributors**. Cleaning these up now is worthwhile.
