"""Constrained-decoding helpers — grammar emission for tool-call boundaries.

Forge calls open-weight LLMs at two boundaries where invalid JSON is fatal:

  1. **Planner sprint-contract output** — the planner emits an array of sprint
     dicts that the scheduler parses; if the JSON is malformed the entire
     plan-and-execute cycle aborts.
  2. **Evaluator verdict** — the evaluator's structured PASS/FAIL output is
     parsed into a verdict; malformed output silently misclassifies.

For both, we want the inference engine to **enforce** valid JSON at the token
level rather than rely on tolerant client-side parsing alone (which is layer 3
in ADR-003's three-layer defense). This module builds the grammar payloads
each inference engine accepts:

  - **vLLM** / **SGLang**: pass a JSON schema dict via ``response_format``;
    the server uses xgrammar (default in vLLM and SGLang since late 2024) to
    constrain decoding. Near-zero overhead per the xgrammar paper.
  - **Ollama / llama.cpp**: pass a GBNF (GGML BNF) grammar string via the
    ``format`` field. llama.cpp has had GBNF support since early 2024;
    Ollama exposes it via ``format`` accepting either ``"json"`` (legacy
    universal-JSON mode) or a JSON schema dict (Ollama 0.5+).

We provide both shapes so the calling code can pick based on which executor
it's dispatching through. Callers usually invoke the convenience wrappers:

    ``planner_response_format()`` → for the planner's sprint-contract output
    ``evaluator_response_format()`` → for the evaluator's per-criterion verdict

Both return a dict suitable for ``response_format=`` (OpenAI-compatible) or
``format=`` (Ollama). The receiving executor knows what to do.
"""

from __future__ import annotations

from typing import Any

# ---- Schemas (the source of truth) ----
#
# These schemas are deliberately *conservative*: they describe the minimum
# fields the parser needs, not a fully strict spec. Looser schemas let the
# model add extra commentary fields without violating constraints (which we
# then ignore on the client side). This trades a bit of strictness for a
# lower failure rate on edge-case open-weight emissions.

SPRINT_CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["id", "description", "done_criteria"],
        "properties": {
            "id": {"type": "string"},
            "description": {"type": "string"},
            "done_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "depends_on": {"type": "array", "items": {"type": "string"}},
            "files_scope": {"type": "array", "items": {"type": "string"}},
            "recommended_model": {"type": "string"},
            "estimated_tokens": {"type": "integer"},
        },
    },
}


EVALUATOR_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict", "criteria"],
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVED", "REVISE"]},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["criterion", "passed"],
                "properties": {
                    "criterion": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "evidence": {"type": "string"},
                    "fix_needed": {"type": "string"},
                },
            },
        },
        "feedback": {"type": "string"},
    },
}


# ---- response_format builders ----


def planner_response_format() -> dict[str, Any]:
    """Build the ``response_format`` payload for the planner's output.

    Compatible with both:
      - OpenAI-format APIs (``response_format=`` on Chat Completions): wraps
        in the ``json_schema`` envelope.
      - Ollama (``format=``): the bare schema is fine on Ollama 0.5+.

    Callers pass the result to whichever executor they're using. Each
    executor knows whether to pass-through or unwrap.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "sprint_contracts",
            "schema": SPRINT_CONTRACT_SCHEMA,
            "strict": True,
        },
    }


def evaluator_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "evaluator_verdict",
            "schema": EVALUATOR_VERDICT_SCHEMA,
            "strict": True,
        },
    }


def ollama_format_for(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAI-style response_format envelope (or a bare schema)
    into Ollama's ``format`` field shape.

    Ollama wants the bare JSON schema, not the ``{"type": "json_schema",
    "json_schema": {...}}`` envelope OpenAI uses. This helper normalizes.
    """
    # Already a bare schema?
    if "type" in schema and schema["type"] in (
        "object",
        "array",
        "string",
        "number",
        "integer",
        "boolean",
    ):
        return schema
    # OpenAI envelope?
    if schema.get("type") == "json_schema":
        return schema.get("json_schema", {}).get("schema", {})
    return schema


# ---- GBNF emission (legacy llama.cpp paths) ----
#
# Most users on Ollama 0.5+ can pass a JSON schema directly as ``format=``.
# But some users on older Ollama / llama.cpp builds need raw GBNF. We don't
# ship a full schema-to-GBNF compiler — that's complex and would duplicate
# llama-grammar — but we do ship a couple of canonical grammars for the
# common cases. If users need fancier grammars, the recommended path is to
# upgrade Ollama / llama.cpp.

# Minimal JSON-array grammar. Forces the output to be a JSON array of objects,
# but doesn't constrain the keys. Useful for "parse-loosely-then-validate"
# pipelines where layer 3 (parsing.py) handles fine-grained validation.
GBNF_JSON_ARRAY = r"""
root   ::= ws "[" ws (object (ws "," ws object)*)? ws "]" ws
object ::= "{" ws (string ws ":" ws value (ws "," ws string ws ":" ws value)*)? ws "}"
value  ::= object | array | string | number | "true" | "false" | "null"
array  ::= "[" ws (value (ws "," ws value)*)? ws "]"
string ::= "\"" ([^"\\] | "\\" .)* "\""
number ::= "-"? ([0-9] | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [+-]? [0-9]+)?
ws     ::= [ \t\n\r]*
""".strip()

GBNF_JSON_OBJECT = r"""
root   ::= ws object ws
object ::= "{" ws (string ws ":" ws value (ws "," ws string ws ":" ws value)*)? ws "}"
value  ::= object | array | string | number | "true" | "false" | "null"
array  ::= "[" ws (value (ws "," ws value)*)? ws "]"
string ::= "\"" ([^"\\] | "\\" .)* "\""
number ::= "-"? ([0-9] | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [+-]? [0-9]+)?
ws     ::= [ \t\n\r]*
""".strip()


def gbnf_for(schema_type: str) -> str:
    """Return a canned GBNF grammar for the requested top-level type.

    Used by older Ollama / llama.cpp builds that don't support JSON-schema
    format. Returns either the array or object grammar.
    """
    if schema_type == "array":
        return GBNF_JSON_ARRAY
    return GBNF_JSON_OBJECT
