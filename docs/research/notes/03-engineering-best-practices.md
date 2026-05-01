# Modern Python Engineering Best Practices for Forge (April 2026)

Research notes on the current Python tooling stack for an asyncio daemon + CLI + Next.js sidecar that runs locally on Apple Silicon, ships as MIT, and lives by a strict "two pip deps" rule.

Author's stance: Forge is a single-developer-operated, local-first project. The advice is biased toward (a) tools that make a solo maintainer faster, (b) speed on Apple Silicon, and (c) keeping the runtime dependency surface small even where dev/CI tooling can be richer.

---

## 1. Project structure and packaging

### 1.1 `pyproject.toml` is the entire config surface

PEP 621 has fully won. As of 2026 every modern tool — uv, Poetry, PDM, Hatch, Ruff, pytest, coverage, mypy, ty, pyright, bandit, commitizen, semantic-release — reads either `[project]` or `[tool.<name>]` out of one `pyproject.toml`. There is no good reason to keep `setup.py`, `setup.cfg`, `requirements*.txt`, or per-tool `*.cfg` files in 2026 unless a tool has not yet caught up (none of Forge's choices fall into that bucket).

The sections that matter for Forge specifically:

- `[build-system]` — pin `requires` and `build-backend`. For a CLI/daemon, `hatchling` is the default unless you have a reason to use `uv_build` (see 1.2).
- `[project]` — `name`, `version` (or dynamic via VCS), `requires-python`, `dependencies`, `description`, `readme`, `license`, `authors`, `classifiers`, `keywords`, `urls`.
- `[project.scripts]` — register the `forge` CLI as a console entry point (`forge = "daemon.cli:main"`). This replaces the bash wrapper in `setup.sh` for users who pip-install. Keep the bash wrapper for the "git clone, no install" path that Forge advertises.
- `[project.optional-dependencies]` (or `[dependency-groups]`, see 1.3) — surface `dev`, `docs`, `test` extras.
- `[tool.uv]` / `[tool.ruff]` / `[tool.pytest.ini_options]` / `[tool.coverage.run]` / `[tool.ty]` — every tool's config lives here.

Source: PEP 621 ([peps.python.org/pep-0621](https://peps.python.org/pep-0621/)), packaging.python.org guide ([packaging.python.org/en/latest/guides/writing-pyproject-toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)).

### 1.2 Packaging tool: uv has won (and OpenAI now owns Astral)

As of April 2026, `uv` from Astral is the recommended choice for new Python projects. It is 10-100× faster than pip/Poetry/PDM, manages Python interpreters natively (Poetry does not), produces a universal cross-platform lockfile, and the Astral team has unified the install + venv + lockfile + Python-bootstrap loop into one binary written in Rust. The 2026 caveat: **Astral was acquired by OpenAI in 2026**, which has injected some uncertainty about long-term steward priorities — but the tool itself is mature and stable, and even if Astral pivots, `uv.lock` is a documented format and the project is permissively licensed.

Honest comparison:

| Tool | Speed | Mgmt of CPython | Lockfile | Build backend | Verdict for Forge |
|---|---|---|---|---|---|
| **uv** | Fastest (Rust) | Yes (auto-installs) | Universal `uv.lock` | optional `uv_build` (or hatchling) | **Recommended** |
| Poetry | Slow (Python) | No (relies on system Python) | `poetry.lock` | `poetry-core` | Mature but slower; smoothest publish UX |
| PDM | Medium | Yes | `pdm.lock` | `pdm-backend` | Standards-first but smaller community |
| Hatch | Fast-ish | Yes | None (deliberately) | `hatchling` | Great backend, weak as a workflow tool |

Concrete recommendation for Forge:

- **Build backend**: `hatchling`. It is the most boring, least controversial choice and will keep working if you swap workflow tools. `uv_build` is fine but newer and offers no real advantage for a non-extension package.
- **Workflow tool**: `uv`. Use `uv sync` for environment setup, `uv run pytest` for tests, `uv lock` to refresh the lockfile.
- **Lockfile**: commit `uv.lock`. It is universal across macOS/Linux/Windows and pins every transitive dep.
- **Setup script**: keep `setup.sh` for users who follow the README "git clone" path, but have it call `uv sync` under the hood instead of pip + venv hand-rolled.

Sources:
- uv vs Poetry/PDM/Hatch overview: [scopir.com 2026 comparison](https://scopir.com/posts/best-python-package-managers-2026/), [dasroot.net 2026](https://dasroot.net/posts/2026/01/python-packaging-best-practices-setuptools-poetry-hatch/), [pydevtools uv guide](https://pydevtools.com/handbook/explanation/uv-complete-guide/).
- Build backends: [Chris Evans 2025](https://medium.com/@dynamicy/python-build-backends-in-2025-what-to-use-and-why-uv-build-vs-hatchling-vs-poetry-core-94dd6b92248f).
- uv lockfile semantics: [docs.astral.sh/uv/concepts/projects/dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/).

### 1.3 Dependency groups vs optional-dependencies

PEP 735 added `[dependency-groups]` to the standard, which is the modern way to declare dev-only deps that should never be exposed as a `pip install forge[dev]` extra. Use this for `dev`, `test`, `docs` (with `requires-runtime = false`-style semantics). uv reads `[dependency-groups]` natively. For deps you *want* end-users to install (e.g. an optional `forge[batch]` for the Anthropic batch executor that pulls in `anthropic`), keep using `[project.optional-dependencies]`.

For Forge: keep runtime deps at `httpx`, `websockets`. Add `[dependency-groups.dev]` with `pytest`, `pytest-asyncio`, `pytest-cov`, `respx`, `ruff`, `ty` (or `pyright`), `pre-commit`. Add `[dependency-groups.docs]` if/when you adopt MkDocs Material.

### 1.4 `src/` layout vs flat layout

Forge currently uses a flat layout with `daemon/` at the repo root. The packaging community consensus in 2026 is: **`src/` layout for anything you intend to publish or test against an installed copy**. The reason is real and pragmatic: with a flat layout, `python -c "import daemon"` from the repo root finds your source tree before the installed wheel, which masks `MANIFEST.in`/packaging bugs. With `src/forge/`, your tests run against the installed copy of the package, which is what users actually get.

For Forge: rename `daemon/` to `src/forge/` (the package name `daemon` is generic and conflicts with the dozens of other "daemon" packages on PyPI; Forge should own its top-level namespace). This also fixes a subtle mental-model issue: `daemon` is a runtime concept, not a package name. Concrete plan:

1. Rename `daemon/` → `src/forge/`.
2. Update imports project-wide (`from daemon.foo` → `from forge.foo`).
3. Update `[project.scripts]` to `forge = "forge.cli:main"`.
4. Update `[tool.hatch.build.targets.wheel]` to `packages = ["src/forge"]`.

Sources: [packaging.python.org src vs flat](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/), [pyOpenSci package guide](https://www.pyopensci.org/python-package-guide/package-structure-code/python-package-structure.html).

### 1.5 Console entry point vs bash wrapper

Right now `setup.sh` writes a bash wrapper that activates the venv and runs Python. This works but is not portable to Windows and requires users to manually add it to their PATH. The PEP 621 way is `[project.scripts]`: pip/uv generates a real cross-platform launcher script automatically.

Recommendation: keep the bash wrapper as the "I just cloned the repo" experience, but **also** declare `[project.scripts]` so that `pip install forge` (or `pipx install forge` or `uv tool install forge`) gives users a working `forge` binary on any OS.

---

## 2. Code quality tooling

### 2.1 Ruff replaces Black, isort, flake8, pyupgrade, and more

Ruff is now the entire linter+formatter stack for Python in 2026. `ruff format` is >99.9% Black-compatible on real-world projects and 30× faster than Black. `ruff check` re-implements >1,000 rules from flake8/pylint/isort/pyupgrade/pydocstyle and runs in milliseconds even on large repos.

For Forge: **adopt Ruff for both `check` and `format`**. Drop Black entirely if it ever shows up. Drop isort. Drop pyupgrade. One tool, one config block, one cache.

Recommended `[tool.ruff]` config for Forge (strict but not annoying):

```toml
[tool.ruff]
line-length = 100
target-version = "py310"  # See "Python version support" section
src = ["src", "tests"]

[tool.ruff.lint]
select = [
  "E", "W",     # pycodestyle
  "F",          # pyflakes
  "I",          # isort
  "B",          # flake8-bugbear  (real bugs)
  "UP",         # pyupgrade       (modernize syntax)
  "C4",         # flake8-comprehensions
  "SIM",        # flake8-simplify
  "RET",        # flake8-return
  "PTH",        # flake8-use-pathlib (no os.path)
  "TID",        # flake8-tidy-imports
  "TC",         # flake8-type-checking
  "ASYNC",      # flake8-async  (catches sync-in-async bugs)
  "S",          # flake8-bandit (subprocess, eval, etc.)
  "RUF",        # ruff-native rules
]
ignore = [
  "E501",   # line length — let the formatter handle it
  "S101",   # assert is fine in tests (override per-file below)
  "S603",   # subprocess call review — Forge legitimately uses subprocess
]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S", "B011"]  # security rules don't apply to tests

[tool.ruff.lint.isort]
known-first-party = ["forge"]
combine-as-imports = true

[tool.ruff.format]
quote-style = "double"
docstring-code-format = true
```

The `ASYNC` rule group is particularly load-bearing for Forge — it catches things like `time.sleep` in async functions and `requests.get` in async code, both of which would block the daemon's event loop. The `S` (bandit-via-ruff) group will flag the subprocess calls, but `S603` is properly ignored because Forge legitimately spawns subprocesses (claude, ollama, git, gh) — the broader audit happens in standalone bandit (see section 10).

Avoid: `select = ["ALL"]` — every Ruff release adds new rules and you'll wake up to a red CI for cosmetic reasons. Stay explicit. Avoid: `D` (pydocstyle) globally — Forge is a daemon, not a library, so a missing docstring on every function is noise. Add `D` selectively if you publish a public API later.

Sources: [docs.astral.sh/ruff/formatter](https://docs.astral.sh/ruff/formatter/), [docs.astral.sh/ruff/configuration](https://docs.astral.sh/ruff/configuration/), [pydevtools ruff guide](https://pydevtools.com/handbook/explanation/ruff-complete-guide/), [astral.sh/blog/the-ruff-formatter](https://astral.sh/blog/the-ruff-formatter).

### 2.2 Type checker: mypy now, pyright soon, ty/pyrefly later

The 2025-2026 type checker landscape exploded. Four real options today:

| Tool | Speed | Maturity | Spec conformance | LSP | Verdict |
|---|---|---|---|---|---|
| **mypy** | Slow | Reference | 57% | Via plugin | Boring, works, slow |
| **pyright** | Medium-fast | Mature | High | First-class (Pylance) | Best DX in editor |
| **pyrefly** (Meta) | Very fast (Rust) | Beta-ish | 58% | Yes | Promising, broader feature set |
| **ty** (Astral) | Fastest (Rust, Salsa) | Beta as of 2025-2026 | ~15% (rapidly improving) | Yes | Editor-first, sub-10ms incremental |

ty is 10-60× faster than mypy and 80× faster than Pyright on incremental edits, but as of early 2026 it passes only ~15% of the official typing-spec conformance tests vs ~57% for mypy and ~58% for pyrefly. Astral has flipped on using ty in their own projects, but it is still beta.

Recommendation for Forge:

- **Adopt now**: `pyright` in strict-but-not-paranoid mode. It is mature, has the best editor integration (Pylance in VS Code, language server everywhere else), and is fast enough for a 3K LOC codebase. mypy is fine too but pyright catches more real issues with no perf cost.
- **Evaluate in 6 months**: switch to `ty` once it passes >70% of the typing spec. Forge's heavy `Optional`/dataclass use is exactly where ty is fast.
- **Skip**: pyrefly. It is good but ty is from the same team that ships uv and ruff, so you keep the toolchain coherent.

Strictness profile that fits Forge (in `pyproject.toml` under `[tool.pyright]`):

```toml
[tool.pyright]
include = ["src", "tests"]
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

Don't go straight to `strict` — you'll spend a week chasing `Optional` warnings on the SQLite/dataclass boundary. Standard mode plus a few escalations is the sweet spot.

Type stubs: `httpx` ships its own; `websockets` is fully typed since 12.x (no stubs needed). Both runtime deps are fine.

Sources: [astral.sh/blog/ty](https://astral.sh/blog/ty), [pydevtools mypy/pyright/ty comparison](https://pydevtools.com/handbook/explanation/how-do-mypy-pyright-and-ty-compare/), [InfoWorld pyrefly vs ty](https://www.infoworld.com/article/4005961/pyrefly-and-ty-two-new-rust-powered-python-type-checking-tools-compared.html), [sinon.github.io conformance deep dive](https://sinon.github.io/future-python-type-checkers/).

### 2.3 `from __future__ import annotations` — wait

PEP 649 ships in Python 3.14 and changes how annotations are evaluated (lazy descriptors instead of strings). Critically, `from __future__ import annotations` (PEP 563 string-based) is **deprecated** as of 3.14 and will be removed after 2 more releases. Adopting it now means writing code you'll eventually have to migrate.

For Forge: **do not add `from __future__ import annotations`** unless you need to write a forward reference today. Modern Python (3.10+) supports `X | Y` unions and `list[int]` natively, which removes 90% of the original reason to use the future import. If you bump the minimum to 3.12+ (see CI section), you can drop any existing future imports as well.

Sources: [PEP 649](https://peps.python.org/pep-0649/), [PEP 749](https://peps.python.org/pep-0749/), [Mergify on 3.14 breakage](https://mergify.com/blog/python-314-what-pep-649-actually-breaks/).

---

## 3. Testing infrastructure

### 3.1 pytest config in pyproject.toml

```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
asyncio_mode = "strict"             # already correct in Forge
asyncio_default_fixture_loop_scope = "function"
addopts = [
  "-ra",                            # show short summary for all but pass
  "--strict-markers",               # catch typo'd markers
  "--strict-config",                # catch typo'd config keys
  "-W error::DeprecationWarning",   # fail on deprecation warnings from us
]
markers = [
  "slow: tests that take >1s",
  "integration: requires Ollama or claude CLI",
  "unit: pure unit tests (default)",
]
filterwarnings = [
  "error",
  "ignore::pytest.PytestUnraisableExceptionWarning",
]
```

`asyncio_mode = "strict"` (Forge's current setting) is the correct choice. The alternative (`auto`) automatically wraps every `async def` test, which is convenient but breaks when you want to support both asyncio and Trio later, and it disables the fixture decorator distinction. Strict requires `@pytest.mark.asyncio` on each test and `@pytest_asyncio.fixture` on async fixtures — explicit beats implicit.

`asyncio_default_fixture_loop_scope = "function"` gives you fresh event loop per test which is the safest default. Bump to `"module"` only for specific expensive fixtures (e.g. a shared in-memory SQLite for read-only tests) using `loop_scope="module"` on the fixture.

Sources: [pytest-asyncio docs](https://pytest-asyncio.readthedocs.io/en/stable/concepts.html), [thinhdanggroup migration guide](https://thinhdanggroup.github.io/pytest-asyncio-v1-migrate/).

### 3.2 conftest.py

Forge has no `conftest.py` today. It should. Belongs there:

- An `event_loop_policy` fixture (if you want uvloop in tests).
- A `tmp_db` fixture that spins up a clean SQLite WAL DB in `tmp_path`.
- A `frozen_time` fixture (via `freezegun` or `time-machine`) for confidence-decay tests.
- A `mock_executor` fixture that stubs the Claude/Ollama subprocess layer so the test suite runs without those binaries installed (already a stated requirement).
- An `anyio_backend` parametrize if you ever support Trio.

Keep the file under 200 lines. If it grows, split into `tests/fixtures/db.py`, `tests/fixtures/executors.py`, etc. and re-export from `conftest.py`.

### 3.3 Coverage targets

For Forge, with 1.9K LOC of test code against ~3K LOC of production code, the realistic and useful target is **75% line coverage with branch coverage on**. Branch coverage matters more than line coverage for an async daemon that has many `if/elif/else` paths and timeout branches.

```toml
[tool.coverage.run]
branch = true
source = ["src/forge"]
omit = ["src/forge/main.py"]  # entry point only, not interesting

[tool.coverage.report]
show_missing = true
skip_covered = false
fail_under = 75
exclude_also = [
  "raise NotImplementedError",
  "if __name__ == .__main__.:",
  "if TYPE_CHECKING:",
  "@(abc\\.)?abstractmethod",
  "\\.\\.\\.",
]

[tool.coverage.html]
directory = "htmlcov"
```

Don't gate at 90% — you'll end up writing tests that exercise impossible error paths just to hit a number. 75% with the *interesting* 25% covered (the planner→generator→evaluator loop) is more valuable than 95% padded with `__repr__` tests. Sources: [scientific-python coverage guide](https://learn.scientific-python.org/development/guides/coverage/), [breadcrumbscollector.tech](https://breadcrumbscollector.tech/how-to-use-code-coverage-in-python-with-pytest/).

### 3.4 Property-based testing (Hypothesis): yes, for parsers

Forge has at least three places where `hypothesis` would pay for itself many times over:

1. **The planner JSON parser** — what happens when the LLM returns `[{...}, ...]` with a missing field, an extra field, a string instead of a list, a boolean instead of a string?
2. **The evaluator PASS/FAIL parser** — same question for free-text output.
3. **The knowledge-base dedup logic** — given any two strings, does `add()` followed by `search()` round-trip correctly?

Anthropic published a piece in early 2026 on using property-based testing with LLM-generated outputs (["Property-Based Testing with Claude"](https://red.anthropic.com/2026/property-based-testing/)) which is directly applicable. Worth ~50 lines of test code per parser to gain confidence.

Adopt now for the parsers. Skip for the orchestration logic (too much state).

Sources: [hypothesis.readthedocs.io](https://hypothesis.readthedocs.io/), [hypothesis-jsonschema on PyPI](https://pypi.org/project/hypothesis-jsonschema/).

### 3.5 Snapshot testing (Syrupy): yes, for prompts and trajectories

`syrupy` is a pytest-native snapshot library, zero deps, that produces `.ambr` files for any pytest assertion. Forge has prompt strings (planner system prompt, evaluator system prompt, generator full prompt with memory injection) that need to be reviewed when they change, but writing string equality tests for them is brittle. Snapshots make every prompt change an explicit reviewable diff.

Use cases for Forge:

- Snapshot the formatted memory context produced by `retriever.get_context_for_task()` for a fixed input.
- Snapshot the planner's prompt assembly given a fixed objective + project context.
- Snapshot the evaluator's verdict-parsing for canned LLM outputs.

Adopt for the prompt-assembly layer. Skip for anything that flows through real LLMs (snapshots of nondeterministic output are noise).

Source: [syrupy-project.github.io](https://syrupy-project.github.io/syrupy/).

### 3.6 HTTP mocking: respx for httpx, not VCR

Forge's only HTTP client is `httpx`, used for Ollama's REST API and (optionally) the Claude API batch endpoint. `respx` is the dedicated httpx mocking library — it patches httpx transports rather than replaying captured cassettes, which means tests stay fast and deterministic.

Use respx for Ollama and Claude API mocks. Don't add `vcrpy` — record/replay cassettes get stale, and Forge's HTTP surface is small enough to mock by hand. `pytest-httpx` is a viable alternative; respx has slightly nicer route-matching semantics.

Source: [github.com/lundberg/respx](https://github.com/lundberg/respx), [rogulski.it pytest+respx+vcr](https://rogulski.it/blog/pytest-httpx-vcr-respx-remote-service-tests/).

### 3.7 Test data and fixtures organization

Forge already has a `tests/` flat layout. As it grows past ~15 test files (it's already at 13), split into:

```
tests/
  conftest.py
  fixtures/
    __init__.py
    db.py            # tmp_db, populated_db
    executors.py     # mock_claude, mock_ollama
    project.py       # ProjectContext fixtures
  data/
    sample_plans/    # JSON fixtures
    evaluator_outputs/
  unit/
    test_knowledge.py
    ...
  integration/
    test_full_session.py
```

Use `pytest.mark.parametrize` heavily for the parser tests — one parametrize block of 20 cases beats 20 separate `def test_x()` functions.

---

## 4. CI/CD (GitHub Actions)

### 4.1 Python version matrix

Forge currently advertises 3.9+. In April 2026:

- **Drop 3.9.** It went end-of-life in October 2025. Keeping it costs you `from __future__ import annotations` everywhere, no `match`, no `X | Y` union syntax, no `tomllib`, no `asyncio.TaskGroup`, no `asyncio.timeout()`. The TaskGroup loss alone is reason enough — Forge's scheduler benefits massively from it (see section 6).
- **Drop 3.10 too if you can stomach it.** 3.10 is end-of-life October 2026 (six months out from now). It buys you `match` statements but nothing else Forge cares about.
- **Recommended floor: 3.11.** Adds `asyncio.TaskGroup`, `asyncio.timeout`, `ExceptionGroup`, `tomllib` (parse pyproject.toml without a dep!), and faster startup (10-60% over 3.10).
- **Test matrix: 3.11, 3.12, 3.13.** 3.14 (which ships 2025-Q4 GA) is interesting but PEP 649 might break runtime introspection of dataclasses you depend on; add it as `continue-on-error: true` for now.

```yaml
strategy:
  fail-fast: false
  matrix:
    python: ["3.11", "3.12", "3.13"]
    os: [ubuntu-latest, macos-latest]
    include:
      - python: "3.14"
        os: ubuntu-latest
        experimental: true
```

### 4.2 OS matrix

Ubuntu always. **macOS yes** — Forge's primary target is Apple Silicon dev machines, you must catch macOS-specific bugs in the worktree/subprocess code there. **Windows: skip** — Forge spawns `claude`, `ollama`, `gh`, `git worktree` and lives inside `.claude/`; the path/permission model is so different that supporting it would be a sustained tax for ~5% of potential users. Ship a "WSL is supported" line in the README and call it done.

### 4.3 Caching

Use `astral-sh/setup-uv@v6` with `enable-cache: true`. The cache key automatically incorporates `uv.lock` so it invalidates correctly on dep changes. For matrix runs:

```yaml
- uses: astral-sh/setup-uv@v6
  with:
    python-version: ${{ matrix.python }}
    enable-cache: true
    cache-dependency-glob: "uv.lock"
- run: uv sync --locked --all-extras --group dev
- run: uv run pytest --cov
```

Sources: [docs.astral.sh/uv/guides/integration/github](https://docs.astral.sh/uv/guides/integration/github/), [github.com/astral-sh/setup-uv](https://github.com/astral-sh/setup-uv).

### 4.4 Concurrency / cancel-in-progress

Always:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

Saves money, saves time, free win.

### 4.5 Required checks for PRs

Gate on (in order of fail-fastness):

1. `ruff check` (sub-second).
2. `ruff format --check` (sub-second).
3. `pyright` (a few seconds for 3K LOC).
4. `pytest` matrix (the bulk of the time).
5. `coverage --fail-under=75`.
6. `bandit -r src/forge -ll` (medium+ severity only — see section 10).

Don't gate on `mkdocs build` — broken docs shouldn't block code merges (warn instead).

### 4.6 Pre-commit in CI

Run `pre-commit run --all-files` in CI as a separate fast job. It catches things contributors skipped (or whose hooks weren't installed). Use `pre-commit/action@v3` or just `uv run pre-commit run --all-files`.

### 4.7 Publishing to PyPI: OIDC trusted publishing

If/when Forge publishes to PyPI, **never use a long-lived API token in `secrets`**. Use OIDC trusted publishing:

```yaml
permissions:
  id-token: write
  contents: read
steps:
  - uses: pypa/gh-action-pypi-publish@release/v1
    # No username/password — uses OIDC
```

Configure the trusted publisher on PyPI side: project name, GitHub owner/repo, workflow filename, environment name (use a `release` environment with required reviewers as an extra gate). PyPI now also produces Sigstore-signed attestations automatically via OIDC, no extra config required.

Source: [docs.pypi.org/trusted-publishers](https://docs.pypi.org/trusted-publishers/), [github.com/pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish).

### 4.8 Security workflows: Dependabot, CodeQL, OSSF Scorecard

- **Dependabot**: enable for `pip` ecosystem (it understands `uv.lock` since 2025) and `github-actions`. One PR per dep update, weekly cadence.
- **CodeQL**: GitHub's native SAST, free for public repos. Add the default Python config (`github/codeql-action/init` + `analyze`). Catches taint-flow bugs that ruff/bandit miss.
- **OSSF Scorecard**: weekly scheduled action that scores your repo on 18+ best-practice checks (branch protection, signed releases, pinned deps, etc.). Hooks into Dependabot already. Adopt later, after the basics — it's a polish thing, not a correctness thing.

Sources: [Medium 2026 Dependabot+CodeQL guide](https://medium.com/@syedalinaqihasni/stay-ahead-of-vulnerabilities-a-guide-to-github-dependabot-and-codeql-80c02e77d0da), [ossf/scorecard](https://github.com/ossf/scorecard).

### 4.9 Reusable workflows

Don't bother for a single-repo project. The complexity tax of `workflow_call` is only worth it if you have 3+ repos sharing a release pipeline.

---

## 5. Pre-commit hooks

Recommended `.pre-commit-config.yaml` for Forge in 2026:

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

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.12   # match the ruff version pinned in dependency-groups.dev
    hooks:
      - id: ruff-check
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.0
    hooks:
      - id: gitleaks
```

Notes on ordering: ruff-check **must** run before ruff-format. `--fix` rewrites code, formatting depends on the rewritten output.

**Don't add mypy/pyright as a pre-commit hook.** Type checking is too slow to put in front of every commit (3-15s for Forge), and pre-commit hooks that take >2s break the flow. Run pyright in CI only.

For the same reason, don't add pytest as a pre-commit hook. Tests in CI, not on commit.

**Conventional commits hook**: if you adopt conventional commits (see section 9), add `commitizen` as a `commit-msg` hook. Else skip.

Sources: [github.com/astral-sh/ruff-pre-commit](https://github.com/astral-sh/ruff-pre-commit), [pydevtools pre-commit guide](https://pydevtools.com/handbook/how-to/how-to-set-up-pre-commit-hooks-for-a-python-project/).

---

## 6. Async patterns and performance

### 6.1 Structured concurrency: TaskGroup over gather

`asyncio.TaskGroup` (3.11+) is strictly better than `asyncio.gather` for Forge's scheduler:

- If any subtask raises, **all siblings get cancelled** automatically. With `gather(return_exceptions=False)` you get one exception and the others keep running until they finish.
- Exceptions from multiple subtasks are wrapped in `ExceptionGroup` so you see all of them.
- Cancellation propagates correctly down the tree — no orphan tasks.

For Forge's `execute_session` loop (the wave-based parallel sprint runner), TaskGroup is the right primitive:

```python
async with asyncio.TaskGroup() as tg:
    for sprint in wave:
        tg.create_task(execute_sprint(sprint, ctx, session.id))
```

If one sprint blows up irrecoverably, the others get cancelled and the whole wave fails fast — which is what you want for a budget-controlled session.

Don't add `anyio` unless you decide to support Trio. anyio is excellent (it's the stdlib of structured concurrency), but it's a third dep that violates Forge's two-deps rule. asyncio.TaskGroup gives you ~80% of anyio's value for zero deps.

Sources: [Python 3.14 asyncio docs](https://docs.python.org/3/library/asyncio-task.html), [Why TaskGroup matters in 3.11](https://www.dataleadsfuture.com/why-taskgroup-and-timeout-are-so-crucial-in-python-3-11-asyncio/).

### 6.2 Timeouts: asyncio.timeout over wait_for

`asyncio.timeout()` (3.11+) is a context manager that composes with structured concurrency:

```python
async with asyncio.timeout(TASK_TIMEOUT_SECONDS):
    result = await generator.generate(sprint, memory, wt_path)
```

vs the older `await asyncio.wait_for(coro, timeout=N)`. Both work, but `timeout()` plays nice with TaskGroup and you can reset the deadline mid-flight (`timeout.reschedule()`). Use `timeout()` everywhere new; leave `wait_for` only where you have a one-shot coroutine and don't care about composition.

### 6.3 Cancellation handling

Two rules:

1. `asyncio.CancelledError` extends `BaseException` (not `Exception`). Don't catch `Exception` and assume you've caught everything. If you have cleanup, use `try/finally` or catch `CancelledError` explicitly and **re-raise**:
   ```python
   try:
       await long_running_op()
   except asyncio.CancelledError:
       await cleanup()
       raise   # CRITICAL — never swallow CancelledError
   ```
2. `asyncio.shield()` exists for the rare case where a coroutine must finish even if the caller is cancelled (e.g. flushing a partial DB write). Use sparingly — overuse leads to unkillable tasks.

For Forge specifically: when a sprint is cancelled (user clicked Cancel in the UI, or budget exhausted mid-wave), the worktree cleanup must run even on cancellation. That's a `try/finally` around the worktree lifecycle:

```python
wt_path = await worktree.create(sprint.id)
try:
    return await execute_sprint_inner(sprint, wt_path)
finally:
    await worktree.cleanup(sprint.id)
```

Source: [docs.python.org asyncio.CancelledError](https://docs.python.org/3/library/asyncio-task.html), [SuperFastPython asyncio.shield](https://superfastpython.com/asyncio-shield/).

### 6.4 Subprocess: avoid stdout deadlocks

Forge's `claude_code.py` and `ollama.py` executors spawn subprocesses and read their output. The deadlock pattern: if you call `proc.wait()` before draining stdout/stderr, and the child writes more than the OS pipe buffer (~64KB), the child blocks on write, you block on wait, deadlock.

Always use `proc.communicate()` (drains both pipes concurrently) or wrap in `asyncio.wait_for(proc.communicate(), timeout=...)`. Forge's current code looks correct on this front — keep it that way.

### 6.5 SQLite: stay sync

Forge currently uses sync `sqlite3` from async code. This is the right call. `aiosqlite` runs the same sync calls on a thread pool, so for a small embedded DB you get worse latency (~15× slower for `fetchone`) and the same throughput. The only reason to use aiosqlite is if you have a high-concurrency workload that genuinely overlaps queries — Forge does not, and SQLite's single-writer lock would serialize them anyway.

Pattern: keep DB calls sync, run them inside `asyncio.to_thread()` if you find a hot path that's blocking the event loop. For most operations (single-row reads, occasional writes), the call returns in microseconds and blocking the loop briefly is fine.

Source: [aiosqlite issue #34 perf](https://github.com/omnilib/aiosqlite/issues/34).

### 6.6 WebSocket: ship-shape patterns for the `websockets` lib

The `websockets` library handles the hard parts (backpressure, ping/pong, close framing) automatically since v15. For Forge's UI server:

- **Bind 127.0.0.1** (already required by spec). Library default is all interfaces — explicitly pass `host="127.0.0.1"`.
- **Ping interval**: default 20s ping with 20s pong timeout. Fine for localhost. Don't disable.
- **Backpressure**: if you broadcast to a slow client, the library's `StreamReader`/`StreamWriter` propagates backpressure to TCP. Wrap broadcasts in `asyncio.wait_for(ws.send(msg), timeout=5.0)` so a stuck client doesn't pin the daemon.
- **Graceful shutdown**: install SIGTERM/SIGINT handlers that send close frames (`code=1001` "going away") to all clients before tearing down. Already in your security spec — implement it.

Source: [websockets.readthedocs.io](https://websockets.readthedocs.io/), [oneuptime 2026 graceful shutdown](https://oneuptime.com/blog/post/2026-02-02-websocket-graceful-shutdown/view).

---

## 7. Logging, observability, error handling

### 7.1 Logging library: stdlib + `logging.config.dictConfig`, plus `python-json-logger` if you want JSON

The 2026 landscape: structlog wins on performance (~2× faster than stdlib for JSON), loguru wins on DX (zero-config), stdlib wins on universality (works in every dependency, no surprises). For Forge specifically, the answer is **stdlib + a JSON formatter** because:

1. Forge has a hard "two pip deps" rule. structlog is a third dep.
2. Forge already streams events over WebSocket as JSON — you'll be hand-formatting structured records anyway, so the value-add of structlog's processor pipeline is reduced.
3. stdlib `logging` interoperates with every library you'll ever import.

If you're willing to add one dep, `structlog` is the right choice — it makes context injection (request IDs, sprint IDs, session IDs) trivial via `contextvars`. The "context follows the task" property is what you want for an async daemon.

Decision rule: if you imagine the WebSocket stream as your primary observability surface (which Forge's spec implies), keep stdlib. If you imagine a CLI user tail-ing a `.forge/forge.log` file, adopt structlog.

For now: stdlib + JSON formatter. Concrete config:

```python
import logging
import logging.config

LOG_CONFIG = {
    "version": 1,
    "formatters": {
        "json": {
            "()": "logging.Formatter",  # or python-json-logger
            "format": '{"ts":"%(asctime)s","lvl":"%(levelname)s","mod":"%(name)s","msg":"%(message)s"}',
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

Sources: [Better Stack 2026 logging](https://betterstack.com/community/guides/logging/best-python-logging-libraries/), [BSWEN structlog vs stdlib](https://docs.bswen.com/blog/2026-04-29-structlog-vs-stdlib-logging/), [Dash0 2026 guide](https://www.dash0.com/guides/python-logging-libraries).

### 7.2 Tracing (OpenTelemetry): skip for now

OpenTelemetry Python is mature and has solid asyncio instrumentation. For Forge, **skip**: the daemon is local-first, the user is the developer, and exporting traces to a backend nobody runs gives zero value. The audit-log JSONL file (next section) gives you the same insights at 1% of the complexity.

Adopt OTel later if/when Forge grows a hosted/team mode. Until then it's complexity tax.

Source: [opentelemetry.io/docs/languages/python](https://opentelemetry.io/docs/languages/python/).

### 7.3 Audit log (JSONL trace file)

The pattern OpenHands uses, and which Forge should adopt:

- Every agent action (planner decision, generator subprocess, evaluator verdict, KB read/write) appends one JSON line to `.forge/sessions/<session_id>/trace.jsonl`.
- Schema: `{"ts": ..., "type": "...", "session_id": "...", "sprint_id": "...", "data": {...}}`.
- Used for: post-mortem debugging, the SessionHistory UI panel, the "what did Forge actually do" question.

Trivial to implement (a single `append_trace_event(type, data)` helper that stdlib-logs to a session-specific file handler), and it pays for itself the first time you debug a multi-hour session.

### 7.4 Error taxonomy

Forge already classifies errors in the schema (`error_category`). Make sure the error type is set consistently from the catch site:

```python
class ForgeError(Exception):
    """Base for all Forge errors."""

class ExecutorError(ForgeError):
    category: str = "runtime"  # subclass overrides

class TimeoutError(ExecutorError):
    category = "timeout"

class DependencyError(ExecutorError):
    category = "dependency"

# etc.
```

Use `raise ... from e` (PEP 3134) to chain causes — preserves the original traceback when you wrap.

### 7.5 Sentry: skip

Forge is local-first and explicitly anti-telemetry. Don't add Sentry or any other crash reporter. The audit log + a `forge logs` command is enough.

---

## 8. Documentation tooling

### 8.1 MkDocs Material (with caveat)

For Forge's docs (`docs/architecture.md`, `docs/memory-system.md`, etc. plus a planned API reference), the right answer in 2026 is **MkDocs Material with mkdocstrings**. Reasons:

- Markdown-native (Forge's docs are already markdown).
- `mkdocs serve` live-reloads on save (Sphinx requires `make html` rebuilds).
- Material theme looks polished off the shelf — no theming work.
- `mkdocstrings-python` auto-generates API reference from docstrings.

**The 2026 caveat**: the maintainers of MkDocs Material and mkdocstrings have started a successor project called **Zensical**, intended to replace MkDocs's aging foundation. Zensical is in alpha and MkDocs Material will be minimally maintained until late 2026. This means:

- Adopt MkDocs Material now if you need docs *now* — your config will likely port to Zensical.
- If you can defer docs by 6-9 months, watch Zensical and adopt that instead.

Sphinx is the alternative if you want intersphinx-style cross-project linking and you write libraries primarily. For Forge (an application), Material is easier and looks better.

Sources: [MkDocs vs Sphinx 2026](https://www.pythonsnacks.com/p/python-documentation-generator), [mkdocstrings.github.io](https://mkdocstrings.github.io/).

### 8.2 Docstring style: Google

mkdocstrings supports Google style natively (NumPy and reST require extra config). Type hints already encode the types — docstrings should focus on **why** and **edge cases**, not parameter types. Good rule: if the docstring repeats the type annotation, delete the type from the docstring.

```python
def add(self, content: str, source: str | None = None, confidence: float = 0.5) -> int:
    """Insert a knowledge item, returning its row ID.

    Deduplicates against existing content via case-insensitive match.
    If a duplicate is found, increments its `times_applied` counter
    and returns the existing ID.

    Raises:
        ValueError: if content exceeds 500 chars (KB items are one-liners).
    """
```

### 8.3 API reference generation

`mkdocstrings-python` is the answer with MkDocs. It reads docstrings, type hints, and source directly — no separate `.rst` files like Sphinx requires.

Adopt only when Forge has a stable public API surface to document (the CLI today, plus possibly the WebSocket protocol). Internal modules don't need API docs.

---

## 9. Versioning and releases

### 9.1 SemVer + git-tag-derived versions

Use `hatch-vcs` (which wraps setuptools-scm) so the package version comes from git tags:

```toml
[project]
name = "forge"
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.hooks.vcs]
version-file = "src/forge/_version.py"
```

Tag `v0.2.0` → wheel is version `0.2.0`. Tag with extra commits → `0.2.0.post3+g<sha>`. Free, deterministic, no manual version bumps.

Sources: [setuptools-scm.readthedocs.io](https://setuptools-scm.readthedocs.io/), [hatch-vcs on PyPI](https://pypi.org/project/hatch-vcs/).

### 9.2 CHANGELOG: Keep a Changelog format

Maintain `CHANGELOG.md` in [Keep a Changelog](https://keepachangelog.com/) format. Sections: Added / Changed / Deprecated / Removed / Fixed / Security. Tag-driven release notes (one section per version).

### 9.3 Conventional Commits + commitizen — adopt later

If/when contributors arrive, adopt conventional commits (`feat:`, `fix:`, `chore:`, etc.) with `commitizen` enforcing the pattern via a commit-msg hook. The big win is automated CHANGELOG generation: `cz bump` reads commits since the last tag and builds the changelog entries.

For a solo-developer phase, this is overkill. Adopt when you have your second contributor.

`python-semantic-release` is the alternative — it can build a fully automated PR-based release flow. More moving parts than commitizen; recommended only if you publish to PyPI on every merge to main.

Sources: [conventionalcommits.org](https://www.conventionalcommits.org/en/v1.0.0/), [commitizen-tools.github.io/commitizen](https://commitizen-tools.github.io/commitizen/), [python-semantic-release on GitHub](https://github.com/python-semantic-release/python-semantic-release).

---

## 10. Security hygiene

### 10.1 Dependency scanning: pip-audit and Dependabot

`pip-audit` reads your installed packages (or `uv.lock`) and queries the PyPA Advisory Database. Run it in CI:

```yaml
- run: uv run pip-audit --strict
```

Dependabot complements it by opening PRs for upgrades. Both are low-effort wins.

### 10.2 Secrets scanning: gitleaks (in pre-commit) + GitHub secret scanning

`gitleaks` as a pre-commit hook prevents accidental commits of API keys. GitHub's native secret scanning catches anything that slipped through. Free for public repos.

### 10.3 SBOM: cyclonedx-bom on releases

Generate a Software Bill of Materials on each release and attach it to the GitHub Release artifacts:

```yaml
- run: uvx cyclonedx-bom --requirement uv.lock -o forge-sbom.json
- uses: softprops/action-gh-release@v2
  with:
    files: forge-sbom.json
```

Worth it for supply-chain transparency. Source: [github.com/CycloneDX/cyclonedx-python](https://github.com/CycloneDX/cyclonedx-python).

### 10.4 bandit: high-value, given the subprocess surface

Forge has a `subprocess` and a `git worktree` and a websocket and an SQLite — exactly the surface bandit was built for. Run it in CI on `medium` confidence and `medium` severity:

```bash
bandit -r src/forge --severity-level medium --confidence-level medium
```

Some rules will fire on legitimate Forge code (`B404 import subprocess`, `B603 subprocess without shell`, `B608 SQL string formatting`). Whitelist them in `.bandit` or `pyproject.toml` `[tool.bandit]` with a comment explaining why each is safe (the spec already says: argument lists only, no `shell=True`, alphanumeric-validated worktree names, parameterized SQL).

Source: [github.com/PyCQA/bandit](https://github.com/PyCQA/bandit), [helpnetsecurity bandit 2026](https://www.helpnetsecurity.com/2026/01/21/bandit-open-source-tool-find-security-issues-python-code/).

Note: ruff's `S` rule group covers ~80% of bandit's checks at much higher speed (see section 2.1). Run ruff `S` on every commit, run standalone bandit in CI weekly. Different tools, complementary coverage.

---

## 11. Forge engineering checklist — adopt now / adopt later / skip

| Area | Recommendation | Why |
|---|---|---|
| **Adopt now** | | |
| pyproject.toml as sole config | Adopt | All tools support it, removes setup.py/cfg/requirements |
| uv as workflow tool | Adopt | 10-100× faster, manages Python, universal lockfile |
| hatchling as build backend | Adopt | Boring, stable, future-proof |
| Commit `uv.lock` | Adopt | Reproducible across contributors and CI |
| Rename `daemon/` → `src/forge/` | Adopt | Owns the namespace; tests run against installed copy |
| `[project.scripts] forge =` | Adopt | Cross-platform CLI entry point |
| Ruff (check + format) | Adopt | One tool replaces black + isort + flake8 + pyupgrade |
| Ruff `ASYNC` rule group | Adopt | Catches sync-in-async bugs that crash the daemon |
| pyright (standard mode) | Adopt | Best editor DX; mature; fast enough |
| pytest-asyncio strict mode | Keep | Already correct |
| pytest config in pyproject | Adopt | Markers, strict-markers, strict-config, filterwarnings=error |
| `tests/conftest.py` | Adopt | Mock executors, tmp_db, frozen_time fixtures |
| Branch coverage, threshold 75% | Adopt | Realistic, gates on the right thing |
| Hypothesis for parsers | Adopt | Planner JSON, evaluator PASS/FAIL, KB dedup |
| Syrupy for prompt assembly | Adopt | Reviewable diffs on prompt changes |
| respx for httpx mocking | Adopt | Fast, deterministic, no cassette staleness |
| GitHub Actions: 3.11/3.12/3.13 × ubuntu/macOS | Adopt | Drop 3.9, drop Windows |
| `astral-sh/setup-uv@v6` with cache | Adopt | Lockfile-keyed cache |
| `concurrency: cancel-in-progress` | Adopt | Free CI cost savings |
| Pre-commit (ruff + std hooks + gitleaks) | Adopt | Fast feedback, no mypy/pytest in pre-commit |
| asyncio.TaskGroup in scheduler | Adopt | Replaces gather; correct cancel semantics |
| asyncio.timeout() over wait_for | Adopt | Composes with TaskGroup |
| stdlib logging + JSON formatter | Adopt | Within two-deps rule, ergonomic enough |
| JSONL audit log per session | Adopt | Free observability for local-first daemon |
| `raise ... from e` everywhere | Adopt | Preserves causal chain |
| `try/finally` around worktree lifecycle | Adopt | Cleanup must run on cancellation |
| Error taxonomy (ForgeError hierarchy) | Adopt | Already implied by `error_category` schema |
| SemVer + hatch-vcs from git tags | Adopt | Removes manual version bumping |
| CHANGELOG.md (Keep a Changelog) | Adopt | One Markdown file, lasts forever |
| pip-audit in CI | Adopt | Low effort, real value |
| gitleaks pre-commit hook | Adopt | Catches accidental key commits |
| ruff S rules | Adopt | 80% of bandit at 100× speed |
| **Adopt later** | | |
| ty (Astral type checker) | Evaluate Q3 2026 | Wait for >70% spec conformance |
| MkDocs Material + mkdocstrings | Adopt when API stabilizes | Watch Zensical successor |
| OIDC PyPI publishing | Adopt at first PyPI release | No tokens in secrets |
| Dependabot + CodeQL | Adopt at first public release | Free for public repos |
| Conventional Commits + commitizen | Adopt at second contributor | Solo overkill |
| cyclonedx-bom on releases | Adopt at first PyPI release | Supply-chain transparency |
| bandit (standalone) in CI | Adopt within 1 month | Subprocess surface warrants it |
| OSSF Scorecard | Adopt at v1.0 | Polish layer |
| **Skip** | | |
| Black | Skip | Ruff format does it |
| isort | Skip | Ruff `I` rule does it |
| Poetry / PDM | Skip | uv has won |
| `from __future__ import annotations` | Skip | Deprecated in 3.14, drop floor to 3.10+ instead |
| `select = ["ALL"]` in ruff | Skip | New rules will randomly fail CI |
| pydocstyle (`D`) globally | Skip | Forge is a daemon, not a library |
| anyio | Skip | Three deps, asyncio.TaskGroup gives 80% of value |
| aiosqlite | Skip | Sync sqlite3 is faster for embedded WAL |
| structlog | Skip (for now) | Stdlib + JSON suffices, two-deps rule |
| loguru | Skip | Same reason |
| OpenTelemetry | Skip (for now) | Local-first, JSONL audit log replaces it |
| Sentry / crash reporting | Skip | Local-first, anti-telemetry |
| vcrpy / cassette HTTP recording | Skip | respx is enough; cassettes go stale |
| Sphinx | Skip | MkDocs Material wins for an application |
| python-semantic-release | Skip | Too automated for solo dev; commitizen later |
| Reusable GHA workflows | Skip | Single repo doesn't justify it |
| Windows CI | Skip | <5% of users, sustained tax |
| LangChain / agent frameworks | Skip | Already in `What NOT to build` |

---

## Sources

Packaging and project layout:
- [PEP 621 – Storing project metadata in pyproject.toml](https://peps.python.org/pep-0621/)
- [packaging.python.org – Writing your pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [packaging.python.org – src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [scopir.com – Best Python Package Managers 2026](https://scopir.com/posts/best-python-package-managers-2026/)
- [dasroot.net – Python Packaging Best Practices 2026](https://dasroot.net/posts/2026/01/python-packaging-best-practices-setuptools-poetry-hatch/)
- [pydevtools – uv complete guide](https://pydevtools.com/handbook/explanation/uv-complete-guide/)
- [Chris Evans – Python build backends in 2025](https://medium.com/@dynamicy/python-build-backends-in-2025-what-to-use-and-why-uv-build-vs-hatchling-vs-poetry-core-94dd6b92248f)
- [docs.astral.sh – uv managing dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- [pyOpenSci – package structure guide](https://www.pyopensci.org/python-package-guide/package-structure-code/python-package-structure.html)
- [KDnuggets – Python project setup 2026: uv + Ruff + Ty + Polars](https://www.kdnuggets.com/python-project-setup-2026-uv-ruff-ty-polars)

Linting, formatting, type checking:
- [docs.astral.sh – Ruff configuration](https://docs.astral.sh/ruff/configuration/)
- [docs.astral.sh – Ruff formatter](https://docs.astral.sh/ruff/formatter/)
- [astral.sh blog – The Ruff formatter](https://astral.sh/blog/the-ruff-formatter)
- [pydevtools – Ruff complete guide](https://pydevtools.com/handbook/explanation/ruff-complete-guide/)
- [astral.sh blog – ty type checker](https://astral.sh/blog/ty)
- [pydevtools – mypy/pyright/ty comparison](https://pydevtools.com/handbook/explanation/how-do-mypy-pyright-and-ty-compare/)
- [InfoWorld – Pyrefly and ty compared](https://www.infoworld.com/article/4005961/pyrefly-and-ty-two-new-rust-powered-python-type-checking-tools-compared.html)
- [sinon.github.io – Future Python type checkers conformance](https://sinon.github.io/future-python-type-checkers/)
- [PEP 649 – Deferred Evaluation Of Annotations](https://peps.python.org/pep-0649/)
- [PEP 749 – Implementing PEP 649](https://peps.python.org/pep-0749/)
- [Mergify – Python 3.14 PEP 649 breakage](https://mergify.com/blog/python-314-what-pep-649-actually-breaks/)

Testing:
- [pytest-asyncio – Concepts](https://pytest-asyncio.readthedocs.io/en/stable/concepts.html)
- [thinhdanggroup – pytest-asyncio v1 migration](https://thinhdanggroup.github.io/pytest-asyncio-v1-migrate/)
- [pytest-cov – Configuration](https://pytest-cov.readthedocs.io/en/latest/config.html)
- [Scientific Python – Coverage guide](https://learn.scientific-python.org/development/guides/coverage/)
- [Hypothesis docs](https://hypothesis.readthedocs.io/)
- [Anthropic Red – Property-Based Testing with Claude (2026)](https://red.anthropic.com/2026/property-based-testing/)
- [syrupy-project.github.io](https://syrupy-project.github.io/syrupy/)
- [github.com/lundberg/respx](https://github.com/lundberg/respx)
- [rogulski.it – pytest with respx and vcr](https://rogulski.it/blog/pytest-httpx-vcr-respx-remote-service-tests/)

CI/CD:
- [docs.astral.sh – uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)
- [github.com/astral-sh/setup-uv](https://github.com/astral-sh/setup-uv)
- [docs.pypi.org – Trusted publishers](https://docs.pypi.org/trusted-publishers/)
- [github.com/pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish)
- [github.com/astral-sh/ruff-pre-commit](https://github.com/astral-sh/ruff-pre-commit)
- [Medium – Dependabot and CodeQL guide (Mar 2026)](https://medium.com/@syedalinaqihasni/stay-ahead-of-vulnerabilities-a-guide-to-github-dependabot-and-codeql-80c02e77d0da)

Async, observability, errors:
- [docs.python.org – asyncio coroutines and tasks](https://docs.python.org/3/library/asyncio-task.html)
- [Why TaskGroup matters in 3.11](https://www.dataleadsfuture.com/why-taskgroup-and-timeout-are-so-crucial-in-python-3-11-asyncio/)
- [SuperFastPython – asyncio.shield](https://superfastpython.com/asyncio-shield/)
- [aiosqlite issue #34 – fetchone perf](https://github.com/omnilib/aiosqlite/issues/34)
- [websockets.readthedocs.io](https://websockets.readthedocs.io/)
- [oneuptime – WebSocket graceful shutdown 2026](https://oneuptime.com/blog/post/2026-02-02-websocket-graceful-shutdown/view)
- [Better Stack – Python logging libraries 2026](https://betterstack.com/community/guides/logging/best-python-logging-libraries/)
- [BSWEN – structlog vs stdlib logging 2026](https://docs.bswen.com/blog/2026-04-29-structlog-vs-stdlib-logging/)
- [Dash0 – Choosing a Python logging library 2026](https://www.dash0.com/guides/python-logging-libraries)

Documentation, releases, security:
- [pythonsnacks – MkDocs vs Sphinx](https://www.pythonsnacks.com/p/python-documentation-generator)
- [mkdocstrings.github.io](https://mkdocstrings.github.io/)
- [setuptools-scm.readthedocs.io](https://setuptools-scm.readthedocs.io/)
- [hatch-vcs on PyPI](https://pypi.org/project/hatch-vcs/)
- [conventionalcommits.org](https://www.conventionalcommits.org/en/v1.0.0/)
- [commitizen-tools.github.io/commitizen](https://commitizen-tools.github.io/commitizen/)
- [pip-audit on PyPI](https://pypi.org/project/pip-audit/)
- [helpnetsecurity – Bandit 2026](https://www.helpnetsecurity.com/2026/01/21/bandit-open-source-tool-find-security-issues-python-code/)
- [github.com/PyCQA/bandit](https://github.com/PyCQA/bandit)
- [github.com/CycloneDX/cyclonedx-python](https://github.com/CycloneDX/cyclonedx-python)
- [github.com/ossf/scorecard](https://github.com/ossf/scorecard)
