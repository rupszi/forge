"""Integration tests: every persistence boundary scrubs / refuses credentials.

These exercise the end-to-end wiring between ``daemon/redact.py`` and the
persistence layers (replay, db.add_knowledge, db.save_episode). Per ADR-017
each boundary has its own behavior:

  - replay: redact and persist
  - KB writes: refuse (don't persist) when content matches a credential pattern
  - episodic writes: redact and persist
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from daemon import replay
from daemon.db import ForgeDB


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as tmp:
        db = ForgeDB(os.path.join(tmp, "test.db"))
        yield db
        db.close()


# ``tmp_forge_dir`` is shared via tests/conftest.py (Task 2.5).


# ---- Trace JSONL: redact and persist ----


def test_trace_event_data_payload_is_redacted_on_write(tmp_forge_dir):
    """append_event runs the data payload through redact_value before write."""
    replay.append_event(
        "session-1",
        "executor.invoke",
        sprint_id="sprint-1",
        data={
            "command": "curl -H 'Authorization: Bearer abc123def456ghi789'",
            "env_var": "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
        },
    )
    contents = (tmp_forge_dir / "sessions" / "session-1" / "trace.jsonl").read_text()
    parsed = json.loads(contents.strip())
    assert "abc123def456ghi789" not in parsed["data"]["command"]
    assert "AKIAIOSFODNN7EXAMPLE" not in parsed["data"]["env_var"]
    assert "REDACTED" in parsed["data"]["command"]
    assert "REDACTED" in parsed["data"]["env_var"]


def test_trace_event_handles_nested_credential(tmp_forge_dir):
    """Nested dicts and lists in data are recursively scrubbed."""
    replay.append_event(
        "session-2",
        "step",
        data={
            "headers": {"Authorization": "Bearer xyz_secret_token_aaaaaaaaaaaaa"},
            "files": [
                {"path": "/etc/x", "contents": "DB_PASSWORD=p@ssw0rd_long_enough"},
            ],
        },
    )
    contents = (tmp_forge_dir / "sessions" / "session-2" / "trace.jsonl").read_text()
    parsed = json.loads(contents.strip())
    assert "xyz_secret_token" not in json.dumps(parsed)
    assert "p@ssw0rd_long_enough" not in json.dumps(parsed)


def test_trace_event_safe_data_passes_through(tmp_forge_dir):
    """Non-secret data is preserved unchanged."""
    replay.append_event(
        "session-3",
        "step",
        data={"task_id": "sprint-42", "duration_ms": 1234, "complete": True},
    )
    contents = (tmp_forge_dir / "sessions" / "session-3" / "trace.jsonl").read_text()
    parsed = json.loads(contents.strip())
    assert parsed["data"]["task_id"] == "sprint-42"
    assert parsed["data"]["duration_ms"] == 1234
    assert parsed["data"]["complete"] is True


# ---- KB writes: REFUSE credentials ----


def test_add_knowledge_refuses_anthropic_key_in_content(tmp_db):
    """The KB write gate returns None and doesn't persist."""
    fake_key = "sk-ant-api03-" + "x" * 90
    result = tmp_db.add_knowledge(
        category="gotcha",
        topic="anthropic",
        content=f"Use {fake_key} for prod",
    )
    assert result is None  # refused

    # Verify nothing was written
    items = tmp_db.search_knowledge(query="prod", topic="anthropic")
    assert items == []


def test_add_knowledge_refuses_aws_key_in_content(tmp_db):
    result = tmp_db.add_knowledge(
        category="solution",
        topic="aws",
        content="Set AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE in CI",
    )
    assert result is None


def test_add_knowledge_refuses_credential_in_topic(tmp_db):
    """Topics are also gated — a credential leaked into the topic field
    would be just as bad as in content."""
    result = tmp_db.add_knowledge(
        category="gotcha",
        topic=f"sk-ant-api03-{'x' * 90}",
        content="some lesson",
    )
    assert result is None


