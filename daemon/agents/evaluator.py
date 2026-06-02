"""Evaluator: external verification of generator's work against sprint contract.

The evaluator is the most important agent in Forge. Its job is to be skeptical:
read the diff the generator produced, grade each ``done_criterion`` of the
sprint contract independently with PASS/FAIL + evidence, and return either
APPROVED or REVISE with specific feedback the generator can act on.

Three architectural rules from ADR-006 govern this code:

  1. **Generator never self-evaluates.** This module is a separate process /
     LLM call from the generator. Always.
  2. **The evaluator runs on a different model family than the generator.**
     Same-family judges share blind spots — Sonnet evaluating Opus is barely
     better than Opus evaluating itself. The selection is delegated to
     ``classifier.pick_evaluator_model()`` which uses the family registry in
     ``config.py``. **This module no longer hardcodes ``"sonnet"``** — see
     the ``evaluate()`` function below.
  3. **Each criterion is graded independently** with PASS/FAIL + evidence.
     No holistic averaging. Hard threshold per criterion.

The parser (``parse_evaluator_result``) recognizes multiple PASS/FAIL formats
because open-weight models often diverge from the prompt template. Patterns
covered:

  - ``- PASS: <criterion> — <evidence>``  (the canonical Claude shape)
  - ``PASS: ...``                          (no leading dash)
  - ``✓ <criterion>`` / ``✗ <criterion>``  (Unicode bullets, common in Qwen)
  - ``[PASS]`` / ``[FAIL]`` / ``[YES]`` / ``[NO]``  (bracket-style, common in
    DeepSeek + reasoning models)
  - ``**PASS**`` / ``**FAIL**``            (Markdown bold, common in gpt-oss)
  - paragraph-style "this criterion is satisfied" / "this criterion is not met"
    as a fuzzy fallback when no structured marker is found

This breadth is critical for the open-weight default lineup (ADR-003) — without
it, the evaluator silently misclassifies criteria when the generator is on
Qwen3-Coder-Next or DeepSeek V4-Flash.
"""

from __future__ import annotations

import logging
import re

from ..config import MAX_DIFF_LENGTH
from ..models import CriterionResult, EvaluatorResult, ProjectContext, SprintContract
from .classifier import pick_evaluator_model


async def _dispatch_eval(prompt: str, eval_model: str):
    """Run the evaluation prompt on the chosen model via the correct executor.

    Mirrors the generator's routing + local-first cloud gate (audit fix): the
    evaluator must run *locally by default* on the cross-family model (e.g.
    llama3.1:8b via Ollama), not unconditionally on the cloud ``claude -p``.
    A cloud evaluator model with cloud disabled raises ``CloudDisabledError``
    rather than dialing out (G-LOC-1/2).
    """
    from .. import routing
    from ..config import cloud_enabled
    from ..executors import (
        claude_code as cc,
        mlx as mx,
        ollama as oll,
        openai_compatible as oc,
    )

    executor_str = routing.select_executor(eval_model)
    if routing.is_cloud_executor(executor_str) and not cloud_enabled():
        msg = (
            f"evaluator model {eval_model!r} routes to the cloud executor "
            f"{executor_str!r}, but FORGE_CLOUD_ENABLED is off. Pick a local "
            "evaluator model (the default is local) or enable cloud."
        )
        raise routing.CloudDisabledError(msg)
    if executor_str == "claude_code":
        return await cc.execute(prompt, None, eval_model)
    module = {"ollama": oll, "openai_compatible": oc, "mlx": mx}[executor_str]
    return await module.execute(prompt, model=eval_model)


logger = logging.getLogger(__name__)

EVALUATOR_SYSTEM = """You are a strict code reviewer and QA engineer.
Your job is to verify that EVERY done criterion is met.
Do NOT give the benefit of the doubt. If something looks incomplete or wrong, FAIL it.
Test criteria that are testable. Read the diff carefully for regressions."""

# ---- PASS/FAIL regex patterns (open-weight friendly) ----
#
# Order matters: the most specific patterns come first. A line that matches
# any of these counts as a structured PASS or FAIL marker. Lines that don't
# match fall through to the paragraph-style fuzzy match in
# ``_paragraph_indicates_pass`` / ``_paragraph_indicates_fail``.

_PASS_PATTERNS = [
    re.compile(r"^\s*[-•*]?\s*\*?\*?PASS\*?\*?[:\s]", re.IGNORECASE),  # PASS:, **PASS**:, - PASS:
    re.compile(r"^\s*\[\s*PASS\s*\]", re.IGNORECASE),  # [PASS]
    re.compile(r"^\s*\[\s*YES\s*\]", re.IGNORECASE),  # [YES]
    re.compile(r"^\s*[-•*]?\s*✓"),  # ✓ or - ✓
    re.compile(r"^\s*[-•*]?\s*✅"),  # emoji checkmark
]

