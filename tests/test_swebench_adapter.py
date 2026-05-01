"""Tests for eval/swebench/adapter.py — Phase 2 Week 7 skeleton."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _import_adapter():
    """Helper: import the adapter module. Wraps the import in a function so
    tests can be discovered even if eval/ isn't on sys.path yet."""
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from eval.swebench import adapter  # type: ignore[import-not-found]

    return adapter


# ---- SWEBenchTask.from_dict ----


def test_task_from_dict_basic():
    adapter = _import_adapter()
    raw = {
        "instance_id": "django__django-12345",
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "Fix the bug",
        "FAIL_TO_PASS": ["test_a", "test_b"],
        "PASS_TO_PASS": ["test_c"],
        "version": "4.2",
    }
    task = adapter.SWEBenchTask.from_dict(raw)
    assert task.instance_id == "django__django-12345"
    assert task.repo == "django/django"
    assert task.fail_to_pass == ["test_a", "test_b"]
    assert task.pass_to_pass == ["test_c"]
    assert task.version == "4.2"


def test_task_from_dict_handles_jsonified_lists():
    """Some SWE-bench dumps store FAIL_TO_PASS as a JSON-stringified list."""
    adapter = _import_adapter()
    raw = {
        "instance_id": "x",
        "repo": "y",
        "base_commit": "z",
        "problem_statement": "p",
        "FAIL_TO_PASS": '["test_a", "test_b"]',
    }
    task = adapter.SWEBenchTask.from_dict(raw)
    assert task.fail_to_pass == ["test_a", "test_b"]


def test_task_from_dict_handles_missing_optional_fields():
    adapter = _import_adapter()
    task = adapter.SWEBenchTask.from_dict({"instance_id": "x"})
    assert task.instance_id == "x"
    assert task.repo == ""
    assert task.fail_to_pass == []
    assert task.pass_to_pass == []


# ---- load_tasks_from_jsonl ----


def test_load_tasks_from_jsonl_empty(tmp_path: Path):
    adapter = _import_adapter()
    f = tmp_path / "empty.jsonl"
    f.write_text("")
    tasks = adapter.load_tasks_from_jsonl(f)
    assert tasks == []


def test_load_tasks_from_jsonl_nonexistent_returns_empty():
    adapter = _import_adapter()
    assert adapter.load_tasks_from_jsonl("/nonexistent/path") == []


def test_load_tasks_from_jsonl_parses_valid_lines(tmp_path: Path):
    adapter = _import_adapter()
    f = tmp_path / "tasks.jsonl"
    f.write_text(
        json.dumps({"instance_id": "a", "problem_statement": "p"})
        + "\n"
        + json.dumps({"instance_id": "b", "problem_statement": "q"})
        + "\n"
    )
    tasks = adapter.load_tasks_from_jsonl(f)
    assert len(tasks) == 2
    assert tasks[0].instance_id == "a"
    assert tasks[1].instance_id == "b"


def test_load_tasks_from_jsonl_skips_malformed_lines(tmp_path: Path):
    adapter = _import_adapter()
    f = tmp_path / "tasks.jsonl"
    f.write_text(
        json.dumps({"instance_id": "good"})
        + "\n"
        + "{not json\n"
        + json.dumps({"instance_id": "good2"})
        + "\n"
    )
    tasks = adapter.load_tasks_from_jsonl(f)
    assert len(tasks) == 2
    assert [t.instance_id for t in tasks] == ["good", "good2"]


# ---- task_to_sprint_contract ----


def test_task_to_sprint_contract_includes_problem_and_tests():
    adapter = _import_adapter()
    task = adapter.SWEBenchTask(
        instance_id="dj-1",
        repo="django/django",
        base_commit="abc",
        problem_statement="Fix the URL routing bug",
        fail_to_pass=["tests.test_router.test_redirect"],
        pass_to_pass=["tests.test_misc.test_unrelated"],
    )
    contract = adapter.task_to_sprint_contract(task)
    assert "Fix the URL routing bug" in contract["description"]
    assert any("test_redirect" in c for c in contract["done_criteria"])
    assert contract["metadata"]["repo"] == "django/django"
    assert contract["metadata"]["base_commit"] == "abc"


