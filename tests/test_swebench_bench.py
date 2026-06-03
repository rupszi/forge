"""Tests for the SWE-bench metric tiers, profiles, metrics, verifier, and CLI.

Covers the tier/profile system that drives the CLI flag + UI dropdown, the
tier-filtered metric computation (incl. Wilson CI), the report-parser, and the
`forge bench` command's offline paths (list/dry-run). The live Docker run is
out of scope (needs hardware) and stays a stub.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from eval.swebench import metrics, tiers, verify
from eval.swebench.adapter import SubsetResult, TaskRunResult

# ---- Tiers + profiles ----


class TestProfiles:
    def test_all_four_profiles_present_and_ordered_by_cost(self):
        specs = tiers.all_profiles()
        values = [s.profile.value for s in specs]
        assert values == ["gate", "diagnostic", "baseline", "full"]
        mults = [s.cost_multiplier() for s in specs]
        assert mults == sorted(mults)  # non-decreasing cost

    def test_gate_is_single_run_tier1_2(self):
        spec = tiers.get_profile("gate")
        assert spec.runs == 1 and not spec.needs_baseline_run
        assert spec.tiers == (tiers.MetricTier.GATE, tiers.MetricTier.VALIDITY)
        assert spec.cost_multiplier() == 1

    def test_baseline_adds_a_second_run(self):
        spec = tiers.get_profile("baseline")
        assert spec.needs_baseline_run is True
        assert spec.cost_multiplier() == 2

    def test_full_includes_all_tiers_and_is_most_expensive(self):
        spec = tiers.get_profile("full")
        assert set(spec.tiers) == set(tiers.MetricTier)
        assert spec.cost_multiplier() == max(s.cost_multiplier() for s in tiers.all_profiles())

    def test_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="unknown bench profile"):
            tiers.get_profile("turbo")

    def test_profile_options_shape_matches_ui_contract(self):
        opts = tiers.profile_options()
        assert {o["value"] for o in opts} == {"gate", "diagnostic", "baseline", "full"}
        for o in opts:
            assert set(o) >= {"value", "label", "description", "tiers", "cost_multiplier", "runs"}
            assert all(isinstance(t, int) for t in o["tiers"])


# ---- Metrics ----


def _subset(n_total: int, n_resolved: int, *, approved_unresolved: int = 0) -> SubsetResult:
    by: dict[str, TaskRunResult] = {}
    for i in range(n_total):
        resolved = i < n_resolved
        # First `approved_unresolved` of the UNRESOLVED tasks are false-approves.
        false_approve = (not resolved) and (i - n_resolved) < approved_unresolved
        verdict = "APPROVED" if (resolved or false_approve) else "REVISE"
        by[f"t{i}"] = TaskRunResult(
            instance_id=f"t{i}",
            success=resolved or false_approve,
            resolved=resolved,
            evaluator_verdict=verdict,
            revisions=i % 3,
            tokens_in=100,
            tokens_out=50,
        )
    return SubsetResult(total=n_total, passed=n_resolved, failed=0, errored=0, by_task=by)


class TestMetrics:
    def test_wilson_ci_known_value(self):
        lo, hi = metrics.wilson_ci(17, 50)
        # Wilson 95% interval for 17/50 ≈ [22.4%, 47.9%]
        assert 22.0 < lo < 23.0
        assert 47.0 < hi < 48.5

    def test_wilson_ci_empty(self):
        assert metrics.wilson_ci(0, 0) == (0.0, 0.0)

    def test_gate_point_passes_but_ci_lower_fails_at_34pct(self):
        m = metrics.compute_metrics(_subset(50, 17), [tiers.MetricTier.GATE])
        g = m["gate"]
        assert g["resolve_rate_pct"] == 34.0
        assert g["kill_passed_point"] is True  # 34 ≥ 30
        assert g["kill_passed_ci_lower"] is False  # lower bound < 30 — honest

    def test_only_requested_tiers_are_computed(self):
        m = metrics.compute_metrics(_subset(10, 5), [tiers.MetricTier.GATE])
        assert "gate" in m
        assert "validity" not in m and "thesis" not in m and "cost" not in m

    def test_evaluator_false_approve_counted(self):
        # 5 resolved + 2 approved-but-unresolved → 2 false approves.
        m = metrics.compute_metrics(
            _subset(10, 5, approved_unresolved=2), [tiers.MetricTier.THESIS]
        )
        assert m["thesis"]["evaluator_false_approve"] == 2
        assert m["thesis"]["evaluator_true_approve"] == 5

    def test_baseline_delta(self):
        full = _subset(10, 6)
        base = _subset(10, 4)
        m = metrics.compute_metrics(full, [tiers.MetricTier.THESIS], baseline=base)
        assert m["thesis"]["baseline_delta_pct"] == 20.0  # 60% - 40%

    def test_determinism_variance(self):
        m = metrics.compute_metrics(
            _subset(10, 5), [tiers.MetricTier.DETERMINISM], run_resolve_rates=[30.0, 34.0, 38.0]
        )
        d = m["determinism"]
        assert d["runs"] == 3
        assert d["mean_pct"] == 34.0
        assert d["spread_pct"] == 8.0


# ---- Verifier ----


class TestVerifier:
    def test_parse_report_marks_absent_as_unresolved(self):
        out = verify.parse_report({"resolved_ids": ["a", "c"]}, ["a", "b", "c"])
        assert out == {"a": True, "b": False, "c": True}

    def test_parse_report_file_missing_is_all_unresolved(self, tmp_path):
        out = verify.parse_report_file(tmp_path / "nope.json", ["a", "b"])
        assert out == {"a": False, "b": False}

    def test_write_predictions_keeps_empty_diffs(self, tmp_path):
        # Empty diffs MUST be written so the denominator isn't silently shrunk.
        p = verify.write_predictions({"a": "diff --git ...", "b": ""}, tmp_path / "preds.jsonl")
        lines = p.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_build_eval_argv_is_a_list_no_shell(self):
        argv = verify.build_eval_argv("preds.jsonl", "run-1")
        assert isinstance(argv, list)
        assert argv[0] == "python" and "run_evaluation" in " ".join(argv)
        assert "--run_id" in argv and "run-1" in argv

    def test_run_verification_uses_injected_invoker(self, tmp_path):
        captured = {}

        def fake_invoker(argv):
            captured["argv"] = argv
            return {"resolved_ids": ["x"]}

        out = verify.run_verification({"x": "d", "y": ""}, "run-1", tmp_path, invoker=fake_invoker)
        assert out == {"x": True, "y": False}
        assert "run_evaluation" in " ".join(captured["argv"])


# ---- CLI ----


class TestBenchCLI:
    def test_list_profiles(self, capsys):
        from daemon import cli

        rc = cli.cmd_bench(SimpleNamespace(list_profiles=True))
        out = capsys.readouterr().out
        assert rc == 0
        for name in ("gate", "diagnostic", "baseline", "full"):
            assert name in out

    def test_dry_run_prints_plan_without_executing(self, capsys):
        from daemon import cli

        rc = cli.cmd_bench(
            SimpleNamespace(list_profiles=False, profile="baseline", subset=None, dry_run=True)
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "Baseline comparison" in out
        assert "dry run" in out.lower()

    def test_invalid_profile_returns_1(self, capsys):
        from daemon import cli

        rc = cli.cmd_bench(
            SimpleNamespace(list_profiles=False, profile="turbo", subset=None, dry_run=True)
        )
        assert rc == 1


# ---- WS handler ----


class TestBenchWSHandler:
    @pytest.mark.asyncio
    async def test_bench_profiles_returns_dropdown_payload(self):
        import json

        from daemon.ws_server import _handle_message_inner

        resp = await _handle_message_inner(
            None, json.dumps({"type": "bench.profiles"}), None, None, None
        )
        assert resp["type"] == "bench_profiles"
        assert {p["value"] for p in resp["profiles"]} == {
            "gate",
            "diagnostic",
            "baseline",
            "full",
        }
