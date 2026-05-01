"""Procedural memory: which model works for which task pattern."""

from __future__ import annotations

from ..db import ForgeDB


class ProceduralStore:
    def __init__(self, db: ForgeDB):
        self.db = db

    def record(
        self, task_pattern: str, model: str, agent: str, success: bool, duration: float
    ) -> None:
        self.db.save_procedure(task_pattern, model, agent, success, duration)

    def get_recommendation(self, task_pattern: str) -> dict | None:
        return self.db.get_procedure(task_pattern)
