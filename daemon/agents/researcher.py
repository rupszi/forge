"""Researcher: web search + solution extraction + caching."""

from __future__ import annotations

import logging

from ..executors import claude_code as claude_executor, ollama as ollama_executor
from ..memory.research import ResearchCache
from ..models import ResearchResult

logger = logging.getLogger(__name__)


class Researcher:
    def __init__(self, cache: ResearchCache):
        self.cache = cache

    async def _generate_queries(self, error: str, context: str = "") -> list[str]:
        """Generate 1-3 focused search queries from an error."""
        prompt = (
            f"Generate 1-3 web search queries to solve this error. "
            f"Reply with one query per line, nothing else.\n\n"
            f"Error: {error[:500]}\n"
        )
        if context:
            prompt += f"Context: {context[:300]}\n"

        result = await ollama_executor.execute(prompt)
        if result.success:
            queries = [
                q.strip().strip("\"'") for q in result.output.strip().split("\n") if q.strip()
            ]
            return queries[:3]
        # Fallback: use error as query
        return [error[:100]]

    async def _web_search(self, query: str) -> list[ResearchResult]:
        """Search the web using Claude Code's search capability."""
        prompt = (
            f"Search the web for: {query}\n\n"
            f"Provide the most relevant result with:\n"
            f"1. URL\n2. Title\n3. Key content (max 3 sentences)\n\n"
            f"Format: URL: <url>\nTitle: <title>\nContent: <content>"
        )
        result = await claude_executor.execute(prompt, model="sonnet")
        if result.success:
            return [
                ResearchResult(
                    content=result.output[:500],
                    url="",
                    title=query,
                    relevance_score=0.5,
                )
            ]
        return []

    async def _extract_raw(self, result: ResearchResult, error: str) -> str:
        """Run the extraction model; return its raw (unredacted) text."""
        prompt = (
            f"Extract the specific solution for this error from the content below.\n"
            f"Reply with 1-3 sentences only.\n\n"
            f"Error: {error[:300]}\n"
            f"Content: {result.content[:500]}"
        )
        extraction = await ollama_executor.execute(prompt)
        return extraction.output[:300] if extraction.success else result.content[:300]

    async def _extract_relevant_content(self, result: ResearchResult, error: str) -> str:
        """Extract the relevant solution, redacting any secrets before it can
        reach the research cache or an agent prompt (G-AGT-4 / audit fix)."""
        from ..redact import redact

        return redact(await self._extract_raw(result, error))

    async def search_for_error(self, error: str, context: str = "") -> ResearchResult | None:
        """Search web for a solution to a specific error."""
        # Check cache first
        cached = self.cache.search(error[:50], limit=1)
        if cached:
            return ResearchResult(
                content=cached[0].get("extracted_content", ""),
                url=cached[0].get("url", ""),
                title=cached[0].get("title", ""),
            )

        queries = await self._generate_queries(error, context)
        for query in queries[:3]:
            results = await self._web_search(query)
            if results:
                extracted = await self._extract_relevant_content(results[0], error)
                self.cache.store(
                    query=query,
                    url=results[0].url,
                    title=results[0].title,
                    extracted_content=extracted,
                )
                return ResearchResult(content=extracted, url=results[0].url)
        return None

    async def research_before_task(self, task_description: str) -> str | None:
        """Proactive research for complex tasks. Checks cache first."""
        cached = self.cache.search(task_description[:50], max_age_days=30)
        if cached:
            return cached[0].get("extracted_content", "")

        results = await self._web_search(task_description[:100])
        if results:
            extracted = await self._extract_relevant_content(results[0], task_description)
            self.cache.store(
                query=task_description[:100],
                url=results[0].url,
                title=results[0].title,
                extracted_content=extracted,
            )
            return extracted
        return None
