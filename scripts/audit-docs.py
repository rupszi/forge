#!/usr/bin/env python3
"""Validate frontmatter on docs/active/ and docs/reference/ markdown files.

Required fields: status, owner, last_reviewed.
Stale = last_reviewed > 90 days old (warning).
Missing frontmatter on files in active/ or reference/ = block (exit 1).

Bypass: set SKIP_DOCS_AUDIT=1 (caller's responsibility).
See docs/ENGINEERING_STANDARDS.md §14.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WATCH_DIRS = ["docs/active", "docs/reference"]
STALE_DAYS = 90
REQUIRED_FIELDS = {"status", "owner", "last_reviewed"}
ALLOWED_STATUS = {"live", "draft", "archived"}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str] | None:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    block = m.group(1)
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    today = dt.date.today()
    errors: list[str] = []
    warnings: list[str] = []
    checked = 0

    for d in WATCH_DIRS:
        root = REPO / d
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.md")):
            checked += 1
            text = p.read_text(encoding="utf-8")
            fm = parse_frontmatter(text)
            rel = p.relative_to(REPO)

            if fm is None:
                errors.append(f"{rel}: missing frontmatter (need: status, owner, last_reviewed)")
                continue

            missing = REQUIRED_FIELDS - fm.keys()
            if missing:
                errors.append(f"{rel}: missing fields: {sorted(missing)}")

            if "status" in fm and fm["status"] not in ALLOWED_STATUS:
                errors.append(f"{rel}: status={fm['status']!r} not in {sorted(ALLOWED_STATUS)}")

            if "last_reviewed" in fm:
                try:
                    last = dt.date.fromisoformat(fm["last_reviewed"])
                except ValueError:
                    errors.append(
                        f"{rel}: last_reviewed={fm['last_reviewed']!r} is not ISO date (YYYY-MM-DD)"
                    )
                else:
                    age = (today - last).days
                    if age > STALE_DAYS:
                        warnings.append(
                            f"{rel}: last_reviewed={fm['last_reviewed']} ({age} days old; max {STALE_DAYS})"
                        )

    print(f"audit-docs: checked {checked} markdown files in {WATCH_DIRS}")
    for w in warnings:
        print(f"  WARN: {w}")
    for e in errors:
        print(f"  FAIL: {e}")

    if errors:
        print(
            f"\n{len(errors)} error(s). Bypass with SKIP_DOCS_AUDIT=1 only with PR justification."
        )
        return 1
    if warnings:
        print(f"\n{len(warnings)} warning(s). Consider refreshing last_reviewed dates.")
    print("\nOK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
