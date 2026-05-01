"""Custom slash command tests (Sprint 7.3).

Users drop ``<name>.md`` files in ``.forge/commands/`` (or
``.claude/commands/`` as a fallback) and ``/<name>`` becomes a working
slash command. Frontmatter is optional; the body becomes the planner
objective with placeholder substitution.
"""

from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path

import pytest

from daemon.budget import BudgetController
from daemon.custom_commands import (
    CustomCommand,
    _parse_frontmatter,
    discover_commands,
    parse_command_file,
    render,
)
from daemon.db import ForgeDB
from daemon.memory.knowledge import KnowledgeBase
from daemon.mode import ModeState
from daemon.slash import SlashContext, dispatch_slash

# ---- frontmatter parsing ----


def test_no_frontmatter_returns_empty_dict_and_full_body() -> None:
    fm, body = _parse_frontmatter("Just a body, no frontmatter\n")
    assert fm == {}
    assert body == "Just a body, no frontmatter\n"


def test_frontmatter_round_trip() -> None:
    text = """---
name: deploy
description: Deploy to staging
argument-hint: [branch]
model: claude-sonnet-4-7
allowed-tools: [Bash, Read]
---

Deploy $1 to staging.
"""
    fm, body = _parse_frontmatter(text)
    assert fm["name"] == "deploy"
    assert fm["description"] == "Deploy to staging"
    # Bracketed values parse as lists (matches YAML semantics + Claude Code behavior)
    assert fm["argument-hint"] == ["branch"]
    assert fm["model"] == "claude-sonnet-4-7"
    assert fm["allowed-tools"] == ["Bash", "Read"]
    assert "Deploy $1 to staging." in body


def test_frontmatter_unterminated_treated_as_body() -> None:
    """No closing --- means the file is body-only — graceful fallback."""
    text = "---\nname: weird\nNo closing fence here\n"
    fm, body = _parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_frontmatter_quoted_strings_unwrapped() -> None:
    text = """---
description: "with: a colon"
name: "x"
---

body
"""
    fm, _ = _parse_frontmatter(text)
    assert fm["description"] == "with: a colon"
    assert fm["name"] == "x"


def test_frontmatter_comments_ignored() -> None:
    text = """---
# this is a comment
name: cmd
---

body
"""
    fm, _ = _parse_frontmatter(text)
    assert fm == {"name": "cmd"}


# ---- parse_command_file ----


def test_parse_command_file_with_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "deploy.md"
    p.write_text("""---
name: deploy
model: sonnet
allowed-tools: [Bash]
---

Deploy $1
""")
    cmd = parse_command_file(p)
    assert cmd.name == "deploy"
    assert cmd.model == "sonnet"
    assert cmd.allowed_tools == ["Bash"]
    assert "Deploy $1" in cmd.body
    assert cmd.source_path == p


def test_parse_command_file_no_frontmatter_uses_filename(tmp_path: Path) -> None:
    p = tmp_path / "ship.md"
    p.write_text("Run the deploy script.\n")
    cmd = parse_command_file(p)
    assert cmd.name == "ship"
    assert cmd.body.strip() == "Run the deploy script."
    assert cmd.allowed_tools == []
    assert cmd.model == ""


def test_parse_command_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        parse_command_file(tmp_path / "nope.md")


# ---- discover_commands ----


def test_discover_finds_forge_commands(tmp_path: Path) -> None:
    forge_cmds = tmp_path / ".forge" / "commands"
    forge_cmds.mkdir(parents=True)
    (forge_cmds / "deploy.md").write_text("Deploy now")
    (forge_cmds / "audit.md").write_text("Run audit")

    out = discover_commands(tmp_path)
    assert set(out.keys()) == {"deploy", "audit"}


def test_discover_falls_back_to_claude_commands(tmp_path: Path) -> None:
    """Users with existing .claude/commands/*.md get them for free."""
    claude_cmds = tmp_path / ".claude" / "commands"
    claude_cmds.mkdir(parents=True)
    (claude_cmds / "test.md").write_text("Run tests")

    out = discover_commands(tmp_path)
    assert "test" in out
    assert "Run tests" in out["test"].body


def test_discover_forge_overrides_claude(tmp_path: Path) -> None:
    """When a name exists in both, .forge/ wins — the user customized it."""
    claude_cmds = tmp_path / ".claude" / "commands"
    claude_cmds.mkdir(parents=True)
    (claude_cmds / "deploy.md").write_text("CLAUDE_VERSION")

    forge_cmds = tmp_path / ".forge" / "commands"
    forge_cmds.mkdir(parents=True)
    (forge_cmds / "deploy.md").write_text("FORGE_VERSION")

    out = discover_commands(tmp_path)
    assert "FORGE_VERSION" in out["deploy"].body
    assert "CLAUDE_VERSION" not in out["deploy"].body


