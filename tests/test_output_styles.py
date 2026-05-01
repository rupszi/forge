"""Output styles tests (Sprint 7.6).

Five built-in voices (default / terse / explanatory / strict-reviewer /
pr-bot) plus user-defined styles in .forge/output-styles/*.md that
shadow built-ins by name.
"""

from __future__ import annotations

from pathlib import Path

from daemon.output_styles import (
    BUILTIN_STYLES,
    discover_styles,
    get_style,
    parse_style_file,
    style_addendum,
)

# ---- built-ins ----


def test_builtin_set_matches_brief() -> None:
    expected = {"default", "terse", "explanatory", "strict-reviewer", "pr-bot"}
    assert expected.issubset(BUILTIN_STYLES.keys())


def test_default_style_has_empty_body() -> None:
    """Default = no addendum so the cacheable prefix is unchanged for
    the most common path."""
    assert BUILTIN_STYLES["default"].body == ""


def test_terse_addendum_mentions_style() -> None:
    assert "TERSE" in BUILTIN_STYLES["terse"].body


def test_explanatory_uses_why_marker() -> None:
    """The convention from the brief is 'WHY:' prefix for inline rationale."""
    assert "WHY:" in BUILTIN_STYLES["explanatory"].body


def test_pr_bot_lists_three_sections() -> None:
    body = BUILTIN_STYLES["pr-bot"].body
    assert "Summary" in body
    assert "Changes" in body
    assert "Test plan" in body


# ---- discover_styles ----


def test_discover_returns_builtins_when_no_user_dir(tmp_path: Path) -> None:
    out = discover_styles(tmp_path)
    assert "default" in out
    assert "terse" in out


def test_user_style_shadows_builtin(tmp_path: Path) -> None:
    """A user can replace ``default`` (or any builtin) by dropping a file."""
    user_dir = tmp_path / ".forge" / "output-styles"
    user_dir.mkdir(parents=True)
    (user_dir / "terse.md").write_text("CUSTOM TERSE")
    out = discover_styles(tmp_path)
    assert out["terse"].body == "CUSTOM TERSE"
    assert out["terse"].source == "user"


def test_user_style_with_frontmatter(tmp_path: Path) -> None:
    user_dir = tmp_path / ".forge" / "output-styles"
    user_dir.mkdir(parents=True)
    (user_dir / "fancy.md").write_text("""---
name: fancy
description: My personal voice
---

Output style: FANCY. Use exclamation marks!
""")
    out = discover_styles(tmp_path)
    assert "fancy" in out
    assert out["fancy"].description == "My personal voice"
    assert "FANCY" in out["fancy"].body


def test_discover_skips_unreadable(tmp_path: Path, caplog) -> None:
    import logging

    user_dir = tmp_path / ".forge" / "output-styles"
    user_dir.mkdir(parents=True)
    bad = user_dir / "bad.md"
    bad.write_text("ok")
    try:
        bad.chmod(0o000)
        with caplog.at_level(logging.WARNING, logger="daemon.output_styles"):
            out = discover_styles(tmp_path)
        # Built-ins remain
        assert "default" in out
    finally:
        bad.chmod(0o644)


# ---- get_style + style_addendum ----


def test_get_style_known_returns_entry(tmp_path: Path) -> None:
    style = get_style("terse", project_path=tmp_path)
    assert style.name == "terse"
    assert "TERSE" in style.body


def test_get_style_unknown_falls_back_to_default(tmp_path: Path, caplog) -> None:
    """A typo'd style name shouldn't crash; it should log + fall back."""
    import logging

    with caplog.at_level(logging.WARNING, logger="daemon.output_styles"):
        style = get_style("megamax", project_path=tmp_path)
    assert style.name == "default"
    assert any("unknown output style" in rec.message for rec in caplog.records)


def test_style_addendum_for_default_is_empty(tmp_path: Path) -> None:
    """Default = empty addendum = cacheable prefix unchanged."""
    assert style_addendum("default", project_path=tmp_path) == ""


def test_style_addendum_for_terse_is_nonempty(tmp_path: Path) -> None:
    text = style_addendum("terse", project_path=tmp_path)
    assert text != ""
    assert "TERSE" in text


# ---- parse_style_file direct ----


def test_parse_style_file_no_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    p.write_text("Just a body, no frontmatter.\n")
    style = parse_style_file(p)
    assert style.name == "x"
    assert "Just a body" in style.body
