"""Dataclasses: Task, Sprint, Session, ProjectContext, ExecutionResult, etc."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Sprint contracts ---


@dataclass
class SprintContract:
    id: str = field(default_factory=lambda: _uid("sprint-"))
    session_id: str = ""
    description: str = ""
    done_criteria: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    files_scope: list[str] = field(default_factory=list)
    assigned_model: str = "sonnet"
    assigned_worktree: str | None = None
    status: str = "pending"
    revision_count: int = 0
    error: str | None = None
    estimated_tokens: int = 0
    # Task 3.2: structured replacement for the legacy ``[critical]`` description
    # prefix. ``recovery.is_critical`` checks this field first and falls back
    # to the prefix scan for backwards-compat with hand-crafted prompts.
    critical: bool = False
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "description": self.description,
            "done_criteria": self.done_criteria,
            "depends_on": self.depends_on,
            "files_scope": self.files_scope,
            "assigned_model": self.assigned_model,
            "assigned_worktree": self.assigned_worktree,
            "status": self.status,
            "revision_count": self.revision_count,
            "error": self.error,
            "estimated_tokens": self.estimated_tokens,
            "critical": self.critical,
            "created_at": self.created_at,
        }


# --- Session ---


@dataclass
class Session:
    id: str = field(default_factory=lambda: _uid("session-"))
    project_path: str = ""
    objective: str = ""
    detected_stack: dict | None = None
    started_at: str = field(default_factory=_now)
    ended_at: str | None = None
    total_sprints: int = 0
    completed_sprints: int = 0
    failed_sprints: int = 0
    total_cost: float = 0.0
    knowledge_items_created: int = 0
    knowledge_items_applied: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_path": self.project_path,
            "objective": self.objective,
            "detected_stack": self.detected_stack,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "total_sprints": self.total_sprints,
            "completed_sprints": self.completed_sprints,
            "failed_sprints": self.failed_sprints,
            "total_cost": self.total_cost,
            "knowledge_items_created": self.knowledge_items_created,
            "knowledge_items_applied": self.knowledge_items_applied,
        }


# --- Execution result (returned by executors) ---


@dataclass
class ExecutionResult:
    success: bool
    output: str = ""
    error: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0


# --- Evaluator result ---


@dataclass
class CriterionResult:
    criterion: str
    passed: bool
    evidence: str = ""
    fix_needed: str = ""


@dataclass
class EvaluatorResult:
    verdict: str = "REVISE"  # APPROVED | REVISE
    criteria_results: list[CriterionResult] = field(default_factory=list)
    feedback: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


# --- Project context (from scanner) ---


@dataclass
class MCPServer:
    name: str = ""
    command: str | None = None
    args: list[str] = field(default_factory=list)


@dataclass
class ProjectContext:
    path: str = ""
    is_git: bool = False
    default_branch: str = "main"
    remote_url: str = ""
    language: str = ""
    framework: str = ""
    package_manager: str = ""
    has_claude: bool = False
    claude_md: str = ""
    mcp_servers: list[MCPServer] = field(default_factory=list)
    claude_rules: list[str] = field(default_factory=list)
    claude_auto_memory: list[str] = field(default_factory=list)
    # Sprint 7.4: AGENTS.md root-to-leaf chain. Each entry is
    # (relative_path, content) — the planner injects each as a separate
    # context block so the model attributes guidance to its origin dir.
    agents_md: list[tuple[str, str]] = field(default_factory=list)
    available_tools: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "is_git": self.is_git,
            "default_branch": self.default_branch,
            "remote_url": self.remote_url,
            "language": self.language,
            "framework": self.framework,
            "package_manager": self.package_manager,
            "has_claude": self.has_claude,
            "mcp_servers": [
                {"name": s.name, "command": s.command, "args": s.args} for s in self.mcp_servers
            ],
            "claude_rules_count": len(self.claude_rules),
            "auto_memory_count": len(self.claude_auto_memory),
            "agents_md_count": len(self.agents_md),
            "available_tools": self.available_tools,
        }


# --- Research result ---


@dataclass
class ResearchResult:
    content: str = ""
    url: str = ""
    title: str = ""
    relevance_score: float = 0.5


# --- Review perspective ---


@dataclass
class ReviewPerspective:
    name: str = ""  # security | performance | maintainability | correctness | architecture
    model: str = "sonnet"
    verdict: str = ""
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    overall_verdict: str = ""
    perspectives: list[ReviewPerspective] = field(default_factory=list)
    critical_issues: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
