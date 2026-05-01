# Contributing to Forge

Thanks for considering a contribution. Forge is a solo-maintained open-source project; contributions are welcome but please read this document first so we agree on the bar.

## TL;DR

1. Open an issue **before** opening a non-trivial PR. Code is cheap; aligned design is precious.
2. Run the local quality gate (`bash scripts/pre-push.sh`) before pushing. CI is intentionally light — pre-push is authoritative.
3. Match the engineering standards at [docs/ENGINEERING_STANDARDS.md](docs/ENGINEERING_STANDARDS.md).
4. Adhere to the locked architectural decisions at [docs/DECISIONS.md](docs/DECISIONS.md). If your proposal contradicts a locked ADR, open a discussion first — the bar to supersede an ADR is high.

## Setup

```sh
git clone https://github.com/<owner>/forge.git
cd forge
./setup.sh    # uses uv if available, falls back to pip + venv
```

After setup:
```sh
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

This installs both pre-commit (fast, every commit) and pre-push (heavy gate, every push) hooks.

## What to work on

- **Issues labeled `good-first-issue`** or `help-wanted` are signals.
- **Bug reports** with a reproduction are always welcome.
- **Documentation improvements** are always welcome.
- **Performance / quality improvements** with benchmarks attached are always welcome.

## What NOT to work on without an issue first

- New agent frameworks as runtime deps (see [ADR-011](docs/DECISIONS.md#adr-011--no-agent-frameworks)). The answer is "no" unless the framework is replacing existing complexity, not adding it.
- Telemetry / analytics / crash reporting (see [ADR-007](docs/DECISIONS.md#adr-007--local-first-no-telemetry-kb-stays-in-forge)). Forge is local-first; we don't phone home.
- Cloud / hosted features in OSS scope (see [ADR-016](docs/DECISIONS.md#adr-016--sustainability-passive-donation-rail-no-pro-tier-in-v010-scope)). v0.1.0 is local-first only.
- Windows native support (see [ADR-013](docs/DECISIONS.md#adr-013--sandbox-git-worktrees-default-docker-as-opt-in-tier-skip-macos-sandbox-exec-skip-windows)). WSL works; native Windows does not.
- Vector embeddings on the knowledge base (see [ADR-012](docs/DECISIONS.md#adr-012--kb-design-sqlite-with-confidencedecaydedup-no-embeddings-on-kb-sqlite-vec-optional-on-episodic)). 200-item KB doesn't need them.

## Quality bar

Every PR must pass:

1. **`uv run ruff check`** — no warnings, no errors
2. **`uv run ruff format --check`** — fully formatted
3. **`uv run pyright`** (when installed) — type-check clean
4. **`uv run pytest -m 'not integration'`** — all unit tests pass
5. **Branch coverage on changed files** stays at or above the 80% project floor (when coverage CI lands)
6. **`bash scripts/pre-push.sh`** — full gate passes locally

The simplest workflow:
```sh
# fast iteration
uv run pytest tests/test_<module>.py -v

# before pushing
bash scripts/pre-push.sh
```

Conditional bypass env vars (use sparingly, document in PR):
- `SKIP_SCHEMA_PARITY=1` — skip schema-parity check (cite a reason in the PR)
- `SKIP_DOCS_AUDIT=1` — skip frontmatter validation
- `RUN_INTEGRATION=1` — also run integration tests (needs Ollama)
- `RUN_SWEBENCH_SMOKE=1` — run a 5-task SWE-bench smoke

## Code style

- **Type hints everywhere** in `daemon/`. Pyright in `standard` mode is the bar.
- **Comments only when WHY is non-obvious.** No "this loops over the items" — the code says that. Yes "this seems redundant but bypasses a bug in vLLM tool-call parser when temperature > 0.5 (see #142)."
- **Async patterns**: `asyncio.TaskGroup` over `asyncio.gather`; `asyncio.timeout()` over `wait_for`; always re-raise `CancelledError` after cleanup; `try/finally` around worktree lifecycle.
- **Logging**: stdlib `logging` only. No `print()` in `daemon/` (lint enforces). Per-session JSONL audit log to `.forge/sessions/<id>/trace.jsonl`.
- **Errors**: use the `ForgeError` taxonomy; chain causes with `raise ... from e`; never swallow `Exception` blindly.
- **No `# type: ignore` without inline reason and issue link.**

See [docs/ENGINEERING_STANDARDS.md §12](docs/ENGINEERING_STANDARDS.md#12-forge-specific-code-conventions) for the full list.

## PR conventions

### Title

Short imperative, optional prefix (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`). Under 70 chars. Example:
- `fix: planner JSON parser drops trailing commas`
- `feat: cross-family evaluator selection in classifier`
- `docs: add ADR-017 for sandbox-bwrap tier`

### Description

```markdown
## Summary
- 1–3 bullets on what changed and why

## Test plan
- [ ] bulleted markdown checklist of TODOs for testing

## Linked issue
Closes #123
```

### Squash vs merge

- **Feature branches → `develop`**: squash on merge
- **`develop` → `main`**: merge commit (preserves boundary; main has linear history)
- Direct push to `main` is blocked at hook + branch protection

## Schema parity rule

If your PR touches any of these five files:
- `daemon/db.py` (SQLite schema)
- `daemon/models.py` (dataclasses)
- `daemon/ws_server.py` (WebSocket event shapes)
- `ui/lib/types.ts` (TypeScript WS types)
- `daemon/schemas/` (JSON schemas for sprint contracts / evaluator verdicts)

… then `scripts/check-schema-parity.py` runs in pre-push and you must keep all five surfaces in sync. The schema parity rule is the single biggest production-incident preventer in this codebase. See [ADR-005](docs/DECISIONS.md#adr-005--schema-parity-rule-across-5-surfaces).

## Reporting bugs

Open a GitHub issue with:
- Forge version (`uv run forge --version` or git SHA)
- Python version (`python --version`)
- OS (macOS version / Linux distro)
- Hardware (RAM, GPU if relevant)
- Models loaded (`ollama list`)
- Minimal reproduction
- Expected vs actual behavior
- Relevant logs from `.forge/forge.log`

For security issues, see [SECURITY.md](SECURITY.md) — do **not** open a public issue.

## Architecture changes (ADR process)

If you propose a change that contradicts a locked ADR in [docs/DECISIONS.md](docs/DECISIONS.md):

1. Open a GitHub Discussion first
2. State the existing ADR you're proposing to supersede
3. Provide rationale + alternatives + trade-offs (the ADR-template)
4. Wait for maintainer ACK before opening a PR

ADRs may be revisited but the bar is high. "I prefer a different style" is not a reason. "Anthropic shipped X, here's how it changes the analysis" is a reason.

## Commit messages

- Use conventional-commit-style prefixes by convention (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `track:`). Not strictly enforced.
- One logical change per commit. Squashable.
- Reference issues with `#NNN` in the body.
- Forge's pattern: end commits with a `Co-Authored-By:` line if AI-assisted.

## License

By contributing, you agree that your contributions will be licensed under the MIT License (see [LICENSE](LICENSE)). You retain copyright on your contributions; the project is governed by MIT.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind. Disagreement is fine; disrespect is not.

## Questions?

- **GitHub Discussions** for architecture / design / "is this worth working on" questions
- **Discord** (link in README) for real-time
- **Issues** for bugs and concrete feature requests

Thanks for reading. Looking forward to your PR.
