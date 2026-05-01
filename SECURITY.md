# Security Policy

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately via one of:

- **GitHub Security Advisories** — preferred. Open a draft advisory at the repository's `Security` tab. GitHub keeps it private until disclosed.
- **Email** — `security@forge.dev` (configured at launch). PGP key fingerprint will be published in this file once available.

## What to include

- Affected version (Forge git SHA, Python version, OS)
- Hardware and model lineup if relevant
- Reproduction steps (minimal as possible)
- Impact assessment (what an attacker could do)
- Suggested mitigation if you have one

## Response timeline

| Stage | Target |
|---|---|
| Acknowledgement | within 72 hours |
| Initial triage + severity assessment | within 7 days |
| Fix scoped + ETA communicated | within 14 days |
| Public disclosure | coordinated with reporter; default 90 days from initial report |

The current maintainer is solo, so emergency response may be slower than enterprise norms — please be patient. Critical CVE-class issues are prioritized over feature work.

## Threat model — the short version

Forge is **local-first by design**. The agent runs on the developer's own machine using their own credentials. The threat model is:

| In scope | Out of scope |
|---|---|
| Agent makes a destructive mistake (rm, git push --force, schema migration on prod) | Agent is malicious / a supply-chain compromise on the *user* |
| Subprocess injection via crafted task descriptions | OS-level zero-days |
| Path traversal in worktree handling | Hardware-level attacks |
| WebSocket exposure beyond 127.0.0.1 | Threat actors with physical access |
| SQL injection into the SQLite KB | Quantum cryptanalysis |
| Sensitive data leaking into trace logs | DoS against localhost services |
| Credential exposure via subprocess env | Multi-tenant isolation (Forge is single-user by design) |

## Hardened defaults

