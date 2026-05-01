"""Tests for evaluator: parse PASS/FAIL, overall verdict, revision feedback."""

from daemon.agents.evaluator import _build_eval_prompt, parse_evaluator_result
from daemon.models import ProjectContext, SprintContract

# --- Parsing ---


def test_parse_all_pass():
    sprint = SprintContract(done_criteria=["Tables created", "Indexes added", "Tests passing"])
    output = """
- PASS: Tables created — verified in migration file
- PASS: Indexes added — idx_users_email found
- PASS: Tests passing — all 5 tests green

Overall verdict: APPROVED
"""
    result = parse_evaluator_result(output, sprint)
    assert result.verdict == "APPROVED"
    assert all(cr.passed for cr in result.criteria_results)


def test_parse_one_fail():
    sprint = SprintContract(done_criteria=["Tables created", "RLS policies applied"])
    output = """
- PASS: Tables created — users and posts tables found
- FAIL: RLS policies applied — no RLS policy on posts table — add policy for authenticated users

Overall verdict: REVISE
The generator must:
- Add RLS policy on posts table for authenticated users
"""
    result = parse_evaluator_result(output, sprint)
    assert result.verdict == "REVISE"
    assert result.criteria_results[0].passed is True
    assert result.criteria_results[1].passed is False
    assert "REVISE" in result.feedback or "RLS" in result.feedback


def test_parse_explicit_approved_with_criterion_match():
    """Per ADR-006 the evaluator must be skeptical: an explicit APPROVED only
    counts when the criterion-level signal supports it. Here the line
    references the criterion AND has a PASS marker."""
    sprint = SprintContract(done_criteria=["Task done"])
    output = "- PASS: Task done — verified end-to-end\n\nAPPROVED"
    result = parse_evaluator_result(output, sprint)
    assert result.verdict == "APPROVED"
    assert result.criteria_results[0].passed is True


def test_parse_explicit_revise_overrides():
    sprint = SprintContract(done_criteria=["Task done"])
    output = "Some issues found.\n\nREVISE\n- Fix the import"
    result = parse_evaluator_result(output, sprint)
    assert result.verdict == "REVISE"


def test_parse_no_matching_lines_defaults_to_fail():
    """Critical ADR-006 behavior: if the evaluator never produces a verdict for
    a criterion, default to FAIL. The 'APPROVED' string alone is NOT enough to
    flip an unverified criterion to passed — that would reintroduce the same
    leniency bias the cross-family evaluator design is meant to prevent."""
    sprint = SprintContract(done_criteria=["Something very specific"])
    output = "I reviewed the code but didn't check the criteria explicitly.\nAPPROVED"
    result = parse_evaluator_result(output, sprint)
    # Explicit APPROVED is overridden because the criterion was never verified.
    # Conservative bias per harness-design.
    assert result.verdict == "REVISE"
    assert result.criteria_results[0].passed is False
    assert "did not produce a verdict" in result.criteria_results[0].fix_needed


def test_feedback_extraction():
    sprint = SprintContract(done_criteria=["Auth works", "Tests pass"])
    output = """
- PASS: Auth works — login flow verified
- FAIL: Tests pass — 2 tests failing — fix the mock setup

REVISE
Changes the generator must make:
- Fix mock setup in test_auth.py
- Add missing import for bcrypt
"""
    result = parse_evaluator_result(output, sprint)
    assert result.verdict == "REVISE"
    assert "mock setup" in result.feedback or "generator must make" in result.feedback


# --- Prompt building ---


def test_eval_prompt_includes_criteria():
    sprint = SprintContract(
        description="Build auth schema",
        done_criteria=["Tables created", "RLS applied"],
    )
    ctx = ProjectContext(framework="next", available_tools={"playwright": True})
    prompt = _build_eval_prompt(sprint, "diff content here", ctx)
    assert "Tables created" in prompt
    assert "RLS applied" in prompt
    assert "diff content here" in prompt
    assert "Playwright" in prompt


def test_eval_prompt_no_playwright():
    sprint = SprintContract(description="Task", done_criteria=["Done"])
    ctx = ProjectContext(framework="express", available_tools={"playwright": False})
    prompt = _build_eval_prompt(sprint, "diff", ctx)
    assert "Playwright" not in prompt


def test_eval_prompt_diff_truncated():
    sprint = SprintContract(description="Task", done_criteria=["Done"])
    ctx = ProjectContext()
    long_diff = "x" * 50000
    prompt = _build_eval_prompt(sprint, long_diff, ctx)
    assert len(prompt) < 60000  # Diff capped at MAX_DIFF_LENGTH


# --- Open-weight friendly parser variants (Phase 1 Week 1) ---


