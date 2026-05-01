"""Tests for learner: gotcha extraction, pattern updates, topic extraction."""

import os
import tempfile
from unittest.mock import patch

import pytest

from daemon.db import ForgeDB
from daemon.memory.learner import Learner
from daemon.models import ExecutionResult


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        d = ForgeDB(os.path.join(tmp, "test.db"))
        yield d
        d.close()


@pytest.fixture
def learner(db):
    return Learner(db)


def test_extract_topic_supabase(learner):
    assert learner._extract_topic("Set up Supabase RLS policies") == "supabase"


def test_extract_topic_auth(learner):
    assert learner._extract_topic("Build auth module") == "auth"


def test_extract_topic_general(learner):
    assert learner._extract_topic("Do something random") == "general"


def test_extract_topic_next(learner):
    assert learner._extract_topic("Configure Next.js middleware") == "next.js"


def test_extract_topic_testing(learner):
    assert learner._extract_topic("Write test suite for components") == "testing"


def test_learn_sync_updates_patterns(db):
    learner = Learner(db)
    # Store some episodes
    db.save_episode(
        "ep-1",
        "sess-1",
        "sp-1",
        "Build auth API",
        "sonnet",
        "claude_code",
        "generator",
        "completed",
        duration_seconds=45.0,
    )
    db.save_episode(
        "ep-2",
        "sess-1",
        "sp-2",
        "Write tests",
        "sonnet",
        "claude_code",
        "generator",
        "failed",
        duration_seconds=30.0,
    )

    stats = learner.learn_sync("sess-1")
    assert stats["patterns_updated"] == 2

    # Check procedure was recorded
    proc = db.get_procedure("Build auth API")
    assert proc is not None
    assert proc["success_rate"] == 1.0


@pytest.mark.asyncio
async def test_learn_from_session_extracts_gotcha(db):
    learner = Learner(db)

    # Create failure + resolution pair
    db.save_episode(
        "ep-1",
        "sess-1",
        "sp-1",
        "Build Supabase auth",
        "sonnet",
        "claude_code",
        "generator",
        "failed",
        error="RLS policy missing on posts table",
    )
    db.save_episode(
        "ep-2",
        "sess-1",
        "sp-1",
        "Build Supabase auth",
        "sonnet",
        "claude_code",
        "generator",
        "completed",
        result="Added RLS policy for authenticated users",
    )

    mock_result = ExecutionResult(
        success=True, output="Always add RLS policies to all tables before testing"
    )
    with patch("daemon.executors.ollama.execute", return_value=mock_result):
        stats = await learner.learn_from_session("sess-1")

    assert stats["gotchas_learned"] >= 1
    # Check KB
    items = db.search_knowledge(query="RLS")
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_learn_skips_generic_gotcha(db):
    learner = Learner(db)
    db.save_episode(
        "ep-1",
        "sess-1",
        "sp-1",
        "Do something",
        "sonnet",
        "claude_code",
        "generator",
        "failed",
        error="Error occurred",
    )
    db.save_episode(
        "ep-2",
        "sess-1",
        "sp-1",
        "Do something",
        "sonnet",
        "claude_code",
        "generator",
        "completed",
        result="Fixed it",
    )

    mock_result = ExecutionResult(success=True, output="SKIP")
    with patch("daemon.executors.ollama.execute", return_value=mock_result):
        stats = await learner.learn_from_session("sess-1")
    assert stats["gotchas_learned"] == 0


@pytest.mark.asyncio
async def test_learn_handles_ollama_failure(db):
    learner = Learner(db)
    db.save_episode(
        "ep-1",
        "sess-1",
        "sp-1",
        "Task",
        "sonnet",
        "claude_code",
        "generator",
        "failed",
        error="Err",
    )
    db.save_episode(
        "ep-2",
        "sess-1",
        "sp-1",
        "Task",
        "sonnet",
        "claude_code",
        "generator",
        "completed",
        result="OK",
    )

    mock_result = ExecutionResult(success=False, error="Ollama offline")
    with patch("daemon.executors.ollama.execute", return_value=mock_result):
        stats = await learner.learn_from_session("sess-1")
    # Should not crash
    assert stats["gotchas_learned"] == 0