def test_add_knowledge_persists_safe_content(tmp_db):
    """Sanity: legitimate KB items still write fine."""
    result = tmp_db.add_knowledge(
        category="gotcha",
        topic="supabase",
        content="RLS test with service_role key (rotated daily; not the literal value)",
    )
    # NB: "service_role key" is referenced as a phrase but no actual key is
    # in the string; should pass.
    assert result is not None
    items = tmp_db.search_knowledge(topic="supabase")
    assert len(items) == 1


def test_add_knowledge_refuses_jwt_in_content(tmp_db):
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTYifQ.abc123signature456789"
    result = tmp_db.add_knowledge(
        category="gotcha",
        topic="auth",
        content=f"Got this JWT in the header: {jwt}",
    )
    assert result is None


# ---- Episodic store: REDACT and persist ----


def test_save_episode_redacts_error_field(tmp_db):
    """save_episode scrubs error/resolution before write."""
    tmp_db.save_episode(
        episode_id="ep-1",
        session_id="s-1",
        sprint_id="sp-1",
        task_description="run install",
        model="qwen3-coder-next",
        agent_type="ollama",
        agent_role="generator",
        status="failed",
        error="curl failed: Authorization: Bearer token_abc123def456ghi789jkl",
        resolution="retry with valid bearer token_xyz789secretvalue123aaa",
    )

    rows = tmp_db.get_episodes_for_session("s-1")
    assert len(rows) == 1
    row = rows[0]
    # Bearer token in error redacted
    assert "token_abc123def456ghi789jkl" not in row["error"]
    assert "REDACTED" in row["error"]
    # Resolution also redacted
    assert "token_xyz789secretvalue123aaa" not in row["resolution"]


def test_save_episode_redacts_evaluator_feedback(tmp_db):
    """The evaluator's feedback might include parts of the diff that
    contain credentials. Redact at write."""
    tmp_db.save_episode(
        episode_id="ep-2",
        session_id="s-2",
        sprint_id="sp-2",
        task_description="add config",
        model="claude-sonnet-4",
        agent_type="claude_code",
        agent_role="evaluator",
        status="completed",
        evaluator_feedback="FAIL: Found AKIAIOSFODNN7EXAMPLE in committed config",
    )

    rows = tmp_db.get_episodes_for_session("s-2")
    assert "AKIAIOSFODNN7EXAMPLE" not in rows[0]["evaluator_feedback"]
    assert "REDACTED" in rows[0]["evaluator_feedback"]


def test_save_episode_passes_safe_text_through(tmp_db):
    """Sanity: non-secret error messages aren't mangled."""
    tmp_db.save_episode(
        episode_id="ep-3",
        session_id="s-3",
        sprint_id="sp-3",
        task_description="add /health endpoint",
        model="qwen3-coder-next",
        agent_type="ollama",
        agent_role="generator",
        status="failed",
        error="ImportError: cannot import name 'NextRequest' from 'next/server'",
    )

    rows = tmp_db.get_episodes_for_session("s-3")
    # Original message preserved
    assert rows[0]["error"] == "ImportError: cannot import name 'NextRequest' from 'next/server'"


# ---- Subprocess env filtering ----


def test_claude_executor_passes_filtered_env(monkeypatch):
    """The claude_code executor calls filtered_subprocess_env when spawning."""
    from daemon.executors import claude_code

    # Set both an allowlisted and a non-allowlisted env var; verify only the
    # allowlisted one is in the env passed to the subprocess.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("MY_PROJECT_TOKEN", "shouldNotLeak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "shouldNotLeak")

    captured: dict = {}

    async def fake_spawn(*args, **kwargs):
        captured["env"] = kwargs.get("env")

        class _Proc:
            returncode = 0

            async def communicate(self):
                return (b"ok\n", b"")

        return _Proc()

    monkeypatch.setattr(claude_code.asyncio, "create_subprocess_exec", fake_spawn)

    import asyncio

    asyncio.run(claude_code.execute("hello", worktree_path=None, model="sonnet"))

    env = captured["env"]
    assert env is not None, "subprocess.create was not called with env="
    assert "ANTHROPIC_API_KEY" in env
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert "MY_PROJECT_TOKEN" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
