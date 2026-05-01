# Forge — Release Gap Analysis

> **Status**: live document. Captures the gap between Forge v0.1.0-alpha (current) and a v0.1.0 release-ready state.
> Last synced: 2026-05-01 against the post-code-review-fix-sweep state (644 tests passing).

This is the **kill list** — every item must close, downgrade to documented limitation, or escalate to ADR before v0.1.0 ships.

---

## Release gates summary

| Gate | Status | Owner |
|---|---|---|
| Code-review fix sweep complete | 🟢 done | shipped 2026-05-01 |
| Test suite green (≥600 passing) | 🟢 done | 644/645 |
| Pre-push gate green | 🟢 done | scripts/pre-push.sh |
| Documentation refresh (this sprint) | 🟢 done | README, INSTALL, CONNECTORS, SKILLS, PLUGIN_DEVELOPMENT, LLMS, SECURITY_AUDIT, GAP_ANALYSIS |
| Install script + uninstall script | 🟢 done | install.sh, uninstall.sh |
| Plugin sandbox (skills/connectors/llm-adapters) | 🟡 in progress | spec done; code in progress |
| 15 security layers from audit | 🟡 partial | 4 of 15 fully shipped, 11 planned |
| Pip-audit / semgrep / bandit in CI | ❌ not yet | needs CI workflow update |
| SWE-bench Verified ≥30% on 50-task subset | ❌ not run | hard kill criterion (ADR-015) — Phase 2 W8 deadline |
| External pen test | ❌ not scoped | post-v0.1.0-alpha |

## Gap matrix — by category

### Functional gaps (must close)

| # | Gap | Severity | Effort | Sprint |
|---|---|---|---|---|
| F1 | Native plugin runtime (`forge_plugin_api` package) | HIGH | 2 weeks | v0.1.0 |
| F2 | Plugin sandbox (subprocess + cap enforcement) | HIGH | 1 week | v0.1.0 |
| F3 | Manifest hash pinning + signed verification | HIGH | 3 days | v0.1.0 |
| F4 | LLM adapter plugin path (`~/.forge/llms/<name>/`) | MED | 3 days | v0.1.0 |
| F5 | `forge connectors` / `forge skills` / `forge llms` CLI subcommands | MED | 2 days | v0.1.0 |
| F6 | Browser dashboard polish (currently scaffold; ~600 LOC) | MED | 2 weeks | v0.1.0 |
| F7 | Lethal-trifecta capability graph in scheduler | HIGH | 3 days | v0.1.0 |
| F8 | Egress allow-list in worktree sandbox | HIGH | 4 days | v0.1.0 |
| F9 | Provenance-tagged context (`trust` labels in retriever) | HIGH | 3 days | v0.1.0 |
| F10 | Markdown / Unicode sanitizer on ingested data | MED | 2 days | v0.1.0 |
| F11 | Pre-egress secret redaction at model boundary | MED | 1 day | v0.1.0 |
| F12 | Append-only tool-call audit log | MED | 2 days | v0.1.0 |
| F13 | Anthropic prompt-cache key isolation | LOW | 1 day | v0.1.0 |
| F14 | WebSocket Origin header + CSRF token | MED | 1 day | v0.1.0 |

**Total functional gap: ~6 weeks of focused work.**

### Performance gaps

| # | Gap | Severity | Effort |
|---|---|---|---|
| P1 | First-token latency on Ollama path (cold start ~5s; want <1s warm) | LOW | tune `keep_alive` per role; partial — already done |
| P2 | Repomap regeneration cost on large repos (>10k files) | LOW | already cached; document |
| P3 | KB retrieval at 50k+ items — no tested benchmark | MED | benchmark + optionally enable sqlite-vec |
| P4 | Concurrent-sprint scaling on M-series 24GB (3+ Qwen3 generators OOMs) | MED | document hardware tiering; semaphore at 2 by default |

### Test coverage gaps

