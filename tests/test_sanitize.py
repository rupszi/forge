"""Unicode / bidi-override sanitizer tests (Sprint 9 / Layer 5).

Pillar Security 2025 documented a class of prompt-injection attacks
that hide instructions in repo files using bidi-override controls
(U+202E and friends) and zero-width characters. These tests verify
the sanitizer catches every documented attack vector while leaving
legitimate text intact.
"""

from __future__ import annotations

from daemon.sanitize import (
    has_bidi_or_invisible,
    sanitize,
    sanitize_strict,
)

# ---- has_bidi_or_invisible ----


def test_clean_ascii_is_safe() -> None:
    assert has_bidi_or_invisible("Hello, world.") is False


def test_clean_unicode_is_safe() -> None:
    """Legitimate non-ASCII (en-dash, smart quote, accented letter) is fine."""
    assert has_bidi_or_invisible("café — résumé") is False


def test_bidi_override_detected() -> None:
    """U+202E RIGHT-TO-LEFT OVERRIDE is the headline attack vector."""
    assert has_bidi_or_invisible("hello‮world") is True


def test_zwsp_detected() -> None:
    """U+200B ZERO-WIDTH SPACE is the second-most-common vector."""
    assert has_bidi_or_invisible("hel​lo") is True


def test_bidi_isolate_detected() -> None:
    """U+2066..U+2069 (LRI/RLI/FSI/PDI) are bidi-override's modern cousins."""
    assert has_bidi_or_invisible("⁦malicious⁩") is True


def test_tag_character_detected() -> None:
    """U+E0000..U+E007F SmartTag attack — invisible payload riding on
    legitimate-looking text."""
    assert has_bidi_or_invisible("hello\U000e0041world") is True


def test_bom_detected() -> None:
    assert has_bidi_or_invisible("﻿hello") is True


def test_variation_selector_detected() -> None:
    assert has_bidi_or_invisible("a️b") is True


# ---- sanitize ----


def test_sanitize_clean_input_unchanged() -> None:
    """Safe input should return verbatim — no allocation, no marker."""
    assert sanitize("hello") == "hello"
    assert sanitize("café") == "café"
    assert sanitize("") == ""


def test_sanitize_replaces_bidi_override() -> None:
    out = sanitize("hello‮world")
    assert "‮" not in out
    assert "\\u{202E}" in out


def test_sanitize_replaces_zwsp() -> None:
    out = sanitize("a​b​c")
    assert "​" not in out
    assert out.count("\\u{200B}") == 2


def test_sanitize_idempotent() -> None:
    """sanitize(sanitize(x)) == sanitize(x)."""
    text = "begin‮end"
    once = sanitize(text)
    twice = sanitize(once)
    assert once == twice


def test_sanitize_real_world_attack_payload() -> None:
    """The Pillar Security PoC shape: an instruction that looks benign
    but reverses meaning when the bidi override is honored."""
    # The classic: "Run ‮POLP‬ check" rendered as "Run check POLP"
    payload = "Run ‮patch‬ verification"
    out = sanitize(payload)
    # Both controls stripped to evidence markers
    assert "‮" not in out
    assert "‬" not in out
    assert "\\u{202E}" in out
    # Visible characters preserved verbatim
    assert "patch" in out
    assert "verification" in out


def test_sanitize_preserves_legitimate_unicode() -> None:
    """Accents, dashes, smart quotes, emoji — none are dangerous."""
    text = "café — “résumé” 😀"
    assert sanitize(text) == text


# ---- sanitize_strict ----


def test_sanitize_strict_removes_control_chars() -> None:
    """Strict mode strips U+0000..U+001F except tab/newline/cr."""
    assert sanitize_strict("hello\x07world") == "helloworld"
    # Whitespace controls preserved
    assert sanitize_strict("a\tb\nc\rd") == "a\tb\nc\rd"


def test_sanitize_strict_also_strips_bidi() -> None:
    """Strict is sanitize + control chars — bidi still goes via the marker."""
    out = sanitize_strict("a‮b\x07c")
    assert "‮" not in out  # bidi → marker
    assert "\x07" not in out  # control char → stripped entirely
    assert "\\u{202E}" in out


def test_sanitize_strict_clean_input_unchanged() -> None:
    assert sanitize_strict("ascii only") == "ascii only"


# ---- Performance characterization (smoke test) ----


def test_sanitize_handles_long_clean_input_efficiently() -> None:
    """A 100KB clean string should pass through fast — no per-char work."""
    text = "x" * 100_000
    assert sanitize(text) == text


def test_sanitize_long_input_with_payload() -> None:
    """A long input with a single payload still scrubs correctly."""
    text = "x" * 50_000 + "‮" + "y" * 50_000
    out = sanitize(text)
    assert "‮" not in out
    assert "\\u{202E}" in out
    # Original: 50000 + 1 (bidi) + 50000 = 100001 chars
    # Output:   50000 + 8 (marker) + 50000 = 100008 chars
    assert len(out) == 100_000 + len("\\u{202E}")
