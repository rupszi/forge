"""Tests for daemon/grammars.py — constrained-decoding payloads."""

from __future__ import annotations

import json

from daemon.grammars import (
    EVALUATOR_VERDICT_SCHEMA,
    GBNF_JSON_ARRAY,
    GBNF_JSON_OBJECT,
    SPRINT_CONTRACT_SCHEMA,
    evaluator_response_format,
    gbnf_for,
    ollama_format_for,
    planner_response_format,
)


def test_sprint_contract_schema_is_valid_json():
    """Round-trip: schema serializes to JSON and back without loss."""
    blob = json.dumps(SPRINT_CONTRACT_SCHEMA)
    assert json.loads(blob) == SPRINT_CONTRACT_SCHEMA


def test_sprint_contract_schema_requires_core_fields():
    item_schema = SPRINT_CONTRACT_SCHEMA["items"]
    required = item_schema["required"]
    assert "id" in required
    assert "description" in required
    assert "done_criteria" in required


def test_evaluator_verdict_schema_uses_enum():
    """The verdict field must be APPROVED or REVISE — enum enforces this."""
    assert EVALUATOR_VERDICT_SCHEMA["properties"]["verdict"]["enum"] == ["APPROVED", "REVISE"]


def test_planner_response_format_wraps_in_envelope():
    fmt = planner_response_format()
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "sprint_contracts"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == SPRINT_CONTRACT_SCHEMA


def test_evaluator_response_format_wraps_in_envelope():
    fmt = evaluator_response_format()
    assert fmt["json_schema"]["schema"] == EVALUATOR_VERDICT_SCHEMA


def test_ollama_format_unwraps_envelope():
    """Ollama wants the bare schema, not the OpenAI envelope."""
    envelope = planner_response_format()
    bare = ollama_format_for(envelope)
    assert bare == SPRINT_CONTRACT_SCHEMA


def test_ollama_format_passes_bare_schema_through():
    """If caller already passes a bare schema, return it unchanged."""
    bare = {"type": "object", "properties": {"x": {"type": "integer"}}}
    assert ollama_format_for(bare) == bare


def test_gbnf_for_array():
    grammar = gbnf_for("array")
    assert grammar == GBNF_JSON_ARRAY
    assert "root" in grammar
    assert '"["' in grammar


def test_gbnf_for_object():
    grammar = gbnf_for("object")
    assert grammar == GBNF_JSON_OBJECT
    assert '"{"' in grammar
