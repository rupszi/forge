"""M4 — CLI completion: plan / run / add / merge / review terminal verbs.

The audit found these spec'd commands missing from the parser. They wrap the
existing backend; here we prove the parser registers them and each dispatches
to the right backend call (planner / scheduler / reviewer / worktree mocked so
no LLM runs).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from daemon import cli


@pytest.fixture
def cli_db(tmp_db, monkeypatch):
    """Patch `cli._get_db` to the shared test db and neutralize its `.close()`
    so a CLI command doesn't close the fixture out from under the assertions."""
    monkeypatch.setattr(tmp_db, "close", lambda: None)
    monkeypatch.setattr(cli, "_get_db", lambda: tmp_db)
    return tmp_db


_VERB_ARGS = {
    "plan": ["plan", "build auth"],
    "run": ["run"],
    "add": ["add", "do a thing"],
    "merge": ["merge"],
    "review": ["review", "sprint-x"],
    "models": ["models"],
}


class TestParserRegistration:
    @pytest.mark.parametrize("verb", list(_VERB_ARGS))
    def test_verb_is_registered(self, verb):
        parser = cli.build_parser()
        args = parser.parse_args(_VERB_ARGS[verb])
        assert args.command == verb

    def test_verb_in_command_table(self):
        for verb in _VERB_ARGS:
            assert hasattr(cli, f"cmd_{verb}")


class TestAdd:
    def test_add_persists_pending_sprint(self, cli_db, monkeypatch):
        tmp_db = cli_db
        rc = cli.cmd_add(SimpleNamespace(description="fix the login bug", model=None))
        assert rc == 0
        sprints = tmp_db.get_sprints_for_session("cli-adhoc")
        assert any("login bug" in s["description"] for s in sprints)
        assert all(s["status"] == "pending" for s in sprints)


class TestPlan:
    def test_plan_invokes_planner_and_saves(self, cli_db, monkeypatch, capsys):
        from daemon.models import SprintContract

        async def fake_scan(path):
            from daemon.models import ProjectContext

            return ProjectContext(path=path)

        async def fake_plan(objective, ctx, session_id="", kb_context="", *a, **k):
            return [
                SprintContract(
                    session_id=session_id,
                    description="sprint one",
                    done_criteria=["done"],
                    assigned_model="qwen3-coder-next",
                )
            ]

        monkeypatch.setattr(cli, "scan_project", fake_scan, raising=False)
        monkeypatch.setattr("daemon.agents.planner.plan", fake_plan)
        rc = cli.cmd_plan(SimpleNamespace(objective="build auth"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "sprint one" in out


class TestRun:
    def test_run_executes_pending_via_scheduler(self, cli_db, monkeypatch, capsys):
        from daemon import scheduler
        from daemon.models import ProjectContext, SprintContract

        tmp_db = cli_db

        async def fake_scan(path):
            return ProjectContext(path=path)

        monkeypatch.setattr(cli, "scan_project", fake_scan, raising=False)
        tmp_db.save_sprint(
            SprintContract(
                id="sprint-run01",
                session_id="cli-adhoc",
                description="do it",
                done_criteria=["x"],
                assigned_model="qwen3-coder-next",
                status="pending",
            )
        )

        async def fake_execute_sprint(sprint, *a, **k):
            sprint.status = "completed"
            return sprint

        monkeypatch.setattr(scheduler, "execute_sprint", fake_execute_sprint)
        rc = cli.cmd_run(SimpleNamespace(sprint_id=None))
        out = capsys.readouterr().out
        assert rc == 0
        assert "1/1 sprint(s) completed" in out

    def test_run_with_no_pending_returns_1(self, cli_db, monkeypatch):
        from daemon.models import ProjectContext

        async def fake_scan(path):
            return ProjectContext(path=path)

        monkeypatch.setattr(cli, "scan_project", fake_scan, raising=False)
        rc = cli.cmd_run(SimpleNamespace(sprint_id=None))
        assert rc == 1


class TestReview:
    def test_review_runs_panel(self, cli_db, monkeypatch, capsys):
        tmp_db = cli_db
        from daemon.models import ReviewPerspective, ReviewResult, SprintContract

        tmp_db.save_sprint(
            SprintContract(id="sprint-rev01", session_id="s1", description="review me")
        )

        async def fake_diff(name):
            return "diff --git a b\n+code"

        async def fake_review(diff, perspectives=None, context=""):
            return ReviewResult(
                overall_verdict="APPROVED",
                perspectives=[ReviewPerspective(name="security", verdict="PASS")],
            )

        monkeypatch.setattr("daemon.worktree.get_diff", fake_diff)
        monkeypatch.setattr("daemon.agents.reviewer.review", fake_review)
        rc = cli.cmd_review(SimpleNamespace(sprint_id="sprint-rev01"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "APPROVED" in out


class TestMerge:
    def test_merge_show_lists_worktrees(self, monkeypatch, capsys):
        async def fake_list():
            return [{"path": "/x/.forge/worktrees/sprint-a", "branch": "refs/heads/forge/sprint-a"}]

        monkeypatch.setattr("daemon.worktree.list_worktrees", fake_list)
        rc = cli.cmd_merge(SimpleNamespace(approve=False, show=True))
        out = capsys.readouterr().out
        assert rc == 0
        assert "sprint-a" in out
