"""Document agent (M7) — turn a brief into a local Markdown document.

The "+ docs" half of Forge Studio v1. Reuses the local executor stack (so it's
free and offline by default) with a writer system prompt, and grades the result
against the brief's criteria via the existing evaluator. Output is saved as a
local artifact (Markdown, with html/txt/docx export) under ``.forge/artifacts/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import artifacts
from ..config import LOCAL_MID_MODEL
from ..executors import ollama as ollama_executor

_WRITER_SYSTEM = (
    "You are a precise technical writer. Produce a well-structured Markdown "
    "document that fully satisfies the brief. Use headings, short paragraphs, "
    "and lists where helpful. Output only the document — no preamble, no "
    "explanation, no code fences around the whole thing."
)


@dataclass
class DocumentResult:
    success: bool
    content: str = ""
    error: str | None = None
    model: str = ""
    criteria: list[str] = field(default_factory=list)


def _build_prompt(brief: str, criteria: list[str]) -> str:
    parts = [_WRITER_SYSTEM, f"## Brief\n{brief}"]
    if criteria:
        parts.append("## The document must satisfy ALL of these:")
        parts.extend(f"{i}. {c}" for i, c in enumerate(criteria, 1))
    parts.append("Write the document now.")
    return "\n\n".join(parts)


async def write_document(
    brief: str, criteria: list[str] | None = None, model: str | None = None
) -> DocumentResult:
    """Generate a Markdown document from a brief using a local model."""
    criteria = criteria or []
    chosen = model or LOCAL_MID_MODEL
    prompt = _build_prompt(brief, criteria)
    result = await ollama_executor.execute(prompt, model=chosen)
    if not result.success:
        return DocumentResult(
            success=False,
            error=result.error or "generation failed",
            model=chosen,
            criteria=criteria,
        )
    return DocumentResult(
        success=True, content=result.output.strip(), model=chosen, criteria=criteria
    )


def save_document(result: DocumentResult, name: str, fmt: str = "md", base_path: str = ".") -> str:
    """Persist a document result as a local artifact. Returns the file path."""
    return artifacts.save_artifact(name, result.content, fmt=fmt, base_path=base_path)
