"""Unified cross-store retrieval. Builds context for agent injection.

Given a task description:
1. Extract keywords from description
2. Query knowledge base for relevant gotchas/solutions (max 5)
3. Query episodic store for past failures on similar tasks (max 3)
4. Query research cache for recent relevant research (max 2)
5. Return formatted context string (max ~500 tokens)
"""

from ..config import KB_MAX_CONTEXT_ITEMS, KB_MAX_CONTEXT_TOKENS
from ..db import ForgeDB


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from a task description."""
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "must",
        "with",
        "for",
        "and",
        "but",
        "or",
        "not",
        "from",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "in",
        "on",
        "at",
        "to",
        "of",
        "by",
        "as",
        "all",
        "each",
        "every",
        "any",
        "some",
        "no",
        "into",
        "over",
        "after",
        "before",
        "between",
        "through",
        "about",
        "than",
        "then",
        "also",
        "just",
        "only",
        "very",
        "too",
        "so",
        "up",
        "out",
        "if",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "why",
    }
    words = text.lower().split()
    return [
        w.strip(".,;:!?()[]{}\"'") for w in words if len(w) > 3 and w.lower() not in stop_words
    ][:15]


class Retriever:
    def __init__(self, db: ForgeDB):
        self.db = db

    def get_context_for_task(self, task_description: str) -> str:
        """Build memory context for an agent. Max ~500 tokens."""
        keywords = _extract_keywords(task_description)
        if not keywords:
            return ""

        sections = []
        token_count = 0

        # 1. Knowledge base items (max 5)
        kb_items = self.db.get_knowledge_for_task(task_description, limit=KB_MAX_CONTEXT_ITEMS)
        if kb_items:
            lines = ["## Known issues and patterns\n"]
            for item in kb_items:
                line = f"- [{item['category']}] {item['content']}"
                est = len(line) // 4
                if token_count + est > KB_MAX_CONTEXT_TOKENS:
                    break
                lines.append(line)
                token_count += est
            if len(lines) > 1:
                sections.append("\n".join(lines))

        # 2. Past failures on similar tasks (max 3)
        failures = self.db.get_recent_failures(limit=20)
        relevant_failures = []
        for f in failures:
            desc = (f.get("task_description") or "").lower()
            if any(kw in desc for kw in keywords[:5]):
                relevant_failures.append(f)
            if len(relevant_failures) >= 3:
                break

        if relevant_failures:
            lines = ["## Past failures on similar tasks\n"]
            for f in relevant_failures:
                error = (f.get("error") or "unknown")[:100]
                resolution = (f.get("resolution") or "none")[:100]
                line = f"- Error: {error}"
                if resolution != "none":
                    line += f" -> Resolution: {resolution}"
                est = len(line) // 4
                if token_count + est > KB_MAX_CONTEXT_TOKENS:
                    break
                lines.append(line)
                token_count += est
            if len(lines) > 1:
                sections.append("\n".join(lines))

        # 3. Recent research (max 2)
        for kw in keywords[:3]:
            if token_count >= KB_MAX_CONTEXT_TOKENS:
                break
            results = self.db.search_research(kw, limit=2)
            for r in results:
                if r.get("extracted_content"):
                    content = r["extracted_content"][:150]
                    line = f"- Research: {content}"
                    est = len(line) // 4
                    if token_count + est > KB_MAX_CONTEXT_TOKENS:
                        break
                    if not any("Research" in s for s in sections):
                        sections.append("## Recent research\n")
                    sections.append(f"- {content} (source: {r.get('url', 'unknown')})")
                    token_count += est

        return "\n\n".join(sections) if sections else ""
