# Forge Engineering Standards

The opinionated engineering bar for Forge. Every contribution adheres to these standards; every config file in the repo is derived from these decisions.

> **Heritage**: this document inherits the philosophy of an existing private TypeScript/Next.js + RN monorepo's engineering practices and translates the patterns to Python. The biggest carry-over is **pre-push > CI** with conditional `SKIP_*` escape hatches.
>
> **Source research**: [03-engineering-best-practices.md](research/notes/03-engineering-best-practices.md) (Python tooling, testing, CI, observability) and [04-anthropic-best-practices.md](research/notes/04-anthropic-best-practices.md) (Anthropic harness, prompt caching, agent SDK, performance).

---

## The three load-bearing opinions

1. **Pre-push > CI.** CI minutes are scarce; developer machines are not. The heavy gate runs locally on every push. CI is reserved for (a) things requiring secrets (PyPI publish), (b) scheduled scans (CodeQL, OSSF Scorecard), (c) clean-environment audits (security audit, SBOM). This shifts feedback left and keeps GitHub Actions cheap.
2. **Conditional checks with `SKIP_*` escape hatches** make the heavy gate tolerable. A pre-push that always runs the entire test suite is a pre-push you'll bypass. Only run what's relevant to the diff, and document the bypass env vars.
3. **Defer to humans on releases.** Multi-target releases (PyPI wheel + git tag + CHANGELOG + version-file + UI package.json) need a single sync script that humans invoke. No `semantic-release`. No auto-deploys.

---

## Table of contents