def test_task_to_sprint_contract_appends_hints():
    adapter = _import_adapter()
    task = adapter.SWEBenchTask(
        instance_id="x",
        repo="r",
        base_commit="c",
        problem_statement="Fix it",
        hints_text="Look at line 42 of foo.py",
    )
    contract = adapter.task_to_sprint_contract(task)
    assert "line 42" in contract["description"]
    assert "Hints:" in contract["description"]


def test_task_to_sprint_contract_falls_back_when_no_failing_tests():
    adapter = _import_adapter()
    task = adapter.SWEBenchTask(
        instance_id="x",
        repo="r",
        base_commit="c",
        problem_statement="Fix it",
        fail_to_pass=[],
    )
    contract = adapter.task_to_sprint_contract(task)
    assert len(contract["done_criteria"]) == 1
    assert "previously-failing" in contract["done_criteria"][0]


# ---- run_subset ----


def test_run_subset_aggregates_pass_fail():
    adapter = _import_adapter()
    tasks = [
        adapter.SWEBenchTask(instance_id=f"t-{i}", repo="r", base_commit="c", problem_statement="p")
        for i in range(5)
    ]

    def fake_runner(task):
        # Pass even-numbered tasks
        i = int(task.instance_id.split("-")[1])
        return adapter.TaskRunResult(instance_id=task.instance_id, success=(i % 2 == 0))

    result = adapter.run_subset(tasks, forge_runner=fake_runner)
    assert result.total == 5
    assert result.passed == 3  # 0, 2, 4
    assert result.failed == 2  # 1, 3
    assert result.errored == 0
    assert result.pct == pytest.approx(60.0)


def test_run_subset_counts_runner_exceptions_as_errored():
    adapter = _import_adapter()
    tasks = [
        adapter.SWEBenchTask(instance_id="t-1", repo="r", base_commit="c", problem_statement="p")
    ]

    def crashing_runner(task):
        raise RuntimeError("oops")

    result = adapter.run_subset(tasks, forge_runner=crashing_runner)
    assert result.errored == 1
    assert result.passed == 0
    assert "runner exception" in result.by_task["t-1"].error


def test_run_subset_invokes_progress_cb():
    adapter = _import_adapter()
    tasks = [
        adapter.SWEBenchTask(instance_id=f"t-{i}", repo="r", base_commit="c", problem_statement="p")
        for i in range(3)
    ]
    calls = []

    def runner(task):
        return adapter.TaskRunResult(instance_id=task.instance_id, success=True)

    def progress_cb(i, total, result):
        calls.append((i, total, result.instance_id))

    adapter.run_subset(tasks, forge_runner=runner, progress_cb=progress_cb)
    assert calls == [(1, 3, "t-0"), (2, 3, "t-1"), (3, 3, "t-2")]


# ---- SubsetResult / kill criterion ----


def test_subset_result_kill_criterion_passes_at_30pct():
    adapter = _import_adapter()
    r = adapter.SubsetResult(total=50, passed=15, failed=35, errored=0)
    assert r.pct == pytest.approx(30.0)
    assert r.kill_criterion_passed is True


def test_subset_result_kill_criterion_fails_below_30pct():
    adapter = _import_adapter()
    r = adapter.SubsetResult(total=50, passed=14, failed=36, errored=0)
    assert r.kill_criterion_passed is False


def test_subset_result_kill_criterion_handles_empty():
    adapter = _import_adapter()
    r = adapter.SubsetResult(total=0, passed=0, failed=0, errored=0)
    assert r.pct == 0.0
    assert r.kill_criterion_passed is False


def test_subset_result_summary_human_readable():
    adapter = _import_adapter()
    r = adapter.SubsetResult(total=50, passed=20, failed=28, errored=2)
    summary = r.summary()
    assert "20/50" in summary
    assert "40.0%" in summary
    assert "PASS" in summary  # kill criterion


# ---- real_forge_runner stub ----


def test_real_forge_runner_raises_not_implemented():
    """The stub raises so users don't accidentally run with it."""
    adapter = _import_adapter()
    task = adapter.SWEBenchTask(instance_id="t", repo="r", base_commit="c", problem_statement="p")
    with pytest.raises(NotImplementedError, match="stub"):
        adapter.real_forge_runner(task)
