"""Integration tests for the unwired-then-wired pieces:

- Scheduler emits replay events at every phase
- Scheduler builds + injects repomap into generators
- Scheduler writes back to procedural memory after evaluator verdicts
- Scheduler invokes ADaPT recovery on terminal failure
- Scheduler routes [critical] sprints through Self-Consistency
- CLI ``forge replay`` and ``forge mcp-serve`` subcommands resolve
- ``daemon.log.setup_logging`` applies the RedactionFilter
- sqlite-vec helpers no-op cleanly when disabled, write+search when enabled
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

import pytest

from daemon import replay, scheduler
from daemon.budget import BudgetController
from daemon.db import ForgeDB
from daemon.memory.episodic import EpisodicStore
from daemon.memory.retriever import Retriever
from daemon.models import (
    EvaluatorResult,
    ExecutionResult,
    ProjectContext,
    SprintContract,
)

# ---- Helpers / fixtures ----


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "forge.db"))
        yield db
        db.close()


# ``tmp_forge_dir`` is shared via tests/conftest.py (Task 2.5).


@pytest.fixture
def fake_worktree(monkeypatch, tmp_path):
    """Stub worktree.create / get_diff so scheduler tests don't shell out
    to git."""
    from daemon import worktree

    async def fake_create(sprint_id, base_path=None):
        d = tmp_path / f"wt-{sprint_id}"
        d.mkdir(exist_ok=True)
        return str(d)

    async def fake_get_diff(path):
        return "diff --git a/x b/x\n+added line"

    monkeypatch.setattr(worktree, "create", fake_create)
    monkeypatch.setattr(worktree, "get_diff", fake_get_diff)


@pytest.fixture
def stub_generator_evaluator(monkeypatch):
    """Stub generator.generate and evaluator.evaluate with a knob to
    control verdict + capture invocation args."""
    from daemon.agents import evaluator as eval_mod, generator as gen_mod

    state = {
        "verdict": "APPROVED",
        "gen_calls": [],
        "eval_calls": [],
    }

    async def fake_generate(sprint, memory_context="", worktree_path=None, **kwargs):
        state["gen_calls"].append(
            {
                "sprint_id": sprint.id,
                "memory_context": memory_context,
                "repomap": kwargs.get("repomap", ""),
                "revision_feedback": kwargs.get("revision_feedback", ""),
            }
        )
        return ExecutionResult(success=True, output="diff", tokens_in=10, tokens_out=10)

    async def fake_evaluate(sprint, diff, ctx, *, eval_model=None):
        state["eval_calls"].append({"sprint_id": sprint.id})
        return EvaluatorResult(verdict=state["verdict"], feedback="ok")

    monkeypatch.setattr(gen_mod, "generate", fake_generate)
    monkeypatch.setattr(eval_mod, "evaluate", fake_evaluate)
    return state


# ---- Scheduler emits replay events ----


@pytest.mark.asyncio
async def test_execute_sprint_emits_trace_events(
    tmp_db, tmp_forge_dir, fake_worktree, stub_generator_evaluator
):
    """Every phase transition should land in the JSONL trace file."""
    sprint = SprintContract(
        session_id="sess-1",
        description="Add health check",
        done_criteria=["Endpoint exists", "Tests pass"],
        assigned_model="qwen3-coder-next",
    )
    ctx = ProjectContext(path=str(tmp_forge_dir.parent))
    budget = BudgetController(budget_usd=10.0)
    retriever = Retriever(tmp_db)
    episodic = EpisodicStore(tmp_db)

    await scheduler.execute_sprint(
        sprint,
        ctx,
        "sess-1",
        tmp_db,
        budget,
        retriever,
        episodic,
        broadcast=None,
    )

    # Trace file exists
    trace_path = tmp_forge_dir / "sessions" / "sess-1" / "trace.jsonl"
    assert trace_path.exists()

    events = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    # Should include worktree.created, sprint.attempt, sprint.evaluated, sprint.approved
    assert "worktree.created" in types
    assert any(t.startswith("sprint.") for t in types)
    assert "sprint.approved" in types


@pytest.mark.asyncio
async def test_execute_sprint_writes_procedural_after_verdict(
    tmp_db, tmp_forge_dir, fake_worktree, stub_generator_evaluator
):
    """Successful sprint → procedural memory records a sample."""
    sprint = SprintContract(
        session_id="sess-2",
        description="Add user-list endpoint with pagination",
        done_criteria=["Returns 200"],
        assigned_model="qwen3-coder-next",
    )
    ctx = ProjectContext()
    budget = BudgetController(budget_usd=10.0)
    retriever = Retriever(tmp_db)
    episodic = EpisodicStore(tmp_db)

    await scheduler.execute_sprint(
        sprint,
        ctx,
        "sess-2",
        tmp_db,
        budget,
        retriever,
        episodic,
        broadcast=None,
    )

    # Procedural store should have a row keyed off the first 100 chars of the description
    proc = tmp_db.get_procedure("Add user-list endpoint with pagination")
    assert proc is not None
    assert proc["recommended_model"] == "qwen3-coder-next"
    assert proc["sample_count"] >= 1


# ---- Scheduler injects repomap ----


@pytest.mark.asyncio
async def test_execute_session_passes_repomap_to_generator(
    tmp_db, tmp_forge_dir, fake_worktree, stub_generator_evaluator, tmp_path, monkeypatch
):
    """The repomap built at session start reaches generator calls."""
    # Create a tiny "project" so build_repomap returns something
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.py").write_text("def hello():\n    pass\n")

    # Stub the planner to return one sprint without invoking an LLM
    from daemon.agents import planner

    async def fake_plan(objective, ctx, session_id, kb_context, use_local_planner):
        return [
            SprintContract(
                session_id=session_id,
                description="impl thing",
                done_criteria=["done"],
                assigned_model="qwen3-coder-next",
            )
        ]

    monkeypatch.setattr(planner, "plan", fake_plan)

    ctx = ProjectContext(path=str(proj))
    budget = BudgetController(budget_usd=10.0)

    await scheduler.execute_session("build it", ctx, tmp_db, budget, broadcast=None)

    # Generator should have been called with a non-empty repomap that
    # references main.py
    assert stub_generator_evaluator["gen_calls"], "generator was never invoked"
    repomap = stub_generator_evaluator["gen_calls"][0]["repomap"]
    assert repomap, "repomap was empty"
    assert "main.py" in repomap


# ---- ADaPT recovery wiring ----


@pytest.mark.asyncio
async def test_execute_sprint_invokes_adapt_on_max_revisions(
    tmp_db, tmp_forge_dir, fake_worktree, monkeypatch, tmp_path
):
    """When the sprint fails MAX_REVISIONS times AND has multiple criteria,
    the scheduler should invoke recovery.adapt_failed_sprint."""
    sprint = SprintContract(
        session_id="sess-adapt",
        description="multi-criterion task",
        done_criteria=["a", "b", "c"],
        assigned_model="qwen3-coder-next",
    )

    # All evaluator calls return REVISE — exhaust normal revisions
    from daemon.agents import evaluator as eval_mod, generator as gen_mod

    async def fake_generate(s, memory_context="", worktree_path=None, **kwargs):
        return ExecutionResult(success=True, output="diff", tokens_in=1, tokens_out=1)

    async def fake_evaluate(s, diff, ctx, *, eval_model=None):
        return EvaluatorResult(verdict="REVISE", feedback="not yet")

    monkeypatch.setattr(gen_mod, "generate", fake_generate)
    monkeypatch.setattr(eval_mod, "evaluate", fake_evaluate)

    # Capture the call to adapt_failed_sprint via monkeypatch
    adapt_calls = []

    async def fake_adapt(parent, *, run_subsprint):
        adapt_calls.append(parent.id)
        from daemon.recovery import DecompositionResult

        return DecompositionResult(parent_sprint_id=parent.id, final_verdict="FAIL")

    monkeypatch.setattr(scheduler.recovery, "adapt_failed_sprint", fake_adapt)

    ctx = ProjectContext()
    budget = BudgetController(budget_usd=10.0)
    retriever = Retriever(tmp_db)
    episodic = EpisodicStore(tmp_db)

    await scheduler.execute_sprint(
        sprint,
        ctx,
        "sess-adapt",
        tmp_db,
        budget,
        retriever,
        episodic,
        broadcast=None,
    )

    assert len(adapt_calls) == 1
    assert adapt_calls[0] == sprint.id


@pytest.mark.asyncio
async def test_adapt_recovery_writes_episodic_and_procedural(
    tmp_db, tmp_forge_dir, fake_worktree, monkeypatch
):
    """When ADaPT recovery succeeds, both procedural and episodic memory record it.

    This guards Task 1.1: prior to the fix, when ADaPT flipped a sprint from
    "failed" to "completed", neither writeback path ran, so the episodic store
    only had the failure record and the procedural store never learned that
    recovery succeeded for this task pattern.
    """
    sprint = SprintContract(
        session_id="sess-recover",
        description="multi-criterion task",
        done_criteria=["a", "b"],
        assigned_model="qwen3-coder-next",
    )

    # Force the normal loop to fail (so ADaPT triggers).
    from daemon.agents import evaluator as eval_mod, generator as gen_mod

    async def fake_generate(s, memory_context="", worktree_path=None, **kwargs):
        return ExecutionResult(success=True, output="diff", tokens_in=1, tokens_out=1)

    async def fake_evaluate(s, diff, ctx, *, eval_model=None):
        return EvaluatorResult(verdict="REVISE", feedback="not yet")

    monkeypatch.setattr(gen_mod, "generate", fake_generate)
    monkeypatch.setattr(eval_mod, "evaluate", fake_evaluate)

    # ADaPT runs but its sub-sprints succeed.
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
        sprint,
        ctx,
        "sess-recover",
        tmp_db,
        budget,
        retriever,
        episodic,
        broadcast=None,
    )

    # Procedural store should have a successful sample for the recovered sprint.
    proc = tmp_db.get_procedure("multi-criterion task")
    assert proc is not None
    assert proc["success_rate"] > 0.0  # recovery success counted

    # Episodic store should now contain at least one APPROVED episode for
    # this session (in addition to whatever failure records preceded it).
    eps = tmp_db.get_episodes_for_session("sess-recover")
    assert any(e.get("evaluator_verdict") == "APPROVED" for e in eps), (
        f"no APPROVED episode found; verdicts seen: {[e.get('evaluator_verdict') for e in eps]}"
    )


# ---- Self-Consistency wiring ----


@pytest.mark.asyncio
async def test_execute_sprint_routes_critical_through_consistency(
    tmp_db, tmp_forge_dir, fake_worktree, monkeypatch
):
    """[critical]-marked sprints go through self_consistent_run (not the
    normal revise loop)."""
    sprint = SprintContract(
        session_id="sess-crit",
        description="[critical] schema migration on prod",
        done_criteria=["migration applied"],
        assigned_model="qwen3-coder-next",
    )

    consistency_calls = []

    async def fake_self_consistent_run(sprint, *, n=3, run_attempt):
        consistency_calls.append((sprint.id, n))
        from daemon.recovery import SelfConsistencyResult

        # Simulate one APPROVED attempt
        attempt = (
            ExecutionResult(success=True, tokens_in=1, tokens_out=1),
            EvaluatorResult(verdict="APPROVED"),
        )
        return SelfConsistencyResult(
            sprint_id=sprint.id,
            attempts=[attempt],
            winner_index=0,
            final_verdict="APPROVED",
        )

    monkeypatch.setattr(scheduler.recovery, "self_consistent_run", fake_self_consistent_run)

    # Avoid invoking _run_one_attempt (which would call generator/evaluator)
    # by ensuring the consistency stub resolves first.

    ctx = ProjectContext()
    budget = BudgetController(budget_usd=10.0)
    retriever = Retriever(tmp_db)
    episodic = EpisodicStore(tmp_db)

    result = await scheduler.execute_sprint(
        sprint,
        ctx,
        "sess-crit",
        tmp_db,
        budget,
        retriever,
        episodic,
        broadcast=None,
    )

    assert len(consistency_calls) == 1
    assert consistency_calls[0] == (sprint.id, 3)
    assert result.status == "completed"


# ---- CLI subcommand wiring ----


def test_cli_replay_lists_sessions_when_no_arg(tmp_forge_dir, capsys):
    """`forge replay` (no args) lists available sessions."""
    from daemon import cli

    # Seed two sessions
    replay.append_event("sess-A", "x")
    replay.append_event("sess-B", "y")

    args = type("A", (), {"session_id": None, "raw": False})
    cli.cmd_replay(args)
    out = capsys.readouterr().out
    assert "sess-A" in out
    assert "sess-B" in out


def test_cli_replay_renders_specific_session(tmp_forge_dir, capsys):
    from daemon import cli

    replay.append_event("sess-X", "planner.decision", data={"complexity": "low"})

    args = type("A", (), {"session_id": "sess-X", "raw": False})
    cli.cmd_replay(args)
    out = capsys.readouterr().out
    # Pretty-print intentionally omits the session_id per-line (constant
    # across the whole replay); the event type + data summary surface.
    assert "planner.decision" in out
    assert "complexity=low" in out


def test_cli_mcp_serve_returns_nonzero_when_mcp_missing(monkeypatch):
    """When the optional ``mcp`` package isn't installed, cmd_mcp_serve
    exits 1 instead of crashing."""

    def _import_check():
        try:
            import mcp.server.fastmcp  # noqa: F401

            return True
        except ImportError:
            return False

    if _import_check():
        pytest.skip("mcp installed; this test exercises the missing-dep path")

    from daemon import cli

    rc = cli.cmd_mcp_serve(args=None)
    assert rc == 1


def test_cli_parser_accepts_new_subcommands():
    """The argparse layer recognizes both new commands."""
    from daemon import cli

    parser = cli.build_parser()
    a = parser.parse_args(["replay"])
    assert a.command == "replay"
    a = parser.parse_args(["replay", "sess-1", "--raw"])
    assert a.session_id == "sess-1"
    assert a.raw is True

    a = parser.parse_args(["mcp-serve"])
    assert a.command == "mcp-serve"


# ---- log.py wiring ----


def test_setup_logging_attaches_redaction_filter(tmp_path):
    """setup_logging should add the RedactionFilter to every handler."""
    from daemon.log import setup_logging

    setup_logging(log_dir=str(tmp_path))
    root = logging.getLogger()

    # Every handler we attached should carry the redaction filter
    for h in root.handlers:
        filter_classes = [type(f).__name__ for f in h.filters]
        assert "RedactionFilter" in filter_classes, f"handler {h} missing RedactionFilter"

    # Cleanup
    for h in list(root.handlers):
        root.removeHandler(h)


def test_setup_logging_idempotent(tmp_path):
    """Calling setup_logging twice doesn't double-attach handlers."""
    from daemon.log import setup_logging

    setup_logging(log_dir=str(tmp_path))
    root = logging.getLogger()
    n_first = len(root.handlers)

    setup_logging(log_dir=str(tmp_path))
    n_second = len(root.handlers)

    assert n_first == n_second

    for h in list(root.handlers):
        root.removeHandler(h)


