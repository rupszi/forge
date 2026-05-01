"""Episodic memory: raw history of every task execution."""

from __future__ import annotations

import uuid

from ..agents.classifier import select_executor
from ..db import ForgeDB
from ..models import EvaluatorResult, ExecutionResult, SprintContract


class EpisodicStore:
    def __init__(self, db: ForgeDB):
        self.db = db

    def store(
        self,
        session_id: str,
        sprint: SprintContract,
        gen_result: ExecutionResult,
        eval_result: EvaluatorResult | None = None,
    ) -> str:
        episode_id = f"ep-{uuid.uuid4().hex[:8]}"
        self.db.save_episode(
            episode_id=episode_id,
            session_id=session_id,
            sprint_id=sprint.id,
            task_description=sprint.description,
            model=sprint.assigned_model,
            # Use the same dispatch logic the scheduler uses, so the
            # agent_type recorded here matches reality across all model
            # families (anthropic full names, ollama models, vLLM via
            # OPENAI_BASE_URL, etc.). Previously this was a hardcoded
            # ``in ("opus", "sonnet")`` check that mislabeled haiku, all
            # full-name Claudes, qwen/devstral/deepseek/gpt-oss, and any
            # openai_compatible-routed model as "ollama".
            agent_type=select_executor(sprint.assigned_model),
            agent_role="generator",
            status="completed" if gen_result.success else "failed",
            result=gen_result.output[:5000] if gen_result.success else None,
            error=gen_result.error[:2000] if gen_result.error else None,
            evaluator_verdict=eval_result.verdict if eval_result else None,
            evaluator_feedback=eval_result.feedback if eval_result else None,
            revision_count=sprint.revision_count,
            tokens_in=gen_result.tokens_in + (eval_result.tokens_in if eval_result else 0),
            tokens_out=gen_result.tokens_out + (eval_result.tokens_out if eval_result else 0),
            cost_usd=gen_result.cost_usd + (eval_result.cost_usd if eval_result else 0),
            duration_seconds=gen_result.duration_seconds,
        )
        return episode_id

    def get_session_episodes(self, session_id: str) -> list[dict]:
        return self.db.get_episodes_for_session(session_id)

    def get_recent_failures(self, limit: int = 10) -> list[dict]:
        return self.db.get_recent_failures(limit)

    def get_failure_resolution_pairs(self, session_id: str) -> list[tuple[dict, dict]]:
        return self.db.get_failure_resolution_pairs(session_id)