_FAIL_PATTERNS = [
    re.compile(r"^\s*[-•*]?\s*\*?\*?FAIL\*?\*?[:\s]", re.IGNORECASE),  # FAIL:, **FAIL**:, - FAIL:
    re.compile(r"^\s*\[\s*FAIL\s*\]", re.IGNORECASE),
    re.compile(r"^\s*\[\s*NO\s*\]", re.IGNORECASE),
    re.compile(r"^\s*[-•*]?\s*✗"),
    re.compile(r"^\s*[-•*]?\s*❌"),
]

# Paragraph-style fallback patterns. Used only when no structured marker
# matches *and* the line clearly references the criterion. These are last
# resort; the prompt explicitly asks for the structured format above.
_PARAGRAPH_PASS_HINTS = re.compile(
    r"\b(satisfied|verified|correct|met|passes|complete|implemented correctly)\b",
    re.IGNORECASE,
)
_PARAGRAPH_FAIL_HINTS = re.compile(
    r"\b(not (?:met|satisfied|verified|implemented)|missing|incomplete|broken|incorrect|fails)\b",
    re.IGNORECASE,
)


def _is_pass(line: str) -> bool:
    """Return True if ``line`` is a structured PASS marker."""
    return any(p.search(line) for p in _PASS_PATTERNS)


def _is_fail(line: str) -> bool:
    """Return True if ``line`` is a structured FAIL marker."""
    return any(p.search(line) for p in _FAIL_PATTERNS)


def _build_eval_prompt(sprint: SprintContract, diff: str, ctx: ProjectContext) -> str:
    parts = [
        f"## Sprint contract\n{sprint.description}",
        "## Done criteria to verify",
    ]
    for i, c in enumerate(sprint.done_criteria, 1):
        parts.append(f"{i}. {c}")

    parts.append(f"\n## Git diff from generator\n```\n{diff[:MAX_DIFF_LENGTH]}\n```")

    if ctx.framework in ("next", "react", "vue") and ctx.available_tools.get("playwright"):
        parts.append(
            "\nYou have Playwright MCP available. Start the dev server and "
            "click through the UI to verify visual/functional criteria."
        )

    parts.append(
        "\nFor each criterion, respond:\n"
        "- PASS: <criterion> — <evidence>\n"
        "- FAIL: <criterion> — <what is wrong> — <specific fix needed>\n"
        "\n"
        "Then give overall verdict: APPROVED (all pass) or REVISE (any fail).\n"
        "If REVISE, list the specific changes the generator must make."
    )

    return "\n\n".join(parts)


def _criterion_matches_line(criterion: str, line_lower: str) -> bool:
    """Heuristic: does ``line_lower`` reference ``criterion``?

    We use first-three-words intersection because the evaluator typically
    paraphrases or truncates the criterion text in its response. Three words
    is a sweet spot — enough to disambiguate between criteria, loose enough
    to tolerate paraphrasing.
    """
    criterion_words = {w for w in criterion.lower().split()[:3] if len(w) > 2}
    if not criterion_words:
        # Criterion is too short to fingerprint; fall back to substring check
        return criterion.lower() in line_lower
    line_words = set(line_lower.split())
    return bool(criterion_words & line_words)


