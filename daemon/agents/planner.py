"""Planner: decomposes objectives into sprint-sized tasks with done criteria."""

import json
import logging
import uuid

from ..executors import claude_code as claude_executor, ollama as ollama_executor
from ..models import ProjectContext, SprintContract

logger = logging.getLogger(__name__)

PLAN_SYSTEM_PROMPT = """You are a software project planner. Given an objective and project context,
decompose the work into sprint-sized tasks. Each sprint must have:
- A clear description
- Explicit "done criteria" that an evaluator can verify
- Dependencies on other sprints (if any)
- Recommended model (opus for complex, sonnet for medium, ollama for simple)

Respond with ONLY a JSON array. No markdown, no explanation. Example:
[
  {
    "id": "sprint-1",
    "description": "Create database schema",
    "done_criteria": ["Tables created", "Indexes added", "Migration tested"],
    "depends_on": [],
    "files_scope": ["db/migrations/"],
    "recommended_model": "sonnet",
    "estimated_tokens": 10000
  }
]"""


def _build_plan_prompt(objective: str, ctx: ProjectContext, kb_context: str = "") -> str:
    parts = [PLAN_SYSTEM_PROMPT]

    # Project context
    parts.append("\n## Project context")
    if ctx.framework:
        parts.append(f"Framework: {ctx.framework}")
    if ctx.language:
        parts.append(f"Language: {ctx.language}")
    if ctx.mcp_servers:
        parts.append(f"MCP servers: {', '.join(s.name for s in ctx.mcp_servers)}")
    if ctx.available_tools:
        active = [k for k, v in ctx.available_tools.items() if v]
        if active:
            parts.append(f"Available CLIs: {', '.join(active)}")

    if kb_context:
        parts.append(f"\n{kb_context}")

    parts.append(f"\n## Objective\n{objective}")
    parts.append("\nDecompose this into sprints. Respond with ONLY the JSON array.")
    return "\n".join(parts)


def _parse_plan(output: str, session_id: str) -> list[SprintContract]:
    """Parse JSON plan from LLM output. Fallback to single sprint on failure."""
    # Try to extract JSON array from output
    text = output.strip()
    # Find the JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start : end + 1]

    try:
        items = json.loads(text)
        if not isinstance(items, list):
            raise ValueError("Not a list")
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse plan JSON: %s", e)
        # Fallback: single sprint from the raw output
        return [
            SprintContract(
                session_id=session_id,
                description=output[:500],
                done_criteria=["Task completed as described"],
                assigned_model="sonnet",
            )
        ]

    sprints = []
    for item in items:
        sprint = SprintContract(
            id=item.get("id", f"sprint-{uuid.uuid4().hex[:4]}"),
            session_id=session_id,
            description=item.get("description", ""),
            done_criteria=item.get("done_criteria", ["Task completed"]),
            depends_on=item.get("depends_on", []),
            files_scope=item.get("files_scope", []),
            assigned_model=item.get("recommended_model", "sonnet"),
            estimated_tokens=item.get("estimated_tokens", 10000),
        )
        sprints.append(sprint)

    return (
        sprints
        if sprints
        else [
            SprintContract(
                session_id=session_id,
                description="Complete the objective",
                done_criteria=["Objective achieved"],
            )
        ]
    )


async def plan(
    objective: str,
    ctx: ProjectContext,
    session_id: str = "",
    kb_context: str = "",
    use_local: bool = True,
) -> list[SprintContract]:
    """Decompose objective into sprints. Uses Ollama (free) or Sonnet."""
    prompt = _build_plan_prompt(objective, ctx, kb_context)

    if use_local:
        result = await ollama_executor.execute(prompt)
    else:
        result = await claude_executor.execute(prompt, model="sonnet")

    if not result.success:
        logger.error("Planning failed: %s", result.error)
        return [
            SprintContract(
                session_id=session_id,
                description=objective,
                done_criteria=["Objective completed"],
                assigned_model="sonnet",
            )
        ]

    return _parse_plan(result.output, session_id)