| # | Gap | Severity | Effort |
|---|---|---|---|
| T1 | E2E test: full session from `forge plan` to merge gate | HIGH | 3 days |
| T2 | Integration test: 3+ concurrent sprints with budget pressure → downgrade cascade fires | MED | 1 day |
| T3 | Property test: budget atomicity under N=1000 concurrent reservations | LOW | 0.5 day |
| T4 | Snapshot test: WebSocket protocol stays stable | MED | 1 day |
| T5 | Plugin sandbox escape test suite — try every known escape (path traversal, fork bomb, etc.) | HIGH | 2 days |
| T6 | Adversarial input fuzz: planner with malformed JSON inputs | LOW | 1 day |
| T7 | Cross-family evaluator regression test for every supported family | LOW | 1 day |

### Security audit gaps

(Detailed in [SECURITY_AUDIT.md](SECURITY_AUDIT.md). Summary:)

| Layer | Status | Effort |
|---|---|---|
| L1 — Provenance tags | 📅 planned | 3 days |
| L2 — MCP manifest pinning | 📅 planned | 3 days |
| L3 — Lethal-trifecta block | 📅 planned | 3 days |
| L4 — Egress allow-list | 📅 planned | 4 days |
| L5 — Unicode sanitizer | 📅 planned | 2 days |
| L6 — Cross-family hardening (extra) | 📅 planned | 2 days |
| L7 — Confirm-token binding | 📅 planned | 2 days |
| L8 — Cache isolation | 📅 planned | 1 day |
| L9 — KB quarantine | 📅 planned | 2 days |
| L10 — WS Origin + CSRF | 📅 planned | 1 day |
| L11 — Strict CSP | 📅 planned | 1 day |
| L12 — Plugin sandbox | 🔨 in progress | 1 week |
| L13 — Pre-egress redaction | 📅 planned | 1 day |
| L14 — Compaction guardrails | 📅 planned | 2 days |
| L15 — Tool-call audit log | 📅 planned | 2 days |

**Security layer total: ~5 weeks of focused work.** Some layers parallelize.

### CI / engineering gaps

| # | Gap | Severity | Effort |
|---|---|---|---|
| C1 | pip-audit in CI on every PR | HIGH | 2 hours |
| C2 | semgrep with `p/python p/security-audit p/owasp-top-ten` rulesets | HIGH | 4 hours |
| C3 | bandit run on `daemon/` | MED | 2 hours |
| C4 | dependabot.yml already present (verified ✓) | DONE | – |
| C5 | CodeQL workflow already present (verified ✓) | DONE | – |
| C6 | Coverage gate (≥80% on `daemon/`) | MED | 0.5 day |
| C7 | Schema parity script in CI | LOW | already exists; just wire to CI |
| C8 | Release workflow (build wheel, sign, attest provenance) | MED | 1 day |

### Documentation gaps

| # | Gap | Severity | Effort |
|---|---|---|---|
| D1 | Architecture diagrams (current text-only) | LOW | 0.5 day mermaid |
| D2 | Video / GIF demo of `forge plan` → `forge serve` flow | MED | 1 day |
| D3 | Migration guide from Aider / OpenHands / Continue | LOW | 1 day |
| D4 | Cookbook: 5 worked examples (Supabase + Vercel auth, Stripe webhooks, etc.) | MED | 2 days |
| D5 | API reference for `forge_plugin_api` (auto-generated from docstrings) | MED | 0.5 day |
| D6 | Threat model diagrams in SECURITY_AUDIT.md | LOW | 0.5 day |
| D7 | "Why not LangChain?" / "Why not CrewAI?" essay (decision rationale) | LOW | 0.5 day |

## Hard kill criterion (ADR-015)

**SWE-bench Verified ≥30% on 50-task subset by Phase 2 Week 8.**

Status: ❌ not run yet. Forge's open-weight thesis stands or falls on this number. If the number doesn't clear:

1. Pivot to claude-code-only (drops the open-weight differentiator; becomes "Claude Code with persistent memory")
2. Pivot to a narrower vertical (e.g., "Forge for Supabase + Vercel projects only")
3. Shut down

The eval harness skeleton is in `eval/swebench/`. Owner: TBD. Deadline: Phase 2 W8 (≈8 weeks from current Phase 1 W4).

## Sprint roadmap to v0.1.0

Working back from "release-ready":

