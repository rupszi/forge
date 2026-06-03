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
from .mode import ModeState
from .models import EvaluatorResult, ExecutionResult, ProjectContext, Session, SprintContract
from .pool import ModelPool, set_active_pool
from .scanner.repomap import build_repomap

# The plugin dispatcher is intentionally re-exported here so callers in the
# agent loop / generator hooks reach for ``daemon.scheduler.dispatch_plugin``
# alongside the rest of the sprint-execution surface. Importing from this
# module rather than ``daemon.skills`` makes the wiring intention explicit:
# plugin invocations are part of sprint execution, not a side channel.
from .skills import DispatchResult, dispatch_plugin  # noqa: F401  # re-export

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


async def _generate_with_pool(
    sprint: SprintContract,
    memory: str,
    wt_path: str,
    repomap: str,
    revision_feedback: str,
    mode: str,
    pool: ModelPool | None,
    num_ctx: int | None = None,
) -> ExecutionResult:
    """Run the generator, optionally holding a model-pool lease for its model."""

    async def _call() -> ExecutionResult:
        return await generator.generate(
            sprint,
            memory_context=memory,
            worktree_path=wt_path,
            repomap=repomap,
            revision_feedback=revision_feedback,
            mode=mode,
            num_ctx=num_ctx,
        )

    if pool is None:
        return await _call()

    from .model_setup import estimate_size_gb

    async with pool.lease(sprint.assigned_model, estimate_size_gb(sprint.assigned_model)):
        return await _call()


async def _run_one_attempt(
    sprint: SprintContract,
    ctx: ProjectContext,
    wt_path: str,
    memory: str,
    repomap: str,
    revision_feedback: str = "",
    *,
    mode: str = "auto",
    pool: ModelPool | None = None,
    num_ctx: int | None = None,
) -> tuple[ExecutionResult, EvaluatorResult]:
    """Run one generate→evaluate cycle.

    Pulled out as a standalone helper so both the normal sprint loop and the
    Self-Consistency layer can call it. Returns the pair so the caller can
    decide what to do (revise, accept, escalate to recovery).

    When a ``pool`` is supplied (M2), the generator model is acquired through
    it so concurrent sprints respect the local RAM budget — large models are
    serialized and LRU-evicted rather than overcommitting memory.
    """
    gen_result = await _generate_with_pool(
        sprint, memory, wt_path, repomap, revision_feedback, mode, pool, num_ctx
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
    mode_state: ModeState | None = None,
    pool: ModelPool | None = None,
) -> SprintContract:
    """Execute one sprint: generate → evaluate → revise (≤MAX_REVISIONS) → done.

    Augmented in Phase 3 with:
      - Self-Consistency mode for ``[critical]`` sprints (N=3 attempts, best wins)
      - ADaPT recovery on `MAX_REVISIONS` exhaustion (recursive decomposition)
      - Procedural-memory writeback after every verdict
      - Trace event emission at every transition

    ``mode_state`` (Sprint 6.2) is read once at the top of the sprint
    loop; we pass the snapshotted ``current_mode`` to each attempt so a
    mid-sprint mode flip from the UI doesn't break invariants in flight.
    """
    import time

    current_mode = (mode_state or ModeState()).mode

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

    memory, injected_kb_ids = retriever.get_context_and_ids(sprint.description)

    # Inject any user-attached files as extra context (budget-capped). Folded
    # into the memory block so the generator's existing context-window
    # truncation applies uniformly.
    from .attachments import get_store as _get_attach_store

    _attach_ctx = _get_attach_store().context(budget_tokens=4000)
    if _attach_ctx:
        memory = f"{memory}\n\n{_attach_ctx}" if memory else _attach_ctx

    # Working-memory scratchpad (.forge/memories/) — persists across sprints.
    from .memory_tool import default_tool as _default_mem_tool
    from .safety import silent_catch as _silent

    try:
        # Scope the scratchpad to THIS (project, session) so a prior session's
        # notes never re-inject into this sprint, and no other project's notes
        # leak in (audit F3).
        _mem_ctx = _default_mem_tool(ctx.path, session_id).context()
        if _mem_ctx:
            memory = f"{memory}\n\n{_mem_ctx}" if memory else _mem_ctx
    except Exception as e:  # never let scratchpad I/O break a sprint
        _silent(__name__, e)

    # Auto-compaction: when the assembled memory block (KB + attachments +
    # scratchpad) gets large, summarize it with a local model instead of
    # letting the generator hard-truncate it. Gated on size, so small contexts
    # (and the test path) never invoke a model.
    from .compaction import (
        MEMORY_CONTEXT_BUDGET_TOKENS,
        compact_text,
        estimate_tokens,
        ollama_summarizer,
        should_compact,
    )
    from .config import auto_compact_enabled

    if (
        auto_compact_enabled()
        and memory
        and should_compact(estimate_tokens(memory), MEMORY_CONTEXT_BUDGET_TOKENS, threshold=1.0)
    ):
        try:
            memory = await compact_text(memory, MEMORY_CONTEXT_BUDGET_TOKENS, ollama_summarizer)
        except Exception as e:
            _silent(__name__, e)

    sprint_start = time.time()

    # Snapshot the context window ONCE for this sprint's (now-finalized) model
    # (F13). context_window._setting / _kv_setting are process globals the UI
    # can flip mid-session; resolving here freezes the value so a flip can't
    # change the window of a sprint already in flight. Threaded to every attempt
    # (normal, revision, Self-Consistency) for this same sprint+model.
    from .context_window import resolve_num_ctx as _resolve_num_ctx

    sprint_num_ctx = _resolve_num_ctx(sprint.assigned_model)

    def _reinforce(completed: bool) -> None:
        """Confidence reinforcement (M3): nudge the KB items that were injected
        into this sprint's context up (approved) or down (failed)."""
        if not injected_kb_ids:
            return
        from .memory.knowledge import KnowledgeBase
        from .safety import silent_catch

        try:
            KnowledgeBase(db).reinforce(injected_kb_ids, helpful=completed)
        except Exception as e:
            silent_catch(__name__, e)

    # ---- Self-Consistency branch for [critical] sprints ----
    #
    # If the sprint is flagged critical (per `recovery.is_critical`), run
    # N=3 sequential attempts and pick the highest-scoring verdict. We bypass
    # the normal revision loop because the failure mode for critical sprints
    # is "model went off the rails on attempt 1" not "needs more iterations".

    if recovery.is_critical(sprint):
        _emit(EventType.RECOVERY_CONSISTENCY_START.value, reason="critical sprint")

        async def _attempt(_sprint, _i):
            return await _run_one_attempt(
                _sprint,
                ctx,
                wt_path,
                memory,
                repomap,
                mode=current_mode,
                pool=pool,
                num_ctx=sprint_num_ctx,
            )

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
            _reinforce(sprint.status == "completed")
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
            sprint,
            ctx,
            wt_path,
            memory,
            repomap,
            revision_feedback,
            mode=current_mode,
            pool=pool,
            num_ctx=sprint_num_ctx,
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
            return await _run_one_attempt(
                sub, ctx, sub_wt_path, sub_memory, repomap, mode=current_mode, pool=pool
            )

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

    _reinforce(sprint.status == "completed")
    db.save_sprint(sprint)
    return sprint


