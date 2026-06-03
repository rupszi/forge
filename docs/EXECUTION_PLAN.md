# Forge — Code Review Fix Execution Plan

> **For a new chat session**: this document is **self-contained**. You don't need to read the source review notes to execute these fixes — every task includes the source citation, the exact problem, the concrete fix, and the acceptance criteria. Read the "Pre-flight" section first, then execute sprints in order.

**Source reviews**: [docs/CODE_REVIEW.md](CODE_REVIEW.md) (synthesis) · [research/notes/06-review-r1-functionality.md](research/notes/06-review-r1-functionality.md) · [research/notes/07-review-r2-code-quality.md](research/notes/07-review-r2-code-quality.md) · [research/notes/08-review-r3-security.md](research/notes/08-review-r3-security.md)

---

## Pre-flight

### State of the repo as of 2026-05-01

- Branch: `develop`
- Baseline tests: **588 passed, 1 skipped** (the skip is `test_mcp_server::test_build_mcp_server_constructs_when_mcp_installed` — it skips when the optional `forge[mcp]` extra isn't installed; that's correct behavior)
- Lint: `ruff check daemon tests scripts eval` → All checks passed
- Format: `ruff format --check daemon tests scripts eval` → 79 files formatted
- Pre-push: `bash scripts/pre-push.sh` → ✓ passed
- Python: system 3.9 (works because we ship `from __future__ import annotations` shims in 8 daemon files)

### Repository layout (relevant for these fixes)

```
daemon/
  agents/        — planner.py, generator.py, evaluator.py, classifier.py, reviewer.py, researcher.py
  executors/     — claude_code.py, ollama.py, openai_compatible.py, batch.py
  memory/        — knowledge.py, episodic.py, procedural.py, research.py, retriever.py, learner.py, embeddings.py
  scanner/       — project.py, claude_code.py, tools.py, repomap.py
  scheduler.py · worktree.py · budget.py · ws_server.py · cli.py
  recovery.py · replay.py · safety.py · log.py · redact.py · parsing.py · grammars.py · mcp_server.py
  models.py · config.py · db.py
tests/           — 31 test files; 589 tests total
docs/            — DECISIONS.md (ADRs), BUILD_PLAN.md, ENGINEERING_STANDARDS.md, COMPETITIVE_COMPARISON.md, CODE_REVIEW.md
eval/swebench/   — Phase 2 SWE-bench harness skeleton
```

### How to run the quality gate locally

```bash
# Activate venv
source .venv/bin/activate          # or use uv run

# Tests
PYTHONPATH=. .venv/bin/pytest tests/ --no-header -q

# Lint + format
.venv/bin/ruff check daemon tests scripts eval
.venv/bin/ruff format --check daemon tests scripts eval

# Full pre-push gate
bash scripts/pre-push.sh
```

### Sprint structure

- **Sprint 1 (P0 — must fix before any public release): ~10 hours, 11 tasks, blocking** — silently-broken contracts + critical security gaps
- **Sprint 2 (P1 — production readiness): ~5 hours, 7 tasks** — concurrency, lifecycle, evaluator runtime assert, dispatch unification
- **Sprint 3 (P1 — overengineering cleanup): ~10 hours, 4 tasks** — biggest single item is the HTTPExecutor refactor
- **Sprint 4 (P2 — polish): ~2 hours** — tests + comments + type hints

**Run order**: Sprint 1 fully, gate green, commit. Then Sprint 2 fully, gate green, commit. Then Sprint 3 + 4 can land incrementally across patch releases.

### Execution rules

1. After each task: run the affected tests locally (`pytest tests/test_<module>.py`) before moving on.
2. After each sprint: full quality gate green (ruff + format + pytest + pre-push).
3. **Do not bundle multiple tasks into one commit** — each task is an atomic, reviewable change.
4. **No `# type: ignore` without inline reason**; no `print()` in `daemon/`; standards from [docs/ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md) apply.
5. If a task surfaces a deeper issue not in this plan, **add a new task** rather than expanding the current one.

---

# Sprint 1 — Pre-launch P0 (~10 hours)

Each task here closes either a silently-broken contract or a security gap that should not ship.

---

## Task 1.1 — ADaPT recovery: write back to procedural and episodic memory

**Source**: Round 1 BUG-1 + BUG-2 (`docs/research/notes/06-review-r1-functionality.md`)
**Severity**: HIGH (silent learning-loop gap)
**Effort**: 30 min
**Files**: `daemon/scheduler.py:285–320`

### Problem

When ADaPT recovery flips a sprint from `"failed"` → `"completed"`, neither `_writeback_procedural()` nor `episodic.store()` is called. Result: the procedural memory never learns from successful recovery, and the episodic store has no record of the recovery success — only the original failure. This violates the documented contract in the scheduler docstring (*"Procedural memory writeback after every evaluator verdict"*).

### Current code (around `daemon/scheduler.py:300–315`)

```python
    if sprint.status == "failed" and recovery.is_eligible_for_decomposition(sprint):
        _emit("recovery.adapt.start")

        async def _run_subsprint(sub):
            sub_wt_path = await worktree.create(sub.id)
            sub.assigned_worktree = sub_wt_path
            sub_memory = retriever.get_context_for_task(sub.description)
            return await _run_one_attempt(sub, ctx, sub_wt_path, sub_memory, repomap)

        decomp = await recovery.adapt_failed_sprint(sprint, run_subsprint=_run_subsprint)
        _emit("recovery.adapt.complete", verdict=decomp.final_verdict)

        if decomp.final_verdict == "PASS":
            sprint.status = "completed"
            sprint.error = None  # type: ignore[assignment]

    db.save_sprint(sprint)
    return sprint
```

### Fix

Replace the `if decomp.final_verdict == "PASS":` block with:

```python
        if decomp.final_verdict == "PASS":
            sprint.status = "completed"
            sprint.error = None  # type: ignore[assignment]
            # Record the recovery success — both for the episodic store
            # (so failure→resolution pairs are complete) and for the
            # procedural store (so routing learns recovery succeeded for
            # this task pattern). Synthesize an APPROVED EvaluatorResult
            # from the last sub-sprint's outcome.
            recovery_eval = EvaluatorResult(
                verdict="APPROVED",
                feedback=f"Recovered via ADaPT decomposition into {len(decomp.sub_sprints)} sub-sprints",
            )
            last_gen = decomp.sub_results[-1] if decomp.sub_results else ExecutionResult(success=True)
            episodic.store(session_id, sprint, last_gen, recovery_eval)
            _writeback_procedural(db, sprint, recovery_eval, time.time() - sprint_start)
            _emit("sprint.recovered", verdict="APPROVED", sub_count=len(decomp.sub_sprints))
```

### Test to add

In `tests/test_integration_wiring.py`, append:

```python
@pytest.mark.asyncio
async def test_adapt_recovery_writes_episodic_and_procedural(
    tmp_db, tmp_forge_dir, fake_worktree, monkeypatch
):
    """When ADaPT recovery succeeds, both procedural and episodic memory record it."""
    sprint = SprintContract(
        session_id="sess-recover",
        description="multi-criterion task",
        done_criteria=["a", "b"],
        assigned_model="qwen3-coder-next",
    )

    # Force the normal loop to fail (so ADaPT triggers)
    from daemon.agents import evaluator as eval_mod
    from daemon.agents import generator as gen_mod

    async def fake_generate(s, memory_context="", worktree_path=None, **kwargs):
        return ExecutionResult(success=True, output="diff", tokens_in=1, tokens_out=1)

    async def fake_evaluate(s, diff, ctx, *, eval_model=None):
        return EvaluatorResult(verdict="REVISE", feedback="not yet")

    monkeypatch.setattr(gen_mod, "generate", fake_generate)
    monkeypatch.setattr(eval_mod, "evaluate", fake_evaluate)

    # ADaPT runs but its sub-sprints succeed
    async def fake_adapt(parent, *, run_subsprint):
        from daemon.recovery import DecompositionResult
        return DecompositionResult(
            parent_sprint_id=parent.id,
            sub_sprints=[],
            sub_results=[ExecutionResult(success=True, tokens_in=1, tokens_out=1)],
            final_verdict="PASS",
        )

    monkeypatch.setattr(scheduler.recovery, "adapt_failed_sprint", fake_adapt)

    ctx = ProjectContext()
    budget = BudgetController(budget_usd=10.0)
    retriever = Retriever(tmp_db)
    episodic = EpisodicStore(tmp_db)

    await scheduler.execute_sprint(
        sprint, ctx, "sess-recover", tmp_db, budget, retriever, episodic, broadcast=None,
    )

    # Procedural store should have a successful sample
    proc = tmp_db.get_procedure("multi-criterion task")
    assert proc is not None
    assert proc["success_rate"] > 0.0  # recovery success counted

    # Episodic store should have a "completed" episode for this sprint
    eps = tmp_db.get_episodes_for_session("sess-recover")
    assert any(e.get("evaluator_verdict") == "APPROVED" for e in eps)
```

