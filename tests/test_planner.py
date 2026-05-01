"""Tests for planner: JSON parsing, dependency chains, fallback."""

import json

from daemon.agents.planner import _build_plan_prompt, _parse_plan
from daemon.models import MCPServer, ProjectContext

# --- Plan parsing ---


def test_parse_valid_json():
    output = json.dumps(
        [
            {
                "id": "sprint-1",
                "description": "Create database schema",
                "done_criteria": ["Tables created", "Indexes added"],
                "depends_on": [],
                "recommended_model": "opus",
                "estimated_tokens": 15000,
            },
            {
                "id": "sprint-2",
                "description": "Build API endpoints",
                "done_criteria": ["Endpoints working", "Tests passing"],
                "depends_on": ["sprint-1"],
                "recommended_model": "sonnet",
            },
        ]
    )
    sprints = _parse_plan(output, "sess-1")
    assert len(sprints) == 2
    assert sprints[0].id == "sprint-1"
    assert sprints[0].description == "Create database schema"
    assert len(sprints[0].done_criteria) == 2
    assert sprints[0].assigned_model == "opus"
    assert sprints[1].depends_on == ["sprint-1"]


def test_parse_json_with_markdown_wrapper():
    output = """Here's the plan:
```json
[{"id": "sprint-1", "description": "Build auth", "done_criteria": ["Auth works"]}]
```
"""
    sprints = _parse_plan(output, "sess-1")
    assert len(sprints) == 1
    assert sprints[0].description == "Build auth"


def test_parse_invalid_json_fallback():
    output = "This is not valid JSON at all, just some text about the task"
    sprints = _parse_plan(output, "sess-1")
    assert len(sprints) == 1
    assert sprints[0].assigned_model == "sonnet"
    assert "Task completed as described" in sprints[0].done_criteria[0]


def test_parse_empty_array_fallback():
    sprints = _parse_plan("[]", "sess-1")
    assert len(sprints) == 1  # Fallback sprint


def test_parse_session_id_propagated():
    output = json.dumps([{"description": "Task 1", "done_criteria": ["Done"]}])
    sprints = _parse_plan(output, "my-session")
    assert sprints[0].session_id == "my-session"


def test_parse_default_model():
    output = json.dumps([{"description": "Task", "done_criteria": ["Done"]}])
    sprints = _parse_plan(output, "s1")
    assert sprints[0].assigned_model == "sonnet"


def test_parse_dependency_chain():
    output = json.dumps(
        [
            {"id": "s1", "description": "Schema", "done_criteria": ["OK"], "depends_on": []},
            {"id": "s2", "description": "API", "done_criteria": ["OK"], "depends_on": ["s1"]},
            {"id": "s3", "description": "UI", "done_criteria": ["OK"], "depends_on": ["s2"]},
        ]
    )
    sprints = _parse_plan(output, "sess")
    assert sprints[2].depends_on == ["s2"]


# --- Prompt building ---


def test_build_prompt_includes_context():
    ctx = ProjectContext(
        framework="next",
        language="typescript",
        mcp_servers=[MCPServer(name="supabase"), MCPServer(name="vercel")],
        available_tools={"gh": True, "supabase": True},
    )
    prompt = _build_plan_prompt("Build auth", ctx, "## Known: RLS gotcha")
    assert "next" in prompt
    assert "typescript" in prompt
    assert "supabase" in prompt
    assert "RLS gotcha" in prompt
    assert "Build auth" in prompt


def test_build_prompt_empty_context():
    ctx = ProjectContext()
    prompt = _build_plan_prompt("Do something", ctx)
    assert "Do something" in prompt
