"""Knowledge base: gotchas, solutions, patterns. One-line imperative statements.

Confidence-scored, deduplicating, pruning, with import from Claude Code auto-memory.
"""

from pathlib import Path

from ..db import ForgeDB


class KnowledgeBase:
    def __init__(self, db: ForgeDB):
        self.db = db

    def add(
        self, category: str, topic: str, content: str, source: str = "", confidence: float = 0.5
    ) -> int:
        return self.db.add_knowledge(category, topic, content, source, confidence)

    def search(
        self, query: str = "", topic: str = "", category: str = "", limit: int = 10
    ) -> list[dict]:
        return self.db.search_knowledge(query, topic, category, limit)

    def get_context_for_task(self, task_description: str, limit: int = 5) -> str:
        """Return max 5 relevant items formatted as agent context (~500 tokens max)."""
        items = self.db.get_knowledge_for_task(task_description, limit=limit)
        if not items:
            return ""
        lines = ["## Known issues and patterns (from past sessions)\n"]
        token_estimate = 10
        for item in items:
            line = f"- [{item['category']}] {item['content']}"
            # Rough token estimate: ~1 token per 4 chars
            token_estimate += len(line) // 4
            if token_estimate > 500:
                break
            lines.append(line)
        return "\n".join(lines)

    def mark_helpful(self, item_id: int) -> None:
        self.db.mark_knowledge_helpful(item_id)

    def mark_unhelpful(self, item_id: int) -> None:
        self.db.mark_knowledge_unhelpful(item_id)

    def delete(self, item_id: int) -> None:
        self.db.delete_knowledge(item_id)

    def prune(
        self, max_items: int = 200, min_confidence: float = 0.2, max_age_days: int = 90
    ) -> int:
        return self.db.prune_knowledge(max_items, min_confidence, max_age_days)

    def count(self) -> int:
        return self.db.knowledge_count()

    def get_all(self) -> list[dict]:
        return self.db.get_all_knowledge()

    def import_from_claude_memory(self, project_path: str) -> int:
        """Read Claude Code auto-memory files and import relevant items."""
        from ..scanner.claude_code import read_auto_memory
        from ..scanner.project import get_project_hash

        project_hash = get_project_hash(project_path)
        memory_path = Path.home() / ".claude" / "projects" / project_hash / "memory"
        if not memory_path.exists():
            return 0

        items = read_auto_memory(str(memory_path))
        imported = 0
        for item in items:
            # Extract topic from content (first word or category)
            words = item.split()
            topic = words[0].lower().rstrip(":") if words else "general"
            result = self.add(
                category="imported",
                topic=topic,
                content=item[:200],  # Cap at 200 chars
                source="claude-memory",
                confidence=0.6,
            )
            if result:
                imported += 1
        return imported