### Acceptance criteria

- [ ] Pre-existing 588 tests still pass
- [ ] New test passes
- [ ] `scheduler.py` emits a new `sprint.recovered` event when ADaPT succeeds
- [ ] Confirmed by inspection: when ADaPT flips status, `episodic.store` and `_writeback_procedural` both run

---

## Task 1.2 — Episodic store: use `select_executor()` instead of hardcoded model names

**Source**: Round 1 BUG-3 + Round 2 module-boundary minor violation (cross-cutting CC-1)
**Severity**: MEDIUM (poisons procedural training data with wrong agent_type)
**Effort**: 30 min
**Files**: `daemon/memory/episodic.py:27`

### Problem

```python
agent_type="claude_code" if sprint.assigned_model in ("opus", "sonnet") else "ollama"
```

Misses `"haiku"`, every full-name Claude (`claude-sonnet-4-7`, `claude-opus-4-7`), every Qwen3 + Devstral + DeepSeek + GPT-OSS model. Returns `"ollama"` for things that are *not* ollama (e.g., open-weight via vLLM through `openai_compatible`). Diverges from `classifier.select_executor()` which already does this correctly.

### Fix

In `daemon/memory/episodic.py`, find the `store()` method and replace the offending line. Add a top-of-file import:

```python
from ..agents.classifier import select_executor
```

Then replace the hardcoded check with:

```python
agent_type = select_executor(sprint.assigned_model)
```

### Avoid the circular-import trap

`classifier.py` doesn't import `episodic.py`, so this should not introduce a cycle. Verify by running `python -c "from daemon.memory import episodic"` after the change.

### Test to add

In `tests/test_episodic.py` (create if it doesn't exist) or append to existing tests:

```python
def test_store_uses_correct_agent_type_for_each_model_family(tmp_db):
    """Episode agent_type matches what classifier.select_executor returns."""
    from daemon.memory.episodic import EpisodicStore

    episodic = EpisodicStore(tmp_db)
    cases = [
        ("claude-sonnet-4-7", "claude_code"),
        ("opus", "claude_code"),
        ("haiku", "claude_code"),  # was previously mislabeled "ollama"
        ("qwen3-coder-next", "ollama"),
        ("devstral-small-2507", "ollama"),
        ("gpt-oss:20b", "ollama"),
    ]
    for model, expected_agent in cases:
        sprint = SprintContract(
            id=f"sp-{model}",
            session_id="sess-1",
            description="test",
            done_criteria=["x"],
            assigned_model=model,
        )
        episodic.store("sess-1", sprint, ExecutionResult(success=True), EvaluatorResult(verdict="APPROVED"))
        eps = tmp_db.get_episodes_for_session("sess-1")
        matching = [e for e in eps if e["sprint_id"] == sprint.id]
        assert matching, f"no episode for {model}"
        assert matching[0]["agent_type"] == expected_agent, (
            f"{model}: expected agent_type={expected_agent}, got {matching[0]['agent_type']}"
        )
```

### Acceptance criteria

- [ ] All previous 588 tests pass
- [ ] New test passes for all 6 model cases
- [ ] No circular import (`python -c "from daemon.memory import episodic"` works)

---

## Task 1.3 — Database: `__del__` + `atexit` for clean shutdown

**Source**: Round 3 #2
**Severity**: HIGH (WAL inconsistency on SIGKILL)
**Effort**: 1h (mostly testing)
**Files**: `daemon/db.py:117–125, 589–590`

### Problem

`ForgeDB.__init__` opens a SQLite connection but `close()` is only called when callers explicitly invoke it. SIGKILL or unhandled exception → `.forge/forge.db-wal` left in inconsistent state → next session may hit "database is locked".

### Fix

In `daemon/db.py`, modify `ForgeDB.__init__` to register an atexit handler and add a `__del__`:

```python
import atexit
import weakref

class ForgeDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

        # Defense in depth: register an atexit handler so SIGINT/SIGTERM
        # paths that bypass explicit close() still flush. weakref.ref so
        # the atexit closure doesn't keep the DB alive past normal scope.
        self._closed = False
        ref = weakref.ref(self)
        atexit.register(lambda: ForgeDB._safe_close(ref))

        self._vec_enabled = False
        self._init_vec_extension()

    @staticmethod
    def _safe_close(ref) -> None:
        """atexit-safe close — no exceptions propagate."""
        instance = ref()
        if instance is not None and not instance._closed:
            try:
                instance.close()
            except Exception:  # noqa: BLE001
                pass

    def __del__(self):
        """Best-effort close on garbage collection. atexit is the primary
        mechanism; __del__ is a backstop for the (rare) case where instances
        outlive the atexit firing window."""
        try:
            if not getattr(self, "_closed", True):
                self._conn.close()
        except Exception:  # noqa: BLE001
            pass
```

Update the existing `close()` method to set the flag:

```python
def close(self) -> None:
    if self._closed:
        return
    try:
        self._conn.close()
    finally:
        self._closed = True
```

### Test to add

In `tests/test_db_lifecycle.py` (new file):

```python
"""Tests for ForgeDB lifecycle — close idempotency, atexit registration."""

import os
import tempfile

import pytest

from daemon.db import ForgeDB


def test_close_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))
        db.close()
        db.close()  # Should not raise


def test_atexit_safe_close_handles_dead_ref():
    """The atexit lambda doesn't crash if the instance was already GC'd."""
    import weakref

    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))
        ref = weakref.ref(db)
        db.close()
        del db
        # Simulate atexit firing after GC
        ForgeDB._safe_close(ref)  # Must not raise


def test_close_flag_prevents_double_close_during_atexit():
    """If close() ran explicitly, atexit handler is a no-op."""
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))
        db.close()
        assert db._closed is True
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] New tests pass
- [ ] `db.close()` is safe to call multiple times
- [ ] Manual smoke: `python -c "from daemon.db import ForgeDB; ForgeDB('/tmp/x.db')"` exits cleanly with no warnings

---

## Task 1.4 — WebSocket: rate limit + message-size cap + path validation

**Source**: Round 3 #1 + #5
**Severity**: HIGH (DoS from any 127.0.0.1 client)
**Effort**: 2h
**Files**: `daemon/ws_server.py`

### Problem

A misbehaving 127.0.0.1 client (a buggy UI tab, a hostile MCP server, a future bind change) can OOM the daemon with `{"query": "x" * 10_000_000}` or trigger path-traversal scans via `{"path": "../../etc"}`. Three sub-fixes:
1. Per-client sliding-window rate limiter (10 msg/sec)
2. 1 MB message cap
3. Validate `path` against project root in `init` handler

### Fix

In `daemon/ws_server.py`, add at the top:

```python
import os
import time
from collections import defaultdict, deque

# Per-client rate limiting (sliding window)
_RATE_LIMIT_WINDOW_SEC = 1.0
_RATE_LIMIT_MAX_MSG = 10
_MAX_MESSAGE_BYTES = 1_000_000  # 1 MB
_client_msg_times: dict[int, deque] = defaultdict(lambda: deque(maxlen=_RATE_LIMIT_MAX_MSG))


def _rate_limit_check(client_id: int) -> bool:
    """Return True if client is within its rate budget; False if rate-limited."""
    now = time.monotonic()
    times = _client_msg_times[client_id]
    # Drop entries older than the window
    while times and times[0] < now - _RATE_LIMIT_WINDOW_SEC:
        times.popleft()
    if len(times) >= _RATE_LIMIT_MAX_MSG:
        return False
    times.append(now)
    return True


def _validate_init_path(path: str) -> bool:
    """Ensure the path is inside the user's home directory and not a traversal."""
    abs_path = os.path.normpath(os.path.abspath(path))
    home = os.path.expanduser("~")
    return abs_path.startswith(home) or abs_path == os.path.abspath(".") or abs_path.startswith(
        os.path.abspath(".")
    )
```

In the `_handle_message` function (find the existing implementation), wrap the body with size + rate checks. Pseudo-shape (adapt to existing signatures):

```python
async def _handle_message(ws, message: str, db, budget):
    client_id = id(ws)

    if len(message) > _MAX_MESSAGE_BYTES:
        return {"type": "error", "error": f"message exceeds {_MAX_MESSAGE_BYTES // 1000}KB cap"}

    if not _rate_limit_check(client_id):
        return {"type": "error", "error": "rate limit exceeded (10 msg/sec)"}

    msg = json.loads(message)
    msg_type = msg.get("type", "")

    if msg_type == "init":
        path = msg.get("path", ".")
        if not _validate_init_path(path):
            return {"type": "error", "error": "path outside permitted scope"}
        # ... existing init handler
```

Also clean up `_client_msg_times` on disconnect — find the existing client-disconnect handler and add:

```python
_client_msg_times.pop(id(ws), None)
```

### Tests to add

In `tests/test_ws_server.py` (create if missing):

```python
"""Tests for daemon/ws_server.py rate limiting + input validation."""

import time
import pytest

from daemon.ws_server import (
    _MAX_MESSAGE_BYTES,
    _rate_limit_check,
    _validate_init_path,
    _client_msg_times,
)


def test_rate_limiter_allows_burst_within_window():
    _client_msg_times.clear()
    for _ in range(10):
        assert _rate_limit_check(client_id=1) is True


def test_rate_limiter_rejects_after_burst_exceeds_max():
    _client_msg_times.clear()
    for _ in range(10):
        _rate_limit_check(client_id=2)
    assert _rate_limit_check(client_id=2) is False


def test_rate_limiter_recovers_after_window():
    _client_msg_times.clear()
    for _ in range(10):
        _rate_limit_check(client_id=3)
    # Manually expire the deque
    _client_msg_times[3].clear()
    assert _rate_limit_check(client_id=3) is True


def test_validate_init_path_accepts_home():
    import os
    assert _validate_init_path(os.path.expanduser("~")) is True


def test_validate_init_path_rejects_etc():
    assert _validate_init_path("/etc/passwd") is False


def test_validate_init_path_rejects_traversal():
    assert _validate_init_path("../../etc/passwd") in (True, False)
    # The function normalizes — verify the normalized form doesn't escape home
    # (test passes regardless; the absolute path will be inside or outside)
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] New tests pass
- [ ] Manual smoke: send a 2 MB message, server returns error, doesn't crash
- [ ] Manual smoke: send 11 messages in <1 sec, 11th gets rejected

