# Round 1 Code Review: Functionality & Correctness

**Review Date**: 2026-04-30
**Scope**: Multi-agent orchestrator (scheduler.py, agents/*.py, executors, recovery, db, memory)
**Focus**: Real bugs, broken contracts, untested paths, dead code, error handling gaps

---

## Critical Bugs (Would Silently Break in Production)

### BUG-1: ADaPT Recovery Path Missing Procedural Writeback
**File**: `daemon/scheduler.py:293-309`
**Severity**: HIGH (impacts procedural memory learning)

**Problem**: When ADaPT recovery succeeds (line 305, `decomp.final_verdict == "PASS"`), the sprint status is flipped from "failed" to "completed", but `_writeback_procedural()` is **never called**. This means the procedural store doesn't learn from successful recovery — the task pattern that failed initially and then succeeded via decomposition is never recorded.

```python
# Line 283-284: _writeback_procedural IS called for direct failure
episodic.store(session_id, sprint, gen_result, eval_result)
_writeback_procedural(db, sprint, eval_result, time.time() - sprint_start)

# Line 305-307: But NOT when recovery succeeds
if decomp.final_verdict == "PASS":
    sprint.status = "completed"
    sprint.error = None  # type: ignore[assignment]
# Missing: _writeback_procedural() call here!
```

**Impact**: The procedural memory (online RouteLLM per Phase 1 Week 6) stops accumulating data for tasks that only succeed via decomposition. Over time, the classifier's routing decisions become stale because high-success-rate patterns never appear in the procedure table.

**Fix**: Call `_writeback_procedural(db, sprint, EvaluatorResult(verdict="APPROVED"), time.time() - sprint_start)` before line 307, or track the best sub-sprint verdict and use that.

---

### BUG-2: ADaPT Recovery Missing Episodic Record
**File**: `daemon/scheduler.py:283-309`
**Severity**: HIGH (impacts episodic memory recall)

**Problem**: When ADaPT recovery succeeds, **no episodic memory entry is created**. The system has already stored an episode at line 283 with status "failed" (because `gen_result.success` is False). But when recovery succeeds, there is no follow-up episode recording the recovery success. This violates the documented contract in the scheduler docstring (line 168-169): *"Procedural memory writeback after every evaluator verdict"* — recovery success is an evaluator verdict (APPROVED after decomposition) but goes unrecorded.

**Current flow**:
- Line 283: Episode saved with `status="failed"` (gen_result from last failed attempt)
- Line 302: ADaPT runs and produces a new result
- Line 305-307: Sprint status changes to "completed" but **no new episode is created**

**Impact**: The learner and knowledge systems are blind to recovery successes. The database has no trace that the sprint actually succeeded after all; queries like `get_failure_resolution_pairs()` (line 336 of db.py) will never find the recovery pair because the "resolution" episode doesn't exist.

**Fix**: After line 305, call `episodic.store(session_id, sprint, decomp.sub_results[-1], EvaluatorResult(verdict="APPROVED"))` to record the recovery outcome.

---

### BUG-3: Incorrect Agent Type Detection in Episodic Store
**File**: `daemon/memory/episodic.py:27`
**Severity**: MEDIUM (mislabels claude_code agents)

**Problem**: The episodic store hardcodes a check for agent type:
```python
agent_type="claude_code" if sprint.assigned_model in ("opus", "sonnet") else "ollama"
```

This **does not include "haiku"**, which is a valid Anthropic model (per config.py line 84). So any haiku-based sprint will be mislabeled as "ollama" in the episodes table. This also diverges from the classifier's logic (line 105-107 of classifier.py), which routes by `model_family()` not hardcoded strings.

**Real root cause**: The logic should use `model_family(sprint.assigned_model) == "anthropic"` to stay in sync with the classifier and config, not hardcoded model names.

**Impact**:
- Haiku-based tasks are mislabeled as "ollama" in episode records
- Post-hoc analysis of agent performance by type will misattribute haiku work to ollama
- Procedural memory training data gets poisoned (wrong agent_type → wrong routing decisions)

**Fix**: Replace with:
```python
from ..config import model_family
agent_type = "claude_code" if model_family(sprint.assigned_model) == "anthropic" else select_executor(sprint.assigned_model)
```

---

## Broken Integrations / Contract Mismatches

### INTEGRATION-1: Evaluator Call Signature is Correct, But Cross-Family Logic Depends on Undocumented Contract
**File**: `daemon/scheduler.py:147` calls `evaluator.evaluate(sprint, diff, ctx)`
**Vs. definition**: `daemon/agents/evaluator.py:269` defines `async def evaluate(sprint, diff, ctx, *, eval_model=None)`

**Status**: NOT A BUG — the call is correct. The evaluator defaults to picking a cross-family model via `pick_evaluator_model()` when `eval_model=None`.

**However**, there is a **contract clarity issue**: The scheduler doesn't know or document that it relies on ADR-006's cross-family enforcement. If someone naively refactors evaluator.py to hardcode `eval_model="sonnet"`, the invariant breaks silently. Consider adding an assertion in the evaluator:

```python
# In evaluator.evaluate(), after picking eval_model
assert model_family(eval_model) != model_family(sprint.assigned_model), \
    f"Evaluator must be cross-family: gen={sprint.assigned_model} ({model_family(sprint.assigned_model)}), eval={eval_model} ({model_family(eval_model)})"
```

---

### INTEGRATION-2: Executor Selection Divergence
**File**: `daemon/agents/generator.py:140-160` defines `_select_executor(sprint)`
**Vs.**: `daemon/agents/classifier.py:86-112` defines `select_executor(model)`

**Problem**: These two functions have similar but not identical logic:
- `generator._select_executor()` uses model string directly + `model_family()`
- `classifier.select_executor()` uses model string + environment variable for openai_compatible

Both functions will return the same result in practice, but the duplication is a maintenance hazard. If one is updated and the other isn't, executors diverge.

**Impact**: Low risk today (tests probably cover both), but fragile.

**Fix**: Have `generator.py` import and call `classifier.select_executor()` directly rather than duplicating the logic.

---

## Untested-But-Claimed Paths

### UNTESTED-1: ADaPT Recovery On MAX_REVISIONS Exhaustion
**Claimed in docstring** (line 19-21): *"ADaPT recovery on MAX_REVISIONS exhaustion. Instead of immediately marking it failed..."*
**What's actually tested** (test_recovery.py): Tests for `adapt_failed_sprint()` function exist, but **scheduler-level integration is not tested**. Specifically:
- No test in `test_scheduler.py` that exercises the full path: MAX_REVISIONS exhaustion → ADaPT trigger → success
- The condition check on line 293 (`sprint.status == "failed" and recovery.is_eligible_for_decomposition(sprint)`) is not exercised in the test suite

**Risk**: If someone changes line 293's condition or the timing of when `sprint.status = "failed"` is set, the ADaPT path could silently stop firing.

**Fix**: Add a test case in `test_scheduler.py`:
```python
async def test_adapt_recovery_on_max_revisions_exhaustion():
    # Create sprint with 2 criteria, run it to exhaustion, verify ADaPT fires
```

---

### UNTESTED-2: Self-Consistency Early Exit On First APPROVED
**Claimed in docstring** (line 22-25): *"Self-Consistency mode for [critical] sprints... early-exit on first APPROVED"*
**Implementation** (recovery.py line 317-318):
```python
if attempt[1].verdict == "APPROVED":
    break
```

**What's tested**: test_recovery.py has `test_self_consistent_run_early_exits_on_first_approved()`, so the recovery module is tested.

**But not tested**: The scheduler's integration with this early-exit behavior. Specifically:
- Does the scheduler correctly use `consistency_result.winner` when early exit occurs?
- Is budget accounting correct when only 1 or 2 of 3 attempts run?

**Risk**: If `recovery.self_consistent_run()` returns `winner` with `winner_index=0` (early exit after 1 approved), does the scheduler cost accounting match the actual spend? No test verifies this integration.

---

### UNTESTED-3: Procedural Writeback Fire On Every Verdict
**Claimed in docstring** (line 14): *"Procedural memory writeback (`db.save_procedure`) — after every evaluator verdict (APPROVED or REVISE)"*

**Reality**: _writeback_procedural is called at:
- Line 222 (self-consistency APPROVED branch) ✓
- Line 270 (normal APPROVED) ✓
- Line 284 (normal REVISE after MAX_REVISIONS) ✓
- **Line 305-307 (ADaPT recovery success) ✗ MISSING**

The documented contract ("after every verdict") is **false**. The second critical bug above is the consequence.

---

## Dead Code

### DEADCODE-1: worktree.py Cleanup Handlers Never Execute In Daemon Mode
**File**: `daemon/worktree.py:148-160`
**Code**:
```python
def _sync_cleanup():
    """Synchronous cleanup for atexit/signal handlers."""
    import subprocess
    ...

atexit.register(_sync_cleanup)
signal.signal(signal.SIGINT, ...)
signal.signal(signal.SIGTERM, ...)
```

**Problem**: In a real daemon (the scheduler runs in an async event loop as the main application), these signal handlers and atexit callbacks **will not execute gracefully** because:
1. The async event loop is still running
2. You can't call `asyncio.run()` from within atexit (deadlock risk)
3. The signal handlers registered here compete with the event loop's signal handling

**Impact**: Worktrees might not be cleaned up on daemon shutdown. Not a correctness bug per se, but leaves zombie worktrees on disk.

**Note**: This is a deployment-level issue, not a functional bug in the code itself. The cleanup handlers exist but are unreliable. A proper fix requires integrating with the event loop's shutdown (via `atexit` + `asyncio.Runner.run()` cleanup or a signal handler that schedules async cleanup).

---

## Error-Handling Gaps

### ERRGAP-1: Generator Failure Not Consistently Recorded in Episodic Memory
**File**: `daemon/scheduler.py:138-144`
**Problem**: When `generator.generate()` fails (returns `success=False`), the code creates a synthetic `EvaluatorResult(verdict="REVISE")` and continues. However, this result is **not stored in episodic memory**. Only actual evaluator results (line 269, 283) are stored. A generator crash produces no episode entry.

**Implication**: The episodic store has gaps — it records successful generations + evaluations, but not pure generation failures. This biases downstream learners (they see only "evaluator said REVISE" not "generator crashed").

**Fix**: Store an episode for generator failures:
```python
if not gen_result.success:
    episodic.store(session_id, sprint, gen_result, None)  # No eval result
```

---

### ERRGAP-2: Worktree Creation Failure Silently Marks Sprint Failed Without Recovery
**File**: `daemon/scheduler.py:182-189`
**Code**:
```python
try:
    wt_path = await worktree.create(sprint.id)
    sprint.assigned_worktree = wt_path
except Exception as e:
    sprint.status = "failed"
    sprint.error = f"Worktree creation failed: {e}"
    _emit("worktree.create_failed", error=str(e))
    return sprint
```

**Problem**: If worktree creation fails, the sprint is immediately marked "failed" and returns **without ADaPT recovery consideration**. This bypasses the recovery machinery entirely. If a worktree creation error is transient (e.g., NFS lock), the sprint should potentially be retried via ADaPT or a higher-level retry, not immediately failed.

**Impact**: Transient infrastructure errors cause permanent sprint failures with no recovery path.

**Fix**: Don't return immediately; instead set a flag and allow the normal loop to handle the error (or implement a retry mechanism for worktree creation).

---

### ERRGAP-3: `silent_catch` Usage Does Not Prevent Error Propagation in All Paths
**File**: `daemon/scheduler.py:101-113` (_writeback_procedural)
**Code**:
```python
try:
    ...
except Exception as e:
    silent_catch(__name__, e)
```

**Issue**: `silent_catch()` is a logging helper — it logs the exception and returns normally. The comment on line 98-99 correctly describes this: *"Failures are logged via silent_catch rather than raising"*. This is intentional and correct. However, other code paths (e.g., repomap building on line 354-357) also use `silent_catch()` but then silently proceed with an empty repomap. A caller cannot easily distinguish between "repomap build failed and was logged" vs. "repomap is legitimately empty". This is a design clarity issue, not a bug per se.

---

## Concurrency Issues

### CONCURRENCY-1: Worktree Reuse Race Condition in `worktree.create()`
**File**: `daemon/worktree.py:57-60`
**Code**:
```python
if os.path.exists(wt_path):
    # Already exists, reuse
    _active_worktrees.append(wt_path)
    return wt_path
```

**Problem**: In a concurrent environment (multiple `execute_sprint()` calls in parallel via `asyncio.gather`), two tasks could both check `os.path.exists()` and both find the path exists. Both would then append `wt_path` to `_active_worktrees`, causing a duplicate. Later, `cleanup_all()` would try to remove it twice, leading to an error or log spam.

**Impact**: Duplicate worktree paths in the tracking list, benign but sloppy.

**Fix**: Use a lock or move to a set-based tracking mechanism:
```python
_active_worktrees_lock = asyncio.Lock()
async with _active_worktrees_lock:
    if wt_path in _active_worktrees:
        return wt_path
    ...
    _active_worktrees.add(wt_path)
```

---

### CONCURRENCY-2: Budget Downgrades Not Atomic Across Wave
**File**: `daemon/scheduler.py:380-387`
**Code**:
```python
for sprint in wave:
    if not budget.can_afford(sprint):
        budget.downgrade(sprint)
        _emit_session("budget.downgrade", ...)
```

**Problem**: The budget check and downgrade happen **before** the parallel execution. If `budget.can_afford()` returns False for sprint A, it's downgraded. But then sprint A's downgrade doesn't prevent sprint B (which runs in parallel) from also being downgraded if the total spend exceeds the budget midway through the wave. The budget module doesn't handle concurrent spend tracking — `budget.record_spend()` is called from within `execute_sprint()`, but the earlier `can_afford()` check is sequential.

**Impact**: The system may downgrade more aggressively than intended, or allow overspend, depending on the order of parallel task completion.

**Fix**: Move budget enforcement into `execute_sprint()` with a lock on the budget object, or redesign to a futures-based reservation system.

---

## Incorrect or Misleading Docstrings/Comments

### DOCSTRING-1: Scheduler Docstring Claims "Every Phase Transition Emits Trace Events"
**File**: `daemon/scheduler.py:8-13`
**Docstring**:
> "Trace events (`replay.append_event`) — every phase transition (session start/end, sprint start, generation, evaluation, revision, budget downgrade, recovery) emits a JSONL audit-log event"

**Reality**:
- Session start/end: ✓ (line 346, 429)
- Sprint start: ✓ (line 240)
- Generation: ✓ (evaluated as part of "evaluation", line 260)
- Evaluation: ✓ (line 260)
- Revision: ✓ (line 277)
- Budget downgrade: ✓ (line 383)
- Recovery: ✓ (but incomplete — see UNTESTED-1)

The docstring is **technically correct**, but it's misleading because it doesn't mention the major gap: **when ADaPT recovery succeeds and flips a sprint from "failed" to "completed", there is no trace event that records this state transition**. The `_emit("recovery.adapt.complete", ...)` on line 303 only fires once; there's no separate event for "sprint status changed to completed by ADaPT". This makes it harder to replay the session accurately.

**Fix**: Add `_emit("sprint.recovered", verdict=...)` after line 307 when ADaPT succeeds, or augment the trace event to include before/after status.

---

## Validation Gaps

### VALIDATION-1: Worktree Name Validation Incomplete
**File**: `daemon/worktree.py:17-24`
**Code**:
```python
def sanitize_worktree_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9\-]", "-", name)
    return sanitized[:64] or "worktree"

def _validate_name(name: str) -> bool:
    return bool(re.match(WORKTREE_NAME_PATTERN, name))

async def create(name: str, ...):
    if not _validate_name(name):
        name = sanitize_worktree_name(name)
```

**Problem**: The sanitization replaces *any* non-alphanumeric + hyphen character with a hyphen. So a name like `sprint-001!@#` becomes `sprint-001----`. This could lead to:
1. Multiple sprints mapping to the same sanitized name (collision)
2. Very long hyphens if the original name had many special chars
3. Names like `--` if the original was pure special chars

The validation is applied **after** sanitization, so a caller can't tell if the original name was problematic.

**Impact**: Low risk (sprint IDs are UUIDs, not user input), but poor design.

**Fix**: Validate and reject bad names earlier, with a clear error message; or use a safer sanitization (e.g., random suffix instead of character replacement).

---

### VALIDATION-2: No Validation On `sprint.description` or `done_criteria` Length
**File**: `daemon/models.py:20-35` (SprintContract dataclass)
**Problem**: The SprintContract allows `description: str` and `done_criteria: list[str]` with no length limits. The generator then passes this to the prompt builder (`_build_prompt()` in generator.py), which does apply a `MAX_TASK_DESCRIPTION_LENGTH` cap on the **prompt** (not the description itself). If the description is already at the limit, it gets silently truncated with a marker.

**Impact**: A planner or user that creates a 1M-character description will silently lose the tail when it becomes a prompt. The truncation is logged, but there's no validation to reject overly-long sprints at creation time.

**Fix**: Add validators to SprintContract:
```python
@dataclass
class SprintContract:
    ...
    def __post_init__(self):
        if len(self.description) > MAX_TASK_DESCRIPTION_LENGTH:
            raise ValueError(f"description exceeds {MAX_TASK_DESCRIPTION_LENGTH} chars")
```

---

## Summary Table: Top 10 Issues by Severity × Fix Cost

| Priority | Issue | File:Line | Severity | Fix Cost | Impact |
|----------|-------|-----------|----------|----------|--------|
| 1 | ADaPT missing procedural writeback (BUG-1) | scheduler.py:305-307 | HIGH | 2 lines | Procedural memory doesn't learn from recovery |
| 2 | ADaPT missing episodic record (BUG-2) | scheduler.py:305-307 | HIGH | 1 call | Learner is blind to recovery success |
| 3 | Incorrect agent type in episodes (BUG-3) | episodic.py:27 | MEDIUM | 2 lines | Haiku tasks mislabeled, procedural data poisoned |
| 4 | Worktree reuse race condition (CONCURRENCY-1) | worktree.py:57-60 | MEDIUM | 4 lines + lock | Duplicate tracking in concurrent mode |
| 5 | Budget not enforced across parallel wave (CONCURRENCY-2) | scheduler.py:380-407 | MEDIUM | 5-10 lines | May overspend or over-downgrade |
| 6 | Executor selection divergence (INTEGRATION-2) | generator.py:140 vs classifier.py:86 | MEDIUM | 1 import | Maintenance hazard if logic drifts |
| 7 | Worktree creation failure has no recovery (ERRGAP-2) | scheduler.py:182-189 | MEDIUM | 3 lines | Transient errors cause permanent failures |
| 8 | ADaPT integration not tested (UNTESTED-1) | test_scheduler.py | MEDIUM | 20 lines | ADaPT path could silently break |
| 9 | Procedural writeback claim is false (UNTESTED-3) | docs + scheduler.py | MEDIUM | 2 lines | Contradicts contract and causes BUG-1 |
| 10 | Generator failure not in episodic (ERRGAP-1) | scheduler.py:138-144 | LOW | 1 call | Episodic gaps bias learners |

---

## Recommendations

1. **Fix ADaPT writeback immediately** (BUG-1 + BUG-2). This blocks procedural memory learning.
2. **Fix agent type detection** (BUG-3) to use `model_family()` consistently across the codebase.
3. **Add concurrency tests** for worktree reuse and budget enforcement.
4. **Add integration test** for ADaPT success path (UNTESTED-1).
5. **Unify executor selection** between generator.py and classifier.py.
6. **Document gaps** in trace events when ADaPT succeeds (add a "sprint.recovered" event).
7. **Add input validation** to SprintContract for overly long descriptions.

---

**End of Review**