### Sprint 5 — Install + docs refresh (✅ DONE this session)
- install.sh, uninstall.sh
- README, INSTALL, CONNECTORS, SKILLS, PLUGIN_DEVELOPMENT, LLMS, SECURITY_AUDIT, GAP_ANALYSIS

### Sprint 6 — Plugin runtime + sandbox (1 week)
- F1, F2, F3 — `forge_plugin_api` package, subprocess sandbox, manifest hashing
- L12 (plugin sandbox)
- T5 (sandbox escape tests)

### Sprint 7 — Connector ecosystem (1 week)
- F4, F5 — LLM adapter path, CLI subcommands
- 4 reference connectors: GitHub-via-MCP, Vercel-via-MCP, Postgres-via-MCP, SendGrid-native
- Plugin signing prototype

### Sprint 8 — Security layers 1–5 (1 week)
- L1 — Provenance tags
- L2 — MCP pinning
- L3 — Lethal trifecta
- L4 — Egress allow-list
- L5 — Unicode sanitizer

### Sprint 9 — Security layers 6–15 (1 week)
- L6–L15 (the rest)
- L13 — Pre-egress redaction
- L15 — Tool-call audit log

### Sprint 10 — CI gates + tests (3 days)
- C1, C2, C3 — pip-audit, semgrep, bandit in CI
- C6 — coverage gate
- T1, T2, T4 — E2E + integration + WS protocol snapshot

### Sprint 11 — UI polish (1 week)
- F6 — dashboard polish
- L11 — strict CSP
- D2 — demo GIF

### Sprint 12 — SWE-bench eval + kill criterion (1 week)
- Run 50-task SWE-bench Verified subset
- ≥30% → ship; <30% → triage

### Sprint 13 — Pre-release hardening (3 days)
- D1, D3, D4 — diagrams, migration guides, cookbook
- External pen test scoping

### v0.1.0 release ✅

**Total: ~7 weeks from current state to v0.1.0** (assuming 1 person full-time; longer with contributors merging in parallel).

## Accepted limitations (will not fix in v0.1.0)

- ❌ Multi-tenant deployment — Forge is local-first by ADR-007. A "Forge Cloud" tier may follow but is out of v0.1.0 scope.
- ❌ Native Windows — WSL2 supported; native Win32 deferred.
- ❌ Intel Mac primary support — works but slow; documented in INSTALL.md.
- ❌ Frontier API completeness — adapters cover Anthropic, OpenAI-compatible, Ollama. Cohere, Mistral La Plateforme native, Google Gemini direct: community plugins.
- ❌ Real-time collaboration — single-user dashboard only.
- ❌ Plugin registry / marketplace — planned for v0.2.0.

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SWE-bench number under 30% | MEDIUM | CRITICAL | Kill criterion forces decision; pivot paths defined |
| Composio AO / Devin v3 closes the niche before v0.1.0 | MEDIUM | HIGH | Trim weeks 1-4 surface that overlaps; double down on KB + open-weight (per April-30 freshness) |
| Ollama / vLLM tool-call reliability regresses | LOW | HIGH | Three-layer defense (native + xgrammar + BAML); tested |
| Plugin supply-chain attack via popular MCP server | MEDIUM | HIGH | Manifest pinning, capability scoping, lethal trifecta block |
| External pen test finds critical issue post-release | MEDIUM | HIGH | Scope pen test pre-v0.1.0; bug bounty post-v0.1.0 |
| Maintainer burnout (single-author bootstrap) | HIGH | HIGH | MIT license + clean engineering perimeter make takeover possible |

## Sign-off checklist for v0.1.0

- [ ] All HIGH-severity functional gaps closed (F1, F2, F3, F7, F8, F9)
- [ ] All HIGH-severity security layers shipped (L1, L2, L3, L4, L12, L15)
- [ ] All MEDIUM gaps either closed or documented as v0.2.0
- [ ] CI gates active (C1, C2, C3, C6)
- [ ] SWE-bench Verified ≥30% confirmed
- [ ] CHANGELOG cleaned and dated
- [ ] CONTRIBUTING.md reflects the plugin authoring path
- [ ] External pen test scoped (results may post-date release)
- [ ] Bug bounty rules drafted

When every box is checked, cut the v0.1.0 tag.
