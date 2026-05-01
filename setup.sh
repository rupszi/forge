#!/usr/bin/env bash
set -euo pipefail

# Forge setup — safe, local, no curl-pipe-bash.
# Prefers `uv` (fast, manages CPython) and falls back to system python3 + venv.
# After Phase 0 of the build plan, uv is the recommended path.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "Forge Setup"
echo "==========="

# ---- git is mandatory ----
if ! command -v git &>/dev/null; then
    echo "ERROR: git is required but not found."
    exit 1
fi
echo "  Git: OK"

# ---- Path A: uv (preferred — fast, reproducible) ----
if command -v uv &>/dev/null; then
    echo "  Using uv: $(uv --version)"
    cd "$SCRIPT_DIR"
    if [ -f uv.lock ]; then
        uv sync --locked --all-extras --group dev --group test
    else
        echo "  No uv.lock yet — running uv sync (will generate lockfile)..."
        uv sync --all-extras --group dev --group test
    fi
    PYRUN="uv run "

# ---- Path B: legacy pip + venv (works while waiting for uv install) ----
else
    if ! command -v python3 &>/dev/null; then
        echo "ERROR: python3 is required but not found."
        echo "       Recommended: install uv (curl -LsSf https://astral.sh/uv/install.sh | sh)"
        exit 1
    fi
    PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
        echo "ERROR: Python 3.9+ required, found $PY_VERSION"
        exit 1
    fi
    if [ "$PY_MINOR" -lt 10 ]; then
        echo "  ⚠  Python $PY_VERSION detected — Forge baseline targets 3.10+ for full feature set."
        echo "     Recommended: brew install python@3.12  OR  install uv (auto-manages Python)."
    fi
    echo "  Python: $PY_VERSION OK (legacy pip path)"

    if [ ! -d "$VENV_DIR" ]; then
        echo "  Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi
    echo "  Installing runtime + dev deps..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet httpx websockets
    "$VENV_DIR/bin/pip" install --quiet pytest pytest-asyncio pytest-cov ruff respx hypothesis syrupy time-machine pre-commit
    PYRUN=".venv/bin/"
fi

# ---- Install pre-commit + pre-push hooks (idempotent) ----
if [ -d .git ]; then
    echo "  Installing pre-commit + pre-push hooks..."
    if command -v uv &>/dev/null; then
        uv run pre-commit install --hook-type pre-commit --hook-type pre-push >/dev/null 2>&1 || true
    elif [ -x "$VENV_DIR/bin/pre-commit" ]; then
        "$VENV_DIR/bin/pre-commit" install --hook-type pre-commit --hook-type pre-push >/dev/null 2>&1 || true
    fi
    chmod +x scripts/pre-push.sh 2>/dev/null || true
fi

# ---- Create forge wrapper for git-clone path ----
FORGE_BIN="$SCRIPT_DIR/forge"
cat > "$FORGE_BIN" << 'WRAPPER'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if command -v uv &>/dev/null; then
    cd "$SCRIPT_DIR" && uv run python -m daemon.main "$@"
else
    PYTHONPATH="$SCRIPT_DIR" "$SCRIPT_DIR/.venv/bin/python3" -m daemon.main "$@"
fi
WRAPPER
chmod +x "$FORGE_BIN"

echo ""
echo "Setup complete!"
echo ""
echo "  Run: ./forge init     (in your project directory)"
echo "  Run: ./forge doctor   (check dependencies)"
echo "  Run: ./forge serve    (start dashboard)"
echo ""
echo "  Quality gate (matches pre-push):"
echo "    ${PYRUN}ruff check daemon tests scripts"
echo "    ${PYRUN}ruff format --check daemon tests scripts"
echo "    ${PYRUN}pytest -m 'not integration'"
echo ""
echo "  See docs/BUILD_PLAN.md for the 14-week roadmap."
echo "  See docs/ENGINEERING_STANDARDS.md for the engineering bar."
