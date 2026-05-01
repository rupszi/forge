"""Scheduler: parallel execution with dependency resolution.

Orchestrates the full planner → generator → evaluator cycle, with all the
Phase-1-through-Phase-3 integration wired in:

  - **Repomap injection** (`scanner/repomap.build_repomap`) — built once per
    session at start; passed to every generator call alongside the memory
    context. Stable across revisions for prompt-cache friendliness.
  - **Trace events** (`replay.append_event`) — every phase transition
    (session start/end, sprint start, generation, evaluation, revision,
    budget downgrade, recovery) emits a JSONL audit-log event under
    `.forge/sessions/<id>/trace.jsonl`. ``forge replay <session-id>`` reads
    these back; same payloads also stream to the WebSocket UI.
  - **Procedural memory writeback** (`db.save_procedure`) — after every
    evaluator verdict (APPROVED or REVISE), record (task_pattern → model →
    success?) in the procedural store. Online RouteLLM: routing accuracy
    improves session-over-session as the procedural store accumulates.
  - **ADaPT recovery** (`recovery.adapt_failed_sprint`) — when a sprint
    fails after `MAX_REVISIONS`, instead of immediately marking it failed,
    we recursively decompose into sub-sprints and run them sequentially
    (per ADR-006 caveat 2 / Prasad et al. arxiv 2311.05772).
  - **Self-Consistency for `[critical]` sprints** (`recovery.self_consistent_run`)
    — sprints with `[critical]` in their description run N=3 sequential
    attempts, with the highest-scoring evaluator verdict winning. Sequential
    on M-series hardware (M4 Pro 48GB can't fit 3 large models in parallel).
  - **Cross-family evaluator** — already wired via `evaluator.evaluate`
    which delegates to `classifier.pick_evaluator_model` (ADR-006).

The scheduler stays thin: each integration point is one or two function calls
to a dedicated module. The bulk of the algorithm logic lives in those modules
so the scheduler is testable and the algorithms are independently unit-testable.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from . import recovery, replay, worktree
from .agents import evaluator, generator, planner
from .budget import BudgetController
from .config import MAX_PARALLEL_AGENTS, MAX_REVISIONS
from .db import ForgeDB
from .events import EventType
from .memory.episodic import EpisodicStore
from .memory.retriever import Retriever
from .models import EvaluatorResult, ExecutionResult, ProjectContext, Session, SprintContract
from .scanner.repomap import build_repomap

logger = logging.getLogger(__name__)


def dependency_waves(sprints: list[SprintContract]) -> list[list[SprintContract]]:
    """Group sprints into waves respecting dependencies.

    Wave 0: sprints with no dependencies
    Wave 1: sprints depending only on wave 0
    etc.
    """
    completed_ids = set()
    remaining = list(sprints)
    waves = []

    while remaining:
        wave = []
        still_remaining = []
        for sprint in remaining:
            deps = set(sprint.depends_on)
            if deps.issubset(completed_ids):
                wave.append(sprint)
            else:
                still_remaining.append(sprint)

        if not wave:
            # Deadlock — add all remaining as final wave
            logger.warning("Dependency deadlock detected, forcing remaining sprints")
            waves.append(still_remaining)
            break

        waves.append(wave)
        completed_ids.update(s.id for s in wave)
        remaining = still_remaining

    return waves


def _writeback_procedural(
    db: ForgeDB, sprint: SprintContract, eval_result: EvaluatorResult, duration: float
) -> None:
    """Record a (task_pattern → model → success) sample in the procedural store.

    Online learning: every sprint outcome shapes future routing decisions
    (`classifier.classify` reads the procedural store first, before its
    heuristic). The pattern key is the first 100 chars of the sprint
    description — short enough to dedupe similar tasks, long enough to
    distinguish meaningfully different ones.

    Failures are logged via `silent_catch` rather than raising; the
    procedural store is observability, not a primary code path.
    """
    from .safety import silent_catch

    try:
        pattern = sprint.description[:100]
        success = eval_result.verdict == "APPROVED"
        # Recover the agent type from the model identifier; fall back to
        # "ollama" since that's the default executor.
        from .agents.classifier import select_executor

        agent_type = select_executor(sprint.assigned_model)
        db.save_procedure(pattern, sprint.assigned_model, agent_type, success, duration)
    except Exception as e:
        silent_catch(__name__, e)


async def _run_one_attempt(
    sprint: SprintContract,
    ctx: ProjectContext,
    wt_path: str,
    memory: str,
    repomap: str,
    revision_feedback: str = "",
) -> tuple[ExecutionResult, EvaluatorResult]:
    """Run one generate→evaluate cycle.

    Pulled out as a standalone helper so both the normal sprint loop and the
    Self-Consistency layer can call it. Returns the pair so the caller can
    decide what to do (revise, accept, escalate to recovery).
    """
    gen_result = await generator.generate(
        sprint,
        memory_context=memory,
        worktree_path=wt_path,
        repomap=repomap,
        revision_feedback=revision_feedback,
    )

    if not gen_result.success:
        # The generator failed entirely (subprocess crash / network error).
        # Surface a synthetic REVISE verdict so the caller knows to retry.
        return gen_result, EvaluatorResult(
            verdict="REVISE",
            feedback=f"Generator failed: {gen_result.error}",
        )

    diff = await worktree.get_diff(wt_path)
    eval_result = await evaluator.evaluate(sprint, diff, ctx)
    return gen_result, eval_result


async def execute_sprint(
    sprint: SprintContract,
    ctx: ProjectContext,
    session_id: str,
    db: ForgeDB,
    budget: BudgetController,
    retriever: Retriever,
    episodic: EpisodicStore,
    broadcast: Callable | None = None,
    *,
    repomap: str = "",
) -> SprintContract:
    """Execute one sprint: generate → evaluate → revise (≤MAX_REVISIONS) → done.

    Augmented in Phase 3 with:
      - Self-Consistency mode for ``[critical]`` sprints (N=3 attempts, best wins)
      - ADaPT recovery on `MAX_REVISIONS` exhaustion (recursive decomposition)
      - Procedural-memory writeback after every verdict
      - Trace event emission at every transition
    """
    import time

    def _emit(typ: str, **data):
        """Convenience wrapper — emit to both the WebSocket broadcast and the
        on-disk trace JSONL."""
        if broadcast:
            broadcast({"type": typ, "sprint_id": sprint.id, **data})
        replay.append_event(session_id, typ, sprint_id=sprint.id, data=data)

    # ---- Budget reservation (Task 2.2) ----
    #
    # Reserve the estimated cost up-front under the budget lock so concurrent
    # sprints in the same wave can't collectively overshoot. If reserve fails,
    # we downgrade and retry once; if still over, mark failed cleanly.
    #
    # Existing per-attempt ``record_spend`` calls below stay as-is — they
    # adjust the running total as token usage becomes known. The reserve
    # here is the *floor*: at minimum we've committed this much of the cap.
    from .budget import estimate_cost as _estimate_cost

    estimated = _estimate_cost(sprint.assigned_model, sprint.estimated_tokens or 10000)
    reserved = await budget.reserve(estimated)
    if not reserved:
        budget.downgrade(sprint)
        estimated = _estimate_cost(sprint.assigned_model, sprint.estimated_tokens or 10000)
        reserved = await budget.reserve(estimated)
        if not reserved:
            sprint.status = "failed"
            sprint.error = "budget exhausted"
            _emit(EventType.BUDGET_EXHAUSTED.value, model=sprint.assigned_model)
            db.save_sprint(sprint)
            return sprint

    # ---- Worktree creation ----

    try:
        wt_path = await worktree.create(sprint.id)
        sprint.assigned_worktree = wt_path
    except Exception as e:
        sprint.status = "failed"
        sprint.error = f"Worktree creation failed: {e}"
        _emit(EventType.WORKTREE_CREATE_FAILED.value, error=str(e))
        return sprint

    _emit(EventType.WORKTREE_CREATED.value, path=wt_path)

    # ---- Memory context ----

    memory = retriever.get_context_for_task(sprint.description)
    sprint_start = time.time()

    # ---- Self-Consistency branch for [critical] sprints ----
    #
    # If the sprint is flagged critical (per `recovery.is_critical`), run
    # N=3 sequential attempts and pick the highest-scoring verdict. We bypass
    # the normal revision loop because the failure mode for critical sprints
    # is "model went off the rails on attempt 1" not "needs more iterations".

    if recovery.is_critical(sprint):
        _emit(EventType.RECOVERY_CONSISTENCY_START.value, reason="critical sprint")

        async def _attempt(_sprint, _i):
            return await _run_one_attempt(_sprint, ctx, wt_path, memory, repomap)

        consistency_result = await recovery.self_consistent_run(sprint, n=3, run_attempt=_attempt)
        winner = consistency_result.winner
        if winner is not None:
            gen_result, eval_result = winner
            budget.record_spend(gen_result.cost_usd + eval_result.cost_usd)
            sprint.status = (
                "completed" if consistency_result.final_verdict == "APPROVED" else "failed"
            )
            if sprint.status == "failed":
                sprint.error = "Self-Consistency: no attempt approved"
            episodic.store(session_id, sprint, gen_result, eval_result)
            _writeback_procedural(db, sprint, eval_result, time.time() - sprint_start)
            db.save_sprint(sprint)
            _emit(
                EventType.RECOVERY_CONSISTENCY_COMPLETE.value,
                verdict=consistency_result.final_verdict,
                attempts=len(consistency_result.attempts),
            )
            return sprint
        # No winner → fall through to normal loop. Rare; happens only if
        # all 3 attempts crashed before producing a verdict.
        _emit(EventType.RECOVERY_CONSISTENCY_NO_WINNER.value)

    # ---- Normal generate → evaluate → revise loop ----

    last_gen_result: ExecutionResult | None = None
    last_eval_result: EvaluatorResult | None = None

    for attempt in range(MAX_REVISIONS + 1):
        _emit(EventType.SPRINT_ATTEMPT.value, attempt=attempt)

        # Build revision feedback as a structured separate block (ADR-006:
        # don't accumulate failures into memory; replace each attempt's
        # feedback so the cacheable prefix stays stable).
        revision_feedback = ""
        if attempt > 0 and last_eval_result is not None:
            revision_feedback = (
                f"Attempt {attempt} feedback (apply these specific fixes):\n"
                f"{last_eval_result.feedback}"
            )

        gen_result, eval_result = await _run_one_attempt(
            sprint, ctx, wt_path, memory, repomap, revision_feedback
        )
        budget.record_spend(gen_result.cost_usd + eval_result.cost_usd)
        last_gen_result = gen_result
        last_eval_result = eval_result

        _emit(
            EventType.SPRINT_EVALUATED.value,
            attempt=attempt,
            verdict=eval_result.verdict,
            tokens_in=gen_result.tokens_in + eval_result.tokens_in,
            tokens_out=gen_result.tokens_out + eval_result.tokens_out,
        )

        if eval_result.verdict == "APPROVED":
            sprint.status = "completed"
            episodic.store(session_id, sprint, gen_result, eval_result)
            _writeback_procedural(db, sprint, eval_result, time.time() - sprint_start)
            _emit(EventType.SPRINT_APPROVED.value)
            break

        # Verdict was REVISE.
        sprint.revision_count = attempt + 1
        if attempt < MAX_REVISIONS:
            _emit(
                EventType.SPRINT_REVISING.value,
                revision=sprint.revision_count,
                feedback=eval_result.feedback,
            )
            continue

        # Exhausted normal revisions. Try ADaPT recovery before giving up.
        sprint.status = "failed"
        sprint.error = f"Failed after {MAX_REVISIONS} revisions: {eval_result.feedback}"
        episodic.store(session_id, sprint, gen_result, eval_result)
        _writeback_procedural(db, sprint, eval_result, time.time() - sprint_start)

    # ---- ADaPT recovery on terminal failure ----
    #
    # Single-criterion sprints don't decompose meaningfully; `is_eligible_for_decomposition`
    # filters those out. For multi-criterion sprints we run each criterion as
    # its own sub-sprint. If recovery succeeds, flip the status back to
    # completed with a note.

    if sprint.status == "failed" and recovery.is_eligible_for_decomposition(sprint):
        _emit(EventType.RECOVERY_ADAPT_START.value)

        async def _run_subsprint(sub):
            sub_wt_path = await worktree.create(sub.id)
            sub.assigned_worktree = sub_wt_path
            sub_memory = retriever.get_context_for_task(sub.description)
            return await _run_one_attempt(sub, ctx, sub_wt_path, sub_memory, repomap)

        decomp = await recovery.adapt_failed_sprint(sprint, run_subsprint=_run_subsprint)
        _emit(EventType.RECOVERY_ADAPT_COMPLETE.value, verdict=decomp.final_verdict)

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
                feedback=(
                    f"Recovered via ADaPT decomposition into {len(decomp.sub_sprints)} sub-sprints"
                ),
            )
            last_gen = (
                decomp.sub_results[-1] if decomp.sub_results else ExecutionResult(success=True)
            )
            episodic.store(session_id, sprint, last_gen, recovery_eval)
            _writeback_procedural(db, sprint, recovery_eval, time.time() - sprint_start)
            _emit(
                EventType.SPRINT_RECOVERED.value,
                verdict="APPROVED",
                sub_count=len(decomp.sub_sprints),
            )

    db.save_sprint(sprint)
    return sprint


async def execute_session(
    objective: str,
    ctx: ProjectContext,
    db: ForgeDB,
    budget: BudgetController,
    broadcast: Callable | None = None,
    use_local_planner: bool = True,
) -> Session:
    """Full session: plan → generate → evaluate → learn.

    Builds the repomap once at session start (per ADR-002 — repomap is
    expensive and stable; rebuild only on `forge init` or major file
    changes). Emits trace events at every phase transition.
    """
    session = Session(
        project_path=ctx.path,
        objective=objective,
        detected_stack=ctx.to_dict(),
    )
    db.save_session(session)

    retriever = Retriever(db)
    episodic = EpisodicStore(db)

    def _broadcast(msg: dict):
        if broadcast:
            msg["session_id"] = session.id
            broadcast(msg)

    def _emit_session(typ: str, **data):
        _broadcast({"type": typ, **data})
        replay.append_event(session.id, typ, data=data)

    _emit_session(EventType.SESSION_START.value, objective=objective, project_path=ctx.path)

    # ---- Build repomap (Phase 1 Week 3) ----
    #
    # Cap at 1500 tokens per ADR-002; the actual generator prompt builder
    # will further truncate if the target model's window is tight.
    try:
        repomap = build_repomap(ctx.path, token_budget=1500) if ctx.path else ""
    except Exception as e:
        from .safety import silent_catch

        silent_catch(__name__, e)
        repomap = ""

    _emit_session(EventType.REPOMAP_BUILT.value, size=len(repomap))

    # ---- Phase 1: Plan ----

    kb_context = retriever.get_context_for_task(objective)
    sprints = await planner.plan(objective, ctx, session.id, kb_context, use_local_planner)
    session.total_sprints = len(sprints)

    for s in sprints:
        db.save_sprint(s)

    _emit_session(EventType.PLAN_CREATED.value, sprint_count=len(sprints))
    _broadcast({"type": "plan_created", "sprints": [s.to_dict() for s in sprints]})

    # ---- Phase 2: Execute waves ----

    for wave_idx, wave in enumerate(dependency_waves(sprints)):
        _emit_session(EventType.WAVE_START.value, wave=wave_idx, sprint_count=len(wave))

        # Budget check + downgrade
        for sprint in wave:
            if not budget.can_afford(sprint):
                budget.downgrade(sprint)
                _emit_session(
                    EventType.BUDGET_DOWNGRADE.value,
                    sprint_id=sprint.id,
                    new_model=sprint.assigned_model,
                )

        # Run wave in parallel (capped). Use TaskGroup-style semantics via
        # a Semaphore + gather; full TaskGroup migration is a follow-up.
        sem = asyncio.Semaphore(MAX_PARALLEL_AGENTS)

        async def _run(s):
            async with sem:
                return await execute_sprint(
                    s,
                    ctx,
                    session.id,
                    db,
                    budget,
                    retriever,
                    episodic,
                    _broadcast,
                    repomap=repomap,
                )

        results = await asyncio.gather(*[_run(s) for s in wave], return_exceptions=True)

        for sprint, result in zip(wave, results):
            if isinstance(result, Exception):
                sprint.status = "failed"
                sprint.error = str(result)
                session.failed_sprints += 1
                _emit_session(
                    EventType.SPRINT_CRASHED.value, sprint_id=sprint.id, error=str(result)
                )
            elif result.status == "completed":
                session.completed_sprints += 1
            else:
                session.failed_sprints += 1

        _emit_session(EventType.WAVE_COMPLETE.value, wave=wave_idx, **budget.to_dict())
        _broadcast({"type": "budget_update", **budget.to_dict()})

    # ---- Finalize ----

    session.total_cost = budget.spent_usd
    session.ended_at = SprintContract().created_at  # Use _now()
    db.save_session(session)

    _emit_session(
        EventType.SESSION_COMPLETE.value,
        completed=session.completed_sprints,
        failed=session.failed_sprints,
        total_cost=session.total_cost,
    )
    _broadcast({"type": "session_complete", "session": session.to_dict()})
    return session