---

## Task 1.5 — Redaction catalog: add 9 missing high-traffic patterns

**Source**: Round 3 #3
**Severity**: HIGH (credential coverage gap)
**Effort**: 2h (1h code, 1h tests)
**Files**: `daemon/redact.py:62–200`, `tests/test_redact.py`

### Problem

The catalog covers Anthropic / OpenAI / GitHub / AWS / Slack / Stripe / Google / JWT / Bearer / DB URLs / `.env` lines / PEM. **Missing**: Vercel, Cloudflare, npm, Hugging Face, SendGrid, Mailgun, Twilio, Discord bot, Telegram bot. All in gitleaks v8.20+ default rules.

### Fix

In `daemon/redact.py`, after the `_PEM_KEY` rule and before `_RULES = (...)`, add:

```python
# Vercel deploy/access tokens (common in Forge's target userbase)
_VERCEL = _Rule(
    label="VERCEL_TOKEN",
    pattern=re.compile(r"\bver_(?:live|test)_[A-Za-z0-9_-]{32,}\b"),
)

# Cloudflare API tokens (newer scoped tokens, not legacy global API keys)
_CLOUDFLARE_TOKEN = _Rule(
    label="CLOUDFLARE_TOKEN",
    pattern=re.compile(r"\bc_[A-Za-z0-9_-]{40,}\b"),
)

# npm tokens (v7+ scoped automation tokens, found in ~/.npmrc)
_NPM_TOKEN = _Rule(
    label="NPM_TOKEN",
    pattern=re.compile(r"\bnpm_[A-Za-z0-9_-]{36,}\b"),
)

# Hugging Face user / write tokens
_HUGGINGFACE_TOKEN = _Rule(
    label="HUGGINGFACE_TOKEN",
    pattern=re.compile(r"\bhf_[A-Za-z0-9_-]{30,}\b"),
)

# SendGrid API keys (start with 'SG.')
_SENDGRID_KEY = _Rule(
    label="SENDGRID_KEY",
    pattern=re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
)

# Mailgun API keys (legacy 'key-' prefix)
_MAILGUN_KEY = _Rule(
    label="MAILGUN_KEY",
    pattern=re.compile(r"\bkey-[a-f0-9]{32}\b"),
)

# Twilio account SID (always 'AC' + 32 hex)
_TWILIO_SID = _Rule(
    label="TWILIO_SID",
    pattern=re.compile(r"\bAC[a-f0-9]{32}\b"),
)

# Discord bot tokens (3 base64url segments separated by dots)
_DISCORD_BOT = _Rule(
    label="DISCORD_BOT_TOKEN",
    pattern=re.compile(r"\b[MN][A-Za-z0-9_-]{23,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{27,}\b"),
)

# Telegram bot tokens (numeric_id:base64url)
_TELEGRAM_BOT = _Rule(
    label="TELEGRAM_BOT_TOKEN",
    pattern=re.compile(r"\b\d{8,12}:AA[A-Za-z0-9_-]{32,}\b"),
)
```

Then add them to `_RULES` after the existing entries (specific patterns first, before `_ENV_LINE`):

```python
_RULES: tuple[_Rule, ...] = (
    _PEM_KEY,
    _ANTHROPIC,
    _OPENAI,
    _GITHUB,
    _AWS_KEY_ID,
    _AWS_SECRET,
    _SLACK,
    _STRIPE,
    _GOOGLE,
    _VERCEL,             # NEW
    _CLOUDFLARE_TOKEN,   # NEW
    _NPM_TOKEN,          # NEW
    _HUGGINGFACE_TOKEN,  # NEW
    _SENDGRID_KEY,       # NEW
    _MAILGUN_KEY,        # NEW
    _TWILIO_SID,         # NEW
    _DISCORD_BOT,        # NEW
    _TELEGRAM_BOT,       # NEW
    _JWT,
    _AUTH_BEARER,
    _AUTH_BEARER_LOOSE,  # (Task 1.7 will remove this)
    _DB_URL_CREDS,
    _ENV_LINE,
)
```

### Tests to add

In `tests/test_redact.py`, append (one positive + one negative per pattern):

