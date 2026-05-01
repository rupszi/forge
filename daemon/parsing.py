r"""Tolerant parsing for messy open-weight model output.

Open-weight LLMs frequently produce JSON that's *almost* valid:

  - Wrapped in markdown fences: ``\`\`\`json\n[...]\n\`\`\```
  - Trailing commas: ``[1, 2, 3,]``
  - Single quotes instead of double: ``{'a': 1}``
  - Comments inside JSON: ``{"a": 1 /* comment */}``
  - Smart quotes from copy-paste: ``"a"`` (U+201C / U+201D)
  - Streaming truncation: ``[{"id": 1}, {"id":`` (incomplete)
  - Verbose preludes: ``Sure, here is the plan:\\n[...]``
  - Extra trailing text: ``[...]\\n\\nLet me know if...``

This module is the **layer-3 fallback** in Forge's three-layer tool-call
defense (per ADR-003):

  1. Native parser at the inference engine (vLLM ``--tool-call-parser``,
     llama.cpp templates) — handled by ``executors/openai_compatible.py`` and
     ``executors/ollama.py``.
  2. Constrained decoding via xgrammar / GBNF — see ``daemon/grammars.py``.
  3. **Tolerant client-side parsing — this file.** Last-resort recovery when
     layers 1 + 2 still produce something that ``json.loads`` won't accept.

The functions here are pure, side-effect-free, and have no soft dependencies
(BAML is optional via ``forge[robust]`` extra; if BAML isn't installed, these
helpers fall back to regex-based recovery and still produce useful results
on the common failure modes).

Usage in the planner:

    from daemon.parsing import parse_json_lenient

    raw = await llm_executor.execute(prompt, ...)
    sprints = parse_json_lenient(raw.output, schema_hint="array")
    if sprints is None:
        # Log + raise + fall back to single-sprint plan
        ...
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---- Markdown fence stripping ----

_FENCE_PATTERNS = [
    # ```json ... ``` (most common)
    re.compile(r"```(?:json|JSON|javascript|js|python|py)?\s*\n(.*?)\n?```", re.DOTALL),
    # ~~~ ... ~~~
    re.compile(r"~~~(?:json|JSON)?\s*\n(.*?)\n?~~~", re.DOTALL),
]


def strip_markdown_fences(text: str) -> str:
    """Pull JSON-or-code content out of markdown code fences.

    Returns the longest fenced block (most likely the actual payload) if any
    fences are present; otherwise returns the input unchanged.
    """
    candidates: list[str] = []
    for pattern in _FENCE_PATTERNS:
        candidates.extend(pattern.findall(text))
    if not candidates:
        return text
    # Pick the longest candidate — most likely the real payload, not a
    # short example fence elsewhere in the response.
    return max(candidates, key=len).strip()


# ---- Bracket-balanced extraction ----


def extract_first_balanced(text: str, *, opener: str, closer: str) -> str | None:
    """Find the first balanced ``opener``...``closer`` pair in ``text``.

    Used to extract a JSON object (``{...}``) or array (``[...]``) from a
    message that has prose before and/or after. Returns the substring
    including the brackets, or None if no balanced pair exists.

    Handles strings (so braces inside JSON strings don't confuse the count)
    and basic escape sequences.
    """
    depth = 0
    start = -1
    in_string = False
    escape = False

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opener:
            if depth == 0:
                start = i
            depth += 1
        elif ch == closer and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : i + 1]

    return None


# ---- Common-case fixers ----


_TRAILING_COMMA_PATTERN = re.compile(r",(\s*[}\]])")
_SMART_QUOTE_TRANSLATIONS = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)


def fix_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] — JSON spec disallows them but
    many models emit them out of habit."""
    return _TRAILING_COMMA_PATTERN.sub(r"\1", text)


def fix_smart_quotes(text: str) -> str:
    """Replace smart quotes (U+2018-U+201D) with plain ASCII quotes."""
    return text.translate(_SMART_QUOTE_TRANSLATIONS)


_COMMENT_PATTERN_LINE = re.compile(r"//[^\n]*\n")
_COMMENT_PATTERN_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_json_comments(text: str) -> str:
    """Remove // and /* ... */ comments. Not part of the JSON spec but
    common in LLM output."""
    text = _COMMENT_PATTERN_BLOCK.sub("", text)
    text = _COMMENT_PATTERN_LINE.sub("\n", text)
    return text


# ---- Top-level lenient parse ----


def parse_json_lenient(
    text: str,
    *,
    schema_hint: str = "any",
) -> Any | None:
    """Try increasingly aggressive recovery to turn ``text`` into a JSON value.

    Strategy ladder (each step is cheap; we stop at the first one that
    produces valid JSON):

      1. ``json.loads(text)`` — the happy path.
      2. Strip markdown fences, retry.
      3. Extract the first balanced ``[...]`` or ``{...}`` (per ``schema_hint``),
         retry.
      4. Apply common-case fixers (smart quotes, trailing commas, comments),
         retry.
      5. Return ``None``.

    ``schema_hint`` is one of:
      - ``"array"`` — caller expects a top-level JSON array
      - ``"object"`` — caller expects a top-level JSON object
      - ``"any"`` — caller doesn't care; tries array first, then object

    Why a ladder of fixers instead of one mega-regex: each step composes; if
    a future model emits some new edge case, we add one rung without breaking
    the others. Also, each step's result is debuggable in the logs.
    """
    # Step 1: happy path
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    # Step 2: strip markdown fences
    stripped = strip_markdown_fences(text)
    if stripped != text:
        try:
            return json.loads(stripped)
        except (ValueError, TypeError):
            pass

    # Step 3: bracket extraction
    candidates: list[str] = []
    if schema_hint in ("array", "any"):
        arr = extract_first_balanced(stripped, opener="[", closer="]")
        if arr:
            candidates.append(arr)
    if schema_hint in ("object", "any"):
        obj = extract_first_balanced(stripped, opener="{", closer="}")
        if obj:
            candidates.append(obj)

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            pass

    # Step 4: common-case fixers, applied to the best candidate (or full text)
    target = candidates[0] if candidates else stripped
    fixed = fix_smart_quotes(target)
    fixed = strip_json_comments(fixed)
    fixed = fix_trailing_commas(fixed)
    try:
        return json.loads(fixed)
    except (ValueError, TypeError) as e:
        logger.debug("parse_json_lenient: all recovery steps failed (%s)", e)
        return None


# ---- BAML integration (optional) ----
#
# BAML (https://github.com/boundaryml/baml) is the recommended layer-3 parser
# when installed. It does schema-aligned parsing — given a target schema, it
# repairs JSON to match. Forge ships BAML as an optional extra (``forge[robust]``)
# so users on the minimal install don't pull in Rust-compiled BAML deps.
#
# When BAML is available, callers can use ``parse_with_baml(text, schema)`` for
# stricter recovery. Falls back to ``parse_json_lenient`` if BAML isn't present.


def has_baml() -> bool:
    """Return True if BAML's Python bindings can be imported."""
    try:
        import baml_py  # noqa: F401

        return True
    except ImportError:
        return False


def parse_with_baml(text: str, schema: dict[str, Any]) -> Any | None:
    """Parse ``text`` using BAML's schema-aligned parser. Falls back to
    ``parse_json_lenient`` if BAML is not installed.

    The BAML integration is intentionally minimal — we use it only when the
    caller has a strict schema in hand (planner sprint contract, evaluator
    verdict). For looser parsing the regex-based ladder is enough.
    """
    if not has_baml():
        # Fall back to lenient parsing using a heuristic schema_hint
        if isinstance(schema, dict):
            hint = "array" if schema.get("type") == "array" else "object"
        else:
            hint = "any"
        return parse_json_lenient(text, schema_hint=hint)

    # NOTE: actual BAML wiring is left as a small follow-up — the public
    # baml-py API is small (parse_with_schema(text, schema)) but pinning the
    # exact API depends on the user's installed BAML version. This stub keeps
    # the rest of the codebase usable without BAML; when a user opts in via
    # forge[robust], we'll wire this through. See BUILD_PLAN.md Phase 1
    # Week 2 follow-up.
    logger.debug("parse_with_baml: BAML available but stub not yet wired; using lenient parser")
    return parse_json_lenient(text, schema_hint="any")
