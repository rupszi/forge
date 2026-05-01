"""SWE-bench Verified harness for Forge — Phase 2 Week 7.

This package wraps Princeton's SWE-bench Verified benchmark runner with a
Forge-specific adapter that:

  1. Loads task instances from ``SWE-bench/SWE-bench`` (or a local subset).
  2. Clones each task's target repo at the task's base commit.
  3. Builds a Forge sprint contract from the task's ``problem_statement``
     + the failing test patches as ``done_criteria``.
  4. Runs Forge's planner/generator/evaluator pipeline against the cloned
     repo.
  5. Captures the resulting diff and submits it to SWE-bench's eval harness.
  6. Reports per-task pass/fail + summary score.

The Week-8 kill criterion (ADR-015) is enforced here: if a 50-task subset
scores < 30%, Forge's open-weight thesis fails for self-host.

NOTE: actually *running* the benchmark requires:
  - Docker (for SWE-bench's Conda-based test envs)
  - Ollama with the default model lineup pulled
  - ~30 GB free SSD per concurrent task
  - GPU (M-series 24GB+ recommended)

The adapter is therefore a **skeleton**: it implements the orchestration
shape, can be unit-tested with mocked dependencies, but leaves the actual
``swebench-runner`` invocation to be wired by the user when they have the
hardware ready.

Usage (when wired):

    from eval.swebench.adapter import run_subset

    score = run_subset(
        task_ids=DJANGO_50_SUBSET,
        forge_config=...,
    )
    # → SubsetResult(passed=15, total=50, pct=30.0, by_task={...})
"""
