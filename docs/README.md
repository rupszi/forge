---
status: live
owner: pal.megyes
last_reviewed: 2026-06-04
---

# Forge documentation index

Forge is a **local-first, free-by-default multi-agent coding orchestrator**: a
planner decomposes work, a generator writes code in a git worktree, and an
**evaluator on a different model family** grades it against explicit
done-criteria. It runs as a local browser dashboard (`forge serve`), keeps a
compounding SQLite knowledge base, and makes zero outbound calls by default.

New here? Read the [root README](../README.md) for the one-paragraph pitch, then
the **User Guide** below.

## Start here
- [USER_GUIDE.md](USER_GUIDE.md) — install → pull models → start → connect models → orchestrate → documents
- [../INSTALL.md](../INSTALL.md) — detailed install + troubleshooting
- [POSITIONING.md](POSITIONING.md) — what Forge is, what it isn't, and why
- [ROADMAP.md](ROADMAP.md) — what's shipped vs open for contributors (each item has a contract + entry point)

## Using Forge
- [configuration.md](configuration.md) — env vars, paths, knobs
- [CONNECTORS.md](CONNECTORS.md) — MCP + native tool integrations
- [SKILLS.md](SKILLS.md) — skills system + security sandbox
- [PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md) — build your own connector / skill
- [LLMS.md](LLMS.md) — add new model providers
- [../eval/swebench/README.md](../eval/swebench/README.md) — the SWE-bench kill gate: metric tiers, profiles, `forge bench`

## Architecture & design
- [architecture.md](architecture.md) — daemon structure, the three-agent pattern
- [harness-design.md](harness-design.md) — planner / generator / evaluator contracts
- [memory-system.md](memory-system.md) — the four-tier knowledge base
- [WEBSOCKET_PROTOCOL.md](WEBSOCKET_PROTOCOL.md) — complete client↔server message reference
- [DECISIONS.md](DECISIONS.md) — locked architectural decision records (ADRs)
- [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md) — the engineering bar: pre-push gate, schema parity, async patterns
- [PROMPTS_AND_GUARDRAILS.md](PROMPTS_AND_GUARDRAILS.md) — prompt structure + guardrails (G-LOC / G-RAM / G-AGT)

## Security
- [../SECURITY.md](../SECURITY.md) — how to report a vulnerability
- [SECURITY_AUDIT.md](SECURITY_AUDIT.md) — threat model + attack-class coverage
- [security.md](security.md) — security requirements reference
- [audits/2026-06-04-forge-studio/](audits/2026-06-04-forge-studio/REPORT.md) — latest audit (all findings closed)
- [audits/2026-06-03-forge-studio/](audits/2026-06-03-forge-studio/REPORT.md) — prior audit

## Comparison
- [COMPETITIVE_COMPARISON.md](COMPETITIVE_COMPARISON.md) — head-to-head with 18+ tools

## Live build status
- [FORGE_STUDIO_TRACKER.md](FORGE_STUDIO_TRACKER.md) — the live build tracker (single source of truth for status)
- [FORGE_STUDIO_BUILD.md](FORGE_STUDIO_BUILD.md) — the local-first ("Studio") build spec
- [GAP_ANALYSIS.md](GAP_ANALYSIS.md) — release gates + remaining work

## Project history & process (internal/historical)
These are planning and process artifacts kept for provenance — **not** user docs.
- [BUILD_PLAN.md](BUILD_PLAN.md), [DELIVERY_PLAN.md](DELIVERY_PLAN.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md) — phased build plans
- [SPRINT_6_PLAN.md](SPRINT_6_PLAN.md) — a sprint plan
- [HANDOVER.md](HANDOVER.md) — contributor handover snapshots
- [CODE_REVIEW.md](CODE_REVIEW.md) — review notes

## Research notes (raw)
- [research/competitive-landscape-and-architecture.md](research/competitive-landscape-and-architecture.md)
- [research/notes/](research/notes/) — raw research + review rounds (01–08)
