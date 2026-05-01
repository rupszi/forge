"""Research cache: web search results with expiry."""

from ..db import ForgeDB


class ResearchCache:
    def __init__(self, db: ForgeDB):
        self.db = db

    def store(
        self,
        query: str,
        url: str = "",
        title: str = "",
        extracted_content: str = "",
        relevance_score: float = 0.5,
    ) -> int:
        return self.db.save_research(query, url, title, extracted_content, relevance_score)

    def search(self, query: str, max_age_days: int = 30, limit: int = 5) -> list[dict]:
        return self.db.search_research(query, max_age_days, limit)

    def mark_used(self, research_id: int, task_id: str, success: bool) -> None:
        self.db.mark_research_used(research_id, task_id, success)