def test_discover_skips_malformed(tmp_path: Path, caplog) -> None:
    """One bad file doesn't break the others."""
    import logging

    forge_cmds = tmp_path / ".forge" / "commands"
    forge_cmds.mkdir(parents=True)
    (forge_cmds / "good.md").write_text("ok")
    (forge_cmds / "bad.md").write_text("ok")
    # Make 'bad.md' unreadable. (Skip on Windows-style filesystems where chmod
    # doesn't apply.)
    try:
        (forge_cmds / "bad.md").chmod(0o000)
        with caplog.at_level(logging.WARNING, logger="daemon.custom_commands"):
            out = discover_commands(tmp_path)
        assert "good" in out
    finally:
        (forge_cmds / "bad.md").chmod(0o644)


# ---- placeholder rendering ----


def test_render_arguments_placeholder() -> None:
    cmd = CustomCommand(name="x", body="Run with $ARGUMENTS")
    assert render(cmd, "alpha beta") == "Run with alpha beta"


def test_render_positional_placeholders() -> None:
    cmd = CustomCommand(name="x", body="$1 then $2")
    assert render(cmd, "first second third") == "first then second"


def test_render_positional_left_intact_when_unset() -> None:
    cmd = CustomCommand(name="x", body="$1 and $2")
    assert render(cmd, "only-first") == "only-first and $2"


def test_render_named_placeholders() -> None:
    cmd = CustomCommand(name="x", body="Hello $NAME!")
    assert render(cmd, "NAME=Pal") == "Hello Pal!"


def test_render_named_then_positional() -> None:
    """NAME=value at the front, then positional follow."""
    cmd = CustomCommand(name="x", body="$ENV deploy $1")
    assert render(cmd, "ENV=staging branch-x") == "staging deploy branch-x"


def test_render_unknown_placeholder_left_intact() -> None:
    cmd = CustomCommand(name="x", body="$NOPE")
    assert render(cmd, "") == "$NOPE"


# ---- end-to-end through the slash dispatcher ----


@pytest.fixture
def ctx(tmp_path: Path) -> SlashContext:
    db = ForgeDB(str(tmp_path / "forge.db"))
    return SlashContext(
        db=db,
        budget=BudgetController(),
        mode_state=ModeState(),
        kb=KnowledgeBase(db),
    )


@pytest.mark.asyncio
async def test_slash_dispatcher_finds_custom_command(
    tmp_path: Path, ctx: SlashContext, monkeypatch
) -> None:
    """A ``/<custom>`` command from .forge/commands/ is reachable through
    the same dispatch_slash entry point as built-in commands."""
    monkeypatch.chdir(tmp_path)
    forge_cmds = tmp_path / ".forge" / "commands"
    forge_cmds.mkdir(parents=True)
    (forge_cmds / "ship.md").write_text("""---
name: ship
model: sonnet
---

Deploy $1 to production.
""")

    result = await dispatch_slash("slash.ship", "v1.2.3", ctx)
    assert result is not None
    assert result["type"] == "custom_command"
    assert result["name"] == "ship"
    assert result["model"] == "sonnet"
    assert "Deploy v1.2.3 to production." in result["objective"]


@pytest.mark.asyncio
async def test_slash_built_in_takes_precedence_over_custom(
    tmp_path: Path, ctx: SlashContext, monkeypatch
) -> None:
    """A user can't override the built-in ``/help`` by dropping
    ``.forge/commands/help.md`` — built-ins are first in resolution."""
    monkeypatch.chdir(tmp_path)
    forge_cmds = tmp_path / ".forge" / "commands"
    forge_cmds.mkdir(parents=True)
    (forge_cmds / "help.md").write_text("FAKE HELP")

    result = await dispatch_slash("slash.help", "", ctx)
    assert result["type"] == "slash_help"
    assert "FAKE HELP" not in result["text"]


@pytest.mark.asyncio
async def test_slash_unknown_after_custom_check(
    tmp_path: Path, ctx: SlashContext, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = await dispatch_slash("slash.does-not-exist", "", ctx)
    assert result["type"] == "error"
    assert "unknown slash command" in result["error"]


_ = (Namespace, os)  # silence unused-import warnings if trim removed sites
