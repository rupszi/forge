"""SWE-bench Verified adapter — Phase 2 Week 7 skeleton.

Bridges Forge's planner/generator/evaluator pipeline with SWE-bench's task
format. The full integration is deliberately split into three stages so each
can be developed and tested independently:

  Stage 1: TaskLoader      — load task records from SWE-bench dataset
  Stage 2: ForgeAdapter    — drive Forge against a single task; produce a diff
  Stage 3: ResultEvaluator — submit the diff to SWE-bench's harness; capture
                             pass/fail

This file ships Stage 1 (TaskLoader) and the ``ForgeAdapter`` interface plus
the ``SubsetResult`` aggregation. Stage 3 (the real Docker invocation of
SWE-bench's runner) is left as a TODO with a clear extension point — running
it requires the user's machine and is out of scope for unit-testable code.

Why a custom adapter instead of using SWE-bench's built-in CLI:

  - We need to inject Forge's harness *between* the task's problem statement
    and the diff — SWE-bench's vanilla runner expects a single LLM call.
  - We want to capture per-task token counts, timing, evaluator verdicts —
    not just pass/fail.
  - We want to record every run to ``.forge/sessions/swebench-<task_id>/``
    so post-mortem replay works the same way as a normal Forge session.

References:
  - SWE-bench paper: https://arxiv.org/abs/2310.06770
  - SWE-bench Verified: https://www.swebench.com/
  - SWE-bench-runner: https://github.com/SWE-bench/SWE-bench
  - ADR-015 (kill criterion: ≥30% on 50-task subset)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---- Stage 1: Task loading ----


@dataclass
class SWEBenchTask:
    """One task instance from SWE-bench Verified.

    Field naming follows the SWE-bench JSON schema verbatim so we can load
    HF datasets dumps directly. See
    https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified
    """

    instance_id: str  # e.g. "django__django-12345"
    repo: str  # e.g. "django/django"
    base_commit: str  # SHA to clone at
    problem_statement: str
    hints_text: str = ""
    test_patch: str = ""  # the patch SWE-bench will apply post-fix to verify
    fail_to_pass: list[str] = field(default_factory=list)  # tests that should pass after the fix
    pass_to_pass: list[str] = field(default_factory=list)  # tests that should still pass
    version: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SWEBenchTask:
        # SWE-bench fields can be JSON-stringified lists; coerce.
        def _aslist(x):
            if isinstance(x, list):
                return x
            if isinstance(x, str):
                try:
                    parsed = json.loads(x)
                    if isinstance(parsed, list):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    return [x] if x else []
            return []

        return cls(
            instance_id=d.get("instance_id", ""),
            repo=d.get("repo", ""),
            base_commit=d.get("base_commit", ""),
            problem_statement=d.get("problem_statement", ""),
            hints_text=d.get("hints_text", ""),
            test_patch=d.get("test_patch", ""),
            fail_to_pass=_aslist(d.get("FAIL_TO_PASS") or d.get("fail_to_pass")),
            pass_to_pass=_aslist(d.get("PASS_TO_PASS") or d.get("pass_to_pass")),
            version=d.get("version", ""),
        )


def load_tasks_from_jsonl(path: str | Path) -> list[SWEBenchTask]:
    """Load tasks from a local JSONL file. Each line = one task dict.

    The simplest way to obtain a 50-task subset:

        # download the django subset
        wget https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/main/test.jsonl
        # filter to django + take 50
        jq -c 'select(.repo == "django/django")' test.jsonl | head -50 > eval/swebench/django_50.jsonl
    """
    p = Path(path)
    if not p.exists():
        return []
    tasks: list[SWEBenchTask] = []
    with p.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                tasks.append(SWEBenchTask.from_dict(json.loads(raw)))
            except json.JSONDecodeError as e:
                logger.warning("swebench: skipping malformed line: %s", e)
    return tasks


# ---- Stage 2: Forge adapter ----


@dataclass
class TaskRunResult:
    """Outcome of one Forge run against a SWE-bench task."""

    instance_id: str
    success: bool
    diff: str = ""  # the patch Forge produced
    error: str = ""
    revisions: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    evaluator_verdict: str = ""  # APPROVED | REVISE | FAIL


def task_to_sprint_contract(task: SWEBenchTask) -> dict[str, Any]:
    """Convert a SWE-bench task into a Forge sprint contract.

    The mapping:
      - ``problem_statement`` becomes the sprint description.
      - ``fail_to_pass`` test names become done_criteria — each must pass.
      - ``pass_to_pass`` becomes context (don't break these).
      - ``hints_text`` is appended to the description.

    Returns a dict (not a SprintContract dataclass) to keep this layer
    independent of Forge's models — useful for testing against mock
    schedulers.
    """
    description = task.problem_statement.strip()
    if task.hints_text:
        description += f"\n\nHints:\n{task.hints_text.strip()}"

    done_criteria: list[str] = []
    for test in task.fail_to_pass:
        done_criteria.append(f"Test passes: {test}")
    if not done_criteria:
        # Fallback when fail_to_pass is empty — just require the diff to
        # apply cleanly; SWE-bench's harness will pick the rest.
        done_criteria.append("All previously-failing tests pass after the fix")

    return {
        "id": f"swebench-{task.instance_id}",
        "session_id": f"swebench-{task.instance_id}",
        "description": description,
        "done_criteria": done_criteria,
        "files_scope": [],  # SWE-bench tasks span arbitrary files; let Forge discover
        "depends_on": [],
        "metadata": {
            "swebench_task_id": task.instance_id,
            "repo": task.repo,
            "base_commit": task.base_commit,
            "pass_to_pass_count": len(task.pass_to_pass),
            "version": task.version,
        },
    }


@dataclass
class SubsetResult:
    """Aggregated result across a SWE-bench subset."""

    total: int
    passed: int
    failed: int
    errored: int
    by_task: dict[str, TaskRunResult] = field(default_factory=dict)

    @property
    def pct(self) -> float:
        if self.total == 0:
            return 0.0
        return 100.0 * self.passed / self.total

    @property
    def kill_criterion_passed(self) -> bool:
        """Per ADR-015: ≥30% on a 50-task subset is the bar."""
        return self.pct >= 30.0

    def summary(self) -> str:
        return (
            f"SWE-bench subset: {self.passed}/{self.total} passed ({self.pct:.1f}%)\n"
            f"  failed: {self.failed}, errored: {self.errored}\n"
            f"  kill_criterion (≥30%): {'PASS' if self.kill_criterion_passed else 'FAIL'}"
        )


# ---- Stage 3: Forge runner (the real-execution path) ----
#
# This is the function the user calls when they have the hardware ready.
# It's parameterized over a ``forge_runner`` callable so tests can substitute
# a mock — the real implementation lives elsewhere (Phase 2 Week 7 follow-up
# task) because spawning Docker, cloning the target repo, and invoking the
# Forge daemon are operationally heavy.


def run_subset(
    tasks: list[SWEBenchTask],
    *,
    forge_runner: Callable[[SWEBenchTask], TaskRunResult],
    progress_cb: Callable[[int, int, TaskRunResult], None] | None = None,
) -> SubsetResult:
    """Run Forge against each task; aggregate results.

    Parameters
    ----------
    tasks
        Tasks to run.
    forge_runner
        Async-or-sync callable that takes a task and returns a
        ``TaskRunResult``. Pass the real Forge invocation in production;
        pass a mock in tests.
    progress_cb
        Optional callback called after each task completes — useful for
        live progress bars. Receives (index, total, result).

    Returns
    -------
    SubsetResult
        Aggregated counts + per-task detail.
    """
    by_task: dict[str, TaskRunResult] = {}
    passed = failed = errored = 0
    total = len(tasks)

    for i, task in enumerate(tasks, start=1):
        try:
            result = forge_runner(task)
        except Exception as e:
            logger.exception("swebench: runner crashed on %s", task.instance_id)
            result = TaskRunResult(
                instance_id=task.instance_id,
                success=False,
                error=f"runner exception: {e}",
            )
            errored += 1
        else:
            if result.success:
                passed += 1
            else:
                failed += 1

        by_task[task.instance_id] = result
        if progress_cb is not None:
            progress_cb(i, total, result)

    return SubsetResult(
        total=total,
        passed=passed,
        failed=failed,
        errored=errored,
        by_task=by_task,
    )


# ---- Stage 3 stub: real Forge invocation ----


def real_forge_runner(task: SWEBenchTask) -> TaskRunResult:
    """Run Forge against ``task``. **Stub** — real implementation requires
    Docker, Ollama, and a cloned target repo.

    The shape this needs to take when wired:

      1. Create a tmp worktree-style directory.
      2. ``git clone`` the task's repo at base_commit.
      3. Build a sprint contract via ``task_to_sprint_contract``.
      4. Invoke ``daemon.scheduler.execute_session`` against that worktree.
      5. Capture ``git diff`` from the worktree.
      6. Submit the diff to SWE-bench's verifier (Docker harness).
      7. Return TaskRunResult with the verdict.

    Raises ``NotImplementedError`` so callers don't accidentally use this in
    production runs without wiring it. Override by passing a custom
    ``forge_runner`` to ``run_subset()``.
    """
    raise NotImplementedError(
        "real_forge_runner is a stub — see eval/swebench/adapter.py for the "
        "shape of the real implementation. Phase 2 Week 7 follow-up."
    )
