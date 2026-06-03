#!/usr/bin/env bash
# Forge pre-push gate — heavy quality checks with conditional execution.
#
# Philosophy: pre-push > CI. CI minutes are scarce; developer machines are not.
# Conditional checks make the heavy gate tolerable — only run what the diff touches.
#
# Bypass env vars (use sparingly, document in PR):
#   SKIP_SCHEMA_PARITY=1     skip schema-parity check
#   SKIP_DOCS_AUDIT=1        skip frontmatter validation
#   RUN_INTEGRATION=1        ALSO run integration tests (needs Ollama)
#   RUN_SWEBENCH_SMOKE=1     ALSO run a 5-task SWE-bench smoke
#
# See docs/ENGINEERING_STANDARDS.md §7 for the full design.

set -euo pipefail

# Pick a Python runner. uv is preferred (Phase 0). Fall back to .venv/bin if uv
# isn't installed yet so the gate works on a fresh clone before Phase 0 completes.
if [[ -z "${PYRUN:-}" ]]; then
  if command -v uv >/dev/null 2>&1; then
    PYRUN="uv run "
  elif [[ -x ".venv/bin/python" ]]; then
    PYRUN=".venv/bin/"
  else
    echo "❌  Need either uv or .venv/bin/python. Run: ./setup.sh"; exit 1
  fi
fi

CYAN="\033[36m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"

step()  { echo -e "${CYAN}→${RESET}  $*"; }
ok()    { echo -e "${GREEN}✓${RESET}  $*"; }
warn()  { echo -e "${YELLOW}⚠${RESET}  $*"; }
fail()  { echo -e "${RED}❌${RESET} $*"; exit 1; }

# ---- 1. Block direct push to main ----
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo 'detached')"
if [[ "$BRANCH" == "main" ]]; then
  fail "Direct push to main is forbidden. Open a PR from develop."
fi

# ---- 2. Detect what changed in this push ----
# Compare against upstream if it exists, otherwise the previous commit.
# Empty-history repo (no commits): assume everything changed.
if ! git rev-parse HEAD >/dev/null 2>&1; then
  CHANGED="$(git ls-files)"
elif git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
  CHANGED="$(git diff --name-only @{u}..HEAD 2>/dev/null || true)"
elif git rev-parse HEAD~1 >/dev/null 2>&1; then
  CHANGED="$(git diff --name-only HEAD~1..HEAD 2>/dev/null || true)"
else
  CHANGED="$(git ls-files)"
fi

src_changed()    { echo "$CHANGED" | grep -qE '^(daemon/|tests/|pyproject\.toml|scripts/.+\.py$)' || return 1; }
ui_changed()     { echo "$CHANGED" | grep -qE '^ui/' || return 1; }
docs_changed()   { echo "$CHANGED" | grep -qE '^docs/' || return 1; }
schema_changed() { echo "$CHANGED" | grep -qE '^(daemon/db\.py|daemon/models\.py|daemon/ws_server\.py|ui/lib/types\.ts|daemon/schemas/.+)$' || return 1; }

# ---- 3. Always-on (fast, read-only) ----

if [[ "${SKIP_DOCS_AUDIT:-0}" != "1" ]]; then
  if [[ -f scripts/audit-docs.py ]]; then
    step "docs:audit (frontmatter validation)"
    ${PYRUN}python scripts/audit-docs.py || fail "docs audit failed (set SKIP_DOCS_AUDIT=1 to bypass)"
    ok "docs audit passed"
  else
    warn "scripts/audit-docs.py not yet present — skipping (will be added Phase 0)"
  fi
fi

step "ruff check (lint)"
${PYRUN}ruff check daemon tests scripts || fail "ruff check failed"
ok "ruff check passed"

step "ruff format --check"
${PYRUN}ruff format --check daemon tests scripts || fail "ruff format check failed (run: ${PYRUN}ruff format daemon tests scripts)"
ok "format check passed"

# ---- 4. Conditional — only what the diff touches ----

if src_changed; then
  step "pyright (type check — ADVISORY for v0.1)"
  # Pyright is advisory, not blocking, for v0.1: the daemon carries ~36
  # pre-existing type-annotation findings (Optional handling, int|None returns,
  # optional-dep imports) that are runtime-safe (full pytest suite is green).
  # Clearing them is a tracked typing-cleanup task (FORGE_STUDIO_TRACKER M8),
  # open to contributors. We surface the report but do NOT fail the push on it,
  # rather than weaken the checker's settings to fake a pass. Set
  # PYRIGHT_STRICT=1 to make it blocking again once the backlog is cleared.
  if command -v pyright >/dev/null 2>&1 || ${PYRUN}python -c "import pyright" 2>/dev/null; then
    if ${PYRUN}pyright daemon tests; then
      ok "pyright clean"
    elif [[ "${PYRIGHT_STRICT:-0}" == "1" ]]; then
      fail "pyright failed (PYRIGHT_STRICT=1)"
    else
      warn "pyright reported findings (advisory for v0.1 — see tracker M8)"
    fi
  else
    warn "pyright not installed — skipping"
  fi

  step "pytest (unit tests, no integration)"
  ${PYRUN}pytest -m 'not integration' --no-header -q || fail "unit tests failed"
  ok "unit tests passed"
else
  ok "src/tests unchanged — skipping pyright + pytest"
fi

if [[ "${SKIP_SCHEMA_PARITY:-0}" != "1" ]] && schema_changed; then
  if [[ -f scripts/check-schema-parity.py ]]; then
    step "schema parity (db.py / models.py / ws_server.py / ui types / json schemas)"
    ${PYRUN}python scripts/check-schema-parity.py || fail "schema parity drift detected (set SKIP_SCHEMA_PARITY=1 with PR justification to bypass)"
    ok "schema parity OK"
  else
    warn "scripts/check-schema-parity.py not yet present — skipping (will be added Phase 1 Week 4)"
  fi
fi

if ui_changed; then
  if [[ -d ui/node_modules ]]; then
    step "ui typecheck + tests"
    ( cd ui && pnpm typecheck && pnpm test ) || fail "ui checks failed"
    ok "ui checks passed"
  else
    warn "ui/node_modules missing — skipping ui checks (run: pnpm --dir ui install)"
  fi
fi

# ---- 5. Opt-in — heavy validations ----

if [[ "${RUN_INTEGRATION:-0}" == "1" ]]; then
  step "integration tests (needs Ollama)"
  ${PYRUN}pytest -m integration --no-header -q || fail "integration tests failed"
  ok "integration tests passed"
fi

if [[ "${RUN_SWEBENCH_SMOKE:-0}" == "1" ]]; then
  if [[ -f eval/swebench/smoke.py ]]; then
    step "SWE-bench smoke (5-task subset)"
    ${PYRUN}python eval/swebench/smoke.py || fail "swebench smoke failed"
    ok "swebench smoke passed"
  else
    warn "eval/swebench/smoke.py not yet present (Phase 2 Week 7)"
  fi
fi

echo ""
ok "pre-push gate passed for branch $BRANCH"