These are non-negotiable security invariants per [docs/DECISIONS.md ADR-007](docs/DECISIONS.md#adr-007--local-first-no-telemetry-kb-stays-in-forge) and [CLAUDE.md security rules](CLAUDE.md):

1. **WebSocket binds 127.0.0.1 only.** Hardcoded; not configurable.
2. **No `shell=True`** in any subprocess call. Argument lists only.
3. **Worktree names**: alphanumeric + hyphens only (regex validated).
4. **Task descriptions**: null-byte / control-char strip; capped at 10 000 chars.
5. **Hard budget cap**: session cannot exceed `SESSION_BUDGET_USD`.
6. **No secrets in code**: API keys from env vars only, never logged.
7. **SQLite WAL mode** for safe concurrent reads.
8. **Git worktree cleanup** on exit via `atexit` + signal handlers.
9. **`.forge/` in `.gitignore`** at init.
10. **No `--dangerously-skip-permissions`** is ever set on Claude Code subprocesses.
11. **Evaluator never runs in the same worktree** as the generator. Read-only against the diff.
12. **Research content is context only** — never executed as code or commands.
13. **No telemetry, no crash reporting, no analytics, no phone-home** — all data stays in `.forge/`.
14. **Outbound credential redaction at every persistence boundary** (per [ADR-017](docs/DECISIONS.md#adr-017--outbound-credential-redaction-at-every-persistence--subprocess-boundary)). Trace JSONL, daemon log, KB writes, episodic `error`/`resolution`, and subprocess environments are all gated by `daemon/redact.py`. Patterns covered: Anthropic / OpenAI / GitHub / AWS / Slack / Stripe / Google API keys, JWT, Bearer headers, `.env` lines, PEM private keys, DB URL passwords. KB writes containing credentials are **rejected** rather than redacted (refuse-to-persist).
15. **Subprocess env is allowlisted, not denylisted** — `claude -p` / `ollama` subprocesses receive only `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_*`, `PATH`, `HOME`, git/SSH context, and a few locale vars. Unrelated env (AWS creds for an unrelated project, GH PATs for other repos, custom CI tokens) is dropped at subprocess spawn.

## Sandbox tiers

| Tier | Default | Threat model |
|---|---|---|
| `worktree` (default) | yes | Agent makes a mistake; trusted code |
| `--sandbox=docker` | opt-in | Untrusted dependency installs (npm postinstall, pip install) |
| `--sandbox=bwrap` (Linux only) | opt-in | Same as Docker, lighter weight |

macOS native sandboxing (`sandbox-exec`) is intentionally **not used** — Apple deprecated it on 15.4 and field reports describe brittle behavior. macOS users seeking stronger isolation should use Docker.

## Dependencies and supply chain

- `pip-audit` runs in CI on every PR
- Dependabot weekly for `pip` and `github-actions`
- `uv.lock` committed and signed
- CodeQL weekly + on push to `main`
- `gitleaks` in pre-commit hook
- SBOM generation (`cyclonedx-bom`) on release tags

If a dependency advisory affects Forge, expect a patch release within 48 hours of the advisory being verified.

## Outbound credential redaction (ADR-017)

Forge gates outbound data at five boundaries with regex-based redaction. Implementation: `daemon/redact.py`. The pattern catalog covers ~95% of common credential shapes; high-entropy custom tokens without recognizable structure can still slip through.

| Boundary | Behavior |
|---|---|
| Trace JSONL writes (`replay.append_event`) | All `data` payload string fields scrubbed; nested dicts/lists recursed |
| Daemon log (`forge.log`) | Optional `RedactionFilter` available for the `logging` config |
| KB writes (`db.add_knowledge`, including via MCP `forge_kb_add`) | **Refuses** to persist content containing credentials (returns `None`, logs a warning) |
| Episodic store (`db.save_episode`) | Free-text columns (`error`, `resolution`, `result`, `evaluator_feedback`, `task_description`) redacted at write time |
| Subprocess env (`claude_code.execute`) | Allowlist: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_*`, `PATH`, `HOME`, git/SSH context, locale; everything else dropped |

Patterns covered: Anthropic (`sk-ant-…`), OpenAI (`sk-…`, `sk-proj-…`), GitHub (`ghp_`, `github_pat_`), AWS (AKIA/ASIA + `aws_secret_access_key=…`), Slack (`xox[a-r]-…`), Stripe (`sk_live_…`), Google (`AIza…`), JWT, `Authorization: Bearer …`, `.env`-line patterns where LHS contains SECRET/TOKEN/PASSWORD/API_KEY, PEM private-key blocks, DB connection URLs.

**Not redacted by default**: outbound LLM prompts (`generator.execute`, `evaluator.execute`). Aggressive prompt redaction would mangle legitimate code. Users can opt in via `FORGE_REDACT_PROMPTS=1`.

## Known limitations

- **Single-user threat model.** Forge is not designed for shared / multi-tenant use. Don't run a Forge daemon on a server multiple users access.
- **No process-level sandboxing on macOS by default.** Use `--sandbox=docker`.
- **Trust boundary at `.claude/` inheritance.** Forge inherits MCP server configs from the user's `.claude/settings.json`. A compromised MCP server in the user's environment is treated as in-scope for that user.
- **Tool-call output is parsed, not validated against a schema by default.** Constrained decoding via xgrammar is wired up at session boundaries (planner JSON, evaluator verdict) but not on every tool call.

## Disclosed vulnerabilities

None as of v0.1.0 baseline. Will be listed here in CHANGELOG.md format once any are reported and fixed.

## Quarterly review checkbox

The redaction catalog and destructive-op classifier drift behind upstream changes (new credential prefixes, new cloud-CLI subcommands) if not reviewed periodically. Every quarter (Mar/Jun/Sep/Dec):

- [ ] Re-sync `daemon/redact.py` against [gitleaks default rules](https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml) — add any new credential patterns.
- [ ] Re-audit `daemon/safety.py` for new cloud-CLI subcommands worth blocking (aws, gcloud, az, kubectl, terraform, gh, vercel, supabase, stripe).
- [ ] Run `pip-audit --strict` on all installed extras (`forge[robust,batch,repomap,vector,mcp]`).
- [ ] Bump `requires-python` floor if a major version is EOL'd.
- [ ] Review any new ADRs in `docs/DECISIONS.md` for security implications.
- [ ] Verify `daemon/events.py::EventType` has entries for any new trace events (typo-safety guard from Task 3.3).
