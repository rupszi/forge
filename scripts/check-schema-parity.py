#!/usr/bin/env python3
"""Schema-parity gate (ENGINEERING_STANDARDS §11).

The same entity is described in up to three places that must not drift:

  1. ``daemon/db.py``        — SQLite ``CREATE TABLE`` column lists (persisted state)
  2. ``daemon/models.py``    — dataclass ``to_dict()`` payloads (the WS/JSON shape)
  3. ``ui/lib/types.ts``     — TypeScript interfaces the UI decodes

When these fall out of sync the failure is silent: the DB rejects a write, or
the UI reads ``undefined`` for a field the daemon now emits. (This audit found
exactly that — ``SprintContract.critical`` existed in the Python payload but
was missing from the TS interface.)

This script asserts parity for the registered entities:

  - DB table columns ⊆ the Python ``to_dict()`` keys (the dataclass may carry
    extra *runtime-only* fields the table doesn't persist — that's allowed; a
    persisted column with **no** model field is not).
  - Python ``to_dict()`` keys == the TS interface field names (exact: the
    ``to_dict`` payload is what crosses the wire, so the UI type must mirror it).

Exit 0 on parity, 1 on any mismatch (with a diff). Bypass: ``SKIP_SCHEMA_PARITY=1``.
``ws_server.py`` is the de-facto WS protocol surface; the typed payloads it
emits come from these ``to_dict()`` methods, so models.py is the source of
truth for message shapes and is what we diff against the TS types.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PY = REPO / "daemon" / "db.py"
MODELS_PY = REPO / "daemon" / "models.py"
TYPES_TS = REPO / "ui" / "lib" / "types.ts"

# (python dataclass, TS interface name, DB table name or None)
REGISTRY = [
    ("SprintContract", "SprintContract", "sprint_contracts"),
    ("Session", "Session", "sessions"),
]

# SQL keywords that begin a constraint line, not a column definition.
_SQL_NON_COLUMN = {
    "primary",
    "foreign",
    "unique",
    "check",
    "constraint",
    "create",
}


def db_table_columns(text: str, table: str) -> set[str]:
    """Column names declared in ``CREATE TABLE <table> ( ... )``."""
    m = re.search(
        rf"CREATE TABLE (?:IF NOT EXISTS )?{re.escape(table)}\s*\((.*?)\);",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        raise SystemExit(f"schema-parity: table {table!r} not found in db.py")
    cols: set[str] = set()
    for raw in m.group(1).splitlines():
        line = raw.strip().strip(",")
        if not line or line.startswith("--"):
            continue
        first = line.split()[0].lower()
        if first in _SQL_NON_COLUMN:
            continue
        cols.add(line.split()[0])
    return cols


def model_todict_keys(text: str, cls_name: str) -> set[str]:
    """Keys of the dict literal returned by ``<cls_name>.to_dict``.

    Parsed via AST so a reordering or comment can't fool a regex. Requires the
    ``to_dict`` body to ``return {<string-literal>: ...}``.
    """
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "to_dict":
                    for stmt in ast.walk(item):
                        if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Dict):
                            keys = set()
                            for k in stmt.value.keys:
                                if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                                    raise SystemExit(
                                        f"schema-parity: {cls_name}.to_dict has a non-literal "
                                        f"dict key; cannot verify parity"
                                    )
                                keys.add(k.value)
                            return keys
                    raise SystemExit(f"schema-parity: {cls_name}.to_dict has no dict return")
            raise SystemExit(f"schema-parity: {cls_name} has no to_dict method")
    raise SystemExit(f"schema-parity: dataclass {cls_name!r} not found in models.py")


def ts_interface_fields(text: str, name: str) -> set[str]:
    """Field names of ``export interface <name> { ... }``."""
    m = re.search(rf"export interface {re.escape(name)}\s*\{{(.*?)\}}", text, re.DOTALL)
    if not m:
        raise SystemExit(f"schema-parity: TS interface {name!r} not found in types.ts")
    fields: set[str] = set()
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        fm = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\??\s*:", line)
        if fm:
            fields.add(fm.group(1))
    return fields


def main() -> int:
    if os.environ.get("SKIP_SCHEMA_PARITY") == "1":
        print("schema-parity: skipped (SKIP_SCHEMA_PARITY=1)")
        return 0

    db_text = DB_PY.read_text()
    models_text = MODELS_PY.read_text()
    types_text = TYPES_TS.read_text()

    failures: list[str] = []
    for cls_name, ts_name, table in REGISTRY:
        model_keys = model_todict_keys(models_text, cls_name)
        ts_fields = ts_interface_fields(types_text, ts_name)

        # Python payload must exactly match the TS interface.
        only_py = model_keys - ts_fields
        only_ts = ts_fields - model_keys
        if only_py or only_ts:
            failures.append(
                f"{cls_name}: models.py.to_dict vs ui/lib/types.ts mismatch\n"
                f"    only in Python: {sorted(only_py) or '—'}\n"
                f"    only in TS:     {sorted(only_ts) or '—'}"
            )

        # DB columns must all have a model field (model may have extra runtime fields).
        if table:
            cols = db_table_columns(db_text, table)
            orphan_cols = cols - model_keys
            if orphan_cols:
                failures.append(
                    f"{cls_name}: db.py table {table!r} has columns with no model field: "
                    f"{sorted(orphan_cols)}"
                )

    if failures:
        print("✗ schema parity FAILED:\n")
        for f in failures:
            print(f"  - {f}\n")
        print("Sync db.py ↔ models.py ↔ ui/lib/types.ts, or set SKIP_SCHEMA_PARITY=1 to bypass.")
        return 1

    checked = ", ".join(c for c, _, _ in REGISTRY)
    print(f"✓ schema parity OK ({checked})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