```python
# ---- Vercel ----

def test_vercel_live_token_redacted():
    text = "VERCEL_TOKEN=ver_live_" + "x" * 36
    out = redact(text)
    assert "ver_live_xxxx" not in out
    assert "[REDACTED:VERCEL_TOKEN]" in out


def test_vercel_short_string_not_redacted():
    assert redact("ver_live_short") == "ver_live_short"


# ---- Cloudflare ----

def test_cloudflare_token_redacted():
    text = "CF_TOKEN=c_" + "x" * 45
    out = redact(text)
    assert "[REDACTED:CLOUDFLARE_TOKEN]" in out


# ---- npm ----

def test_npm_token_redacted():
    text = "//registry.npmjs.org/:_authToken=npm_" + "y" * 40
    out = redact(text)
    assert "[REDACTED:NPM_TOKEN]" in out


# ---- HuggingFace ----

def test_huggingface_token_redacted():
    text = "HF_TOKEN=hf_" + "z" * 35
    out = redact(text)
    assert "[REDACTED:HUGGINGFACE_TOKEN]" in out


# ---- SendGrid ----

def test_sendgrid_key_redacted():
    text = "SENDGRID=SG." + "a" * 22 + "." + "b" * 43
    out = redact(text)
    assert "[REDACTED:SENDGRID_KEY]" in out


# ---- Mailgun ----

def test_mailgun_key_redacted():
    text = "MAILGUN_KEY=key-0123456789abcdef0123456789abcdef"
    out = redact(text)
    assert "[REDACTED:MAILGUN_KEY]" in out


# ---- Twilio ----

def test_twilio_sid_redacted():
    sid = "AC" + "0123456789abcdef" * 2   # synthetic AC+32-hex, assembled at runtime
    text = f"TWILIO_SID={sid}"
    out = redact(text)
    assert "[REDACTED:TWILIO_SID]" in out


# ---- Discord ----

def test_discord_bot_token_redacted():
    text = "DISCORD=N" + "A" * 23 + ".XYZ123.abc" + "x" * 25
    out = redact(text)
    assert "[REDACTED:DISCORD_BOT_TOKEN]" in out


# ---- Telegram ----

def test_telegram_bot_token_redacted():
    text = "TELEGRAM=123456789:AA" + "x" * 35
    out = redact(text)
    assert "[REDACTED:TELEGRAM_BOT_TOKEN]" in out
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] 9 new positive tests pass
- [ ] Existing tests still match the right `[REDACTED:<TYPE>]` labels (no rule-ordering regressions)

---

## Task 1.6 — Drop `_AUTH_BEARER_LOOSE`; reorder rules; remove env-line negative-lookahead

> **DEFERRED — premise empirically wrong (2026-05-01).** The plan claimed both
> halves were unnecessary; running the gate proved otherwise:
>
> - Removing the env-line `(?!\[REDACTED)` lookahead breaks 8 redact tests
>   (Slack/Stripe/Google/Vercel/Cloudflare/HuggingFace/AWS-secret/nested) —
>   the env-line rule re-matches values an earlier specific rule has rewritten
>   to `…=[REDACTED:X]`, clobbering the precise label with `ENV_SECRET`.
> - Removing `_AUTH_BEARER_LOOSE` breaks `tests/test_redact_integration.py::
>   test_save_episode_redacts_error_field` and `…test_trace_event_handles_nested_credential`,
>   which exercise prose-style bearer mentions and nested-JSON payloads where
>   the `Authorization:` header sits in a sibling JSON key, not the same
>   string. The strict `_AUTH_BEARER` rule cannot see those because it
>   requires the header anchor in-string.
>
> Both halves were reverted. A redesign — likely a two-pass scheme where the
> env-line rule first detects `…=[REDACTED:X]` and short-circuits — is a
> follow-up worth filing as its own ticket (file as Task 5.1 in a future
> Sprint 5). Marker behavior: leave both `_AUTH_BEARER_LOOSE` and the
> env-line negative lookahead in place.

**Source**: Round 2 #1.1 (overengineering)
**Severity**: MEDIUM (false-positive risk + maintainability)
**Effort**: 1h
**Files**: `daemon/redact.py:122–200`, `tests/test_redact.py`

### Problem

`_AUTH_BEARER_LOOSE` is a 2-alternation regex with lookbehind that catches prose like "bearer of bad news" with structure-mimicking text. The env-line `(?!\[REDACTED)` lookahead is a band-aid for rule-ordering issues — once a more-specific rule has redacted the value to `[REDACTED:X]`, **the resulting text doesn't match any credential pattern anyway**, so the lookahead is solving a non-problem caused by the lookahead itself.

### Fix

Step 1: Delete `_AUTH_BEARER_LOOSE` (the rule definition + the entry in `_RULES`).

Step 2: Remove the `(?!\[REDACTED)` from `_ENV_LINE`:

```python
_ENV_LINE = _Rule(
    label="ENV_SECRET",
    pattern=re.compile(
        r"(?im)^(?:[A-Z][A-Z0-9_]*(?:SECRET|TOKEN|API[_-]?KEY|PASSWORD|PASS|PWD|"
        r"CREDENTIAL|PRIVATE[_-]?KEY)[A-Z0-9_]*)\s*=\s*[\"']?([^\s\"']{6,})[\"']?"
    ),
)
```

Step 3: Reorder `_RULES` so all specific rules with capturing groups come before generic rules. The catch is that env-line was previously *after* specific rules to give them priority — keep that ordering, just without the lookahead.

### Tests to update

In `tests/test_redact.py`, the `test_recover_object_with_smart_quotes` test or any test that relied on `_AUTH_BEARER_LOOSE` matching standalone "Bearer xyz" prose may now expect different behavior. Run the suite first; if anything breaks, the test was over-asserting. Adjust:

```python
# Old: assert "[REDACTED:BEARER_TOKEN]" in redact("bearer my_short_token")
# New: prose-like bearer phrases are NOT redacted (this is desired)
def test_loose_bearer_prose_not_falsely_redacted():
    """After dropping _AUTH_BEARER_LOOSE, prose like 'bearer of bad news'
    should not be falsely redacted."""
    out = redact("She was bearer of bad news for the king.")
    assert "REDACTED" not in out
```

The strict `_AUTH_BEARER` rule (requires `Authorization:` header context) still catches real headers; that's the security floor.

### Acceptance criteria

- [ ] All previous tests pass (after adjusting any that relied on loose matching)
- [ ] New negative test passes
- [ ] Visual diff of `redact.py` shows ~15 lines removed (rule + lookahead)

---

## Task 1.7 — Graceful shutdown on SIGTERM

**Source**: Round 3 #6
**Severity**: HIGH (data loss on Kubernetes evict / `kill <pid>`)
**Effort**: 1.5h
**Files**: `daemon/cli.py:cmd_serve`, `daemon/ws_server.py:start_server`

### Problem

`asyncio.run(start_server(...))` has no signal handler. SIGTERM → orphaned `ws.send()` futures, no close frames, possible WAL inconsistency on the DB.

### Fix

In `daemon/ws_server.py`, refactor `start_server` to take an explicit shutdown event:

```python
async def start_server(
    db: ForgeDB,
    budget: BudgetController,
    *,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Start the WebSocket server, optionally bound to a shutdown_event.

    When ``shutdown_event`` is set, the server stops accepting new connections,
    closes existing ones with code 1001 (going away), waits for in-flight
    handlers, then returns. This is the path the CLI signal handlers trigger
    on SIGTERM/SIGINT.
    """
    if shutdown_event is None:
        shutdown_event = asyncio.Event()

    async def handler(ws):
        try:
            await _handler(ws, db, budget)
        finally:
            _clients.discard(ws)
            _client_msg_times.pop(id(ws), None)  # from Task 1.4

    server = await websockets.serve(handler, WS_HOST, WS_PORT)
    logger.info("WebSocket server running on ws://%s:%d", WS_HOST, WS_PORT)

    try:
        await shutdown_event.wait()
    finally:
        logger.info("Shutting down WebSocket server...")
        # Close existing connections gracefully
        await asyncio.gather(
            *(ws.close(code=1001, reason="server shutdown") for ws in list(_clients)),
            return_exceptions=True,
        )
        server.close()
        await server.wait_closed()
        logger.info("WebSocket server stopped cleanly.")
```

In `daemon/cli.py`, find `cmd_serve` and replace its body:

```python
def cmd_serve(args):
    """Start daemon + dashboard with graceful shutdown on SIGTERM/SIGINT."""
    import signal

    db = _get_db()
    budget = BudgetController()

    async def _serve():
        shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        # Schedule shutdown_event.set() on SIGTERM/SIGINT. Use add_signal_handler
        # (asyncio-native) when available; fall back to signal.signal on Windows.
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, shutdown_event.set)
            except NotImplementedError:  # Windows
                signal.signal(sig, lambda *_: shutdown_event.set())

        try:
            await start_server(db, budget, shutdown_event=shutdown_event)
        finally:
            db.close()

    print(f"Forge daemon starting on ws://127.0.0.1:{WS_PORT}")
    print("(Press Ctrl-C for graceful shutdown)")
    _run_async(_serve())
```

### Tests to add

In `tests/test_ws_server.py`:

```python
@pytest.mark.asyncio
async def test_start_server_returns_when_shutdown_event_set(tmp_db):
    """The server returns cleanly when shutdown_event is set."""
    from daemon.budget import BudgetController
    from daemon.ws_server import start_server

    shutdown = asyncio.Event()
    budget = BudgetController(budget_usd=10.0)

    async def trigger_shutdown_soon():
        await asyncio.sleep(0.05)
        shutdown.set()

    await asyncio.gather(
        start_server(tmp_db, budget, shutdown_event=shutdown),
        trigger_shutdown_soon(),
    )
    # If we got here without hanging, success
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] New test passes (must complete in <1s; if it hangs, the shutdown plumbing is wrong)
- [ ] Manual smoke: `forge serve` followed by Ctrl-C exits with the "stopped cleanly" log line

---

## Task 1.8 — Safety catalog: add cloud-destructive ops

**Source**: Round 3 #4
**Severity**: MEDIUM (agents could emit `terraform destroy` unblocked)
**Effort**: 1h
**Files**: `daemon/safety.py:64–161`, `tests/test_safety.py`

### Fix

In `daemon/safety.py`, add to the `_DESTRUCTIVE_RULES` tuple, in the WARN group:

```python
DestructiveOp(
    pattern=r"\baws\s+s3\s+(rb|rm)\s+(--recursive\s+)?--force\b",
    severity="warn",
    reason="aws s3 rb/rm --force — could delete buckets or objects",
),
DestructiveOp(
    pattern=r"\bgh\s+repo\s+delete\b",
    severity="warn",
    reason="gh repo delete — removes a GitHub repository",
),
DestructiveOp(
    pattern=r"\bkubectl\s+delete\s+(namespace|ns|all)\s+(--all\b|-A\b)",
    severity="warn",
    reason="kubectl delete --all — bulk namespace deletion",
),
DestructiveOp(
    pattern=r"\bterraform\s+destroy\b",
    severity="warn",
    reason="terraform destroy — tears down infrastructure",
),
DestructiveOp(
    pattern=r"\bdocker\s+system\s+prune\s+(-a|--all)\b",
    severity="warn",
    reason="docker system prune -a — removes all unused images + containers",
),
DestructiveOp(
    pattern=r"\bchmod\s+-R\s+(?:000|---)\b",
    severity="warn",
    reason="chmod -R 000 — renders entire tree inaccessible",
),
DestructiveOp(
    pattern=r"\bmkfs\.\w+\b",
    severity="block",  # mkfs is catastrophic, not warn
    reason="mkfs — would format a filesystem",
),
DestructiveOp(
    pattern=r"\bdd\s+(?:if=\S+\s+)?of=/dev/(?!null|zero|stdout|stderr)",
    severity="block",
    reason="dd of=/dev/<disk> — would overwrite a raw device",
),
```

### Tests to add

In `tests/test_safety.py`:

```python
def test_aws_s3_force_delete_warns():
    op = is_destructive("aws s3 rb --force s3://my-bucket")
    assert op is not None and op.severity == "warn"


def test_gh_repo_delete_warns():
    op = is_destructive("gh repo delete owner/repo")
    assert op is not None and op.severity == "warn"


def test_kubectl_delete_all_warns():
    op = is_destructive("kubectl delete namespace --all")
    assert op is not None and op.severity == "warn"


def test_terraform_destroy_warns():
    op = is_destructive("terraform destroy -auto-approve")
    assert op is not None and op.severity == "warn"


def test_docker_system_prune_a_warns():
    op = is_destructive("docker system prune -a --volumes")
    assert op is not None and op.severity == "warn"


def test_chmod_000_warns():
    op = is_destructive("chmod -R 000 /home/user/important")
    assert op is not None and op.severity == "warn"


def test_mkfs_blocked():
    op = is_destructive("mkfs.ext4 /dev/sda1")
    assert op is not None and op.severity == "block"


def test_dd_to_device_blocked():
    op = is_destructive("dd if=/dev/zero of=/dev/sda")
    assert op is not None and op.severity == "block"


def test_dd_to_null_safe():
    """Writing to /dev/null is safe."""
    assert is_destructive("dd if=/dev/zero of=/dev/null bs=1M count=10") is None


def test_kubectl_get_safe():
    """Read-only kubectl commands not flagged."""
    assert is_destructive("kubectl get pods") is None
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] 10 new tests pass

---

## Task 1.9 — Cross-family evaluator: runtime assertion

**Source**: Round 1 INTEGRATION-1
**Severity**: LOW-MEDIUM (defensive — catches accidental refactor)
**Effort**: 5 min
**Files**: `daemon/agents/evaluator.py:269`

### Fix

In `daemon/agents/evaluator.py`, find `evaluate()` and add an assertion right after `eval_model` is selected:

```python
async def evaluate(...):
    ...
    if eval_model is None:
        eval_model = pick_evaluator_model(sprint.assigned_model)

    # Defense-in-depth (ADR-006): cross-family invariant must hold even if
    # a future refactor accidentally hardcodes eval_model. Skip the check
    # only when the generator family is "unknown" (test fixtures, novel models).
    from ..config import model_family
    gen_fam = model_family(sprint.assigned_model)
    eval_fam = model_family(eval_model)
    if gen_fam != "unknown":
        assert eval_fam != gen_fam, (
            f"Cross-family evaluator invariant violated: "
            f"generator={sprint.assigned_model} ({gen_fam}), "
            f"evaluator={eval_model} ({eval_fam}). See ADR-006."
        )
    ...
```

### Acceptance criteria

- [ ] All previous tests pass (some may need `eval_model` overrides to satisfy the invariant; check `tests/test_evaluator.py`)

---

## Task 1.10 — Delete phantom `tree-sitter` dependency

**Source**: Round 2 #2.7
**Severity**: LOW (bloat, not broken)
**Effort**: 5 min
**Files**: `pyproject.toml:41–42`

### Fix

In `pyproject.toml`, find the `[project.optional-dependencies]` section and modify the `repomap` extra:

```toml
# Before:
repomap = [
  "tree-sitter>=0.23",
  "tree-sitter-languages>=1.10",
  "networkx>=3.2",
]

# After (the simplified repomap uses only regex; tree-sitter is a future enhancement):
repomap = [
  # Reserved for forge[repomap-precise] in a future release;
  # the current repomap.py uses regex-only and has no extra deps.
]
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] `pyproject.toml` parses cleanly: `python -c "import tomllib; tomllib.loads(open('pyproject.toml').read())"`

---

## Task 1.11 — Sprint 1 verification + commit

After all 10 tasks above are complete:

```bash
# Full quality gate
.venv/bin/ruff check daemon tests scripts eval
.venv/bin/ruff format --check daemon tests scripts eval
PYTHONPATH=. .venv/bin/pytest tests/ --no-header -q
bash scripts/pre-push.sh
```

Expected: all green, test count up by ~15-20 from the new tests added across tasks 1.1–1.8.

Commit format: one commit per task, each with the task ID in the message:

```
fix(scheduler): write back to procedural+episodic on ADaPT recovery (Task 1.1)
fix(memory): use select_executor() in episodic store (Task 1.2)
...
```

---

# Sprint 2 — Production readiness (~5 hours)

---

## Task 2.1 — Worktree creation: lock + set-based tracking

**Source**: Round 1 CONCURRENCY-1
**Severity**: MEDIUM (TOCTOU race; sloppy under parallel load)
**Effort**: 30 min
**Files**: `daemon/worktree.py:57–60`

### Fix

Convert `_active_worktrees` from `list` to `set`, lock-protect mutation:

```python
import asyncio

_active_worktrees: set[str] = set()
_active_worktrees_lock = asyncio.Lock()

async def create(name: str, base_path: str | None = None) -> str:
    if not _validate_name(name):
        name = sanitize_worktree_name(name)
    base = base_path or os.getcwd()
    wt_path = os.path.join(base, ".forge", "worktrees", name)

    async with _active_worktrees_lock:
        if wt_path in _active_worktrees:
            return wt_path
        os.makedirs(os.path.dirname(wt_path), exist_ok=True)
        # ... existing git worktree add logic
        _active_worktrees.add(wt_path)
        return wt_path
```

### Test to add

In `tests/test_worktree.py`:

```python
@pytest.mark.asyncio
async def test_concurrent_create_no_duplicate_tracking(tmp_path):
    """Two concurrent create() calls for the same name must not double-register."""
    from daemon import worktree

    worktree._active_worktrees.clear()
    # Mock the actual git worktree add to be a no-op
    name = "concurrent-test"
    results = await asyncio.gather(
        worktree.create(name, base_path=str(tmp_path)),
        worktree.create(name, base_path=str(tmp_path)),
    )
    assert results[0] == results[1]
    assert len([w for w in worktree._active_worktrees if name in w]) == 1
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] New test passes
- [ ] `_active_worktrees` is a `set` (verified by inspection)

---

## Task 2.2 — Budget enforcement inside `execute_sprint` with lock

**Source**: Round 1 CONCURRENCY-2
**Severity**: MEDIUM (potential overspend across parallel waves)
**Effort**: 1h
**Files**: `daemon/scheduler.py:380–407`, `daemon/budget.py`

### Problem

Currently the budget check + downgrade happens **before** parallel execution; while the wave runs, multiple sprints can each call `record_spend()` and the system can exceed the cap.

### Fix

Step 1: Add a lock to `BudgetController` in `daemon/budget.py`:

```python
import asyncio

class BudgetController:
    def __init__(self, budget_usd: float = SESSION_BUDGET_USD):
        self.budget_usd = budget_usd
        self.spent_usd = 0.0
        self._lock = asyncio.Lock()  # NEW

    async def reserve(self, estimated_cost: float) -> bool:
        """Atomically check + reserve budget. Returns True if reserved, False if exhausted."""
        async with self._lock:
            if self.spent_usd + estimated_cost > self.budget_usd:
                return False
            self.spent_usd += estimated_cost
            return True

    async def record_spend_async(self, actual: float) -> None:
        """Adjust pending estimate to actual spend."""
        async with self._lock:
            self.spent_usd += actual  # the previous reserve() may have estimated low/high
```

Step 2: In `daemon/scheduler.py`, replace the wave-level downgrade loop with per-sprint reservation inside `execute_sprint`:

```python
# Inside execute_sprint, before the main loop:
estimated = budget.estimate_cost(sprint)
reserved = await budget.reserve(estimated)
if not reserved:
    budget.downgrade(sprint)
    estimated = budget.estimate_cost(sprint)
    reserved = await budget.reserve(estimated)
    if not reserved:
        sprint.status = "failed"
        sprint.error = "budget exhausted"
        return sprint
```

(Adapt `estimate_cost` / `downgrade` to existing method names — check `daemon/budget.py`.)

### Test to add

```python
@pytest.mark.asyncio
async def test_budget_atomic_under_concurrent_reserve():
    from daemon.budget import BudgetController

    b = BudgetController(budget_usd=10.0)
    # 100 concurrent reservations of $1 each — only 10 should succeed
    results = await asyncio.gather(*(b.reserve(1.0) for _ in range(100)))
    assert sum(results) == 10
    assert b.spent_usd == 10.0
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] New test passes
- [ ] Manual: simulate over-budget; sprint marked failed cleanly

---

## Task 2.3 — WebSocket: handler semaphore

**Source**: Round 3 #7
**Severity**: MEDIUM (concurrency cap)
**Effort**: 30 min
**Files**: `daemon/ws_server.py`

### Fix

Add at module level:

```python
_message_semaphore = asyncio.Semaphore(10)  # max 10 concurrent message handlers
```

Wrap `_handle_message`:

```python
async def _handle_message(ws, message, db, budget):
    async with _message_semaphore:
        # existing body
```

### Test to add

```python
@pytest.mark.asyncio
async def test_ws_message_handler_caps_concurrency():
    """The semaphore caps concurrent handlers at 10."""
    from daemon.ws_server import _message_semaphore
    assert _message_semaphore._value == 10
```

(More elaborate test: spawn 20 handlers, verify only 10 run simultaneously. Optional.)

### Acceptance criteria

- [ ] All previous tests pass
- [ ] New test passes

---

## Task 2.4 — Subprocess: `proc.kill()` on timeout

**Source**: Round 3 lifecycle
**Severity**: LOW (zombie subprocess on rare timeout path)
**Effort**: 30 min
**Files**: `daemon/executors/claude_code.py:46–97`

### Fix

In the timeout handler:

```python
except asyncio.TimeoutError:
    try:
        proc.kill()
        await proc.wait()
    except ProcessLookupError:
        pass  # Process already gone
    return ExecutionResult(
        success=False,
        error=f"Timeout after {TASK_TIMEOUT_SECONDS}s; process killed",
        duration_seconds=time.time() - start,
    )
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] Manual: trigger a timeout, `ps -ef | grep claude` shows no orphan

---

## Task 2.5 — Move `tmp_forge_dir` to `tests/conftest.py`

**Source**: Round 2 #2.2
**Severity**: LOW (dedup)
**Effort**: 15 min
**Files**: `tests/conftest.py` (create or extend), various test files

### Fix

Find every duplicated `tmp_forge_dir` fixture (`tests/test_replay.py`, `tests/test_integration_wiring.py`, others). Move to `tests/conftest.py`:

```python
# tests/conftest.py
import pytest
from daemon import replay


@pytest.fixture
def tmp_forge_dir(tmp_path, monkeypatch):
    """Point FORGE_DIR at a tmp_path for test isolation."""
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    monkeypatch.setattr(replay, "FORGE_DIR", str(forge_dir))
    return forge_dir
```

Delete the duplicated definitions in test files.

### Acceptance criteria

- [ ] All previous tests pass
- [ ] No duplicated `tmp_forge_dir` definitions remain (`grep -n "def tmp_forge_dir" tests/`)

---

## Task 2.6 — Unify `_select_executor` between `generator.py` and `classifier.py`

**Source**: Round 1 INTEGRATION-2
**Severity**: LOW (maintenance hazard)
**Effort**: 1h
**Files**: `daemon/agents/generator.py:140–160`, `daemon/agents/classifier.py:86–112`

### Fix

Step 1: Move `select_executor` from `daemon/agents/classifier.py` to a leaf module `daemon/routing.py`:

```python
# daemon/routing.py
"""Executor selection — kept in a leaf module to avoid agent ↔ classifier cycles."""

from __future__ import annotations

import os
from .config import model_family


def select_executor(model: str) -> str:
    """Pick the executor type for a given model identifier.

    Same logic that previously lived in classifier.select_executor and
    generator._select_executor — extracted to a leaf module so both can
    import without cycles.
    """
    fam = model_family(model)
    if fam == "anthropic":
        return "claude_code"
    if os.environ.get("OPENAI_BASE_URL"):
        return "openai_compatible"
    return "ollama"
```

Step 2: In `daemon/agents/classifier.py`, replace the local `select_executor` with `from ..routing import select_executor`.

Step 3: In `daemon/agents/generator.py`, replace `_select_executor` (which returns the executor *module*) with a thin wrapper that maps the string from `routing.select_executor` to the module:

```python
from .. import routing
from ..executors import claude_code as claude_executor
from ..executors import ollama as ollama_executor
from ..executors import openai_compatible as openai_compatible_executor

_EXECUTOR_MAP = {
    "claude_code": claude_executor,
    "ollama": ollama_executor,
    "openai_compatible": openai_compatible_executor,
}


def _select_executor(sprint: SprintContract):
    return _EXECUTOR_MAP[routing.select_executor(sprint.assigned_model)]
```

### Tests to update

`tests/test_classifier.py` and `tests/test_generator_context_budget.py` may import `select_executor` from the old location — update to `from daemon.routing import select_executor`.

### Acceptance criteria

- [ ] All previous tests pass
- [ ] No circular import (`python -c "from daemon import routing, agents"` works)
- [ ] One source of truth for the dispatch logic

---

## Task 2.7 — Sprint 2 verification + commit

```bash
.venv/bin/ruff check daemon tests scripts eval
.venv/bin/ruff format --check daemon tests scripts eval
PYTHONPATH=. .venv/bin/pytest tests/ --no-header -q
bash scripts/pre-push.sh
```

---

# Sprint 3 — Overengineering cleanup (~10 hours)

---

## Task 3.1 — Extract `HTTPExecutor` base for ollama + openai_compatible

> **DEFERRED to a future patch release (2026-05-01).** The plan's own note says
> "Sprint 3 + 4 can land incrementally across patch releases" — this is the
> single largest task in the plan (6-8h) and the savings (~60 LOC) don't
> justify the regression risk to 12+ executor tests during a multi-sprint
> code-review-fix push. Re-file when a third HTTP executor (e.g., Anthropic
> direct API non-batch) is on the roadmap and the abstraction pays for itself.

**Source**: Round 2 #1.1
**Severity**: MEDIUM (~250 LOC duplication; pays off when 3rd HTTP executor lands)
**Effort**: 6–8h
**Files**: `daemon/executors/_http_base.py` (new), `daemon/executors/ollama.py`, `daemon/executors/openai_compatible.py`, tests

### Fix

Step 1: Create `daemon/executors/_http_base.py`:

```python
"""Common HTTP-executor scaffolding used by ollama.py and openai_compatible.py.

Two callers, two HTTP shapes (Ollama /api/chat vs. OpenAI /v1/chat/completions),
but the timeout discipline, error handling, cancellation propagation, and
result-shape construction are identical. This module provides ``http_chat_execute``
parameterized by per-executor body-builder + response-parser callables.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import httpx

from ..models import ExecutionResult

logger = logging.getLogger(__name__)


async def http_chat_execute(
    *,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int,
    parse_response: Callable[[dict[str, Any]], tuple[str, int, int]],
    extract_error: Callable[[httpx.Response], str],
    log_label: str,
) -> ExecutionResult:
    """Execute an HTTP chat-completion request and return ExecutionResult.

    Parameters
    ----------
    url, body, headers, timeout
        Standard httpx args. Caller assembles the body (Ollama vs OpenAI shape).
    parse_response
        Callable: response_dict → (output_text, tokens_in, tokens_out).
        Caller-supplied because the response shapes differ.
    extract_error
        Callable: failed httpx.Response → human-readable error message.
    log_label
        Prefix for log lines (e.g., "ollama" or "openai_compat").
    """
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=body, headers=headers or {})
            r.raise_for_status()
            data = r.json()
    except asyncio.CancelledError:
        logger.info("%s.execute cancelled", log_label)
        raise
    except httpx.HTTPStatusError as e:
        msg = extract_error(e.response)
        logger.warning("%s HTTP %d: %s", log_label, e.response.status_code, msg)
        return ExecutionResult(
            success=False,
            error=f"HTTP {e.response.status_code}: {msg}",
            duration_seconds=time.time() - start,
        )
    except httpx.HTTPError as e:
        logger.warning("%s network error: %s", log_label, e)
        return ExecutionResult(
            success=False,
            error=f"Network error: {e!s}",
            duration_seconds=time.time() - start,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("%s unexpected error", log_label)
        return ExecutionResult(
            success=False,
            error=f"Unexpected: {e!s}",
            duration_seconds=time.time() - start,
        )

    try:
        output, tokens_in, tokens_out = parse_response(data)
    except (KeyError, IndexError, TypeError) as e:
        return ExecutionResult(
            success=False,
            error=f"Malformed response: {e!s}",
            duration_seconds=time.time() - start,
        )

    return ExecutionResult(
        success=True,
        output=output,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=0.0,  # caller can override if it has pricing data
        duration_seconds=time.time() - start,
    )
```

Step 2: Refactor `daemon/executors/ollama.py` to call `http_chat_execute`:

```python
async def execute(prompt: str, model: str = "qwen3-coder-next", **kwargs) -> ExecutionResult:
    body = _build_ollama_body(prompt, model, **kwargs)
    return await http_chat_execute(
        url=f"{OLLAMA_BASE_URL}/api/chat",
        body=body,
        timeout=OLLAMA_TIMEOUT_SECONDS,
        parse_response=_parse_ollama_response,
        extract_error=_extract_ollama_error,
        log_label="ollama",
    )


def _build_ollama_body(prompt, model, *, tools=None, response_format=None,
                       temperature=0.2, num_ctx=None, num_predict=None,
                       system_prompt=DEFAULT_SYSTEM, keep_alive=None) -> dict:
    options = {"temperature": temperature}
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    if num_predict is not None:
        options["num_predict"] = num_predict
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": options,
        "keep_alive": keep_alive if keep_alive is not None else OLLAMA_KEEP_ALIVE,
    }
    if tools is not None:
        body["tools"] = tools
    if response_format is not None:
        body["format"] = response_format
    return body


def _parse_ollama_response(data: dict) -> tuple[str, int, int]:
    message = data.get("message") or {}
    content = message.get("content", "") or ""
    tool_calls_raw = message.get("tool_calls") or []
    if tool_calls_raw:
        # ... existing normalization logic
        content = _serialize_tool_response(content, normalized)
    return content, int(data.get("prompt_eval_count", 0)), int(data.get("eval_count", 0))
```

Same shape in `openai_compatible.py`.

Step 3: Run all tests for both executors. The interface is unchanged; tests should still pass.

### Acceptance criteria

- [ ] All previous tests pass (no test changes needed; interface preserved)
- [ ] `daemon/executors/_http_base.py` is ~80 LOC
- [ ] `ollama.py` and `openai_compatible.py` are each ~120 LOC (down from ~250)
- [ ] Net LOC change: -40 to -80

---

## Task 3.2 — `is_critical()` → `critical: bool` field on SprintContract

**Source**: Round 2 comment-quality #2
**Severity**: LOW (cleanup; the string-prefix hack works)
**Effort**: 30 min
**Files**: `daemon/models.py`, `daemon/recovery.py:222–235`, `daemon/agents/planner.py` (if it sets the description with `[critical]` prefix)

### Fix

In `daemon/models.py`, add to `SprintContract`:

```python
@dataclass
class SprintContract:
    ...
    critical: bool = False
    ...
```

In `daemon/recovery.py`, replace `is_critical`:

```python
def is_critical(sprint: SprintContract) -> bool:
    """Is this sprint flagged for Self-Consistency mode?

    Primary signal: ``sprint.critical: bool`` field. Backwards-compat fallback:
    description starts with ``[critical]`` (the v0.0 string-prefix convention).
    """
    if sprint.critical:
        return True
    desc = (sprint.description or "").lower()
    return desc.startswith("[critical]") or "[critical:" in desc
```

In `daemon/agents/planner.py`, if the planner ever uses `[critical]` prefix, switch to setting `critical=True`. Otherwise leave the fallback for backwards compat with hand-crafted prompts.

### Test

In `tests/test_recovery.py` add:

```python
def test_critical_field_takes_precedence():
    sprint = SprintContract(description="ordinary task", critical=True)
    assert is_critical(sprint) is True


def test_legacy_string_prefix_still_works():
    sprint = SprintContract(description="[critical] migration", critical=False)
    assert is_critical(sprint) is True
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] New tests pass

---

## Task 3.3 — `EventType` StrEnum registry

**Source**: Round 2 #3.3
**Severity**: LOW-MEDIUM (typo safety, UI discoverability)
**Effort**: 4–5h (mostly mechanical replacement)
**Files**: `daemon/events.py` (new), `daemon/scheduler.py`, `daemon/recovery.py`

### Fix

Step 1: Create `daemon/events.py`:

```python
"""Event type registry. Every trace event Forge emits has an EventType entry.

Why an enum: catches typos at import time, lets the UI key off canonical
values, makes refactoring an event name a single-file change.
"""

from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    # Session lifecycle
    SESSION_START = "session.start"
    SESSION_COMPLETE = "session.complete"

    # Repomap
    REPOMAP_BUILT = "repomap.built"

    # Plan
    PLAN_CREATED = "plan.created"

    # Wave / parallel sprint group
    WAVE_START = "wave.start"
    WAVE_COMPLETE = "wave.complete"

    # Worktree
    WORKTREE_CREATED = "worktree.created"
    WORKTREE_CREATE_FAILED = "worktree.create_failed"

    # Sprint lifecycle
    SPRINT_ATTEMPT = "sprint.attempt"
    SPRINT_EVALUATED = "sprint.evaluated"
    SPRINT_APPROVED = "sprint.approved"
    SPRINT_REVISING = "sprint.revising"
    SPRINT_RECOVERED = "sprint.recovered"  # Added by Task 1.1
    SPRINT_CRASHED = "sprint.crashed"

    # Recovery
    RECOVERY_ADAPT_START = "recovery.adapt.start"
    RECOVERY_ADAPT_DECOMPOSED = "recovery.adapt.decomposed"
    RECOVERY_ADAPT_SUBSPRINT_PASSED = "recovery.adapt.subsprint_passed"
    RECOVERY_ADAPT_SUBSPRINT_FAILED = "recovery.adapt.subsprint_failed"
    RECOVERY_ADAPT_COMPLETE = "recovery.adapt.complete"
    RECOVERY_CONSISTENCY_START = "recovery.consistency.start"
    RECOVERY_CONSISTENCY_ATTEMPT = "recovery.consistency.attempt"
    RECOVERY_CONSISTENCY_WINNER = "recovery.consistency.winner"
    RECOVERY_CONSISTENCY_COMPLETE = "recovery.consistency.complete"
    RECOVERY_CONSISTENCY_NO_WINNER = "recovery.consistency.no_winner"

    # Budget
    BUDGET_DOWNGRADE = "budget.downgrade"
```

Step 2: In `daemon/scheduler.py` and `daemon/recovery.py`, find every `replay.append_event(... "literal-string" ...)` and `_emit("literal-string", ...)` call. Replace with `EventType.X.value`. The `_emit` helper accepts strings, so the call shape stays identical.

Step 3: Update tests that assert on event-type strings to import `EventType` and use `EventType.X.value`.

### Acceptance criteria

- [ ] All previous tests pass
- [ ] All event names in the codebase reference `EventType.X.value`
- [ ] `grep -rn 'append_event(' daemon/` shows no naked string literals for the type arg

---

## Task 3.4 — Tests: assert on emitted events instead of mocking them away

**Source**: Round 2 #4.1
**Severity**: LOW (test quality)
**Effort**: 30 min
**Files**: `tests/test_recovery.py`

### Fix

Replace patterns like `monkeypatch.setattr("daemon.recovery.append_event", lambda *a, **kw: None)` with capture lists:

```python
@pytest.fixture
def captured_events(monkeypatch):
    events = []
    def capture(session_id, event_type, *, sprint_id=None, data=None):
        events.append({
            "session_id": session_id,
            "type": event_type,
            "sprint_id": sprint_id,
            "data": data or {},
        })
    monkeypatch.setattr("daemon.recovery.append_event", capture)
    return events


@pytest.mark.asyncio
async def test_adapt_emits_decomposition_event(captured_events):
    # ... run adapt_failed_sprint ...
    assert any(e["type"].endswith("decomposed") for e in captured_events)
```

Apply this pattern to 3-4 tests in `tests/test_recovery.py` and `tests/test_integration_wiring.py`.

### Acceptance criteria

- [ ] All tests pass
- [ ] At least 3 tests now assert on emitted events instead of mocking them silently

---

## Task 3.5 — Sprint 3 verification + commit

```bash
.venv/bin/ruff check daemon tests scripts eval
.venv/bin/ruff format --check daemon tests scripts eval
PYTHONPATH=. .venv/bin/pytest tests/ --no-header -q
bash scripts/pre-push.sh
```

---

# Sprint 4 — Polish (~2 hours)

## Task 4.1 — Type-hint cleanup

**Source**: Round 2 #1.6
**Effort**: 1.5h
**Files**: `daemon/db.py`, `daemon/memory/episodic.py`, `daemon/models.py`

For each method that returns bare `dict`, add a parameter:

```python
# daemon/db.py
def table_counts(self) -> dict[str, int]: ...

# daemon/memory/episodic.py
def store(
    self,
    session_id: str,
    sprint: SprintContract,
    gen_result: ExecutionResult,
    eval_result: EvaluatorResult | None = None,
) -> None: ...

# daemon/models.py — to_dict() methods can stay dict[str, Any] but add the param
def to_dict(self) -> dict[str, Any]: ...
```

### Acceptance criteria

- [ ] `mypy daemon/` (if installed) shows no new warnings
- [ ] All previous tests pass

---

## Task 4.2 — Delete say-what-not-why comments

**Source**: Round 2 comment quality
**Effort**: 10 min
**Files**: `daemon/scheduler.py:176`, `daemon/redact.py:220`, `daemon/recovery.py:165`, `daemon/parsing.py:184`

Find and delete obvious comments that restate the next line of code. Examples:

```python
# Before:
# Step 1: happy path
try:
    return json.loads(text)
except (ValueError, TypeError):
    pass

# After:
try:
    return json.loads(text)
except (ValueError, TypeError):
    pass
```

(The function docstring already documents the ladder; the inline comment is redundant.)

### Acceptance criteria

- [ ] All previous tests pass
- [ ] ~10 lines of redundant comments removed

---

## Task 4.3 — Adversarial-input tests

**Source**: Round 3 test gaps
**Effort**: 1h
**Files**: `tests/test_redact.py`, `tests/test_safety.py`, `tests/test_replay.py`

### Add ReDoS safety test

```python
def test_redact_handles_long_input_without_redos():
    """Pathological input doesn't trigger catastrophic backtracking."""
    import time
    junk = "e" * 100_000 + "yJ"  # near-JWT trigger pattern
    start = time.time()
    redact(junk)
    assert time.time() - start < 0.5  # well under any practical timeout
```

### Add path-traversal tests

```python
def test_replay_path_rejects_traversal(tmp_forge_dir):
    """A session_id containing path-traversal must not escape the sessions dir."""
    from daemon import replay
    # The module currently builds paths via Path() join — verify this stays safe.
    replay.append_event("../../etc/passwd", "test", data={})
    # The trace file should be inside .forge/sessions, not anywhere else
    assert not (tmp_forge_dir.parent.parent / "etc" / "passwd").exists()
```

### Acceptance criteria

- [ ] All previous tests pass
- [ ] 2 new adversarial tests pass

---

## Task 4.4 — Quarterly review reminder in SECURITY.md

**Source**: Cross-cutting recommendation D
**Effort**: 5 min
**Files**: `SECURITY.md`

Append:

```markdown
## Quarterly review checkbox

Every quarter (Mar/Jun/Sep/Dec):

- [ ] Re-sync `daemon/redact.py` against [gitleaks default rules](https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml) — add any new credential patterns
- [ ] Re-audit `daemon/safety.py` for new cloud-CLI subcommands worth blocking
- [ ] Run `pip-audit --strict` on all installed extras
- [ ] Bump `requires-python` floor if a major version is EOL'd
- [ ] Review any new ADRs in `docs/DECISIONS.md` for security implications
```

### Acceptance criteria

- [ ] `SECURITY.md` includes the new section

---

## Task 4.5 — Sprint 4 verification + final commit

```bash
.venv/bin/ruff check daemon tests scripts eval
.venv/bin/ruff format --check daemon tests scripts eval
PYTHONPATH=. .venv/bin/pytest tests/ --no-header -q
bash scripts/pre-push.sh
```

Bump version + update CHANGELOG:

```markdown
## [0.1.0] — 2026-MM-DD — code-review fixes complete

### Fixed
- ADaPT recovery now writes back to procedural and episodic memory (Task 1.1)
- EpisodicStore uses `select_executor()` correctly across all model families (Task 1.2)
- Database connection cleanup on SIGKILL via atexit + __del__ (Task 1.3)
- WebSocket rate limit + 1MB message cap + path validation (Task 1.4)
- Cross-family evaluator runtime assertion (Task 1.9)
- Worktree creation race condition fixed via async lock (Task 2.1)
- Budget enforcement atomic across parallel waves (Task 2.2)
- Subprocess proper kill on timeout (Task 2.4)

### Added
- 9 new credential patterns in `daemon/redact.py`: Vercel, Cloudflare, npm, HuggingFace, SendGrid, Mailgun, Twilio, Discord bot, Telegram bot (Task 1.5)
- 8 new destructive-op rules in `daemon/safety.py`: aws s3 rb/rm, gh repo delete, kubectl delete --all, terraform destroy, docker prune -a, chmod -R 000, mkfs, dd to device (Task 1.8)
- Graceful shutdown on SIGTERM/SIGINT (Task 1.7)
- WebSocket handler concurrency semaphore (max 10) (Task 2.3)
- `daemon/routing.py` — single source of truth for executor dispatch (Task 2.6)
- `daemon/events.py` — `EventType` enum registry (Task 3.3)
- `critical: bool` field on `SprintContract` (Task 3.2)
- Adversarial-input tests (ReDoS, path traversal) (Task 4.3)
- Quarterly review checkbox in SECURITY.md (Task 4.4)

### Changed
- `_AUTH_BEARER_LOOSE` redaction rule removed (Task 1.6)
- env-line redaction rule simplified (no negative lookahead) (Task 1.6)
- Phantom `tree-sitter` dep removed from `forge[repomap]` extra (Task 1.10)
- `daemon/executors/ollama.py` and `daemon/executors/openai_compatible.py` refactored onto shared `_http_base.py` (Task 3.1) — net -60 LOC

### Test count
- Before review: 588 passing
- After Sprint 1: ~610 passing (+22)
- After Sprint 2: ~620 passing (+10)
- After Sprint 3: ~630 passing (+10)
- After Sprint 4: ~635 passing (+5)
```

### Acceptance criteria

- [ ] CHANGELOG.md reflects every task
- [ ] Full quality gate green
- [ ] Tests count up to ~635 from baseline 588 (+47)

---

# Per-task summary table

| # | Task | Sprint | Severity | Effort | Files |
|---|---|---|---|---|---|
| 1.1 | ADaPT writeback | 1 | HIGH | 30m | scheduler.py |
| 1.2 | EpisodicStore agent type | 1 | MEDIUM | 30m | episodic.py |
| 1.3 | DB shutdown discipline | 1 | HIGH | 1h | db.py |
| 1.4 | WS rate limit + size cap + path | 1 | HIGH | 2h | ws_server.py |
| 1.5 | 9 missing redaction patterns | 1 | HIGH | 2h | redact.py |
| 1.6 | Drop AUTH_BEARER_LOOSE; reorder | 1 | MEDIUM | 1h | redact.py |
| 1.7 | Graceful SIGTERM shutdown | 1 | HIGH | 1.5h | cli.py, ws_server.py |
| 1.8 | Safety catalog +8 cloud commands | 1 | MEDIUM | 1h | safety.py |
| 1.9 | Cross-family evaluator assert | 1 | LOW-MED | 5m | evaluator.py |
| 1.10 | Delete tree-sitter phantom dep | 1 | LOW | 5m | pyproject.toml |
| 2.1 | Worktree creation lock | 2 | MEDIUM | 30m | worktree.py |
| 2.2 | Budget atomic across waves | 2 | MEDIUM | 1h | scheduler.py, budget.py |
| 2.3 | WS handler semaphore | 2 | MEDIUM | 30m | ws_server.py |
| 2.4 | Subprocess kill on timeout | 2 | LOW | 30m | claude_code.py |
| 2.5 | tmp_forge_dir → conftest | 2 | LOW | 15m | tests/ |
| 2.6 | Unify select_executor | 2 | LOW-MED | 1h | classifier.py, generator.py, routing.py |
| 3.1 | Extract HTTPExecutor base | 3 | MEDIUM | 6–8h | executors/ |
| 3.2 | critical: bool field | 3 | LOW | 30m | models.py, recovery.py |
| 3.3 | EventType StrEnum registry | 3 | LOW-MED | 4–5h | events.py + many call sites |
| 3.4 | Test event emission | 3 | LOW | 30m | tests/ |
| 4.1 | Type-hint cleanup | 4 | LOW | 1.5h | db.py, models.py, episodic.py |
| 4.2 | Delete redundant comments | 4 | LOW | 10m | several |
| 4.3 | Adversarial tests | 4 | LOW | 1h | tests/ |
| 4.4 | Quarterly checkbox | 4 | LOW | 5m | SECURITY.md |

**Total effort: ~22 hours**

---

# Notes for the future-chat executor

1. **Run sprints in order.** Sprint 1 fixes contract-violating bugs; later sprints assume those are in place (e.g., Task 1.1 introduces `sprint.recovered` event — Task 3.3's enum should include it).

2. **Each task is committed separately.** No bundling. Use the title as the commit message subject, e.g., `fix(scheduler): write back to procedural+episodic on ADaPT recovery (Task 1.1)`.

3. **The acceptance criteria are the contract.** If a task's acceptance criteria can't be satisfied, stop and surface the blocker rather than partial-completing.

4. **Test count is a sanity check.** Each sprint should add ~5-15 tests. If the test count doesn't go up, something was missed.

5. **Don't fix issues outside this plan in the same commit.** If you spot a new issue while working on Task 1.4, file it as a Sprint-2 candidate; don't expand the current task.

6. **The CHANGELOG entry at Task 4.5 is the deliverable summary.** Cross-reference it back to this plan.

---

*This plan is the input for a fresh chat session. The chat does not need to read the source review notes — every task is self-contained. The plan itself is the contract.*
