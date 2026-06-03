"""SWE-bench metric tiers + run profiles.

The kill gate produces one number (resolve rate), but a bare percentage is
neither trustworthy (n=50 is small) nor enough to justify Forge's three-agent
thesis. So metrics are organized into **tiers**, and users pick a **profile**
that bundles tiers by *cost* — because tiers are NOT equally cheap:

  - Tiers 1, 2, 4 are pure aggregations of a **single** run → free to add.
  - Tier 3's *baseline delta* needs a **second** run (single-agent) → 2× cost.
  - Tier 5 (determinism) needs **N** repeat runs → N× cost.

A flat "tick any tier" UI would hide that cost cliff. A profile dropdown makes
the trade-off explicit: each profile maps to a tier set *and* a run plan.

This module is pure data + small helpers (no I/O), so the CLI flag, the WS
handler that feeds the UI dropdown, and the metrics layer all share one source
of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MetricTier(int, Enum):
    """Metric groups, ordered by what they tell you (and what they cost)."""

    GATE = 1  # resolve rate + Wilson CI — the go/no-go
    VALIDITY = 2  # apply / empty / harness-error / regression — is the score real?
    THESIS = 3  # baseline delta + evaluator accuracy — does the architecture earn it?
    COST = 4  # tokens / time / $ per resolved task
    DETERMINISM = 5  # variance across repeated runs


# Human-facing labels for each tier (UI legend / report headers).
TIER_LABELS: dict[MetricTier, str] = {
    MetricTier.GATE: "Kill gate (resolve rate + confidence interval)",
    MetricTier.VALIDITY: "Validity (patch-apply, empty, harness error, regressions)",
    MetricTier.THESIS: "Thesis (single-agent baseline delta + evaluator accuracy)",
    MetricTier.COST: "Cost & efficiency (tokens / time / $ per resolved task)",
    MetricTier.DETERMINISM: "Determinism (variance across repeated runs)",
}


class BenchProfile(str, Enum):
    """A user-selectable benchmark depth. The dropdown is populated from these."""

    GATE = "gate"
    DIAGNOSTIC = "diagnostic"
    BASELINE = "baseline"
    FULL = "full"


@dataclass(frozen=True)
class ProfileSpec:
    """What a profile computes and how expensive it is."""

    profile: BenchProfile
    label: str
    description: str
    tiers: tuple[MetricTier, ...]
    runs: int  # how many full passes over the subset
    needs_baseline_run: bool  # run the single-agent comparison?

    def cost_multiplier(self) -> int:
        """Rough run-count multiplier vs the single-run gate (for the UI)."""
        return self.runs + (1 if self.needs_baseline_run else 0)


# Profiles are additive in tiers and increasing in cost. DETERMINISM_RUNS is the
# default repeat count for the FULL profile (kept small — each run is heavy).
DETERMINISM_RUNS = 3

_PROFILES: dict[BenchProfile, ProfileSpec] = {
    BenchProfile.GATE: ProfileSpec(
        profile=BenchProfile.GATE,
        label="Kill gate only",
        description="Single run. Resolve rate + confidence interval + validity. "
        "The minimal go/no-go (≥30% on the subset).",
        tiers=(MetricTier.GATE, MetricTier.VALIDITY),
        runs=1,
        needs_baseline_run=False,
    ),
    BenchProfile.DIAGNOSTIC: ProfileSpec(
        profile=BenchProfile.DIAGNOSTIC,
        label="Diagnostic",
        description="Single run. Adds cost/efficiency and evaluator-accuracy "
        "diagnostics — no extra passes, so same wall-clock as the gate.",
        tiers=(MetricTier.GATE, MetricTier.VALIDITY, MetricTier.THESIS, MetricTier.COST),
        runs=1,
        needs_baseline_run=False,
    ),
    BenchProfile.BASELINE: ProfileSpec(
        profile=BenchProfile.BASELINE,
        label="Baseline comparison (2×)",
        description="Two runs: the full harness AND a single-agent baseline, so "
        "the three-agent-beats-single-agent delta is measured. ~2× cost.",
        tiers=(MetricTier.GATE, MetricTier.VALIDITY, MetricTier.THESIS, MetricTier.COST),
        runs=1,
        needs_baseline_run=True,
    ),
    BenchProfile.FULL: ProfileSpec(
        profile=BenchProfile.FULL,
        label=f"Full ({DETERMINISM_RUNS}× + baseline)",
        description=f"{DETERMINISM_RUNS} repeated runs (for variance) plus the "
        "single-agent baseline. Most thorough and most expensive.",
        tiers=tuple(MetricTier),  # all five
        runs=DETERMINISM_RUNS,
        needs_baseline_run=True,
    ),
}


def get_profile(profile: BenchProfile | str) -> ProfileSpec:
    """Resolve a profile (enum or string) to its spec."""
    if isinstance(profile, str):
        try:
            profile = BenchProfile(profile)
        except ValueError as e:
            valid = ", ".join(p.value for p in BenchProfile)
            raise ValueError(f"unknown bench profile {profile!r}; pick one of: {valid}") from e
    return _PROFILES[profile]


def profile_tiers(profile: BenchProfile | str) -> tuple[MetricTier, ...]:
    """The metric tiers a profile computes."""
    return get_profile(profile).tiers


def all_profiles() -> list[ProfileSpec]:
    """Ordered list of every profile (for the CLI list + UI dropdown)."""
    return [_PROFILES[p] for p in BenchProfile]


def profile_options() -> list[dict]:
    """Dropdown payload: one option per profile with tiers + cost + description.

    Shape mirrored by ``ui/lib/types.ts::BenchProfileOption`` so the UI can
    render the selector directly.
    """
    return [
        {
            "value": spec.profile.value,
            "label": spec.label,
            "description": spec.description,
            "tiers": [int(t) for t in spec.tiers],
            "tier_labels": [TIER_LABELS[t] for t in spec.tiers],
            "runs": spec.runs,
            "cost_multiplier": spec.cost_multiplier(),
        }
        for spec in all_profiles()
    ]
