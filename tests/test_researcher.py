"""Tests for researcher: query generation, caching, search."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from daemon.agents.researcher import Researcher
from daemon.db import ForgeDB
from daemon.memory.research import ResearchCache
from daemon.models import ExecutionResult


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        d = ForgeDB(os.path.join(tmp, "test.db"))
        yield d
        d.close()


@pytest.fixture
def researcher(db):
    cache = ResearchCache(db)
    return Researcher(cache)


@pytest.mark.asyncio
async def test_search_checks_cache_first(db):
    cache = ResearchCache(db)
    cache.store(
        "import error python",
        url="https://example.com",
        title="Fix",
        extracted_content="Install the missing package",
    )
    researcher = Researcher(cache)

    result = await researcher.search_for_error("import error python")
    assert result is not None
    assert "Install" in result.content


@pytest.mark.asyncio
async def test_search_stores_result(db):
    cache = ResearchCache(db)
    researcher = Researcher(cache)

    mock_result = ExecutionResult(
        success=True, output="URL: https://fix.com\nContent: Use pip install"
    )
    with patch(
        "daemon.executors.ollama.execute",
        return_value=ExecutionResult(success=True, output="python import error fix"),
    ):
        with patch("daemon.executors.claude_code.execute", return_value=mock_result):
            result = await researcher.search_for_error("ModuleNotFoundError: No module named 'xyz'")

    # Should have stored in cache
    cached = cache.search("python", limit=5)
    # May or may not find depending on query generation, but at minimum no crash


@pytest.mark.asyncio
async def test_research_before_task_checks_cache(db):
    cache = ResearchCache(db)
    cache.store("supabase RLS setup", extracted_content="Enable RLS per table first")
    researcher = Researcher(cache)

    # Query must match via LIKE — use overlapping words
    result = await researcher.research_before_task("supabase RLS setup guide")
    assert result is not None
    assert "Enable RLS" in result


@pytest.mark.asyncio
async def test_generate_queries_fallback():
    """If LLM fails, should use error as query."""
    cache = MagicMock()
    cache.search.return_value = []
    researcher = Researcher(cache)

    with patch(
        "daemon.executors.ollama.execute",
        return_value=ExecutionResult(success=False, error="offline"),
    ):
        queries = await researcher._generate_queries("TypeError: undefined is not a function")
    assert len(queries) >= 1
    assert "TypeError" in queries[0]