def test_parse_unicode_check_marker():
    """Qwen / Devstral often emit ✓ / ✗ instead of PASS / FAIL."""
    sprint = SprintContract(done_criteria=["Auth endpoint added", "Tests pass"])
    output = """
✓ Auth endpoint added — POST /api/login returns 200
✗ Tests pass — test_login fails with 401 — fix the password hash mock

REVISE
"""
    result = parse_evaluator_result(output, sprint)
    assert result.verdict == "REVISE"
    assert result.criteria_results[0].passed is True
    assert result.criteria_results[1].passed is False


def test_parse_bracket_yes_no_marker():
    """DeepSeek-style [YES] / [NO] markers."""
    sprint = SprintContract(done_criteria=["Migration created"])
    output = "[YES] Migration created — file exists in supabase/migrations/\nAPPROVED"
    result = parse_evaluator_result(output, sprint)
    assert result.verdict == "APPROVED"
    assert result.criteria_results[0].passed is True


def test_parse_bracket_pass_fail_marker():
    sprint = SprintContract(done_criteria=["Schema valid"])
    output = "[PASS] Schema valid — verified by SQL parser\nAPPROVED"
    result = parse_evaluator_result(output, sprint)
    assert result.verdict == "APPROVED"
    assert result.criteria_results[0].passed is True


def test_parse_markdown_bold_marker():
    """gpt-oss often uses **PASS** / **FAIL** in markdown."""
    sprint = SprintContract(done_criteria=["API works"])
    output = "**PASS**: API works — endpoint returns expected JSON\nAPPROVED"
    result = parse_evaluator_result(output, sprint)
    assert result.verdict == "APPROVED"
    assert result.criteria_results[0].passed is True


def test_parse_paragraph_style_pass():
    """Fallback: paragraph hints when no structured marker exists."""
    sprint = SprintContract(done_criteria=["Login flow"])
    output = "I checked the login flow and confirmed the implementation is correct and tests pass."
    result = parse_evaluator_result(output, sprint)
    # Paragraph hint "correct" + "implementation" should mark as passed
    assert result.criteria_results[0].passed is True


def test_parse_paragraph_style_fail():
    """Fallback: paragraph hints saying something is missing."""
    sprint = SprintContract(done_criteria=["Tests pass"])
    output = "After running the tests, several are missing assertions and one is broken."
    result = parse_evaluator_result(output, sprint)
    assert result.criteria_results[0].passed is False


def test_parse_emoji_markers():
    sprint = SprintContract(done_criteria=["Endpoint added"])
    output = "✅ Endpoint added — verified\nAPPROVED"
    result = parse_evaluator_result(output, sprint)
    assert result.criteria_results[0].passed is True


def test_parse_no_dash_separator():
    """Some models drop the em-dash; we fall back to colons."""
    sprint = SprintContract(done_criteria=["Build succeeds"])
    output = "PASS: Build succeeds: verified locally\nAPPROVED"
    result = parse_evaluator_result(output, sprint)
    assert result.criteria_results[0].passed is True


# --- Cross-family enforcement wiring ---


def test_evaluate_uses_cross_family_when_eval_model_omitted(monkeypatch):
    """``evaluate()`` defaults to picking a cross-family evaluator via the
    classifier when ``eval_model`` is not provided."""
    import asyncio

    from daemon.agents import evaluator as evaluator_module

    captured = {}

    async def fake_execute(prompt, model, **kwargs):
        captured["model"] = model
        from daemon.models import ExecutionResult

        return ExecutionResult(success=True, output="- PASS: Done — ok\nAPPROVED")

    monkeypatch.setattr(evaluator_module.claude_executor, "execute", fake_execute)

    sprint = SprintContract(
        description="Build login",
        done_criteria=["Done"],
        assigned_model="qwen3-coder-next",  # qwen family
    )
    ctx = ProjectContext()
    asyncio.run(evaluator_module.evaluate(sprint, "diff", ctx))

    # Must have picked a non-qwen evaluator (cross-family rule)
    from daemon.config import model_family

    assert model_family(captured["model"]) != "qwen", (
        f"Picked {captured['model']!r} — same family as generator (qwen)"
    )


def test_evaluate_respects_explicit_eval_model_override(monkeypatch):
    """Callers may override the cross-family pick by passing ``eval_model=``."""
    import asyncio

    from daemon.agents import evaluator as evaluator_module

    captured = {}

    async def fake_execute(prompt, model, **kwargs):
        captured["model"] = model
        from daemon.models import ExecutionResult

        return ExecutionResult(success=True, output="- PASS: Done — ok\nAPPROVED")

    monkeypatch.setattr(evaluator_module.claude_executor, "execute", fake_execute)

    sprint = SprintContract(
        description="t", done_criteria=["Done"], assigned_model="qwen3-coder-next"
    )
    ctx = ProjectContext()
    asyncio.run(evaluator_module.evaluate(sprint, "diff", ctx, eval_model="haiku"))

    assert captured["model"] == "haiku"
