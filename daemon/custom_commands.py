"""Custom slash commands — Sprint 7.3.

Users define slash commands via Markdown files with YAML frontmatter.
Drop the file in ``.forge/commands/<name>.md`` and ``/<name>`` is
available immediately. The format is frontmatter-compatible with Claude
Code's so existing ``.claude/commands/*.md`` files work unchanged —
Forge falls back to that directory if the file isn't in ``.forge/``.

Example ``.forge/commands/deploy.md``:

    ---
    name: deploy
    description: Deploy current branch to staging
    argument-hint: [branch]
    model: claude-sonnet-4-7
    allowed-tools: [Bash, Read]
    ---

    Deploy $1 (or current branch if empty) to staging via Vercel.
    After deploy, verify the health endpoint at $2 (default: /health) returns 200.

The body becomes the planner objective. Placeholders ``$ARGUMENTS``,
``$1``..``$9``, and named ``$NAME=value`` substitute from the slash
command's argument string.

Frontmatter is OPTIONAL. A bare Markdown file with no ``---`` block
becomes a custom command whose name is the filename and whose body is
the entire content; no model override, no tool restriction. Useful for
quick one-line aliases.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CustomCommand:
    """A user-defined slash command parsed from a Markdown file."""

    name: str
    body: str
    description: str = ""
    argument_hint: str = ""
    model: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    source_path: Path | None = None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a Markdown file into frontmatter dict + body.

    Returns ``({}, text)`` when no YAML frontmatter is present (a bare
    Markdown file is still a valid custom command).
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if len(lines) < 2:
        return {}, text

    # Find the closing --- on its own line
    try:
        end_idx = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, text

    frontmatter_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")

    # Tiny YAML parser — handles the subset Claude Code's command files use:
    # bare keys, quoted/unquoted scalars, comma-separated lists in [brackets].
    # Avoids bringing in PyYAML for what's effectively `key: value` parsing.
    fm: dict = {}
    for raw in frontmatter_lines:
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip matching quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # Bracketed list
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            items = [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()]
            fm[key] = items
        elif value.lower() in ("true", "false"):
            fm[key] = value.lower() == "true"
        else:
            fm[key] = value
    return fm, body


def parse_command_file(path: Path) -> CustomCommand:
    """Read one .md file and return a CustomCommand. Raises on missing file."""
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    return CustomCommand(
        name=fm.get("name", path.stem),
        description=fm.get("description", ""),
        argument_hint=fm.get("argument-hint", ""),
        model=fm.get("model", ""),
        allowed_tools=list(fm.get("allowed-tools", [])),
        body=body,
        source_path=path,
    )


def discover_commands(project_path: Path) -> dict[str, CustomCommand]:
    """Walk ``.forge/commands/`` and (fallback) ``.claude/commands/``.

    A command name in ``.forge/`` shadows the same name in ``.claude/`` —
    Forge users who customize a command don't lose Claude Code as a
    fallback for the rest. Files that fail to parse are logged and
    skipped (one bad file shouldn't break the whole registry).
    """
    out: dict[str, CustomCommand] = {}

    # .claude first so .forge can override
    for root in (project_path / ".claude" / "commands", project_path / ".forge" / "commands"):
        if not root.is_dir():
            continue
        for md in sorted(root.glob("*.md")):
            try:
                cmd = parse_command_file(md)
            except (OSError, ValueError) as e:
                logger.warning("custom command %s skipped: %s", md, e)
                continue
            out[cmd.name] = cmd
    return out


_PLACEHOLDER_RE = re.compile(r"\$([A-Za-z_]\w*|[0-9]+|ARGUMENTS)")


def render(command: CustomCommand, args: str) -> str:
    """Substitute placeholders in ``command.body`` from the arg string.

    Recognized placeholders:
      ``$ARGUMENTS``  → the entire arg string verbatim
      ``$1``..``$9``  → space-separated positional from the arg string
      ``$NAME``       → bound from ``NAME=value`` segments at the front
                        of the arg string

    Unset placeholders are left intact so the model can see them in the
    prompt rather than a blank — surfaces user errors early.
    """
    args = args or ""
    # Pull leading NAME=value pairs off the front; the remainder is the
    # positional + ARGUMENTS source.
    named: dict[str, str] = {}
    tokens = args.split()
    positional_start = 0
    for i, tok in enumerate(tokens):
        if "=" in tok and tok[0].isalpha():
            key, _, val = tok.partition("=")
            named[key] = val
            positional_start = i + 1
        else:
            break
    positional = tokens[positional_start:]
    arguments_str = " ".join(positional)

    def _sub(match: re.Match[str]) -> str:
        placeholder = match.group(1)
        if placeholder == "ARGUMENTS":
            return arguments_str
        if placeholder.isdigit():
            idx = int(placeholder) - 1
            if 0 <= idx < len(positional):
                return positional[idx]
            return match.group(0)
        if placeholder in named:
            return named[placeholder]
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_sub, command.body)
