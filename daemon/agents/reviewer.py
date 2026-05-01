"""Multi-perspective review panel. Spawns parallel agents for code review."""

import asyncio
import logging

from ..executors import claude_code as claude_executor, ollama as ollama_executor
from ..models import ReviewPerspective, ReviewResult

logger = logging.getLogger(__name__)

# Perspective definitions
PERSPECTIVES = {
    "security": {
        "system": "You are a security auditor. Look for: injection, XSS, auth bypasses, data exposure, secrets in code.",
        "model": "sonnet",
        "agent": "claude_code",
    },
    "performance": {
        "system": "You are a performance engineer. Look for: N+1 queries, missing indexes, excessive bundle size, O(n^2) algorithms, unnecessary re-renders.",
        "model": "ollama",
        "agent": "ollama",
    },
    "maintainability": {
        "system": "You are a senior developer reviewing for maintainability. Look for: poor naming, missing types, tight coupling, no tests, magic numbers.",
        "model": "ollama",
        "agent": "ollama",
    },
    "correctness": {
        "system": "You are a QA engineer. Look for: edge cases, off-by-one errors, null handling, race conditions, error handling gaps.",
        "model": "sonnet",
        "agent": "claude_code",
    },
    "architecture": {
        "system": "You are a software architect. Look for: separation of concerns, scalability, proper abstraction, API design, dependency management.",
        "model": "opus",
        "agent": "claude_code",
    },
}

DEFAULT_PERSPECTIVES = ["security", "correctness", "maintainability"]


def _build_review_prompt(perspective_config: dict, diff: str, context: str = "") -> str:
    parts = [perspective_config["system"]]
    if context:
        parts.append(f"\n## Context\n{context}")
    parts.append(f"\n## Code diff to review\n```\n{diff[:8000]}\n```")
    parts.append(
        "\nList issues found (if any). For each issue:\n"
        "- ISSUE: <description>\n- SUGGESTION: <how to fix>\n\n"
        "End with VERDICT: PASS (no critical issues) or FAIL (has critical issues)."
    )
    return "\n".join(parts)


def _parse_perspective_result(output: str, name: str) -> ReviewPerspective:
    issues = []
    suggestions = []
    verdict = "PASS"

    for line in output.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- ISSUE:") or stripped.startswith("ISSUE:"):
            issues.append(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("- SUGGESTION:") or stripped.startswith("SUGGESTION:"):
            suggestions.append(stripped.split(":", 1)[1].strip())
        if "VERDICT:" in stripped.upper():
            if "FAIL" in stripped.upper():
                verdict = "FAIL"
            else:
                verdict = "PASS"

    return ReviewPerspective(
        name=name,
        verdict=verdict,
        issues=issues,
        suggestions=suggestions,
    )


async def _run_perspective(name: str, diff: str, context: str = "") -> ReviewPerspective:
    config = PERSPECTIVES[name]
    prompt = _build_review_prompt(config, diff, context)

    if config["agent"] == "ollama":
        result = await ollama_executor.execute(prompt)
    else:
        result = await claude_executor.execute(prompt, model=config["model"])

    if not result.success:
        return ReviewPerspective(name=name, verdict="ERROR", issues=[result.error])

    perspective = _parse_perspective_result(result.output, name)
    perspective.model = config["model"]
    return perspective


async def review(diff: str, perspectives: list[str] = None, context: str = "") -> ReviewResult:
    """Run multi-perspective review. Returns synthesized result."""
    if perspectives is None:
        perspectives = DEFAULT_PERSPECTIVES

    # Validate perspectives
    perspectives = [p for p in perspectives if p in PERSPECTIVES]
    if not perspectives:
        perspectives = DEFAULT_PERSPECTIVES

    # Run all perspectives in parallel
    tasks = [_run_perspective(name, diff, context) for name in perspectives]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    perspective_results = []
    for r in results:
        if isinstance(r, Exception):
            logger.error("Review perspective failed: %s", r)
        elif isinstance(r, ReviewPerspective):
            perspective_results.append(r)

    # ---- Synthesize ----
    #
    # Two synthesis passes:
    # 1. Critical issues — anything flagged by 2+ reviewers (intersection
    #    consensus). Uses fuzzy matching on the issue text rather than exact
    #    string equality so different reviewers' phrasings of the same
    #    underlying issue are recognized.
    # 2. Action items — deduplicated suggestions across perspectives.
    #    Sorted by perspective importance (security first, then correctness,
    #    then performance / maintainability / architecture).

    issue_buckets: dict[str, int] = {}
    for p in perspective_results:
        for issue in p.issues:
            # Lowercase + strip punctuation for fuzzy matching
            key = " ".join(issue.lower().split())[:80]
            issue_buckets[key] = issue_buckets.get(key, 0) + 1

    # Issues mentioned by 2+ reviewers → critical. Find the original (best
    # phrased) version of each by going back to the raw issues list.
    critical_keys = {k for k, count in issue_buckets.items() if count >= 2}
    critical_issues: list[str] = []
    seen_critical: set[str] = set()
    for p in perspective_results:
        for issue in p.issues:
            key = " ".join(issue.lower().split())[:80]
            if key in critical_keys and key not in seen_critical:
                critical_issues.append(issue)
                seen_critical.add(key)

    # Deduplicate action items while preserving perspective ordering
    # (security-first prioritization comes from PERSPECTIVES dict order).
    perspective_order = list(PERSPECTIVES.keys())
    perspective_results.sort(
        key=lambda p: perspective_order.index(p.name) if p.name in perspective_order else 999
    )

    action_items: list[str] = []
    seen_actions: set[str] = set()
    for p in perspective_results:
        for suggestion in p.suggestions:
            key = " ".join(suggestion.lower().split())[:80]
            if key not in seen_actions:
                action_items.append(suggestion)
                seen_actions.add(key)

    # Overall verdict — FAIL if 2+ perspectives flagged FAIL OR there's any
    # critical (multi-reviewer-flagged) issue.
    fail_count = sum(1 for p in perspective_results if p.verdict == "FAIL")
    overall = "FAIL" if fail_count >= 2 or critical_issues else "PASS"

    return ReviewResult(
        overall_verdict=overall,
        perspectives=perspective_results,
        critical_issues=critical_issues,
        action_items=action_items,
    )
