"""SWE-bench verification — submit Forge's patches to the official harness.

Forge must never grade its own patches. The truth of "did this fix the issue"
comes from SWE-bench's own evaluation harness, which applies the held-out
``test_patch``, runs ``FAIL_TO_PASS`` + ``PASS_TO_PASS`` in the task's Docker
environment, and writes a report JSON.

This module:
  - writes a ``predictions.jsonl`` in the shape the harness expects,
  - builds the harness ``argv`` (no ``shell=True`` — security rule),
  - parses the harness report into a ``{instance_id: resolved}`` map.

The actual ``subprocess`` invocation lives in :func:`run_verification`, which
is injected/mocked in tests — it needs Docker and is operationally heavy. The
*parser* and *argv builder* are pure and unit-tested against fixtures.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Field the harness reads to identify which model produced the patch.
DEFAULT_MODEL_NAME = "forge"


def write_predictions(
    predictions: dict[str, str], path: str | Path, model_name: str = DEFAULT_MODEL_NAME
) -> Path:
    """Write a ``predictions.jsonl`` (one row per task) for the harness.

    ``predictions`` maps ``instance_id -> unified diff``. Empty diffs are still
    written (so the harness records them as unresolved) — silently dropping a
    task would inflate the resolve rate by shrinking the denominator.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for instance_id, diff in predictions.items():
            row = {
                "instance_id": instance_id,
                "model_patch": diff or "",
                "model_name_or_path": model_name,
            }
            f.write(json.dumps(row) + "\n")
    return p


def build_eval_argv(
    predictions_path: str | Path,
    run_id: str,
    *,
    dataset: str = "princeton-nlp/SWE-bench_Verified",
    max_workers: int = 1,
) -> list[str]:
    """Argv for the official harness. Run as ``python -m swebench.harness...``.

    Kept as a list (never a shell string) per the security rules. ``run_id``
    scopes the harness's output dir so concurrent runs don't collide.
    """
    return [
        "python",
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        dataset,
        "--predictions_path",
        str(predictions_path),
        "--run_id",
        run_id,
        "--max_workers",
        str(max_workers),
    ]


def parse_report(report: dict[str, Any], instance_ids: list[str]) -> dict[str, bool]:
    """Parse a SWE-bench report dict into ``{instance_id: resolved}``.

    The harness report lists ``resolved_ids`` (and ``error_ids`` etc.). Every
    requested instance is present in the output map: a task absent from
    ``resolved_ids`` is ``False`` (conservative — unverified ⇒ not resolved).
    """
    resolved_ids = set(report.get("resolved_ids", []))
    return {iid: (iid in resolved_ids) for iid in instance_ids}


def parse_report_file(path: str | Path, instance_ids: list[str]) -> dict[str, bool]:
    """Load + parse a harness report JSON file. Missing file ⇒ all unresolved."""
    p = Path(path)
    if not p.exists():
        logger.warning("swebench: report %s missing — treating all as unresolved", p)
        return dict.fromkeys(instance_ids, False)
    return parse_report(json.loads(p.read_text(encoding="utf-8")), instance_ids)


def run_verification(
    predictions: dict[str, str],
    run_id: str,
    work_dir: str | Path,
    *,
    invoker: Callable[[list[str]], dict[str, Any]] | None = None,
) -> dict[str, bool]:
    """Verify ``predictions`` and return ``{instance_id: resolved}``.

    ``invoker`` runs the harness argv and returns its report dict; the default
    raises (needs Docker), so tests pass a mock. This keeps the orchestration
    here unit-testable while the heavy Docker call stays injectable.
    """
    work = Path(work_dir)
    preds_path = write_predictions(predictions, work / "predictions.jsonl")
    instance_ids = list(predictions.keys())
    argv = build_eval_argv(preds_path, run_id)

    if invoker is None:

        def invoker(_argv: list[str]) -> dict[str, Any]:
            raise NotImplementedError(
                "SWE-bench verification needs Docker. Pass an `invoker` that runs "
                f"{argv!r} and returns the parsed report JSON, or run the harness "
                "manually and use parse_report_file()."
            )

    report = invoker(argv)
    return parse_report(report, instance_ids)