async def execute_session(
    objective: str,
    ctx: ProjectContext,
    db: ForgeDB,
    budget: BudgetController,
    broadcast: Callable | None = None,
    use_local_planner: bool = True,
    *,
    mode_state: ModeState | None = None,
) -> Session:
    """Full session: plan → generate → evaluate → learn.

    Builds the repomap once at session start (per ADR-002 — repomap is
    expensive and stable; rebuild only on `forge init` or major file
    changes). Emits trace events at every phase transition.

    ``mode_state`` (Sprint 6.2) gates the wave-execution phase: in
    ``plan`` mode the planner runs and persists the sprint contracts,
    but the wave loop is skipped — the user reviews in the UI and
    flips to ``auto`` to run. ``bypass`` mode is logged loudly. Other
    modes (auto / accept_edits / ask) execute waves normally; ``ask``
    additionally injects a prompt addendum at the generator boundary
    (handled by ``generator.generate``).
    """
    if mode_state is None:
        mode_state = ModeState()
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

    # ---- Sprint 7.1: SessionStart hooks ----
    #
    # User-supplied scripts in .forge/hooks.toml can fire here to
    # inject project-specific context (e.g., load CI status, fetch
    # recent PR descriptions). A blocking SessionStart hook aborts
    # the session before any tokens are spent.
    from pathlib import Path as _Path

    from . import hooks as _hooks

    _hooks_cfg = _Path(ctx.path or ".") / ".forge" / "hooks.toml"
    if _hooks_cfg.is_file():
        try:
            _hook_results = await _hooks.run_hooks(
                "SessionStart",
                {"session_id": session.id, "objective": objective, "cwd": ctx.path},
                config_path=_hooks_cfg,
                target=objective,
            )
            blocker = _hooks.has_blocking_result(_hook_results)
            if blocker is not None:
                logger.warning("SessionStart hook blocked: %s", blocker.reason)
                _emit_session(
                    EventType.SESSION_HOOK_BLOCKED.value,
                    event_name="SessionStart",
                    reason=blocker.reason,
                )
                session.ended_at = SprintContract().created_at
                db.save_session(session)
                return session
        except Exception as e:  # hooks must never crash the daemon
            logger.warning("SessionStart hooks raised, ignoring: %s", e)

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

    # ---- Sprint 6.2: mode gate ----
    #
    # In ``plan`` mode the user wants to review before any code runs. We
    # emit a lifecycle event explaining the early return and stop here —
    # the planner output is already persisted via db.save_sprint above
    # so the user can flip to auto and run the same plan with no replan.
    if mode_state.is_plan_only():
        logger.info("plan-only mode: skipping wave execution; %d sprints await user", len(sprints))
        _emit_session(EventType.SESSION_PLAN_ONLY.value, sprint_count=len(sprints))
        session.ended_at = SprintContract().created_at
        db.save_session(session)
        _broadcast(
            {
                "type": "session_complete",
                "session": session.to_dict(),
                "plan_only": True,
            }
        )
        return session

    if mode_state.is_bypass():
        # No real "bypass" surface for the daemon to skip yet — log loudly
        # so the audit trail and `forge replay` show that the user explicitly
        # chose this. When per-tool checkpoints land in Sprint 7 they branch
        # on ModeState.is_bypass() to decide whether to prompt.
        logger.warning(
            "BYPASS mode active for session %s — capability prompts suppressed", session.id
        )
        _emit_session(EventType.SESSION_BYPASS.value, session_id=session.id)

    # ---- Phase 2: Execute waves ----
    #
    # One model pool per session (M2). Bound by the local RAM budget; the
    # orchestrator + embedding models are pinned so on-demand coder/evaluator
    # models evict around them instead of them. on_change pushes pool_state to
    # the UI so the RAM meter is live. Constructed here (inside the running
    # loop) so its asyncio primitives bind to the right event loop.
    from .config import LOCAL_EMBED_MODEL, LOCAL_PLAN_MODEL

    pool = ModelPool(
        on_change=_broadcast,
        pinned={LOCAL_PLAN_MODEL, LOCAL_EMBED_MODEL},
    )
    set_active_pool(pool)

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
                    mode_state=mode_state,
                    pool=pool,
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
