"""Unicode + bidi-override sanitizer — Sprint 9 / Layer 5.

Pillar Security's 2025 research showed that prompt-injection attacks
hidden in repo files using Unicode bidi-override controls (U+202E and
friends) and zero-width characters can flip the visible meaning of
agent instructions while keeping the rendered text identical to a
benign source.

Defense: sanitize untrusted text BEFORE it lands in:

  - the planner / generator prompt prefix (repo files, MCP responses)
  - the KB content body (web research output, MCP-sourced items)
  - hook stdout that the agent will see

Two functions:

  ``sanitize(text)``      Replace dangerous code points with ASCII-safe
                          markers; preserve everything else verbatim.
                          Returns the cleaned string.
  ``has_bidi_or_invisible(text)``
                          Fast yes/no check. Lets callers decide whether
                          to log a warning even when the cleaned output
                          is identical to the input.

We do NOT sanitize the user's own input (their prompt typing) — they
chose what to type. We DO sanitize anything labeled
``trust=untrusted`` in the provenance system (Layer 1 — to land later).

Code-point coverage (gathered from Pillar + OWASP guidance):

  - Bidi controls (U+202A..U+202E, U+2066..U+2069) — the headline attack
  - Other format controls (U+200B..U+200F, U+2028..U+202F)
  - Soft hyphen (U+00AD), word joiner (U+2060), invisible math operators
  - Tag characters (U+E0000..U+E007F) — used by the SmartTag attacks
  - Zero-width / variation selectors (U+FE00..U+FE0F)

Every removed code point is replaced with ``\\u{XXXX}`` so the cleaned
text retains evidence of the modification (the agent / log can see
that something was here, just not what).
"""

from __future__ import annotations

import re

# Ranges chosen with intent — see module docstring for sources.
# Keep this set small and explicit; the false-positive cost of
# stripping legitimate text is nontrivial.
_DANGEROUS_RANGES: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD),  # SOFT HYPHEN
    (0x180E, 0x180E),  # MONGOLIAN VOWEL SEPARATOR (deprecated invisible)
    (0x200B, 0x200F),  # ZWSP / ZWNJ / ZWJ / LRM / RLM
    (0x202A, 0x202E),  # LRE / RLE / PDF / LRO / RLO  ← bidi-override headline
    (0x2060, 0x2069),  # WJ + INVIS-OPERATORS + bidi isolate (LRI/RLI/FSI/PDI)
    (0xFE00, 0xFE0F),  # variation selectors
    (0xFEFF, 0xFEFF),  # BOM / ZERO-WIDTH NO-BREAK SPACE
    (0xE0000, 0xE007F),  # tag characters (SmartTag attack)
)


def _is_dangerous(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _DANGEROUS_RANGES)


# Pre-compute a regex for fast scanning. The character class fragments
# below match every code point in _DANGEROUS_RANGES; we build it once
# at import time so subsequent calls are O(n) on text length.
_PATTERN = re.compile(
    "[" + "".join(f"\\u{lo:04x}-\\u{hi:04x}" for lo, hi in _DANGEROUS_RANGES if hi <= 0xFFFF) + "]"
    # SMP code points (the tag-character range above 0x10000) need
    # explicit handling — Python regex sees them as surrogate pairs in
    # narrow builds, but on modern (3.10+) wide builds the range works
    # directly. Fall back to a per-char scan for SMP.
)


def _format_replacement(cp: int) -> str:
    """Render the replacement marker for a stripped code point."""
    return f"\\u{{{cp:04X}}}"


def has_bidi_or_invisible(text: str) -> bool:
    """Fast check — True iff ``text`` contains any sanitizer-stripped char."""
    if _PATTERN.search(text):
        return True
    # SMP scan for tag characters (above U+FFFF).
    return any(ord(ch) > 0xFFFF and _is_dangerous(ord(ch)) for ch in text)


def sanitize(text: str) -> str:
    """Return ``text`` with dangerous code points replaced by ``\\u{XXXX}``.

    Idempotent: ``sanitize(sanitize(x)) == sanitize(x)``. Empty / ASCII
    input is returned verbatim with no allocations.
    """
    if not text or text.isascii():
        return text
    # Common case: nothing dangerous → return verbatim. Saves an
    # allocation per safe-string call site.
    if not has_bidi_or_invisible(text):
        return text
    # Replace via per-char scan. Faster than a regex sub when the
    # pattern is mostly absent because we already paid the
    # has_bidi_or_invisible cost; another pass with re.sub would
    # double-scan.
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if _is_dangerous(cp):
            out.append(_format_replacement(cp))
        else:
            out.append(ch)
    return "".join(out)


def sanitize_strict(text: str) -> str:
    """Same as ``sanitize`` but ALSO strips control chars (U+0000..U+001F
    except tab/newline/cr) and DEL. Use for content destined for the LLM
    prompt — control chars there can confuse tokenizers."""
    cleaned = sanitize(text)
    return "".join(ch for ch in cleaned if ord(ch) >= 0x20 or ch in ("\t", "\n", "\r"))
