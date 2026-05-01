"""Output styles — Sprint 7.6.

User-selectable per-agent voices. Each style is a Markdown file with
optional YAML frontmatter; the body is a system-prompt addendum that
shapes how the model writes.

Built-in starter set (compiled into the daemon, no disk required):

  default            — current behavior (no addendum)
  terse              — PR-bot voice; minimal prose, no preamble
  explanatory        — Inline rationale ("I'm doing X because Y") on
                       non-obvious decisions
  strict-reviewer    — evaluator persona; harshest grading
  pr-bot             — output formatted as a PR description (Summary /
                       Changes / Test plan)

User-defined styles live in ``.forge/output-styles/<name>.md`` and
shadow built-ins by the same name.

Selection happens at the SprintContract level (per-sprint override)
or at the session level via ``/output-style <name>``. The active style
flows into ``generator._build_prompt`` alongside the mode addendum.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .custom_commands import _parse_frontmatter

logger = logging.getLogger(__name__)


@dataclass
class OutputStyle:
    """A named system-prompt addendum that shapes the generator's voice."""

    name: str
    description: str
    body: str
    source: str = "builtin"  # "builtin" | "user"


# Built-in styles. Bodies kept short — the addendum sits in the
# cacheable prefix block, so terse text preserves cache hit rate.
BUILTIN_STYLES: dict[str, OutputStyle] = {
    "default": OutputStyle(
        name="default",
        description="Current behavior. No addendum.",
        body="",
    ),
    "terse": OutputStyle(
        name="terse",
        description="PR-bot voice — minimal prose, no preamble, no apologies.",
        body=(
            "Output style: TERSE. Skip preamble and recap. Skip 'I will…' "
            "and 'Let me…' framings. State results and decisions directly. "
            "When code is the answer, lead with the diff."
        ),
    ),
    "explanatory": OutputStyle(
        name="explanatory",
        description="Inline rationale on non-obvious decisions.",
        body=(
            "Output style: EXPLANATORY. When a decision is non-obvious "
            "(unusual library choice, performance trade-off, security-relevant "
            "design), add a one-line rationale prefixed with 'WHY:' on the "
            "next line. Skip rationale for routine work."
        ),
    ),
    "strict-reviewer": OutputStyle(
        name="strict-reviewer",
        description="Evaluator persona — harshest grading, finds the bugs others miss.",
        body=(
            "Output style: STRICT REVIEWER. You are reviewing this code "
            "against an evaluator that will fail it on any of: "
            "off-by-one errors, null/None handling, race conditions, "
            "secret leakage, error swallowing, missing edge cases. "
            "Before declaring done, list every assumption you made and "
            "every edge case you didn't test."
        ),
    ),
    "pr-bot": OutputStyle(
        name="pr-bot",
        description="Output formatted as a PR description (Summary / Changes / Test plan).",
        body=(
            "Output style: PR BOT. Structure final output as three sections: "
            "## Summary (1-3 bullets), ## Changes (file: what changed), "
            "## Test plan (checklist of TODOs to verify). "
            "Suitable for `gh pr create --body-file`."
        ),
    ),
}


def parse_style_file(path: Path) -> OutputStyle:
    """Read a user-defined style. Frontmatter optional."""
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    return OutputStyle(
        name=fm.get("name", path.stem),
        description=fm.get("description", ""),
        body=body.strip(),
        source="user",
    )


def discover_styles(project_path: Path) -> dict[str, OutputStyle]:
    """Build the resolution registry: built-ins + user overrides.

    User files at ``.forge/output-styles/<name>.md`` shadow built-ins
    of the same name. Files that fail to parse are logged and skipped
    so one bad file doesn't break the registry.
    """
    out: dict[str, OutputStyle] = dict(BUILTIN_STYLES)
    user_dir = project_path / ".forge" / "output-styles"
    if user_dir.is_dir():
        for md in sorted(user_dir.glob("*.md")):
            try:
                style = parse_style_file(md)
            except (OSError, ValueError) as e:
                logger.warning("output-style %s skipped: %s", md, e)
                continue
            out[style.name] = style
    return out


def get_style(name: str, project_path: Path | None = None) -> OutputStyle:
    """Resolve a style by name. Falls back to ``default`` for unknown names.

    Unknown styles surface as a WARNING in the log so a typo in a
    sprint contract or slash command doesn't silently no-op.
    """
    if project_path is None:
        project_path = Path.cwd()
    registry = discover_styles(project_path)
    if name in registry:
        return registry[name]
    logger.warning("unknown output style %r; falling back to 'default'", name)
    return registry["default"]


def style_addendum(name: str, project_path: Path | None = None) -> str:
    """Return the system-prompt addendum for a style. Empty for ``default``."""
    return get_style(name, project_path).body
