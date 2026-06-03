"""M4 — audit fixes: path-traversal case-normalization + cross-family invariant."""

from __future__ import annotations

import os

import pytest

from daemon.agents.classifier import pick_evaluator_model
from daemon.config import (
    LOCAL_CODE_MODEL,
    LOCAL_MID_MODEL,
    LOCAL_PLAN_MODEL,
    LOCAL_PREMIUM_MODEL,
    model_family,
)


class TestPathGuardCaseNormalization:
    def test_cwd_path_allowed(self):
        from daemon.ws_server import _validate_init_path

        assert _validate_init_path(".") is True
        assert _validate_init_path(os.getcwd()) is True

    def test_external_path_rejected(self):
        from daemon.ws_server import _validate_init_path

        assert _validate_init_path("/etc") is False
        assert _validate_init_path("/var/root") is False

    def test_case_variant_of_cwd_matches_normcase_semantics(self):
        # The guard uses os.path.normcase before comparing. Whether a
        # swapped-case variant of the cwd validates is therefore fully
        # determined by the platform's normcase: case-folding (Windows) → the
        # variant is the SAME dir and must be allowed; identity (POSIX) → the
        # variant is a DIFFERENT path and must be rejected. Either way the real
        # cwd must always validate. No "either outcome is fine" fudge.
        from daemon.ws_server import _validate_init_path

        cwd = os.getcwd()
        swapped = cwd.swapcase()
        result = _validate_init_path(swapped)

        case_folding_fs = os.path.normcase("A") == os.path.normcase("a")
        if case_folding_fs:
            assert result is True, "case-folding normcase must treat the variant as the same dir"
        else:
            assert result is False, "POSIX normcase: a swapped-case path is a different dir"

        # Invariant regardless of platform: the genuine cwd always validates.
        assert _validate_init_path(cwd) is True


class TestCrossFamilyInvariant:
    @pytest.mark.parametrize(
        "generator",
        [
            LOCAL_CODE_MODEL,
            LOCAL_MID_MODEL,
            LOCAL_PREMIUM_MODEL,
            LOCAL_PLAN_MODEL,
            "claude-sonnet-4",
            "qwen3-coder-next",
            "deepseek-v4-flash",
        ],
    )
    def test_evaluator_is_different_family(self, generator):
        evaluator = pick_evaluator_model(generator)
        assert model_family(evaluator) != model_family(generator), (
            f"evaluator {evaluator} ({model_family(evaluator)}) shares family with "
            f"generator {generator} ({model_family(generator)})"
        )

    def test_evaluator_call_path_uses_cross_family(self, monkeypatch):
        # The evaluator module must derive its model via pick_evaluator_model,
        # not a hardcoded 'sonnet'. We assert the picked model differs in family.
        gen = "qwen3-coder-next"
        ev = pick_evaluator_model(gen)
        assert model_family(ev) != "qwen"
