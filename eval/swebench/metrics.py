"""SWE-bench metrics — tier-filtered computation over a run's results.

Given a :class:`~eval.swebench.adapter.SubsetResult` (and optionally a
single-agent baseline + repeated-run resolve rates), compute exactly the metric
tiers a profile selected. The output is a plain dict keyed by tier number so
the report renderer and the WS layer can consume it without importing enums.

The kill criterion (ADR-015) is ≥30% on the subset. At n=50 that point estimate
has a wide confidence interval, so the GATE tier reports the Wilson 95% CI and
whether the *lower bound* clears 30% — a far more honest "did we pass" signal
than the point estimate alone.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .adapter import SubsetResult, TaskRunResult
from .tiers import MetricTier

KILL_THRESHOLD_PCT = 30.0
_Z_95 = 1.959963984540054  # z for a 95% two-sided normal interval


def wilson_ci(passed: int, total: int, z: float = _Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, returned as percentages.

    Preferred over the normal approximation for small n / extreme rates (it
    never escapes [0, 1] and behaves near 0% / 100%). ``total == 0`` → (0, 0).
    """
    if total == 0:
        return (0.0, 0.0)
    p = passed / total
    z2 = z * z
    denom = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total)) / denom
    lo = max(0.0, center - margin)
    hi = min(1.0, center + margin)
    return (round(lo * 100, 2), round(hi * 100, 2))


def _is_resolved(r: TaskRunResult) -> bool:
    """Verified truth from the harness; unverified (None) counts as not resolved."""
    return bool(r.resolved)


def _gate(results: list[TaskRunResult]) -> dict:
    total = len(results)
    resolved = sum(_is_resolved(r) for r in results)
    errored = sum(r.harness_error for r in results)
    rate = round(100.0 * resolved / total, 2) if total else 0.0
    lo, hi = wilson_ci(resolved, total)
    # Conservative gate excludes harness/infra failures from the denominator so
    # Docker flakes don't sink an otherwise-passing run (reported alongside).
    effective = total - errored
    eff_rate = round(100.0 * resolved / effective, 2) if effective else 0.0
    return {
        "total": total,
        "resolved": resolved,
        "resolve_rate_pct": rate,
        "ci95_pct": [lo, hi],
        "threshold_pct": KILL_THRESHOLD_PCT,
        "kill_passed_point": rate >= KILL_THRESHOLD_PCT,
        "kill_passed_ci_lower": lo >= KILL_THRESHOLD_PCT,
        "resolve_rate_excl_harness_errors_pct": eff_rate,
    }


def _validity(results: list[TaskRunResult]) -> dict:
    total = len(results) or 1
    return {
        "patch_apply_rate_pct": round(100.0 * sum(r.patch_applied for r in results) / total, 2),
        "empty_patch_rate_pct": round(100.0 * sum(r.empty_patch for r in results) / total, 2),
        "harness_error_rate_pct": round(100.0 * sum(r.harness_error for r in results) / total, 2),
        "p2p_regression_rate_pct": round(100.0 * sum(r.p2p_regressed for r in results) / total, 2),
    }


def _thesis(results: list[TaskRunResult], baseline: SubsetResult | None) -> dict:
    # Evaluator reliability: when Forge said APPROVED, did the harness agree?
    approved = [r for r in results if r.evaluator_verdict == "APPROVED"]
    true_pos = sum(_is_resolved(r) for r in approved)
    false_approve = len(approved) - true_pos
    resolved_total = sum(_is_resolved(r) for r in results)
    out: dict = {
        "approved": len(approved),
        "evaluator_true_approve": true_pos,
        "evaluator_false_approve": false_approve,
        "evaluator_precision_pct": round(100.0 * true_pos / len(approved), 2) if approved else 0.0,
        "evaluator_recall_pct": (
            round(100.0 * true_pos / resolved_total, 2) if resolved_total else 0.0
        ),
        "resolve_by_revisions": _resolve_by_revisions(results),
    }
    if baseline is not None:
        full_rate = (
            round(100.0 * sum(_is_resolved(r) for r in results) / len(results), 2)
            if results
            else 0.0
        )
        base_rate = (
            round(
                100.0
                * sum(_is_resolved(r) for r in baseline.by_task.values())
                / len(baseline.by_task),
                2,
            )
            if baseline.by_task
            else 0.0
        )
        out["full_resolve_rate_pct"] = full_rate
        out["baseline_resolve_rate_pct"] = base_rate
        out["baseline_delta_pct"] = round(full_rate - base_rate, 2)
    return out


def _resolve_by_revisions(results: list[TaskRunResult]) -> dict[str, dict]:
    buckets: dict[int, list[TaskRunResult]] = {}
    for r in results:
        buckets.setdefault(r.revisions, []).append(r)
    return {
        str(rev): {
            "tasks": len(rs),
            "resolved": sum(_is_resolved(x) for x in rs),
        }
        for rev, rs in sorted(buckets.items())
    }


def _cost(results: list[TaskRunResult]) -> dict:
    resolved = [r for r in results if _is_resolved(r)]
    tin = sum(r.tokens_in for r in results)
    tout = sum(r.tokens_out for r in results)
    cost = round(sum(r.cost_usd for r in results), 4)
    dur = sum(r.duration_seconds for r in results)
    n = len(results) or 1
    nr = len(resolved) or 1
    return {
        "tokens_in_total": tin,
        "tokens_out_total": tout,
        "cost_usd_total": cost,
        "wallclock_seconds_total": round(dur, 1),
        "mean_seconds_per_task": round(dur / n, 1),
        "tokens_per_resolved": round((tin + tout) / nr, 1) if resolved else None,
        "cost_per_resolved_usd": round(cost / nr, 4) if resolved else None,
    }


def _determinism(run_resolve_rates: Sequence[float] | None) -> dict:
    rates = list(run_resolve_rates or [])
    if len(rates) < 2:
        return {"runs": len(rates), "note": "need ≥2 runs for variance"}
    mean = sum(rates) / len(rates)
    var = sum((x - mean) ** 2 for x in rates) / len(rates)
    return {
        "runs": len(rates),
        "resolve_rates_pct": [round(x, 2) for x in rates],
        "mean_pct": round(mean, 2),
        "stdev_pct": round(math.sqrt(var), 2),
        "spread_pct": round(max(rates) - min(rates), 2),
    }


def compute_metrics(
    subset: SubsetResult,
    tiers: Sequence[MetricTier],
    *,
    baseline: SubsetResult | None = None,
    run_resolve_rates: Sequence[float] | None = None,
) -> dict:
    """Compute exactly the selected ``tiers`` over ``subset``.

    Tiers not requested are absent from the output (the profile dropdown drives
    which ones appear). GATE is always cheap; THESIS uses ``baseline`` when the
    profile ran one; DETERMINISM uses ``run_resolve_rates`` from repeated runs.
    """
    results = list(subset.by_task.values())
    want = set(tiers)
    out: dict = {"tiers": sorted(int(t) for t in want)}
    if MetricTier.GATE in want:
        out["gate"] = _gate(results)
    if MetricTier.VALIDITY in want:
        out["validity"] = _validity(results)
    if MetricTier.THESIS in want:
        out["thesis"] = _thesis(results, baseline)
    if MetricTier.COST in want:
        out["cost"] = _cost(results)
    if MetricTier.DETERMINISM in want:
        out["determinism"] = _determinism(run_resolve_rates)
    return out
