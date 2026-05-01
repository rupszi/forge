"""Post-session insight extraction. Learns from failures, successes, and research."""

from __future__ import annotations

import logging

from ..db import ForgeDB
from ..executors import ollama as ollama_executor
from ..memory.knowledge import KnowledgeBase
from ..memory.procedural import ProceduralStore

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = (
    "Extract ONE imperative sentence from this failure and resolution. "
    "The sentence should be a reusable gotcha or tip for future work. "
    "If too generic or not useful, respond with SKIP.\n\n"
    "Failure: {error}\n"
    "Resolution: {resolution}\n\n"
    "One imperative sentence:"
)


class Learner:
    def __init__(self, db: ForgeDB):
        self.db = db
        self.kb = KnowledgeBase(db)
        self.procedures = ProceduralStore(db)

    async def learn_from_session(self, session_id: str) -> dict:
        """Post-session extraction. Returns summary of what was learned."""
        stats = {
            "gotchas_learned": 0,
            "patterns_updated": 0,
            "research_insights": 0,
        }

        # 1. Learn from failure+resolution pairs
        pairs = self.db.get_failure_resolution_pairs(session_id)
        for failed, resolved in pairs:
            gotcha = await self._extract_gotcha(
                failed.get("error", ""),
                resolved.get("result", ""),
            )
            if gotcha:
                # Extract topic from description
                desc = failed.get("task_description", "")
                topic = self._extract_topic(desc)
                self.kb.add(
                    category="gotcha",
                    topic=topic,
                    content=gotcha,
                    source=f"learned:{session_id}",
                    confidence=0.7,
                )
                stats["gotchas_learned"] += 1

        # 2. Update routing patterns from all episodes
        episodes = self.db.get_episodes_for_session(session_id)
        for ep in episodes:
            if ep.get("agent_role") == "generator":
                success = ep["status"] == "completed"
                self.procedures.record(
                    task_pattern=ep["task_description"][:100],
                    model=ep["model"],
                    agent=ep["agent_type"],
                    success=success,
                    duration=ep.get("duration_seconds") or 0.0,
                )
                stats["patterns_updated"] += 1

        # 3. Confidence reinforcement
        # (In a full implementation, we'd track which KB items were injected per sprint)

        # 4. Prune KB
        self.kb.prune()

        return stats

    async def _extract_gotcha(self, error: str, resolution: str) -> str | None:
        """Use local LLM to distill a one-line gotcha from failure+resolution."""
        if not error or not resolution:
            return None

        prompt = EXTRACT_PROMPT.format(
            error=error[:500],
            resolution=resolution[:500],
        )
        result = await ollama_executor.execute(prompt)
        if result.success:
            text = result.output.strip()
            if text.upper() == "SKIP" or len(text) < 10 or len(text) > 200:
                return None
            return text
        return None

    def _extract_topic(self, description: str) -> str:
        """Extract a topic keyword from a task description."""
        keywords = {
            "supabase": "supabase",
            "vercel": "vercel",
            "next": "next.js",
            "react": "react",
            "auth": "auth",
            "database": "database",
            "api": "api",
            "test": "testing",
            "deploy": "deployment",
            "style": "css",
            "tailwind": "css",
            "typescript": "typescript",
            "migration": "database",
            "rls": "supabase",
            "stripe": "stripe",
            "email": "email",
            "upload": "storage",
            "image": "media",
        }
        desc_lower = description.lower()
        for keyword, topic in keywords.items():
            if keyword in desc_lower:
                return topic
        return "general"

    def learn_sync(self, session_id: str) -> dict:
        """Synchronous version — updates patterns only (no LLM)."""
        stats = {"patterns_updated": 0}
        episodes = self.db.get_episodes_for_session(session_id)
        for ep in episodes:
            if ep.get("agent_role") == "generator":
                success = ep["status"] == "completed"
                self.procedures.record(
                    task_pattern=ep["task_description"][:100],
                    model=ep["model"],
                    agent=ep["agent_type"],
                    success=success,
                    duration=ep.get("duration_seconds") or 0.0,
                )
                stats["patterns_updated"] += 1
        self.kb.prune()
        return stats