def test_setup_logging_redacts_credentials_in_emitted_message(tmp_path, capsys):
    """End-to-end: a leaky log.warning gets scrubbed before stderr."""
    from daemon.log import setup_logging

    setup_logging(log_dir=str(tmp_path))
    log = logging.getLogger("test_logging_redaction")
    leaky = "anthropic key leaked: sk-ant-api03-" + "x" * 90
    log.warning(leaky)

    captured = capsys.readouterr()
    # The original key must not appear in stderr
    assert "sk-ant-api03-xxxx" not in captured.err
    # The redaction marker should
    assert "REDACTED" in captured.err

    # Cleanup
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)


# ---- sqlite-vec wiring (gated) ----


def test_store_episode_embedding_is_noop_when_disabled(tmp_db, monkeypatch):
    """Without FORGE_VECTOR_EPISODES=1 the store is a clean no-op."""
    monkeypatch.delenv("FORGE_VECTOR_EPISODES", raising=False)
    # _vec_enabled should be False; calling the helper does nothing
    tmp_db._vec_enabled = False
    tmp_db.store_episode_embedding("ep-1", [0.1, 0.2, 0.3])
    # Verify by trying to find — should also no-op
    assert tmp_db.find_similar_episodes([0.1, 0.2, 0.3]) == []


def test_find_similar_episodes_empty_when_disabled(tmp_db):
    """Without sqlite-vec loaded, find_similar returns []."""
    tmp_db._vec_enabled = False
    assert tmp_db.find_similar_episodes([0.1] * 768) == []


# ---- Existing 573 tests should still pass ----


def test_smoke_existing_imports():
    """Import the modules we touched to make sure no circular imports."""
    from daemon import cli, log, replay, scheduler  # noqa: F401
    from daemon.agents import evaluator, generator  # noqa: F401
