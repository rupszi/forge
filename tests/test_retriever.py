"""Tests for retriever: cross-store retrieval, context formatting, token budget."""

import os
import tempfile

import pytest

from daemon.db import ForgeDB
from daemon.memory.retriever import Retriever, _extract_keywords


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        d = ForgeDB(os.path.join(tmp, "test.db"))
        yield d
        d.close()


@pytest.fixture
def retriever(db):
    return Retriever(db)


# --- Keyword extraction ---


def test_extract_keywords():
    kws = _extract_keywords("Build user authentication with Supabase RLS policies")
    assert "supabase" in kws
    assert "authentication" in kws
    assert "policies" in kws
    # Stop words excluded
    assert "with" not in kws


def test_extract_keywords_short_words_excluded():
    kws = _extract_keywords("Fix the bug in src")
    assert "the" not in kws
    assert "bug" not in kws  # 3 chars, excluded (>3 required)


def test_extract_keywords_limit():
    long_text = " ".join([f"keyword{i}" for i in range(50)])
    kws = _extract_keywords(long_text)
    assert len(kws) <= 15


# --- Retriever context ---


def test_empty_context(retriever):
    ctx = retriever.get_context_for_task("Build something")
    assert ctx == ""


def test_knowledge_items_included(db):
    retriever = Retriever(db)
    db.add_knowledge("gotcha", "supabase", "RLS requires service_role key for testing", "s1", 0.9)
    db.add_knowledge("solution", "supabase", "Use supabase gen types for TypeScript", "s1", 0.8)

    ctx = retriever.get_context_for_task("Configure service_role key for supabase testing")
    assert "Known issues" in ctx
    assert "service_role" in ctx


def test_failures_included(db):
    retriever = Retriever(db)
    db.save_episode(
        "ep-1",
        "s1",
        "sp-1",
        "Build authentication module",
        "sonnet",
        "claude_code",
        "generator",
        "failed",
        error="ImportError: cannot import bcrypt",
    )

    ctx = retriever.get_context_for_task("Build authentication module with bcrypt")
    assert "Past failures" in ctx
    assert "ImportError" in ctx


def test_research_included(db):
    retriever = Retriever(db)
    db.save_research(
        "supabase RLS tutorial",
        url="https://supabase.com/docs",
        title="RLS Guide",
        extracted_content="Enable RLS per table then add policies",
    )

    ctx = retriever.get_context_for_task("Configure Supabase RLS policies")
    assert "Enable RLS" in ctx


def test_token_budget_enforced(db):
    retriever = Retriever(db)
    # Add many knowledge items with long content
    for i in range(20):
        db.add_knowledge("gotcha", "auth", f"Authentication gotcha {i}: " + "x" * 200, f"s{i}", 0.9)

    ctx = retriever.get_context_for_task("Fix authentication")
    # ~500 tokens = ~2000 chars. Allow some overhead for headers.
    assert len(ctx) < 3000


def test_max_5_knowledge_items(db):
    retriever = Retriever(db)
    for i in range(10):
        db.add_knowledge("gotcha", "auth", f"Auth tip {i} about password handling", f"s{i}", 0.9)

    ctx = retriever.get_context_for_task("Fix password handling")
    # Count bullet points
    bullets = [l for l in ctx.split("\n") if l.strip().startswith("- [")]
    assert len(bullets) <= 5


def test_cross_store_integration(db):
    retriever = Retriever(db)
    # Add data to all stores
    db.add_knowledge("gotcha", "testing", "Always mock external API calls in testing", "s1", 0.9)
    db.save_episode(
        "ep-1",
        "s1",
        "sp-1",
        "Write testing suite for external APIs",
        "sonnet",
        "claude_code",
        "generator",
        "failed",
        error="Timeout: external API unreachable",
    )
    db.save_research(
        "api testing best practices",
        url="https://example.com",
        extracted_content="Use nock or msw for API mocking in tests",
    )

    ctx = retriever.get_context_for_task("Write testing suite for external APIs mocking")
    # Should have content from at least episodic or research
    assert "mock" in ctx.lower() or "Timeout" in ctx
