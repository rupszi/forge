"""Tests for cross-family evaluator selection in classifier.py.

The cross-family-evaluator invariant (ADR-006) is one of Forge's load-bearing
correctness rules: the evaluator must run on a model from a different family
than the generator, to avoid the same-family self-evaluation bias documented
in MT-Bench (Claude-v1 +25% self-bias, GPT-4 +10%).

These tests verify:
  - The family registry correctly identifies model lineages
  - pick_evaluator_model() never picks an evaluator from the generator's family
    when an alternative is available
  - The selection is deterministic (same generator → same evaluator across
    runs, so procedural memory accumulates clean signal)
  - Edge cases: unknown model families fall through cleanly
"""

from __future__ import annotations

import pytest

from daemon.agents.classifier import pick_evaluator_model
from daemon.config import (
    LOCAL_BACKUP_MID_MODEL,
    LOCAL_CLASSIFY_MODEL,
    LOCAL_CODE_MODEL,
    LOCAL_MID_MODEL,
    LOCAL_PREMIUM_MODEL,
    model_family,
)

# ---- Family registry ----


@pytest.mark.parametrize(
    "model,expected_family",
    [
        # Anthropic
        ("claude-sonnet-4", "anthropic"),
        ("claude-opus-4-7", "anthropic"),
        ("opus", "anthropic"),
        ("sonnet", "anthropic"),
        ("haiku", "anthropic"),
        # OpenAI (closed and open-weight)
        ("gpt-oss:20b", "openai"),
        ("gpt-oss:120b", "openai"),
        ("gpt-4-turbo", "openai"),
        ("gpt-5", "openai"),
        ("o1-preview", "openai"),
        # Qwen line
        ("qwen3-coder-next", "qwen"),
        ("qwen3.6:27b", "qwen"),
        ("qwen2.5-coder-32b", "qwen"),
        ("Qwen3-235B-A22B-Instruct", "qwen"),  # case-insensitive
        # Mistral line
        ("mistral-large-2", "mistral"),
        ("devstral-small-2507", "mistral"),
        ("codestral-22b", "mistral"),
        # DeepSeek
        ("deepseek-v4-flash", "deepseek"),
        ("deepseek-r1-distill-qwen-32b", "deepseek"),
        # Llama
        ("llama-3.3-70b-instruct", "llama"),
        ("llama3:70b", "llama"),
        ("llama4-scout", "llama"),
        ("meta-llama/Llama-3.3-70B", "llama"),
        # Granite
        ("granite-code-34b", "granite"),
        ("granite4:8b", "granite"),
        # GLM / Zhipu
        ("glm-4.5", "zhipu"),
        ("glm5-flagship", "zhipu"),
        # MiniMax / Kimi
        ("minimax-m2.5", "minimax"),
        ("kimi-k2", "moonshot"),
        # Unknown
        ("some-random-model", "unknown"),
        ("foo-bar-7b", "unknown"),
    ],
)
def test_model_family_registry(model: str, expected_family: str):
    assert model_family(model) == expected_family


def test_family_match_is_case_insensitive():
    assert model_family("QWEN3-CODER-NEXT") == "qwen"
    assert model_family("ClAuDe-Sonnet-4") == "anthropic"


def test_family_match_handles_whitespace():
    assert model_family("  qwen3.6:27b  ") == "qwen"


# ---- pick_evaluator_model: cross-family invariant ----


def test_evaluator_is_different_family_than_qwen_generator():
    """When the generator is Qwen, the evaluator must NOT be Qwen."""
    evaluator = pick_evaluator_model("qwen3-coder-next")
    assert model_family(evaluator) != "qwen", (
        f"Evaluator {evaluator!r} is in same family as generator (qwen)"
    )


def test_evaluator_is_different_family_than_devstral_generator():
    """Devstral (mistral family) generator → non-mistral evaluator."""
    evaluator = pick_evaluator_model("devstral-small-2507")
    assert model_family(evaluator) != "mistral"


def test_evaluator_is_different_family_than_deepseek_generator():
    """DeepSeek generator → non-deepseek evaluator."""
    evaluator = pick_evaluator_model("deepseek-v4-flash")
    assert model_family(evaluator) != "deepseek"


def test_evaluator_is_different_family_than_claude_generator():
    """Claude generator → non-Anthropic evaluator (the Sonnet-eval-Opus
    case the harness research warns about)."""
    evaluator = pick_evaluator_model("claude-sonnet-4")
    assert model_family(evaluator) != "anthropic"


def test_evaluator_is_different_family_than_gpt_oss_generator():
    """gpt-oss generator → non-openai evaluator."""
    evaluator = pick_evaluator_model("gpt-oss:120b")
    assert model_family(evaluator) != "openai"


# ---- Determinism ----


@pytest.mark.parametrize(
    "generator",
    [
        "qwen3-coder-next",
        "qwen3.6:27b",
        "devstral-small-2507",
        "deepseek-v4-flash",
        "claude-sonnet-4",
        "gpt-oss:20b",
    ],
)
def test_selection_is_deterministic(generator: str):
    """Same generator always picks the same evaluator. Required so the
    procedural memory accumulates clean signal across runs."""
    first = pick_evaluator_model(generator)
    for _ in range(5):
        assert pick_evaluator_model(generator) == first


# ---- Behavior: candidate ordering ----


def test_qwen_generator_prefers_gpt_oss_evaluator():
    """The candidate list is ordered cheap-and-tested first. For a Qwen
    generator the first non-Qwen candidate is gpt-oss:20b (the classify
    model)."""
    evaluator = pick_evaluator_model("qwen3.6:27b")
    assert evaluator == LOCAL_CLASSIFY_MODEL  # gpt-oss:20b
    assert model_family(evaluator) == "openai"


def test_openai_generator_prefers_devstral_evaluator():
    """For a gpt-oss / openai generator, the first cross-family candidate
    is the backup mid-tier (devstral-small-2507)."""
    evaluator = pick_evaluator_model("gpt-oss:20b")
    assert evaluator == LOCAL_BACKUP_MID_MODEL


# ---- Edge cases ----


def test_unknown_family_generator_still_returns_something():
    """An unrecognized generator family should not crash; pick_evaluator_model
    should return one of the known candidates (the first one whose family
    doesn't match 'unknown', which is all of them)."""
    evaluator = pick_evaluator_model("some-mystery-model-7b")
    # Any candidate is fine since 'unknown' doesn't match any known family
    assert evaluator in (
        LOCAL_CLASSIFY_MODEL,
        LOCAL_BACKUP_MID_MODEL,
        LOCAL_MID_MODEL,
        LOCAL_PREMIUM_MODEL,
        LOCAL_CODE_MODEL,
        "claude-sonnet-4",
    )


def test_no_candidate_exhaustion_in_practice():
    """For every default generator in Forge's lineup, pick_evaluator_model
    returns a valid candidate without hitting the pathological fallback."""
    for generator in (
        LOCAL_CODE_MODEL,
        LOCAL_MID_MODEL,
        LOCAL_PREMIUM_MODEL,
        LOCAL_BACKUP_MID_MODEL,
        LOCAL_CLASSIFY_MODEL,
    ):
        evaluator = pick_evaluator_model(generator)
        # Cross-family invariant must hold
        assert model_family(evaluator) != model_family(generator), (
            f"{generator} ({model_family(generator)}) → "
            f"{evaluator} ({model_family(evaluator)}) violates cross-family rule"
        )
