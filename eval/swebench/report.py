"""Render a SWE-bench metrics dict (from metrics.compute_metrics) as a scorecard.

Two outputs: a machine-readable JSON blob (for CI / the WS layer) and a human
markdown scorecard. Both only show the tiers that were computed, so the report
matches the profile the user selected from the dropdown.
"""

from __future__ import annotations

import json

from .tiers import TIER_LABELS, BenchProfile, MetricTier, get_profile


def to_json(metrics: dict, *, indent: int = 2) -> str:
    return json.dumps(metrics, indent=indent, sort_keys=True)


def render_markdown(metrics: dict, profile: BenchProfile | str) -> str:
    """Human scorecard for the selected profile + computed tiers."""
    spec = get_profile(profile)
    lines: list[str] = [
        f"# SWE-bench scorecard — profile: {spec.label}",
        "",
        spec.description,
        "",
    ]

    gate = metrics.get("gate")
    if gate:
        verdict = "PASS ✅" if gate["kill_passed_point"] else "FAIL ❌"
        ci_verdict = "yes" if gate["kill_passed_ci_lower"] else "no"
        lines += [
            f"## {TIER_LABELS[MetricTier.GATE]}",
            "",
            f"- **Resolve rate: {gate['resolve_rate_pct']}%** "
            f"({gate['resolved']}/{gate['total']}) — kill gate (≥{gate['threshold_pct']}%): "
            f"**{verdict}**",
            f"- 95% CI: [{gate['ci95_pct'][0]}%, {gate['ci95_pct'][1]}%] "
            f"— lower bound clears {gate['threshold_pct']}%? **{ci_verdict}**",
            f"- Excl. harness errors: {gate['resolve_rate_excl_harness_errors_pct']}%",
            "",
        ]

    validity = metrics.get("validity")
    if validity:
        lines += [
            f"## {TIER_LABELS[MetricTier.VALIDITY]}",
            "",
            f"- patch-apply: {validity['patch_apply_rate_pct']}%",
            f"- empty patch: {validity['empty_patch_rate_pct']}%",
            f"- harness error: {validity['harness_error_rate_pct']}%",
            f"- PASS_TO_PASS regression: {validity['p2p_regression_rate_pct']}%",
            "",
        ]

    thesis = metrics.get("thesis")
    if thesis:
        lines += [f"## {TIER_LABELS[MetricTier.THESIS]}", ""]
        if "baseline_delta_pct" in thesis:
            lines.append(
                f"- **Baseline delta: {thesis['baseline_delta_pct']:+}%** "
                f"(full {thesis['full_resolve_rate_pct']}% vs single-agent "
                f"{thesis['baseline_resolve_rate_pct']}%)"
            )
        lines += [
            f"- evaluator false-approve: {thesis['evaluator_false_approve']} "
            f"(precision {thesis['evaluator_precision_pct']}%, "
            f"recall {thesis['evaluator_recall_pct']}%)",
            f"- resolve by revisions: {thesis['resolve_by_revisions']}",
            "",
        ]

    cost = metrics.get("cost")
    if cost:
        lines += [
            f"## {TIER_LABELS[MetricTier.COST]}",
            "",
            f"- tokens: {cost['tokens_in_total']} in / {cost['tokens_out_total']} out",
            f"- cost: ${cost['cost_usd_total']} total"
            + (
                f", ${cost['cost_per_resolved_usd']}/resolved"
                if cost.get("cost_per_resolved_usd") is not None
                else ""
            ),
            f"- wall-clock: {cost['wallclock_seconds_total']}s "
            f"({cost['mean_seconds_per_task']}s/task)",
            "",
        ]

    det = metrics.get("determinism")
    if det:
        lines += [f"## {TIER_LABELS[MetricTier.DETERMINISM]}", ""]
        if det.get("runs", 0) >= 2:
            lines += [
                f"- rates: {det['resolve_rates_pct']}%",
                f"- mean {det['mean_pct']}% ± {det['stdev_pct']}% (spread {det['spread_pct']}%)",
                "",
            ]
        else:
            lines += [f"- {det.get('note', 'n/a')}", ""]

    return "\n".join(lines).rstrip() + "\n"
