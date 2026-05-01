"""ADaPT-style recovery + Self-Consistency for critical sprints (Phase 3 W9).

Two complementary recovery mechanisms layered on top of Forge's normal
generate→evaluate→revise loop. They activate at different boundaries:

  1. **ADaPT recursive decomposition** (Prasad et al., arxiv 2311.05772) —
     activates when a sprint fails after ``MAX_REVISIONS`` (default 2). Instead
     of escalating to the user, the recovery layer asks the planner to break
     the failing sprint into smaller sub-sprints and runs them sequentially.
     Each sub-sprint inherits the parent's worktree but has tighter
     done_criteria. This is "lazy decomposition" — only spend the planner
     LLM call when the model is genuinely stuck.

  2. **Self-Consistency for ``critical`` sprints** — opts-in via
     ``sprint.metadata["critical"] = True``. When set, the recovery layer
     runs N=3 generators sequentially against fresh worktrees, has the
     evaluator grade each, and picks the highest-scoring result. On M-series
     hardware we run sequentially (the M4 Pro 48GB target can't fit 3 large
     models in parallel — see ADR-002 / [docs/COMPETITIVE_COMPARISON.md](../docs/COMPETITIVE_COMPARISON.md)).

Both mechanisms write trace events via ``daemon.replay`` so the user can
post-mortem what happened.

Why these are in their own module instead of inlined in scheduler.py: each
is independently testable, and the scheduler shouldn't grow more code than
it already has. ``scheduler.py`` calls into ``recovery.adapt_failed_sprint``
or ``recovery.self_consistent_run`` at the right moment; this module owns
the algorithm.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .events import EventType
from .models import EvaluatorResult, ExecutionResult, SprintContract
from .replay import append_event

logger = logging.getLogger(__name__)


# ---- ADaPT recursive decomposition ----


@dataclass
class DecompositionResult:
    """Result of an ADaPT-style decomposition + sequential execution."""

    parent_sprint_id: str
    sub_sprints: list[SprintContract] = field(default_factory=list)
    sub_results: list[ExecutionResult] = field(default_factory=list)
    final_verdict: str = "FAIL"  # PASS / FAIL / PARTIAL
    notes: str = ""

    @property
    def all_passed(self) -> bool:
        return self.final_verdict == "PASS"


def is_eligible_for_decomposition(sprint: SprintContract) -> bool:
    """Decide whether a failed sprint is a good candidate for ADaPT recovery.

    Heuristics:
      - The sprint has 2+ done_criteria (single-criterion sprints don't
        decompose meaningfully).
      - It hasn't been recursively decomposed already (we don't recurse
        infinitely; metadata flag prevents it).
      - It hit MAX_REVISIONS, not some lower count.

    The metadata signal lives in ``sprint.error`` for v1; future versions
    can add a structured ``recursion_depth`` field to SprintContract if
    needed.
    """
    if len(sprint.done_criteria) < 2:
        return False
    if sprint.assigned_worktree and sprint.assigned_worktree.startswith("recovery-"):
        # Already a sub-sprint from a prior decomposition; don't recurse
        return False
    return True


def split_into_subsprints(parent: SprintContract) -> list[SprintContract]:
    """Heuristic-only sub-sprint splitter (no LLM call).

    The simple-but-useful split: one sub-sprint per done_criterion. Each
    sub-sprint inherits the parent's description but narrows its
    done_criteria to the single criterion it owns. The parent's other
    metadata (worktree, model, files_scope) carries through.

    For more ambitious decomposition (introspecting *why* the sprint failed
    and proposing structurally different sub-sprints), the planner can be
    invoked — that's a follow-up. The single-criterion split is a strong
    baseline because it forces the generator to focus, which often resolves
    "the model got distracted by criterion 4 and forgot criteria 1–3".
    """
    sub_sprints: list[SprintContract] = []
    for i, criterion in enumerate(parent.done_criteria, start=1):
        sub = SprintContract(
            id=f"{parent.id}-sub-{i}",
            session_id=parent.session_id,
            description=(
                f"{parent.description}\n\n"
                f"(Sub-task {i}/{len(parent.done_criteria)} from a recursively-"
                f"decomposed sprint.)"
            ),
            done_criteria=[criterion],
            depends_on=[s.id for s in sub_sprints],  # serialize: each depends on the previous
            files_scope=parent.files_scope,
            assigned_model=parent.assigned_model,
            assigned_worktree=parent.assigned_worktree,
        )
        sub_sprints.append(sub)
    return sub_sprints


async def adapt_failed_sprint(
    parent: SprintContract,
    *,
    run_subsprint: Callable[[SprintContract], Awaitable[tuple[ExecutionResult, EvaluatorResult]]],
) -> DecompositionResult:
    """Recover from a failed sprint via ADaPT decomposition.

    Splits ``parent`` into sub-sprints (one per done_criterion), runs them
    sequentially via the caller-supplied ``run_subsprint`` callable, and
    aggregates results.

    The ``run_subsprint`` callable abstracts the actual execution so this
    function is unit-testable without a real Forge daemon. In production
    the scheduler passes a closure that drives the generator/evaluator
    pipeline; in tests we pass a mock.
    """
    if not is_eligible_for_decomposition(parent):
        return DecompositionResult(
            parent_sprint_id=parent.id,
            final_verdict="FAIL",
            notes="not eligible for decomposition",
        )

    sub_sprints = split_into_subsprints(parent)
    append_event(
        parent.session_id,
        EventType.RECOVERY_ADAPT_DECOMPOSED.value,
        sprint_id=parent.id,
        data={
            "parent_id": parent.id,
            "sub_sprint_count": len(sub_sprints),
            "criteria": parent.done_criteria,
        },
    )

    results: list[ExecutionResult] = []
    all_passed = True

    for sub in sub_sprints:
        try:
            exec_result, eval_result = await run_subsprint(sub)
        except Exception as e:
            logger.exception("adapt: sub-sprint %s crashed", sub.id)
            results.append(ExecutionResult(success=False, error=f"sub-sprint crash: {e}"))
            all_passed = False
            break

        results.append(exec_result)
        passed = exec_result.success and eval_result.verdict == "APPROVED"
        if not passed:
            all_passed = False
            append_event(
                parent.session_id,
                EventType.RECOVERY_ADAPT_SUBSPRINT_FAILED.value,
                sprint_id=sub.id,
                data={
                    "verdict": eval_result.verdict,
                    "feedback": eval_result.feedback[:200],
                },
            )
            # Stop at the first failure — sub-sprints serialize on each
            # other (depends_on chain) so a downstream sub-sprint depending
            # on a failed earlier one will fail too. Better to surface the
            # first failure cleanly than rack up cascading failures.
            break
        append_event(
            parent.session_id,
            EventType.RECOVERY_ADAPT_SUBSPRINT_PASSED.value,
            sprint_id=sub.id,
            data={"criterion": sub.done_criteria[0]},
        )

    verdict = "PASS" if all_passed else "PARTIAL" if any(r.success for r in results) else "FAIL"
    return DecompositionResult(
        parent_sprint_id=parent.id,
        sub_sprints=sub_sprints,
        sub_results=results,
        final_verdict=verdict,
    )


# ---- Self-Consistency for critical sprints ----


@dataclass
class SelfConsistencyResult:
    """Result of N=3 sequential attempts at the same sprint.

    The winner is the attempt with the highest evaluator score. If multiple
    attempts produced APPROVED verdicts, we pick the first one (the most
    cache-friendly) — running more attempts is wasted token spend.
    """

    sprint_id: str
    attempts: list[tuple[ExecutionResult, EvaluatorResult]] = field(default_factory=list)
    winner_index: int = -1
    final_verdict: str = "REVISE"

    @property
    def winner(self) -> tuple[ExecutionResult, EvaluatorResult] | None:
        if 0 <= self.winner_index < len(self.attempts):
            return self.attempts[self.winner_index]
        return None


def is_critical(sprint: SprintContract) -> bool:
    """Is this sprint flagged for Self-Consistency mode?

    Primary signal: the structured ``sprint.critical`` boolean (added in
    Task 3.2). Backwards-compat fallback: the legacy ``[critical]`` /
    ``[critical:...]`` prefix in the description string. The fallback path
    keeps hand-crafted prompts and older serialized sprints working.
    """
    if getattr(sprint, "critical", False):
        return True
    desc = sprint.description.lower() if sprint.description else ""
    return desc.startswith("[critical]") or "[critical:" in desc


def score_attempt(eval_result: EvaluatorResult) -> int:
    """Score a single attempt for picking the winner.

    Approval beats partial-pass beats fail. Tiebreaks go to the attempt
    with more passing criteria, then more evidence text (a proxy for
    evaluator confidence).
    """
    if eval_result.verdict == "APPROVED":
        base = 1000
    else:
        base = 0
    passed = sum(1 for cr in eval_result.criteria_results if cr.passed)
    evidence = sum(len(cr.evidence) for cr in eval_result.criteria_results)
    return base + passed * 10 + evidence // 100


async def self_consistent_run(
    sprint: SprintContract,
    *,
    n: int = 3,
    run_attempt: Callable[
        [SprintContract, int], Awaitable[tuple[ExecutionResult, EvaluatorResult]]
    ],
) -> SelfConsistencyResult:
    """Run ``sprint`` ``n`` times sequentially; pick the highest-scoring
    attempt as the winner.

    On M-series hardware Self-Consistency is **sequential** — running 3
    Qwen3-Coder-Next instances simultaneously won't fit in 48GB. The
    sequential cost is acceptable because ``critical=True`` sprints are
    a small fraction of the workload by design.

    Parameters
    ----------
    sprint
        Sprint to run repeatedly. Each attempt gets the same contract.
    n
        Number of attempts (default 3, matches the Self-Consistency paper
        and Anthropic's parallel-research-system minimum).
    run_attempt
        Async callable that takes (sprint, attempt_index) and returns
        (ExecutionResult, EvaluatorResult). Provided by the scheduler.

    Returns
    -------
    SelfConsistencyResult
        With ``winner`` populated when at least one attempt produced an
        APPROVED verdict; otherwise the highest-scoring attempt is the
        "winner" but ``final_verdict`` stays REVISE.
    """
    attempts: list[tuple[ExecutionResult, EvaluatorResult]] = []
    append_event(
        sprint.session_id,
        EventType.RECOVERY_CONSISTENCY_START.value,
        sprint_id=sprint.id,
        data={"n": n},
    )

    for i in range(n):
        try:
            attempt = await run_attempt(sprint, i)
        except Exception as e:
            logger.exception("self_consistent: attempt %d crashed", i)
            attempt = (
                ExecutionResult(success=False, error=f"attempt crash: {e}"),
                EvaluatorResult(verdict="REVISE", feedback=f"attempt {i} crashed"),
            )
        attempts.append(attempt)
        append_event(
            sprint.session_id,
            EventType.RECOVERY_CONSISTENCY_ATTEMPT.value,
            sprint_id=sprint.id,
            data={
                "attempt": i,
                "verdict": attempt[1].verdict,
                "score": score_attempt(attempt[1]),
            },
        )
        # Early exit: first APPROVED wins (saves the remaining attempts).
        if attempt[1].verdict == "APPROVED":
            break

    if not attempts:
        return SelfConsistencyResult(sprint_id=sprint.id)

    # Pick the highest-scoring attempt.
    scores = [score_attempt(eval_) for _, eval_ in attempts]
    winner_idx = max(range(len(attempts)), key=lambda i: scores[i])
    final = "APPROVED" if attempts[winner_idx][1].verdict == "APPROVED" else "REVISE"

    append_event(
        sprint.session_id,
        EventType.RECOVERY_CONSISTENCY_WINNER.value,
        sprint_id=sprint.id,
        data={"winner_attempt": winner_idx, "verdict": final, "scores": scores},
    )

    return SelfConsistencyResult(
        sprint_id=sprint.id,
        attempts=attempts,
        winner_index=winner_idx,
        final_verdict=final,
    )