1. [Project structure & packaging](#1-project-structure--packaging)
2. [Dependency policy](#2-dependency-policy)
3. [Linting & formatting](#3-linting--formatting)
4. [Type checking](#4-type-checking)
5. [Testing](#5-testing)
6. [CI/CD](#6-cicd)
7. [Pre-commit & pre-push hooks](#7-pre-commit--pre-push-hooks)
8. [Async, concurrency, performance patterns](#8-async-concurrency-performance-patterns)
9. [Logging, tracing, observability](#9-logging-tracing-observability)
10. [Error handling](#10-error-handling)
11. [Security hygiene](#11-security-hygiene)
12. [Docstrings & comments](#12-docstrings--comments)
13. [Versioning & releases](#13-versioning--releases)
14. [Documentation](#14-documentation)
15. [Code review & PR conventions](#15-code-review--pr-conventions)
16. [Observability of LLM/agent calls](#16-observability-of-llmagent-calls)
17. [Forbidden / "do NOT" list](#17-forbidden--do-not-list)
18. [The first 5 commands](#18-the-first-5-commands-a-contributor-runs-from-a-fresh-clone)

---

## 1. Project structure & packaging

### Layout

```
/                          ← repo root
  pyproject.toml           ← single config surface
  uv.lock                  ← committed
  setup.sh                 ← `uv sync` wrapper for git-clone path
  CLAUDE.md                ← project instructions (re-injected every Claude Code request)
  CHANGELOG.md             ← Keep a Changelog format
  .pre-commit-config.yaml  ← fast hooks (commit stage)
  .gitleaks.toml           ← secret-scan allowlist
  .gitignore
daemon/                    ← THE package (flat layout; a src/forge/ rename is NOT planned for v0.1)
    agents/                ← planner, generator, evaluator, reviewer, researcher, classifier
    executors/             ← claude_code, ollama, openai_compatible, batch, mlx
    memory/                ← knowledge, episodic, procedural, research, retriever, learner
    scanner/               ← project, claude_code, tools, repomap
    # schemas/             ← (PLANNED) JSON schemas for contracts/verdicts — not yet implemented
    cli.py
    db.py
    models.py
    config.py
    scheduler.py
    worktree.py
    budget.py
    safety.py              ← destructive-op allow/deny lists (new)
    parsing.py             ← BAML tolerant parsing (extras only)
    ws_server.py
    mcp_server.py          ← KB-as-MCP server (new)
tests/
  conftest.py              ← shared fixtures (tmp_db, mock_executor, frozen_time)
  unit/                    ← fast, isolated, no external binaries
  integration/             ← requires Ollama or claude CLI; gated by marker
  fixtures/
    db.py                  ← reusable fixture factories
    executors.py
    project.py
  data/
    sample_plans/          ← JSON fixtures
    evaluator_outputs/     ← real Qwen3/Devstral outputs for regression
ui/                        ← Next.js dashboard (separate package.json)
docs/
  BUILD_PLAN.md            ← single source of truth (the live tracker)
  ENGINEERING_STANDARDS.md ← this file
  active/                  ← live trackers, sprint plans, runbooks
  reference/               ← stable specs (architecture, memory-system, security)
  audits/                  ← dated audits (e.g. 2026-04-30-baseline/)
  archive/                 ← retired docs
  operations/
    GOTCHAS.md             ← hard-won lessons (the human equivalent of Forge's KB)
    LEARNINGS.md           ← append-only; last 5 entries mandatory reading at session start
  research/                ← notes/ + competitive-landscape-and-architecture.md
scripts/
  pre-push.sh              ← heavy gate (the killer file — see §7)
  audit-docs.py            ← frontmatter validator (last_reviewed, owner)
  check-schema-parity.py   ← schema parity gate (see §11)
  # sync-version.py        ← (PLANNED) multi-target release version sync — not yet implemented
  # find-flakes.py         ← (PLANNED) flake detection (5x test runner aggregator) — not yet implemented
.github/
  workflows/
    ci.yml                 ← intentionally light: security audit + advisory build
    codeql.yml             ← weekly Mon 08:00 UTC
  dependabot.yml
```

### Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Config surface | **`pyproject.toml` only** | PEP 621 has won; no `setup.py`, `setup.cfg`, requirements files, or per-tool configs |
| Workflow tool | **`uv`** (Astral) | 10–100× faster than pip/Poetry; manages Python; universal lockfile |
| Build backend | **`hatchling`** | Boring, stable, future-proof; survives workflow tool swaps |
| Lockfile | **`uv.lock` committed** | Reproducible across contributors and CI; CI uses `uv sync --locked` |
| Package layout | **`daemon/`** (flat package; a `src/forge/` rename is *not planned* for v0.1) | Single import root; tests run against the working tree |
| CLI entry point | **`[project.scripts] forge = "daemon.cli:main"`** | Cross-platform launcher; `setup.sh` is the git-clone convenience path |
| Python floor | **3.10+** (recommended **3.11+**) | TaskGroup, asyncio.timeout, `match`, `X \| Y` unions, `tomllib` |
| Dep groups | **PEP 735 `[dependency-groups]`** for dev/test/docs | Keeps user-visible extras clean |

### Tests live where Python expects them

The reference TS/RN repo co-locates tests next to source. Python convention is the inverse — `pytest` defaults expect `tests/test_*.py`, IDE/coverage tooling assumes it, and the `src/` layout depends on it (so tests run against the installed wheel, not local source). **Adopt the standard `tests/` tree, but split by category** (the reference repo's good idea):

- `tests/unit/` — fast, isolated, no external binaries (must run without Ollama or `claude` installed)
- `tests/integration/` — requires Ollama or `claude`; gated by `@pytest.mark.integration`
- `tests/fixtures/` — reusable fixture factories, importable from both
- `tests/data/` — JSON fixtures, sample LLM outputs, sample diffs

### Bootstrap from fresh clone

Single command. See [§18](#18-the-first-5-commands-a-contributor-runs-from-a-fresh-clone).

### Tried & rejected

- **Poetry / PDM** — `uv` has won (10–100× faster, manages Python, universal lockfile)
- **Co-located tests** — Python tooling fights it; `tests/` tree with category subdirs is the right Python adaptation
- **Flat `daemon/` package** — the codebase ships as a flat `daemon/` package imported directly; a `src/forge/` layout was considered but is *not planned* for v0.1 (it would churn every import for no v0.1 benefit)
- **`setup.py` / `setup.cfg` / `requirements*.txt`** — all subsumed by `pyproject.toml`

---

## 2. Dependency policy

### Hard rules

- **Runtime deps stay narrow.** The original spec had a strict two-deps rule (`httpx`, `websockets`). Hardening for open weights pushes that to **6 hard runtime deps + 2 dev/test + 1 extras**. Each addition is documented in [BUILD_PLAN.md → Dependency tracker](BUILD_PLAN.md#dependency-tracker).
- **Pin transitive CVE fixes** when upstream is slow, via `[tool.uv.constraints]` (uv's equivalent of npm overrides):
  ```toml
  [tool.uv]
  constraint-dependencies = [
    # one-line per pin; comment with CVE / upstream issue link
  ]
  ```
- **No GPL.** MIT, BSD, Apache 2.0 only for runtime. AGPL/LGPL/GPL excluded — this is also a license gate in `pyproject.toml`.
- **No agent frameworks.** No LangChain, no CrewAI, no AutoGen as runtime deps. Lift ideas, not libraries. (See [research/competitive-landscape-and-architecture.md §3.3](research/competitive-landscape-and-architecture.md).)

### Runtime vs dev split

Strict. Runtime in `[project.dependencies]`. Dev/test in `[dependency-groups.dev]` and `[dependency-groups.test]`. Optional user-installable extras in `[project.optional-dependencies]` (e.g. `forge[robust]` for BAML, `forge[batch]` for the Anthropic batch SDK).

No "I'll move it later" exceptions.

### Updates

| Ecosystem | Cadence | Rule |
|---|---|---|
| `pip` (Python) | Daily, max 5 open PRs | Patch + minor only; major bumps require human review |
| `github-actions` | Weekly Monday | Patch + minor auto-PR |

`.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule: { interval: "daily" }
    open-pull-requests-limit: 5
    labels: ["dependencies", "security"]
    ignore:
      - dependency-name: "*"
        update-types: ["version-update:semver-major"]
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly", day: "monday" }
    open-pull-requests-limit: 3
```

### Pinning policy

| Type of dep | Specifier | Why |
|---|---|---|
| Direct runtime | `>=X.Y.Z` (loose, allow patch+minor) | Lockfile pins exactly; specifier just bounds |
| Tooling (ruff, pyright, pre-commit) | Pinned exactly in `[dependency-groups.dev]` | Reproducible dev experience; bumps are deliberate |
| `requires-python` | `>=3.10` | Hard floor; CI matrix tests 3.11/3.12/3.13 |
| Build backend | Pinned exactly | Versions matter for reproducibility |

### Tried & rejected

- **Renovate** — Dependabot is GitHub-native and CodeQL is already there
- **Auto-merge of patch bumps** — disabled; humans review even patches because the LLM/agent surface is volatile
- **Major-version auto-PRs** — explicitly ignored

---

## 3. Linting & formatting

### Stack (one tool per concern, no overlap)

| Concern | Tool | Notes |
|---|---|---|
| Lint | **Ruff** (`ruff check`) | Sub-second on Forge's 3 K LOC |
| Format | **Ruff** (`ruff format`) | Replaces Black; >99.9% Black-compatible; 30× faster |
| Import sort | Ruff `I` rule | Replaces isort |
| Modernize syntax | Ruff `UP` rule | Replaces pyupgrade |
| Async-bug check | Ruff `ASYNC` rule | **Critical for Forge** — catches sync-in-async bugs |
| Security lint | Ruff `S` + standalone bandit | Ruff covers ~80%; bandit weekly in CI |

### Skip list

❌ Black, isort, flake8, pylint, pyupgrade — all subsumed by Ruff
❌ `from __future__ import annotations` — PEP 649 deprecates it in 3.14; we target 3.10+ which has `X | Y`

### Ruff config

Lives in `pyproject.toml`. The full config is in [§3 of the engineering-best-practices research](research/notes/03-engineering-best-practices.md#21-ruff-replaces-black-isort-flake8-pyupgrade-and-more) and replicated in [pyproject.toml](../pyproject.toml). Highlights:

```toml
[tool.ruff.lint]
select = [
  "E", "W", "F", "I", "B", "UP", "C4", "SIM", "RET", "PTH",
  "TID", "TC", "ASYNC", "S", "RUF",
  "T20",   # flake8-print — no print() in committed code (use logging)
  "EM",    # exception messages must be variables
  "G",     # logging format strings
]
ignore = [
  "E501",   # line length — formatter handles it
  "S101",   # assert is fine in tests
  "S603",   # subprocess is intentional in Forge
  "EM101", "EM102",  # too noisy for one-line raises
]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S", "B011", "T20"]
"scripts/**/*.py" = ["T20"]   # scripts can print
```

### Hard rules

- **No `print()` in committed `daemon/` code.** Use `logging`. Enforced by ruff `T20`.
- **No `# type: ignore` without inline reason + issue link.** Enforced by ruff `RUF100` (banned without code) + `pyright` config `reportUnnecessaryTypeIgnoreComment = "warning"`. Pattern when truly needed:
  ```python
  result = legacy_api.call()  # type: ignore[no-any-return]  # see #142, upstream stub missing
  ```
- **No `Any` without justification.** Pyright catches this in `standard` mode for explicit `Any` usage in your code.
- **No empty `except: pass` blocks.** Either log + re-raise, or call the helper:
  ```python
  except SomeError as e:
      log.warning("dropped %s during cleanup: %s", op, e)
      # explicit: we know this can fire on a torn-down session
  ```

---

## 4. Type checking

### Decision: pyright now, ty later

| Tool | Speed | Conformance | DX | Verdict |
|---|---|---|---|---|
| **pyright** | Medium-fast | High | Best (Pylance) | **Adopt now** |
| mypy | Slow | Reference (~57%) | Plugin-based | Skip — pyright is faster + better DX |
| ty (Astral) | Fastest | ~15% in early 2026 | Yes | Revisit Q3 2026 |
| pyrefly (Meta) | Very fast | ~58% | Yes | Skip — keep Astral toolchain coherent |

### Pyright config (in `pyproject.toml`)

```toml
[tool.pyright]
include = ["src", "tests", "scripts"]
pythonVersion = "3.10"
typeCheckingMode = "standard"
reportMissingTypeStubs = "warning"
reportImplicitStringConcatenation = "warning"
reportUnnecessaryIsInstance = "information"
reportUnnecessaryTypeIgnoreComment = "warning"
strictListInference = true
strictDictionaryInference = true
strictSetInference = true
```

`standard` mode (not `strict`) — strict spends a week chasing `Optional` warnings on the SQLite/dataclass boundary without proportional value. Standard + the strict-list/dict/set inference flags is the sweet spot.

### Type stubs

- `httpx` ships its own
- `websockets` is fully typed since 12.x
- `tree-sitter-languages`, `networkx` need community stubs (`pip install types-networkx`) where they exist

---

## 5. Testing

### Stack

| Component | Tool | Notes |
|---|---|---|
| Test runner | **pytest** ≥8.0 | Already in use; 243 tests pass in 1.15s |
| Async support | **pytest-asyncio** strict mode | Forge already uses this — keep it |
| Coverage | **pytest-cov** | Branch coverage **on**; thresholds below |
| HTTP mocking | **respx** | Dedicated httpx mocking |
| Property-based | **hypothesis** | Selectively for parsers (planner JSON, evaluator PASS/FAIL) |
| Snapshot | **syrupy** | For prompt assembly + retriever output |
| Flake detection | `scripts/find-flakes.py` *(PLANNED)* | Will run pytest 5x, JSON output, aggregate flakes |

### Pytest config

```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
asyncio_mode = "strict"
asyncio_default_fixture_loop_scope = "function"
addopts = [
  "-ra",
  "--strict-markers",
  "--strict-config",
  "-W error::DeprecationWarning",
]
markers = [
  "slow: tests that take >1 s",
  "integration: requires Ollama or claude CLI",
  "unit: pure unit tests (default)",
]
filterwarnings = [
  "error",
  "ignore::pytest.PytestUnraisableExceptionWarning",
]
```

### Coverage thresholds (higher than the Python research baseline)

The reference TS/RN stack uses 85/85/75/82 for lines/functions/branches/statements. Translate to Python:

```toml
[tool.coverage.run]
branch = true
source = ["daemon"]
omit = [
  "daemon/main.py",
  "daemon/_version.py",
]

[tool.coverage.report]
show_missing = true
fail_under = 80         # lines (Python's primary metric; pytest-cov reports lines+branches)
exclude_also = [
  "raise NotImplementedError",
  'if __name__ == "__main__":',
  "if TYPE_CHECKING:",
  "@(abc\\.)?abstractmethod",
  "\\.\\.\\.",
]

[tool.coverage.html]
directory = "htmlcov"
```

**Why 80%, not 75%**: the reference repo's higher gates discipline behaviour. 80% with branch coverage on (which pytest-cov enforces alongside line) is the right floor for an async daemon. Don't padding-test `__repr__` to hit it; instead, ruthlessly cover the planner→generator→evaluator loop, the scheduler dependency-wave logic, and the parsers.

### Test directory layout

```
tests/
  conftest.py                 ← shared fixtures
  fixtures/
    __init__.py
    db.py                     ← tmp_db, populated_db
    executors.py              ← mock_claude, mock_ollama, mock_openai_compatible
    project.py                ← ProjectContext factories
  data/
    sample_plans/             ← JSON fixtures
    evaluator_outputs/        ← Qwen3/Devstral output regression suite
    sample_diffs/
  unit/
    test_knowledge.py
    test_planner.py
    ...
  integration/
    test_full_session.py
    test_repomap_against_real_repo.py
```

### Async test mode

`strict` (Forge already uses this — keep it). `auto` mode wraps every `async def` test automatically but breaks Trio support and disables fixture distinctions. Strict requires explicit `@pytest.mark.asyncio` on each test and `@pytest_asyncio.fixture` on async fixtures — explicit beats implicit.

### conftest.py — what belongs there

- `tmp_db` — clean SQLite WAL DB in `tmp_path`
- `frozen_time` — via `time-machine` for confidence-decay tests
- `mock_executor` — stubs Claude/Ollama subprocess layer (already a stated requirement: tests must run without those binaries installed)
- `populated_kb` — KB pre-seeded with N gotchas

### Where Hypothesis pays off

✅ **Adopt for**:
- Planner JSON parser — malformed JSON, missing fields, wrong types
- Evaluator PASS/FAIL parser — variants, Unicode bullets, paragraph-style
- KB dedup logic — `add()` + `search()` round-trip

❌ **Skip for**:
- Orchestration logic (too much state)
- Anything flowing through real LLMs (snapshots of nondeterministic output are noise)

Reference: [Anthropic Red — Property-Based Testing with Claude](https://red.anthropic.com/2026/property-based-testing/).

### LLM/network mocking

- **HTTP**: `respx` patches httpx transports. Fast, deterministic, no cassette staleness.
- **Subprocess**: stub `executors/*.py` at the executor boundary, not the subprocess level. Tests run without Ollama/claude installed.
- **Anthropic SDK** (when adopted): mock the SDK client, not raw HTTP.
- **No VCR / cassette replay** — Forge's HTTP surface is small enough to hand-mock; cassettes stale fast on signed URLs and timestamps.
- **No MSW equivalent** — Python doesn't have one and we don't need it.

### Flake detection

*(PLANNED — not yet implemented.)* `scripts/find-flakes.py` will run pytest 5× with JSON output, aggregate failures, and write `docs/active/FLAKY-MEASURED.md`. Intended to run weekly via the `scheduled-tasks` skill or manually before each release. Until then, use `pytest -p randomly` across a few seeds (the suite ships `pytest-randomly`).

### Tried & rejected

- **MSW-equivalent** — direct mocking at the executor boundary is enough
- **VCR / pytest-recording** — Supabase signed URLs and Anthropic streaming would make cassettes useless
- **Mandatory ≥90% coverage** — incentivizes padding; 80% with branch coverage on the right paths is better

---

## 6. CI/CD

### Provider: GitHub Actions

### Philosophy: pre-push > CI

Pre-push runs the full quality gate locally on every push. CI is for things that pre-push **can't** do:
- (a) Things requiring secrets (PyPI publish, signed releases)
- (b) Scheduled scans (CodeQL weekly, OSSF Scorecard)
- (c) Clean-environment audits (security audit on a fresh runner; SBOM)
- (d) Cross-OS/Python validation (the matrix exists for *this* reason — local dev is one OS/Python)

CI minutes are scarce; developer machines are not. This is the single most important opinion in this stack.

### Workflows

| File | Trigger | Purpose |
|---|---|---|
| `.github/workflows/ci.yml` | push to `main`/`develop`/`feature/**` + PRs to `main` | Security audit (always) + matrix build (advisory) + coverage upload |
| `.github/workflows/codeql.yml` | weekly Mon 08:00 UTC + manual | SAST scan; SARIF artifact retained 90 days |
| `.github/workflows/release.yml` | tag push `v*` | OIDC PyPI publish + signed Sigstore attestation + GitHub Release with SBOM |

### Matrix (just enough)

```yaml
strategy:
  fail-fast: false
  matrix:
    python: ["3.11", "3.12", "3.13"]
    os: [ubuntu-latest, macos-latest]
```

- ✅ macOS — Forge's primary target is Apple Silicon; bugs in worktree/subprocess code surface there
- ❌ Windows — `claude`, `ollama`, `gh`, `git worktree`, `.claude/` paths all behave differently. Document "WSL is supported" and stop.
- ❌ Python 3.9 — EOL October 2025
- ❌ Python 3.10 — EOL October 2026 (six months out)

### Action versions pinned (always)

```yaml
- uses: actions/checkout@v6
- uses: astral-sh/setup-uv@v6
  with:
    python-version: ${{ matrix.python }}
    enable-cache: true
    cache-dependency-glob: "uv.lock"
- run: uv sync --locked --all-extras --group dev
- run: uv run pytest --cov
```

Never use `@latest` or `@v6.x.x` — always pin to a specific tag.

### PR checks (the exact ordered list)

The full quality gate runs in pre-push. CI runs:

1. **Security audit** (`uv run pip-audit --strict`) — must pass
2. **Build** (matrix × OS) — advisory (`continue-on-error: true`); the failure surfaces in the PR check, but doesn't block. Pre-push is authoritative.
3. **Coverage upload** — informational; uploaded to Codecov for visibility

CodeQL is informational (not blocking) — runs weekly + on push to `main`.

### Concurrency

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

### Releases

Manual, tag-driven. *(PLANNED — `scripts/sync-version.py` is not yet implemented.)* `forge version:bump` (calling `scripts/sync-version.py`) will atomically update:
1. `pyproject.toml` `[project].version` (or git-tag-derived via `hatch-vcs` — preferred)
2. `daemon/_version.py`
3. `CHANGELOG.md` (section heading + date)
4. `ui/package.json` `version`
5. `docs/BUILD_PLAN.md` (status header)
6. Git tag (signed, `git tag -s v0.2.0 -m '...'`)

Then push tag, which triggers `.github/workflows/release.yml` (OIDC PyPI publish).

### Branch protection

- `main` is protected: no force push, no direct push (also enforced in pre-push hook)
- Feature branches off `develop`; `develop → main` via PR
- Required check: security audit
- Linear history required (squash on `develop`, merge commit on `main`)

### Tried & rejected

- **Heavy CI matrix (multi-OS for every PR)** — pre-push catches 95% locally
- **Auto-deploy on push** — premature ship of broken code; explicitly disabled
- **`semantic-release`** — multi-target releases (PyPI + git tag + CHANGELOG + UI package.json) need human judgement

---

## 7. Pre-commit & pre-push hooks

### The split

- **Pre-commit (fast, sub-2-second)**: secret scan + lint-staged (ruff fix + format on staged files) + std hooks
- **Pre-push (heavy, 30 s – 3 min)**: full lint + format + typecheck + tests + build, with **conditional checks** that skip work irrelevant to the diff

### Pre-commit (`.pre-commit-config.yaml`)

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-toml
      - id: check-yaml
      - id: check-added-large-files
        args: [--maxkb=500]
      - id: check-merge-conflict
      - id: detect-private-key

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.0
    hooks:
      - id: gitleaks

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.12
    hooks:
      - id: ruff-check
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format
```

**Order matters**: gitleaks first (don't waste time formatting a file with a leaked key), then `ruff-check --fix` (rewrites code), then `ruff-format` (formats the rewritten output).

### Pre-push (`scripts/pre-push.sh`) — the killer file

Conditional, with `SKIP_*` escape hatches. Pseudocode:

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Block direct push to main (hook + branch protection)
[[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] && {
  echo "❌  Direct push to main is forbidden. Open a PR from develop."; exit 1; }

# 2. Detect what changed in the push
CHANGED=$(git diff --name-only @{u}..HEAD 2>/dev/null || git diff --name-only HEAD~1..HEAD)
src_changed()    { echo "$CHANGED" | grep -qE '^(daemon/|tests/|pyproject\.toml)'; }
ui_changed()     { echo "$CHANGED" | grep -qE '^ui/'; }
docs_changed()   { echo "$CHANGED" | grep -qE '^docs/'; }
schema_changed() { echo "$CHANGED" | grep -qE '^(daemon/db\.py|daemon/models\.py|daemon/ws_server\.py|ui/lib/types\.ts)$'; }

# 3. Always-on (fast, read-only)
echo "→ docs:audit"   ; uv run python scripts/audit-docs.py
echo "→ ruff check"   ; uv run ruff check src tests scripts
echo "→ ruff format"  ; uv run ruff format --check src tests scripts

# 4. Conditional — only what changed
if src_changed; then
  echo "→ pyright"    ; uv run pyright
  echo "→ pytest"     ; uv run pytest -m 'not integration'
fi

if [[ "${SKIP_SCHEMA_PARITY:-0}" != "1" ]] && schema_changed; then
  echo "→ schema parity"  ; uv run python scripts/check-schema-parity.py
fi

if ui_changed; then
  ( cd ui && pnpm typecheck && pnpm test )
fi

# 5. Opt-in — heavy validations
if [[ "${RUN_INTEGRATION:-0}" == "1" ]]; then
  echo "→ integration tests"  ; uv run pytest -m integration
fi

if [[ "${RUN_SWEBENCH_SMOKE:-0}" == "1" ]]; then
  echo "→ swebench smoke"  ; uv run python eval/swebench/smoke.py
fi

echo "✅  pre-push gate passed"
```

### Bypass env vars (documented)

| Env var | Skips |
|---|---|
| `SKIP_SCHEMA_PARITY=1` | Schema-parity check (use sparingly — see §11) |
| `SKIP_DOCS_AUDIT=1` | Frontmatter validation |
| `RUN_INTEGRATION=1` | Adds the integration test suite (requires Ollama running) |
| `RUN_SWEBENCH_SMOKE=1` | Adds a 5-task SWE-bench smoke run |

### What's NOT in pre-commit or pre-push

- ❌ **Tests on every commit** (slow; pre-push is the right place, conditional)
- ❌ **Typecheck in pre-commit** (slow; pre-push, conditional)
- ❌ **Build in pre-push** (very slow; only via `RUN_BUILD=1` opt-in)
- ❌ **Conventional commits hook** — followed by convention, not enforced

### Tried & rejected

- **commitlint / commitizen** — adds churn for a small team without much value
- **Full test suite on every commit** — friction tax; people bypass it
- **CI as the only gate** — pre-push catches earlier and cheaper

---

## 8. Async, concurrency, performance patterns

### Use `asyncio.TaskGroup` (3.11+) over `asyncio.gather`

For Forge's wave-based parallel sprint runner in `daemon/scheduler.py`:

```python
async with asyncio.TaskGroup() as tg:
    for sprint in wave:
        tg.create_task(execute_sprint(sprint, ctx, session.id))
```

Benefits: any subtask raises → all siblings cancelled; multiple exceptions wrapped in `ExceptionGroup`; cancellation propagates correctly down the tree.

### Use `asyncio.timeout()` (3.11+) over `wait_for`

```python
async with asyncio.timeout(TASK_TIMEOUT_SECONDS):
    result = await generator.generate(sprint, memory, wt_path)
```

Composes with TaskGroup; `timeout.reschedule()` mid-flight if needed.

### Cancellation discipline (two rules)

1. `asyncio.CancelledError` extends `BaseException`. Don't catch `Exception` and assume you've caught everything. Always re-raise:
    ```python
    try:
        await long_running_op()
    except asyncio.CancelledError:
        await cleanup()
        raise   # NEVER swallow CancelledError
    ```
2. `asyncio.shield()` exists for the rare case where a coroutine must finish even if the caller is cancelled. Use sparingly — overuse leads to unkillable tasks.

For Forge: worktree cleanup must run on cancellation:
```python
wt_path = await worktree.create(sprint.id)
try:
    return await execute_sprint_inner(sprint, wt_path)
finally:
    await worktree.cleanup(sprint.id)
```

### Subprocess: avoid stdout deadlocks

Always use `proc.communicate()` (drains both pipes concurrently). Wrap in `asyncio.wait_for(proc.communicate(), timeout=…)` for a hard cap. Forge's current code is correct; keep it.

### Timeouts are mandatory on every external call

| Surface | Timeout |
|---|---|
| `claude -p` subprocess | `TASK_TIMEOUT_SECONDS=600` (env-overridable) |
| Ollama HTTP call | `OLLAMA_TIMEOUT=300` |
| OpenAI-compatible HTTP call | `OPENAI_TIMEOUT=300` |
| Web fetch (researcher) | `RESEARCH_TIMEOUT=30` |
| WebSocket broadcast (per-client) | `WS_BROADCAST_TIMEOUT=5` |

### SQLite: stay sync, skip aiosqlite

Forge uses sync `sqlite3` from async code. **This is the right call.** `aiosqlite` runs the same sync calls on a thread pool, ~15× slower for `fetchone`. For occasional hot paths that block the event loop, wrap in `asyncio.to_thread()`.

### Skip `anyio` and `aiosqlite`

❌ Both — `asyncio.TaskGroup` gives 80% of `anyio`'s value for zero deps; `aiosqlite` is slower than sync at Forge's scale.

### WebSocket patterns (`daemon/ws_server.py`)

- **Bind 127.0.0.1 explicitly.** Library default is all interfaces.
- **Default ping/pong intervals (20s/20s)** — fine for localhost; don't disable.
- **Backpressure on broadcasts**: wrap `ws.send()` in `asyncio.wait_for(..., timeout=5.0)` so a stuck client doesn't pin the daemon.
- **Graceful shutdown**: SIGTERM/SIGINT handlers send close frames (code=1001 "going away") before tearing down.

### Profiling

- **`py-spy`** (sampling profiler, no instrumentation needed) — `py-spy record -o profile.svg -- python -m forge.main`
- **`austin`** (lighter alternative)
- **Bundle gate for the UI**: configure `size-limit` in `ui/package.json` against `.next/static/chunks/**/*.js` with a 2 MB gzip ceiling.

---

## 9. Logging, tracing, observability

### Decision: stdlib logging + JSON formatter

Reasoning:
- Two-deps rule (no structlog/loguru/pino-equivalent)
- Forge already streams events over WebSocket as JSON
- stdlib `logging` interoperates with every library

If you ever add one dep, `structlog` is the right choice. Defer until needed.

### Concrete config (`daemon/log.py`)

```python
import logging
import logging.config

LOG_CONFIG = {
    "version": 1,
    "formatters": {
        "json": {
            "format": '{"ts":"%(asctime)s","lvl":"%(levelname)s",'
                      '"mod":"%(name)s","msg":%(message)s}',
        },
    },
    "handlers": {
        "stderr": {"class": "logging.StreamHandler", "formatter": "json", "level": "INFO"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": ".forge/forge.log",
            "maxBytes": 5_000_000,
            "backupCount": 3,
            "formatter": "json",
        },
    },
    "root": {"handlers": ["stderr", "file"], "level": "INFO"},
}
logging.config.dictConfig(LOG_CONFIG)
```

### Per-session JSONL audit log (the OpenHands pattern)

Adopt this. Every agent action appends one JSON line to `.forge/sessions/<session_id>/trace.jsonl`:

```json
{"ts":"...","type":"planner.decision","session_id":"...","sprint_id":"...","data":{...}}
```

Used for: post-mortem debugging, the SessionHistory UI panel, replay via `forge replay <session-id>`. Trivial to implement (a single `append_trace_event(type, data)` helper).

### Structured log convention (similar to the reference repo's `console.error("[scope]", {...})`)

```python
log.warning("anthropic.usage", extra={"input_tokens": ..., "output_tokens": ..., "model": ...})
```

Use `logging.LoggerAdapter` to inject session/sprint IDs as a context.

### Sentry: skip (Forge is local-first, anti-telemetry)

If Forge ever grows a hosted/team mode, adopt Sentry with the **triple-gate** pattern from the reference repo:
```python
if (sentry_dsn and ENV == "production" and not is_localhost()):
    sentry_sdk.init(...)
```
Keep `traces_sample_rate=0.1`, `replays_disabled`. Add a noise filter for transient HMR/streaming errors.

### OpenTelemetry: skip

Mature but for a local-first daemon, exporting traces to a backend nobody runs gives zero value. JSONL audit log gives the same insights at 1% complexity.

---

## 10. Error handling

### Hierarchy

```python
class ForgeError(Exception):
    """Base for all Forge errors."""
    category: str = "runtime"

class ExecutorError(ForgeError):
    pass

class TimeoutError(ExecutorError):
    category = "timeout"

class DependencyError(ExecutorError):
    category = "dependency"

class PermissionError(ExecutorError):
    category = "permission"

class BudgetExhaustedError(ForgeError):
    category = "budget"
```

### Causal chaining is mandatory

```python
try:
    parsed = json.loads(output)
except json.JSONDecodeError as e:
    raise ForgeError("planner returned invalid JSON") from e
```

Always `raise ... from e` (PEP 3134). Preserves the original traceback when wrapping.

### Validation at boundaries only

- **System boundaries** (CLI args, WebSocket messages, MCP requests, subprocess output): validate aggressively. *(PLANNED)* JSON schemas will live in `daemon/schemas/`; today validation is done in code (e.g. `daemon/safety.py`, the WS handlers).
- **Internal functions**: trust callers. No double validation.

### Retry policy: minimal

- **Tanstack-Query equivalent** for HTTP: explicit backoff loop in `executors/openai_compatible.py` with max-3 retries on 5xx + connection errors. Mutations don't retry.
- **No `tenacity` or `backoff` deps** — hand-rolled is fine for the small surface.
- **Stripe-webhook-style idempotency** isn't relevant here.

### Fail-fast default + explicit silentCatch helper

The reference repo's `silentCatch()` helper is the right pattern. Python equivalent:

```python
# daemon/safety.py
def silent_catch(scope: str, e: BaseException, *, log_level: int = logging.WARNING) -> None:
    """Explicitly drop an exception. Reported once to the audit log so it's grep-able."""
    logging.getLogger(scope).log(log_level, "silentCatch: %s", e, exc_info=True)
```

Empty `except: pass` is forbidden. Either log + re-raise, or `silent_catch(__name__, e)` with a comment explaining why.

---

## 11. Security hygiene

### Tool stack

| Tool | When | Why |
|---|---|---|
| `pip-audit` | CI on every PR (always-on) | Reads `uv.lock`, queries PyPA Advisory DB |
| `gitleaks` | Pre-commit hook | Catches accidental key commits |
| GitHub native secret scanning | Always-on (free for public) | Catches what slips through |
| `bandit` (standalone) | Weekly CI scheduled, medium severity + medium confidence | Subprocess + SQLite + WebSocket surface |
| Ruff `S` rules | Every commit | Covers ~80% of bandit at 100× speed |
| `cyclonedx-bom` | On release tags | Supply-chain transparency (SBOM) |
| Dependabot | Weekly | Auto-PRs for dep updates |
| CodeQL | Weekly + on push to `main` | GitHub-native SAST |

### `.gitleaks.toml` (with Forge-specific allowlist)

```toml
[extend]
useDefault = true   # 150+ built-in rules

[allowlist]
description = "Forge research notes contain example URLs and snippet IDs that aren't secrets"
paths = [
  '''docs/research/notes/.*\.md$''',
  '''CHANGELOG\.md$''',
]
regexes = [
  # Example Anthropic message IDs in docs
  '''msg_[A-Za-z0-9]{20,}''',
  # Sprint contract example IDs
  '''sprint-[a-z0-9]{6,8}''',
]
```

### Bandit config (in `pyproject.toml`)

```toml
[tool.bandit]
exclude_dirs = ["tests", ".venv", "ui", "docs"]
skips = [
  "B101",  # assert in tests is fine
  "B404",  # subprocess import is intentional
  "B603",  # subprocess called without shell — explicitly chosen
  "B608",  # SQL string composition uses parameterized queries (verified manually)
]
```

### Secrets handling

- `.env.local` (gitignored), `.env.example` committed as template
- API keys (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`) only from environment
- Never logged, never in trace files
- WebSocket binds **127.0.0.1 only** — no external exposure

### Subprocess / shell-injection rules

- **No `shell=True`** anywhere. `asyncio.create_subprocess_exec` with argument lists only.
- Worktree names: alphanumeric + hyphens only (regex validated).
- Task descriptions: strip null bytes and control chars, cap at 10 000 chars.

### SQL parameterization

Always parameterized. No f-strings or `%` formatting in SQL. Manually verified per `B608` skip above.

### Schema parity rule (the reference repo's killer pattern)

Forge has a similar dual-store surface:

| Layer | Owns | Risk if drifted |
|---|---|---|
| `daemon/db.py` | SQLite schema (CREATE TABLE statements) | DB rejects writes |
| `daemon/models.py` | Python dataclasses | TypeError at runtime |
| `daemon/ws_server.py` | WebSocket event JSON shapes | UI breaks silently |
| `ui/lib/types.ts` | TypeScript types for the WS protocol | Runtime errors only |
| `daemon/schemas/` | *(PLANNED)* JSON schemas for contracts + evaluator verdicts | Not yet implemented |

**`scripts/check-schema-parity.py`** asserts the **four implemented locations**
(`daemon/db.py` ↔ `daemon/models.py` ↔ `ui/lib/types.ts`, with `ws_server.py`
emitting the `models.py` `to_dict()` payloads) are in sync. It verifies, per
registered entity: DB columns ⊆ the `to_dict()` keys, and `to_dict()` keys ==
the TS interface fields. Runs on pre-push when any of those files changes
(skippable with `SKIP_SCHEMA_PARITY=1`). Failure prevents the push. This is the
single biggest production-incident preventer. The fifth location
(`daemon/schemas/` JSON schemas for constrained decoding) is planned, not built;
the gate will extend to it when it lands.

### Auth rule (LAW)

Never trust client-supplied IDs over the WebSocket. Forge runs on `127.0.0.1` and is single-user, so this is less critical than in the reference TS stack — but the principle holds: validate session_id, sprint_id, worktree_name as belonging to the current daemon process before acting on them.

### Tried & rejected

- **CSP for the UI** — Next.js inline scripts force `'unsafe-inline'` which defeats the purpose. Revisit when Next provides better nonce support.
- **OSSF Scorecard** — adopt at v1.0; polish layer

---

## 12. Docstrings & comments

### Style: Google docstrings, applied sparingly

Default: write no comments. From [CLAUDE.md](../CLAUDE.md):
> Don't explain WHAT the code does, since well-named identifiers already do that. Don't reference the current task, fix, or callers ("used by X", "added for the Y flow"), since those belong in the PR description.

Add a comment only when the WHY is non-obvious — a hidden constraint, a subtle invariant, a workaround for a specific bug, behavior that would surprise a reader.

### Public API of shared modules — full Google docstring

```python
def add(self, content: str, source: str | None = None, confidence: float = 0.5) -> int:
    """Insert a knowledge item, returning its row ID.

    Deduplicates against existing content via case-insensitive match. If a
    duplicate is found, increments its `times_applied` counter and returns
    the existing ID.

    Raises:
        ValueError: if content exceeds 500 chars (KB items are one-liners).
    """
```

Type hints encode the types — docstrings should focus on **why** and **edge cases**, not parameter types. If the docstring repeats the type annotation, delete the repetition.

### API reference generation: defer

No `mkdocstrings` / `sphinx-autodoc` site for v0.1. Internal users read source. Adopt when there's a stable public API surface (the CLI, the WebSocket protocol).

---

## 13. Versioning & releases

### SemVer + git-tag-derived versions

Use `hatch-vcs`:

```toml
[project]
name = "forge"
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.hooks.vcs]
version-file = "daemon/_version.py"
```

Tag `v0.2.0` → wheel is `0.2.0`. Tag with extra commits → `0.2.0.post3+g<sha>`.

### Multi-target sync via `scripts/sync-version.py` *(PLANNED)*

The reference repo has 6 sync points; Forge has 5. Script atomically updates:

1. `daemon/_version.py` (auto via `hatch-vcs` on build)
2. `CHANGELOG.md` — add a section heading + date + cut the `## [Unreleased]` content into the new heading
3. `ui/package.json` — `version` field
4. `docs/BUILD_PLAN.md` — status header
5. Git tag (signed): `git tag -s v0.2.0 -m '...'`

```bash
$ uv run python scripts/sync-version.py 0.2.0
✓ updated CHANGELOG.md
✓ updated ui/package.json
✓ updated docs/BUILD_PLAN.md
✓ created signed tag v0.2.0
Push: git push origin v0.2.0
```

### CHANGELOG

[Keep a Changelog](https://keepachangelog.com/) format. Sections: Added / Changed / Deprecated / Removed / Fixed / Security. One section per version. The `## [Unreleased]` section accumulates between releases.

### Conventional Commits — by convention, not enforced

Use prefixes (`feat:`, `fix:`, `docs:`, `chore:`, `track:`) but no commitlint. Adopt when you have your second contributor.

### Branch strategy

- `develop` (default integration) → `main` (prod) via PR
- Feature branches off `develop`
- No direct push to `main` (hook + branch protection)
- Squash on merge to `develop`; merge commit on `develop → main` (preserves boundary)

### Tried & rejected

- **`semantic-release`** — multi-target sync needs human judgement (UI version bumps, docs status header)
- **`commitizen` for automated CHANGELOG** — overkill for solo phase

---

## 14. Documentation

### Site tool: defer (markdown rendered by GitHub for now)

When you adopt one, **MkDocs Material + mkdocstrings** is the choice — but watch the **Zensical** successor (alpha as of 2026, full release expected late 2026; same maintainers).

### Docs structure

```
docs/
  BUILD_PLAN.md            ← single source of truth (the live tracker; Forge's STATE.md analog)
  ENGINEERING_STANDARDS.md ← this file
  active/                  ← live trackers, sprint plans, runbooks
  reference/               ← stable specs (architecture, memory-system, security)
  audits/                  ← dated audits (e.g. 2026-04-30-baseline/)
  archive/                 ← retired docs
  operations/
    GOTCHAS.md             ← human-readable hard-won lessons (Forge KB has the machine version)
    LEARNINGS.md           ← append-only; last 5 entries mandatory at session start
  research/                ← notes/ + competitive-landscape-and-architecture.md
```

### Frontmatter requirement (`active/` and `reference/` only)

```yaml
---
status: live | draft | archived
owner: <name>
last_reviewed: 2026-04-30
---
```

Enforced by `scripts/audit-docs.py` (always runs in pre-push). Stale frontmatter (>90 days without `last_reviewed` bump) emits a warning; missing frontmatter blocks the push.

### Docstring style: Google (when you write them — see §12)

---

## 15. Code review & PR conventions

### PR title

Short imperative, prefix optional: `fix: planner JSON parser drops trailing commas`. Under 70 chars.

### PR description

```
## Summary
- 1–3 bullets

## Test plan
- [ ] bulleted markdown checklist of TODOs for testing the PR
```

### Required reviewers

Single human (small team). For security-sensitive paths (`daemon/safety.py`, `daemon/db.py` schema changes, anything under `daemon/schemas/`), explicit approval required.

### Self-merge

Allowed for `docs/`, `chore:`, `ci:`, `track:` PRs. Code changes require a review.

### Squash vs merge vs rebase

- Squash for feature branches into `develop`
- Merge commit for `develop → main` (preserves boundary)
- Linear history required on `main`

### Stacked PRs

Used informally (`feature/X-part-1`, `feature/X-part-2`). No `git-spice` / `Graphite` tooling.

---

## 16. Observability of LLM/agent calls

### LLM SDK usage

- **Anthropic SDK** (when migrating off `claude -p` subprocess): `anthropic ^0.81.0`. Behind `daemon/executors/anthropic_sdk.py` so tests can `respx`-mock it.
- **`claude -p` subprocess**: Forge's primary path today; instrumentation via stderr parsing.
- **Ollama HTTP**: `daemon/executors/ollama.py` reports `prompt_eval_count` + `eval_count` per call.
- **OpenAI-compatible HTTP**: `daemon/executors/openai_compatible.py` reports `usage.prompt_tokens` + `usage.completion_tokens`.

### Trace capture

Per-session JSONL trace at `.forge/sessions/<id>/trace.jsonl`. Every agent step appends one line:

```json
{"ts":"...","type":"generator.invoke","sprint_id":"...","model":"devstral-small-2507","input_tokens":12345,"output_tokens":678,"duration_ms":15234,"cache_read_tokens":0}
```

### Token accounting

Real counts from API responses (not `len(s) // 4` heuristic). Replace [daemon/executors/claude_code.py:51-52](../daemon/executors/claude_code.py) (currently naive) with proper token counts when migrating to the Agent SDK.

Budget enforcement happens in `daemon/budget.py` per-session against `SESSION_BUDGET_USD`.

### Prompt versioning

Prompts live in TS-style modules under `daemon/prompts/*.py`:

```python
EVALUATOR_SYSTEM_PROMPT = """..."""
EVALUATOR_FEW_SHOT = [...]
```

Versioned with git. Tests assert prompt structure (length bounds, required tokens), not full text. Snapshot via `syrupy` for the assembled output.

No external prompt registry (Promptlayer / Helicone) — adds vendor + complexity.

### Eval harness

`eval/swebench/` — Forge's SWE-bench Verified harness. See [BUILD_PLAN.md Phase 2 Week 7–8](BUILD_PLAN.md#week-7--swe-bench-harness-setup-25-h).

### Tried & rejected

- **LangChain / LangGraph for agent orchestration** — explicitly forbidden in CLAUDE.md
- **Hosted prompt registry** — small surface; git is enough
- **Helicone / OpenLLMetry** — local-first; trace JSONL is enough

---

## 17. Forbidden / "do NOT" list

### Frameworks deliberately not used

- **LangChain / LangGraph / LlamaIndex** — abstraction tax > value at our scale
- **CrewAI / AutoGen / MetaGPT** — see [research/notes/02b-open-source-frameworks.md](research/notes/02b-open-source-frameworks.md) for the per-framework rejection rationale
- **Black, isort, flake8, pyupgrade, pylint** — Ruff replaces all
- **mypy** — pyright is faster + better DX
- **Poetry / PDM / pip directly** — uv has won
- **anyio** — `asyncio.TaskGroup` gives 80% for zero deps
- **aiosqlite** — slower than sync at our scale
- **structlog / loguru / pino-style loggers** — stdlib + JSON formatter is enough
- **OpenTelemetry / Sentry** — local-first, anti-telemetry
- **vcrpy / cassette HTTP recording** — respx is enough; cassettes go stale

### Patterns deliberately avoided

- `print()` in committed `daemon/` code (lint warns via `T20`)
- `Any` type without justification (pyright flags)
- `# type: ignore` without inline reason + issue link
- Empty `except: pass` blocks — must call `silent_catch(scope, e)` helper with a comment
- Trusting client-supplied IDs over the WebSocket (rule applies to single-user too)
- Modifying old SQLite migrations (one migration per schema change, never edit in place — when migrations exist)
- Auto-deploys (every release is human-triggered via `scripts/sync-version.py`)
- Direct push to `main` (hook + branch protection)
- Skipping schema-parity check on five-location changes (`SKIP_SCHEMA_PARITY=1` only with PR justification)
- `select = ["ALL"]` in ruff (every rule must justify itself)
- Premature abstractions; "three similar lines is better than a wrong abstraction"

### Dependencies explicitly evaluated and rejected

- LangChain, CrewAI, AutoGen (agent frameworks)
- Letta, Mem0, Zep (managed memory)
- LanceDB, Turbopuffer (vector DBs at our scale)
- VCR / pytest-recording (HTTP cassettes)
- aiosqlite (async SQLite wrapper)
- TGI (HF Text Generation Inference — entered maintenance mode Dec 2025)

---

## 18. The first 5 commands a contributor runs from a fresh clone

```sh
# 1. Install uv (Python workflow tool — installs CPython too if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Sync deps + create venv (reads pyproject.toml + uv.lock; reproducible across machines)
uv sync --locked --all-extras --group dev

# 3. Install pre-commit + pre-push hooks
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
chmod +x scripts/pre-push.sh

# 4. Run the full quality gate locally (matches what pre-push enforces)
uv run forge check
# == ruff check src tests scripts && ruff format --check src tests scripts
#    && pyright && pytest -m 'not integration' && python scripts/audit-docs.py

# 5. Start the dev server (daemon + Next.js dashboard)
uv run forge serve
# → http://localhost:3000
```

Optional follow-ups:

```sh
brew install gitleaks                       # enable pre-commit secret scan
brew install ollama && ollama serve         # local LLM backend
ollama pull devstral-small-2507             # the cheap-tier generator
ollama pull qwen3-coder:30b                 # the medium-tier generator
ollama pull gpt-oss:20b                     # the planner / evaluator
RUN_INTEGRATION=1 uv run pytest             # integration suite (needs Ollama)
```

---

## Quick adoption checklist (Phase 0 — Week 0)

- [ ] `pyproject.toml` with all sections (replaces `daemon/requirements.txt`)
- [ ] `uv.lock` committed
- [ ] `setup.sh` updated to call `uv sync --locked --all-extras --group dev`
- [ ] `.gitignore` covering `.venv/`, `.forge/`, `__pycache__/`, `htmlcov/`, `.pytest_cache/`, `.ruff_cache/`, `node_modules/`, `.next/`, `.coverage`
- [ ] `.pre-commit-config.yaml` with std hooks + gitleaks + Ruff (commit stage only)
- [ ] `scripts/pre-push.sh` with conditional gate + `SKIP_*` escape hatches
- [ ] `scripts/audit-docs.py`, `scripts/sync-version.py`, `scripts/check-schema-parity.py`, `scripts/find-flakes.py`
- [ ] `.gitleaks.toml` with Forge-specific allowlist
- [ ] `.github/workflows/ci.yml` (light: security audit + advisory matrix)
- [ ] `.github/workflows/codeql.yml` (weekly)
- [ ] `.github/dependabot.yml`
- [ ] `tests/conftest.py` with `tmp_db`, `mock_executor`, `frozen_time` fixtures
- [ ] `CHANGELOG.md` with `## [0.0.1] – 2026-04-30 — initial baseline` entry
- [ ] `pre-commit install --hook-type pre-commit --hook-type pre-push` run locally
- [ ] `uv run pytest` works (replaces `PYTHONPATH=. .venv/bin/pytest tests/`)
- [ ] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` all pass
- [ ] `uv run forge check` umbrella command works end-to-end

---

## Closing notes

- **Pre-push > CI** is the single biggest opinion in this stack. CI minutes are scarce; developer machines are not. Push the slow gate left.
- **Conditional checks in pre-push** (only test what changed, with `SKIP_*` escape hatches) is what makes the heavy gate tolerable.
- **One script touches all version sync points** — UI versions diverge from daemon silently otherwise.
- **Schema parity rule (4 implemented locations + 1 planned, 1 commit)** is the single biggest production-incident preventer. SQL schema in `db.py` + dataclasses in `models.py` (the `to_dict()` payloads `ws_server.py` emits) + UI types in `ui/lib/types.ts` must move together; JSON schemas in `daemon/schemas/` are planned and will join when built.

---

*Living document. Update when a decision changes. Linked from [BUILD_PLAN.md](BUILD_PLAN.md) and [CLAUDE.md](../CLAUDE.md).*