def parse_evaluator_result(output: str, sprint: SprintContract) -> EvaluatorResult:
    """Parse evaluator output into structured result.

    Algorithm (per criterion):
      1. Walk the lines of ``output`` looking for structured PASS/FAIL markers
         (``_PASS_PATTERNS`` / ``_FAIL_PATTERNS``).
      2. A marker only counts if the line also references the criterion (via
         ``_criterion_matches_line``). Multiple criteria in one paragraph
         won't all match the same marker.
      3. If no structured marker is found, fall back to paragraph-style hints
         (``_PARAGRAPH_PASS_HINTS`` / ``_PARAGRAPH_FAIL_HINTS``) on lines that
         do reference the criterion.
      4. If neither structured nor paragraph-style hints match, the criterion
         defaults to FAIL — being conservative here matches the harness-design
         "Don't give the benefit of the doubt" instruction. Better to ask for
         a revision than approve unverifiable work.
    """
    criteria_results: list[CriterionResult] = []

    lines = output.split("\n")

    for criterion in sprint.done_criteria:
        passed: bool | None = None
        evidence = ""
        fix_needed = ""

        for line in lines:
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            if not _criterion_matches_line(criterion, line_lower):
                continue

            if _is_pass(line_stripped):
                passed = True
                # Evidence is whatever comes after an em-dash, en-dash, hyphen,
                # or colon. Try each separator in turn.
                for sep in ("—", "–", " - ", ": "):
                    if sep in line_stripped:
                        evidence = line_stripped.split(sep, 1)[1].strip()
                        break
                break

            if _is_fail(line_stripped):
                passed = False
                # Fix-needed is typically the last em-dash-separated chunk:
                # "FAIL: X — what's wrong — fix needed"
                # We try em-dash first, then en-dash, then hyphen.
                for sep in ("—", "–", " - "):
                    parts = line_stripped.split(sep)
                    if len(parts) >= 3:
                        fix_needed = parts[2].strip()
                        break
                    if len(parts) == 2:
                        fix_needed = parts[1].strip()
                        break
                break

            # Paragraph-style fallback. Cheaper signals; only consult when
            # the line wasn't a structured marker.
            if _PARAGRAPH_PASS_HINTS.search(line_lower) and not _PARAGRAPH_FAIL_HINTS.search(
                line_lower
            ):
                passed = True
                evidence = line_stripped
                break
            if _PARAGRAPH_FAIL_HINTS.search(line_lower):
                passed = False
                fix_needed = line_stripped
                break

        # If we never matched anything for this criterion, default to FAIL.
        # Conservative bias per harness-design.
        if passed is None:
            passed = False
            fix_needed = "(evaluator did not produce a verdict for this criterion)"

        criteria_results.append(
            CriterionResult(
                criterion=criterion,
                passed=passed,
                evidence=evidence,
                fix_needed=fix_needed,
            )
        )

    # Overall verdict: APPROVED only if every criterion passed AND the output
    # explicitly says APPROVED. Belt-and-suspenders against partial reads.
    all_passed = all(cr.passed for cr in criteria_results)
    output_upper = output.upper()
    explicit_approved = "APPROVED" in output_upper and "REVISE" not in output_upper
    explicit_revise = "REVISE" in output_upper

    if explicit_revise:
        verdict = "REVISE"
    elif all_passed and explicit_approved:
        verdict = "APPROVED"
    elif all_passed:
        # All criteria passed but no explicit verdict — be safe, mark APPROVED.
        # The criterion-level signal is more reliable than missing keywords.
        verdict = "APPROVED"
    else:
        verdict = "REVISE"

    # Extract feedback. Prefer the explicit "Required changes:" / "REVISE"
    # block if present; otherwise compose from FAIL reasons.
    feedback = ""
    for marker in ("Required changes:", "REVISE", "Changes needed:", "What to fix:"):
        idx = output.find(marker)
        if idx >= 0:
            feedback = output[idx:].strip()
            break

    if not feedback and verdict == "REVISE":
        fails = [cr.fix_needed for cr in criteria_results if not cr.passed and cr.fix_needed]
        feedback = "Required changes:\n" + "\n".join(f"- {f}" for f in fails)

    return EvaluatorResult(
        verdict=verdict,
        criteria_results=criteria_results,
        feedback=feedback,
    )


async def evaluate(
    sprint: SprintContract,
    diff: str,
    ctx: ProjectContext,
    *,
    eval_model: str | None = None,
) -> EvaluatorResult:
    """Evaluate generator's work against sprint contract. Be skeptical.

    The evaluator model is chosen via ``pick_evaluator_model`` to enforce the
    cross-family invariant from ADR-006. Callers may override by passing
    ``eval_model=`` explicitly — useful for tests and for users who want to
    pin a specific evaluator. The default behavior (delegate to the
    classifier) is what production should use.
    """
    prompt = _build_eval_prompt(sprint, diff, ctx)

    # Cross-family enforcement (ADR-006). The generator's model is on the
    # sprint contract; we route the evaluator to a different family.
    if eval_model is None:
        eval_model = pick_evaluator_model(sprint.assigned_model)
        logger.debug(
            "evaluator: generator=%s, picked cross-family eval_model=%s",
            sprint.assigned_model,
            eval_model,
        )

    # Defense-in-depth (Task 1.9 / ADR-006): the cross-family invariant must
    # hold even if a future refactor accidentally hardcodes ``eval_model``,
    # or a caller passes an explicit override that violates it. We skip the
    # check when the generator family is "unknown" — that's the test-fixture
    # case (mocked model registries) where strict enforcement would just
    # block coverage-only tests.
    from ..config import model_family

    gen_fam = model_family(sprint.assigned_model)
    eval_fam = model_family(eval_model)
    if gen_fam != "unknown":
        assert eval_fam != gen_fam, (
            f"Cross-family evaluator invariant violated: "
            f"generator={sprint.assigned_model} ({gen_fam}), "
            f"evaluator={eval_model} ({eval_fam}). See ADR-006."
        )

    result = await _dispatch_eval(prompt, eval_model)

    if not result.success:
        logger.error("Evaluator execution failed: %s", result.error)
        return EvaluatorResult(
            verdict="REVISE",
            feedback=f"Evaluator failed to run: {result.error}",
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )

    eval_result = parse_evaluator_result(result.output, sprint)
    eval_result.tokens_in = result.tokens_in
    eval_result.tokens_out = result.tokens_out
    eval_result.cost_usd = result.cost_usd
    return eval_result
