"""Tests for daemon/parsing.py — tolerant JSON recovery for messy LLM output.

This is layer 3 of Forge's tool-call defense (per ADR-003). The tests cover
each rung of the recovery ladder and a few real-world failure modes observed
when running open-weight models in the wild.
"""

from __future__ import annotations

from daemon.parsing import (
    extract_first_balanced,
    fix_smart_quotes,
    fix_trailing_commas,
    parse_json_lenient,
    strip_json_comments,
    strip_markdown_fences,
)

# ---- Happy path ----


def test_clean_json_array_passes_through():
    assert parse_json_lenient("[1, 2, 3]") == [1, 2, 3]


def test_clean_json_object_passes_through():
    assert parse_json_lenient('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_returns_none_on_total_garbage():
    assert parse_json_lenient("not json at all, no brackets here") is None


# ---- Markdown fence stripping ----


def test_strip_simple_json_fence():
    text = "```json\n[1, 2, 3]\n```"
    assert strip_markdown_fences(text) == "[1, 2, 3]"


def test_strip_unspecified_fence():
    text = "```\n[1, 2, 3]\n```"
    assert strip_markdown_fences(text) == "[1, 2, 3]"


def test_strip_picks_longest_fence():
    """When the response has both an example fence and the real payload,
    pick the longest."""
    text = """
```json
[]
```

Here is the real plan:

```json
[{"id": "sprint-1", "description": "do thing", "done_criteria": ["done"]}]
```
"""
    out = strip_markdown_fences(text)
    assert "sprint-1" in out
    assert out.startswith("[{")


def test_no_fence_returns_unchanged():
    text = "[1, 2, 3]"
    assert strip_markdown_fences(text) == text


def test_parse_handles_fenced_with_prelude():
    text = "Sure, here is the plan:\n\n```json\n[1, 2, 3]\n```\n\nLet me know!"
    assert parse_json_lenient(text) == [1, 2, 3]


# ---- Bracket extraction ----


def test_extract_balanced_array_simple():
    assert extract_first_balanced("[1, 2, 3]", opener="[", closer="]") == "[1, 2, 3]"


def test_extract_balanced_with_prose():
    text = "Here is the data: [1, 2, 3]\n\nAnd that's all."
    assert extract_first_balanced(text, opener="[", closer="]") == "[1, 2, 3]"


def test_extract_balanced_handles_nested():
    text = 'prelude {"a": [1, 2], "b": {"c": 3}} suffix'
    assert extract_first_balanced(text, opener="{", closer="}") == '{"a": [1, 2], "b": {"c": 3}}'


def test_extract_balanced_ignores_brackets_in_strings():
    """Braces inside JSON strings shouldn't confuse the depth counter."""
    text = '{"text": "this is { not a brace"}'
    assert extract_first_balanced(text, opener="{", closer="}") == text


def test_extract_balanced_returns_none_when_unbalanced():
    assert extract_first_balanced("[1, 2, 3", opener="[", closer="]") is None


def test_extract_balanced_handles_escaped_quote():
    text = '{"key": "value with \\"quote"}'
    out = extract_first_balanced(text, opener="{", closer="}")
    assert out == text


# ---- Common-case fixers ----


def test_fix_trailing_comma_array():
    assert fix_trailing_commas("[1, 2, 3,]") == "[1, 2, 3]"


def test_fix_trailing_comma_object():
    assert fix_trailing_commas('{"a": 1,}') == '{"a": 1}'


def test_fix_trailing_comma_nested():
    assert fix_trailing_commas('{"a": [1, 2,], "b": 3,}') == '{"a": [1, 2], "b": 3}'


def test_fix_smart_quotes_replaces_curly():
    assert fix_smart_quotes("“hello”") == '"hello"'


def test_strip_line_comments():
    assert strip_json_comments("// header\n[1, 2]\n") == "\n[1, 2]\n"


def test_strip_block_comments():
    assert strip_json_comments("[1, /* skip me */ 2]") == "[1,  2]"


# ---- Full ladder integration ----


def test_recover_array_with_trailing_comma_in_fence():
    text = """```json
[
  {"id": "sprint-1", "description": "x", "done_criteria": ["done"],},
]
```"""
    result = parse_json_lenient(text, schema_hint="array")
    assert result is not None
    assert len(result) == 1
    assert result[0]["id"] == "sprint-1"


def test_recover_object_with_smart_quotes():
    text = "Here it is: “{”“key”: 1”}”"
    # Smart quotes are pathological — this is a hard case. We expect the
    # parser to fail on this gracefully (return None), not crash.
    result = parse_json_lenient(text, schema_hint="object")
    # Either it parses or returns None — either is acceptable, just don't crash
    assert result is None or isinstance(result, dict)


def test_recover_with_prose_prefix():
    text = 'Sure, here is the plan: [{"id": "a", "description": "b", "done_criteria": ["c"]}]'
    result = parse_json_lenient(text, schema_hint="array")
    assert result is not None
    assert result[0]["id"] == "a"


def test_recover_with_javascript_comments():
    text = """[
      {"id": "1"}, // first sprint
      {"id": "2"}  /* second */
    ]"""
    result = parse_json_lenient(text, schema_hint="array")
    assert result is not None
    assert len(result) == 2


def test_schema_hint_array_skips_object_extraction():
    """When schema_hint=array, don't return the inner {...} from a string
    like 'thing {a:1} else'. We expect the array path not to find anything."""
    result = parse_json_lenient('thing {"a": 1} no array here', schema_hint="array")
    assert result is None


def test_schema_hint_any_tries_both():
    """schema_hint=any tries array first (no array exists), then object."""
    result = parse_json_lenient('prose {"a": 1}', schema_hint="any")
    assert result == {"a": 1}


# ---- BAML availability ----


def test_has_baml_returns_bool():
    from daemon.parsing import has_baml

    # Don't assert True/False — depends on whether baml-py is installed.
    # We just check it returns a bool without raising.
    assert isinstance(has_baml(), bool)


def test_parse_with_baml_falls_back_when_unavailable():
    """When BAML isn't installed, parse_with_baml falls back to lenient parse."""
    from daemon.parsing import parse_with_baml

    schema = {"type": "array"}
    result = parse_with_baml("[1, 2, 3]", schema)
    # Should at least not crash, and return the parsed array
    assert result == [1, 2, 3]
