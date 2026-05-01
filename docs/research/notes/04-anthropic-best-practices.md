# Anthropic Best-Practices Research → Forge Mapping

Research note distilling Anthropic's published engineering writing into actionable, file-level recommendations for Forge's planner / generator / evaluator / scheduler / memory / executor stack. All citations are Anthropic-source.

---

## 1. Harness Design — the foundational document

Source: *Harness design for long-running application development* (anthropic.com/engineering/harness-design-long-running-apps).

### Core findings

- **Generator/evaluator separation is the load-bearing lever.** Anthropic states: *"Separating the agent doing the work from the agent judging it proves to be a strong lever."* Self-evaluation is unreliable; the evaluator must be a different process, prompted to be skeptical, and ideally on a different model.
- **Sprint contracts.** The harness has the planner+evaluator negotiate explicit done-criteria *before* the generator writes code. Each criterion is independently graded as PASS/FAIL with evidence.
- **Hard-threshold grading.** A sprint fails if any criterion falls below the threshold — no holistic averaging.
- **Calibrate the evaluator.** *"Calibrated the evaluator using few-shot examples with detailed score breakdowns."* Out-of-the-box Claude approves mediocre work; the evaluator prompt requires several iterations.
- **Criterion wording steers the generator.** Phrases like "museum quality" produce visual convergence. Words in done-criteria become design pressure on the generator.
- **Context anxiety persists under compaction.** *"Compaction preserves continuity, it doesn't give the agent a clean slate."* The harness uses **context resets with structured handoff**, not compaction, when coherence degrades.
- **The Sonnet 4.5 → Opus 4.6 finding.** Sonnet 4.5 needed sprint-sized resets; Opus 4.6 handled longer coherence natively. Anthropic's recommendation: *"Remove one component at a time and review what impact it had"* — re-examine the harness whenever a new model ships.

### Initialization artifacts (from the follow-up *Effective harnesses for long-running agents*)

The follow-up post adds a concrete bootstrapping pattern for multi-session work:

- **Feature-list JSON file**: 200+ features, all initially marked failing. JSON over Markdown because *"the model is less likely to inappropriately change or overwrite JSON files compared to Markdown files."*
- **`claude-progress.txt`**: append-only progress log read at session start.
- **`init.sh`**: dev-server startup script so subsequent sessions don't re-discover how to run the app.
- **Initial git commit** showing all setup files.
- **Session startup sequence**: `pwd` → read git log → review feature list → run `init.sh` → verify basics → only then begin feature work.

### Forge mapping

Forge's `agents/planner.py`, `agents/generator.py`, `agents/evaluator.py`, and the revise loop in `scheduler.py` already implement most of this. Concrete gaps:

- The evaluator prompt in `evaluator.py` is stateless (one shot, no calibration examples). See §A below for a few-shot upgrade.
- Forge has no `init.sh` / `claude-progress.txt` artifact for cross-session resume. The sprint contracts in `sprint_contracts` table are the in-DB equivalent, but they're not surfaced into the worktree as files the agent can read on resume.
- Forge does compact via memory injection but has no equivalent of "context reset between sprints" — when revisions stack, the prompt grows monotonically (see `scheduler.py:89` and `:112` where memory is mutated by `+=`).

---

## 2. Building Effective Agents — the taxonomy

Source: *Building effective agents* (anthropic.com/research/building-effective-agents).

Anthropic distinguishes **workflows** (*"systems where LLMs and tools are orchestrated through predefined code paths"*) from **agents** (*"systems where LLMs dynamically direct their own processes and tool usage"*). Forge is structurally a **workflow with embedded agents**: the scheduler is the predefined path; the generator subprocesses are autonomous agents inside it.

The five workflow patterns:

| Pattern | Definition | Forge use |
| --- | --- | --- |
| **Prompt chaining** | Sequential LLM calls with programmatic gates between steps. | scheduler.py runs planner → generator → evaluator with structured handoffs. |
| **Routing** | Classify input, dispatch to specialised handler. | `agents/classifier.py` routes by complexity to opus/sonnet/ollama. |
| **Parallelization** | Concurrent calls; sectioning or voting. | `dependency_waves` in scheduler.py runs independent sprints concurrently; `agents/reviewer.py` is a 2-5 voting panel. |
| **Orchestrator-workers** | Central LLM dynamically decomposes and delegates. | The planner is exactly this. |
| **Evaluator-optimizer** | One LLM generates, another evaluates, loop. | The generate→evaluate→revise loop in scheduler.py:79-122. |

Key principle from the post: *"Find the simplest solution possible, and only increase complexity when needed."* Forge currently uses all five patterns simultaneously — every pattern should be justified, otherwise stripped.

---

## 3. Context Engineering

Source: *Effective context engineering for AI agents* (anthropic.com/engineering/effective-context-engineering-for-ai-agents).

### Load-bearing claims (verbatim)

- *"Context is a critical but finite resource for AI agents."*
- Goal is *"the smallest possible set of high-signal tokens that maximize the likelihood of some desired outcome."*
- Just-in-time pattern: agents *"maintain lightweight identifiers (file paths, stored queries, web links) and use these references to dynamically load data into context at runtime."*
- Compaction: preserve *"architectural decisions, unresolved bugs, and implementation details while discarding redundant tool outputs."*
- Subagents return *"condensed, distilled summary of its work (often 1,000-2,000 tokens)."*

### Five concrete patterns

1. **Token-budget thinking** — every component (system, tools, examples, history) competes for attention.
2. **Just-in-time vs upfront** — references over content; load on demand via Bash/Grep.
3. **Persistent project context (CLAUDE.md)** — naively injected upfront, hybrid with runtime exploration.
4. **Compaction** — start by maximising recall, then improve precision by trimming redundant tool outputs.
5. **Sub-agent context isolation** — specialised agents in clean windows, returning condensed summaries.

### Forge mapping → `memory/retriever.py`

The current `KB_MAX_CONTEXT_TOKENS = 500` budget is well-aligned. Strengths: deduplication, max-5 items, falls through KB → past failures → research. Gaps:

- Token estimation `len(line) // 4` is crude; it under-counts tokens for code-heavy content and over-counts for natural language. A real `tiktoken`-style estimator would be more accurate, but for KB lines this is acceptable.
- Keyword extraction (line 15-30) is stop-word based. The retriever has no understanding of synonymy — "Supabase RLS" won't surface for "row-level security." Topic-tagging at write time mitigates this; a simple BM25 score over content+topic would be a marginal improvement without adding embedding infrastructure.
- The retriever currently dumps **all three sections at once**. That is "upfront" not "just-in-time." For long sessions, exposing the KB as a *tool the agent can query mid-task* is the just-in-time pattern. See §B (MCP-out skeleton) below.
- The 500-token budget is shared across KB / failures / research but only checked sequentially. If KB items burn the full budget, failures and research are silently dropped. Consider per-section budgets (300/100/100).

---

## 4. Tool Design

Source: *Writing effective tools for AI agents* (anthropic.com/engineering/writing-tools-for-agents).

### Recommendations

- **Consolidate.** *"Instead of implementing a `list_users`, `list_events`, and `create_event` tools, consider implementing a `schedule_event` tool which finds availability and schedules an event."* Few high-value tools beat many granular ones.
- **Namespace.** *"Namespacing tools by service (e.g., `asana_search`, `jira_search`) and by resource (e.g., `asana_projects_search`) can help agents select the right tools at the right time."*
- **Semantic returns over opaque IDs.** *"Agents tend to grapple with natural language names, terms, or identifiers significantly more successfully than they do with cryptic identifiers."*
- **`response_format` enums.** Expose `"concise"` vs `"detailed"` so the agent picks the right token budget.
- **Descriptions for new hires.** *"Think of how you would describe your tool to a new hire on your team."*

### Forge mapping → `done_criteria` as a tool surface

Sprint contracts ARE Forge's tool API for the generator — the generator reads them, the evaluator graders against them. The same tool-design principles apply:

- Today, `planner.py` emits `done_criteria` as plain strings. Each criterion is a brittle natural-language line evaluated by fuzzy match in `evaluator.py:55-60` (`criterion_words.intersection(set(line_lower.split()))`). This is the *"cryptic identifier"* failure mode.
- **Recommendation**: each criterion should be a structured object with `id`, `description`, `verification_method` (one of `static-diff` | `unit-test` | `e2e-playwright` | `manual-llm-judge`), and `verification_target` (file path, test command, URL). This eliminates fuzzy matching and lets the evaluator dispatch deterministic checks for the verifiable subset.
- **Namespace recommendation**: when Forge eventually exposes itself via MCP-out, prefix tools `forge_kb_*`, `forge_episode_*`, `forge_research_*`.

---

## 5. Prompt Caching

Source: Anthropic prompt-caching docs (platform.claude.com/docs/en/build-with-claude/prompt-caching).

### Verbatim facts

- 5-minute TTL default, 1-hour TTL via `"ttl": "1h"`.
- *"Cache writes 1.25x"* base input price (5m), 2x (1h). Cache reads = 0.1x (90% savings).
- Minimum cacheable: 1024 tokens for Sonnet 4.5, 2048 for Sonnet 4.6, 4096 for Opus 4.5/4.6/4.7. Below that, *"shorter prompts are silently processed without caching."*
- *"Place `cache_control` on the last block whose prefix is identical across requests."*
- 20-block lookback window; max 4 explicit breakpoints.
- Cacheable: tool definitions, system messages, user/assistant text, images, tool results.
- Cache invalidation cascade: changes to tools invalidate everything; changes to system invalidate system+messages; changes to messages only invalidate downstream messages.

### Forge mapping → `executors/claude_code.py`

`claude -p` invocations DO use prompt caching internally (Claude Code caches `.claude/settings.json`, CLAUDE.md, and tool defs), but Forge currently passes one big prompt as a single argv string. Implications:

- The CLAUDE.md and MCP server defs are cached *automatically* per worktree because the worktree shares the project root. This is "free" caching that Forge benefits from.
- Forge's *injected* memory context (`memory_context` from `retriever.py`) is **prepended to the user prompt** every invocation. It changes per task → never benefits from caching. This is correct behaviour for ad-hoc tasks, but if the same memory context is reused across revisions of the same sprint, those identical prefixes go uncached because every call is a fresh `claude -p` subprocess.
- **Recommendation**: for a sprint that hits multiple revisions (the generate→evaluate→revise loop), if Forge migrates from `claude -p` subprocesses to the Claude Agent SDK in-process, the SDK can hold the conversation and cache the full prefix across revisions — the revision payload (evaluator feedback) becomes the cheap delta. With separate `claude -p` calls per revision, this caching benefit is lost.
- For the **open-weight executor** (vLLM serving Qwen3-Coder / Devstral / gpt-oss): vLLM has automatic **prefix caching** that reuses the KV cache for identical prompt prefixes. Same principle, different mechanism. Architectural recommendation: structure the prompt as `[stable system prelude] + [stable memory context] + [variable task delta]` so prefix-caching engages on both Claude (cache_control breakpoint) and vLLM (automatic prefix match). See §A bullet on `executors/ollama.py`.

---

## 6. Claude Agent SDK & sub-agents

Source: *Building agents with the Claude Agent SDK* (claude.com/blog/building-agents-with-the-claude-agent-sdk) + sub-agents docs (code.claude.com/docs/en/sub-agents) + hooks docs.

### The agent loop primitive

*"Gather context → take action → verify work → repeat."* This is the same shape as Forge's generate→evaluate→revise but inside a single agent call rather than across subprocess boundaries.

### Sub-agents (`.claude/agents/*.md`)

Markdown files with YAML frontmatter. Required fields: `name`, `description`. Optional: `tools`, `disallowedTools`, `model` (`sonnet`/`opus`/`haiku`/`inherit`/full ID), `permissionMode`, `mcpServers`, `hooks`, `maxTurns`, `memory` (`user`/`project`/`local`), `isolation` (`worktree` for git-isolated copy), `color`, `skills`, `effort`, `background`.

Quote from the doc: *"Each subagent runs in its own context window with a custom system prompt, specific tool access, and independent permissions."* And: *"Subagents are loaded at session start. If you create a subagent by manually adding a file, restart your session."*

The `isolation: worktree` field is striking — **Claude Code natively supports worktree-isolated sub-agents.** This duplicates Forge's `daemon/worktree.py` machinery for the in-Claude-Code path.

### Permission modes

`default` | `acceptEdits` | `auto` | `dontAsk` | `bypassPermissions` | `plan`. Forge currently inherits `default` (correct per security rule §2 of CLAUDE.md).

### Hooks

`PreToolUse`, `PostToolUse`, `PostToolBatch`, `PreCompact`, `UserPromptSubmit`, `SessionStart`, `Stop`, `SubagentStop`, `SubagentStart`. JSON output schema:

```json
{ "continue": true, "decision": "block", "reason": "...", "hookSpecificOutput": { ... } }
```

Exit code 2 = blocking error (stderr shown to Claude).

### Forge mapping

**The strategic question**: should Forge ship `.claude/agents/forge-evaluator.md` and `.claude/agents/forge-reviewer.md` and let Claude Code dispatch them, or keep `claude -p` subprocesses?

| Dimension | Sub-agent files | Forge's `claude -p` subprocesses |
| --- | --- | --- |
| Cross-model evaluation | Hard (sub-agent inherits or hardcodes one model) | Easy (Forge picks per call) |
| Parallelism | Limited (single Claude session) | Native (asyncio.gather) |
| Memory context injection | Via system prompt at startup | Per-call dynamic |
| Visibility / UI | Inside Claude Code transcript | Forge dashboard |
| Worktree isolation | `isolation: worktree` built-in | Custom worktree.py |
| Free benefit | Inherits Claude Code's optimised loop, hooks, prompt caching | Full control |

**Recommendation**: Keep the current `claude -p` design as the primary path for Forge's autonomous orchestration (parallelism, cross-model eval, dashboard observability are all blocked by sub-agent files). But ALSO ship optional `.claude/agents/forge-*.md` files so a user inside an interactive Claude Code session can say "use the forge-reviewer agent" and get the same review prompts. See §C below.

---

## 7. Memory tool

Source: *Memory tool* docs (platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool).

The Memory tool is a client-side filesystem abstraction with `view` / `create` / `str_replace` / `insert` / `delete` / `rename` commands, all rooted at `/memories`. Verbatim: *"This is the key primitive for just-in-time context retrieval: rather than loading all relevant information upfront, agents store what they learn in memory and pull it back on demand."*

The auto-injected protocol prompt:

> *"IMPORTANT: ALWAYS VIEW YOUR MEMORY DIRECTORY BEFORE DOING ANYTHING ELSE. … ASSUME INTERRUPTION: Your context window might be reset at any moment."*

### Forge mapping

Forge's three-tier memory (KB/episodic/procedural) is functionally equivalent to a Memory tool but **invisible to the executing agent** — it is injected pre-flight by the retriever, not queried by the agent. Two recommendations:

1. **Expose Forge KB as an MCP server** (§B). Each Claude Code session in a worktree gets `forge_kb_search`, `forge_kb_add`, `forge_episode_search` tools. This implements the just-in-time pattern: the generator can query the KB mid-task instead of relying on what the retriever pre-decided was relevant.
2. **Optional**: implement the Memory tool contract as a *thin wrapper* over Forge's SQLite. Files in `/memories` map to KB rows by topic. This lets non-Forge Claude API users plug in Forge's persistent memory without running the Forge daemon.

---

## 8. Performance: Batch API, streaming, thinking

Source: Anthropic Batch processing docs (platform.claude.com/docs/en/build-with-claude/batch-processing).

### Batch API verbatim

- *"This approach is well-suited to tasks that do not require immediate responses, with most batches finishing in less than 1 hour while reducing costs by 50% and increasing throughput."*
- Async pattern: submit batch → poll for status → retrieve results.
- Use cases: large-scale evals, content moderation, data analysis.

### Forge mapping

`daemon/executors/batch.py` already exists per the spec but the Batch API path is **not currently used in `scheduler.py`**. Candidate work for batch (non-urgent, parallelisable):

- The post-session learner (`memory/learner.py:_extract_gotcha`) — currently runs serially on Ollama. Could batch all failure-resolution pairs to Sonnet via batch for higher quality at no premium.
- Multi-perspective reviewer panel (`agents/reviewer.py`) — 2-5 perspectives per sprint. If review is non-urgent (e.g. nightly pass over a session), batch.
- Research summarisation in `agents/researcher.py` — extract content from multiple URLs.

---

## 9. Evaluation

Source: *Demystifying evals for AI agents* (anthropic.com/engineering/demystifying-evals-for-ai-agents).

Verbatim:
- *"20-50 simple tasks drawn from real failures is a great start."*
- *"Clear, structured rubrics to grade each dimension of a task, and then grade each dimension with an isolated LLM-as-judge rather than using one to grade all dimensions."*
- *"We do not take eval scores at face value until someone digs into the details of the eval and reads some transcripts."*
- *"Could they pass the task themselves? If not, the task needs refinement."*

### Forge mapping → `evaluator.py`

Forge's evaluator already grades each criterion separately (good — matches "isolated LLM-as-judge per dimension"). Gaps:

- Single evaluator call grades all criteria together (one prompt, one LLM call). The Anthropic recommendation is **one LLM call per dimension**. For a 4-criterion sprint, this is 4× cost but materially higher accuracy.
- The evaluator does not have a *task-self-test* gate before grading: did the planner's done-criteria actually capture verifiable conditions? When the rubric is bad, evaluator scores are noise.
- No cross-model meta-evaluation. The Forge spec says "Always run evaluator on a DIFFERENT model than generator" but `evaluator.py:120` hardcodes `eval_model = "sonnet"` regardless of generator model. If generator is sonnet too, this is same-model.

### Self-evaluation reliability — the citation Forge depends on

The harness-design post is the canonical citation: *"Separating the agent doing the work from the agent judging it proves to be a strong lever."* The follow-up *Building agents with the Claude Agent SDK* states LLM-as-judge is *"useful but 'not a very robust method.'"* Both cited verbatim. The cross-model evaluator pattern in Forge is correctly grounded.

---

## 10. MCP

Source: modelcontextprotocol.io and the Python SDK.

MCP is *"an open-source standard for connecting AI applications to external systems"* exposing three capabilities:
1. **Tools**: functions callable by the LLM.
2. **Resources**: file-like data the client reads.
3. **Prompts**: reusable templates.

Forge already *consumes* MCP via inheritance (`scanner/claude_code.py` reads `.claude/settings.json`). The recommendation from the architecture review is that Forge should also *publish* itself as an MCP server. Concrete skeleton in §B below.

---

# A. Forge core file restructuring recommendations

## `daemon/agents/planner.py`

1. **Cache the system prompt prelude.** When migrating off `claude -p` to direct API, mark `PLAN_SYSTEM_PROMPT` (line 14-32) as `cache_control: ephemeral` — it changes only when Forge code changes.
2. **Make `done_criteria` structured, not strings.** Replace each criterion string with `{id, description, verification_method, verification_target}`. The evaluator gains deterministic dispatch (run a test, check a file exists) and the fuzzy-match logic in `evaluator.py:57-60` becomes unnecessary.
3. **Inject `init.sh` / progress-file artifacts into the worktree.** When the planner produces sprints, also emit a `.forge/sprint-progress.json` file that subsequent generator revisions can read on resume. This applies the *Effective harnesses* multi-session pattern even within a single Forge session for revision continuity.
4. **Split the planner into two LLM calls.** First call generates the spec from the objective; second call produces the contract (done-criteria) given the spec. Anthropic's eval-design recommendation: each dimension gets its own call.
5. **Inject Claude Code auto-memory at plan time** (per CLAUDE.md §1, "reads ~/.claude/projects/<project>/memory/"). The planner should see what Claude Code has already learned about this project.

## `daemon/agents/generator.py`

1. **Stable prompt structure for prefix caching.** Order the prompt as `[stable system] + [stable project context] + [stable memory context] + [variable task description] + [variable revision feedback]`. This way the first three blocks hit cache on revisions (Claude) or KV-prefix-cache (vLLM).
2. **Honor an `effort` budget.** Add a `max_thinking_tokens` parameter sourced from the sprint's complexity (planner output). Reduces over-budget thinking on simple tasks.
3. **Pass a structured tool list, not bare prose.** Instead of "Run tests if applicable," provide a structured `tools_available` list (the MCP servers, the available CLIs from `scanner/tools.py`). The generator should know what tools are present without inferring.
4. **Emit a structured progress writeback.** After each call, write to `.forge/sprint-progress/<sprint-id>.json` with `{files_changed, tests_run, todo}`. The evaluator and the next revision both read this.

## `daemon/agents/evaluator.py`

1. **One LLM call per criterion** (§9). Replace the single big prompt with `asyncio.gather` over criteria. Use the cheapest model that passes calibration (Haiku for binary file-exists checks; Sonnet for design grading). Cost goes up linearly with criteria count but accuracy improves materially.
2. **Few-shot calibration block.** Per the harness-design post, evaluators need *"few-shot examples with detailed score breakdowns."* Add a `EVALUATOR_FEW_SHOT` constant — 2-3 worked examples of correct PASS/FAIL with evidence formatting. Cache it.
3. **Dispatch by `verification_method`** (assuming criteria are structured per §A.planner.2): `static-diff` → run a regex over the diff; `unit-test` → run the test command and check exit code; `e2e-playwright` → invoke the Playwright MCP; `manual-llm-judge` → fall through to the current LLM grading. Saves both cost and accuracy.
4. **Hard-fail on parsing errors.** Today `parse_evaluator_result` (line 44) silently uses fuzzy `criterion_words.intersection`. If parsing fails, return REVISE with explicit "Evaluator output unparseable" feedback rather than guessing.
5. **Force the cross-model invariant.** `eval_model = "sonnet"` (line 120) hardcoded. Replace with `eval_model = "opus" if sprint.assigned_model == "sonnet" else "sonnet"` to guarantee cross-model.

## `daemon/scheduler.py`

1. **Context reset between revisions, not append.** Lines 89 (`memory += ...error...`) and 112 (`memory += ...feedback...`) both monotonically grow the prompt. Per the harness-design context-reset finding, the second revision should start from a CLEAN context with a structured handoff: `[original sprint] + [evaluator's specific feedback]`, not the accumulated history of failed attempts. Replace `+=` with reassignment to a structured `revision_context = build_revision_context(sprint, eval_result)`.
2. **Track which KB items were injected** so the learner (line 71-73) can correctly call `mark_helpful` / `mark_unhelpful`. Currently the learner has a TODO comment ("In a full implementation, we'd track which KB items were injected per sprint"). Resolve by carrying KB item IDs alongside `memory_context`.
3. **Add a session-level `init.sh` / `progress.json` step before any sprint runs**, per the *Effective harnesses* pattern. The scheduler creates these artefacts so generators can read them on cold start.
4. **Surface compaction trigger.** When prompt approaches the model context limit, the scheduler should call a compaction LLM (cheap, Haiku) to summarise prior episode results into a 1-2k-token summary, per the context-engineering recommendation. Today there is no compaction.
5. **Implement a `PreCompact`-style hook surface.** Forge users may want to inject custom logic before a session compaction or evaluator dispatch — mirror Claude Code's hook lifecycle in WS events.

## `daemon/memory/retriever.py`

1. **Per-section budgets.** Currently 500 tokens shared; if KB fills it, failures and research are dropped. Split: 300 KB / 100 failures / 100 research, with overflow allowed when sections are empty.
2. **Replace `len(line) // 4` with a real token count.** For Claude paths, use the API's tokeniser; for Ollama, use the model's HuggingFace tokeniser. The 4-chars-per-token heuristic miscounts code by ~30%.
3. **Add topic-tag fallback.** When keyword extraction produces zero hits, fall back to topic-tag retrieval ("any items with topic in {detected_topics}"). Avoids returning empty context for tasks whose wording diverges from KB content.
4. **Expose a `query_kb` tool to the agent.** This is the just-in-time pattern. The retriever stops being a one-shot pre-flight injection and becomes a callable surface (via MCP). See §B.
5. **Track citations.** When an item is injected, record `(sprint_id, kb_item_id, position_in_context)`. The learner reads this for confidence reinforcement.

## `daemon/memory/learner.py`

1. **Resolve the TODO at line 71-73** (confidence reinforcement). Use the citation tracking from §A.retriever.5 to call `kb.mark_helpful(item_id)` for items injected into successful sprints, `mark_unhelpful` otherwise.
2. **Batch the gotcha extraction.** Today `_extract_gotcha` (line 79) runs sequentially. Use `asyncio.gather` over all `failure_resolution_pairs`, or better, the Claude Batch API for higher-quality extraction at 50% off.
3. **Add cross-session pattern learning.** `learn_from_session` operates on a single session. After every N sessions, run a meta-learner that looks for repeated gotchas across sessions and promotes high-confidence items into `CLAUDE.md` suggestions (per CLAUDE.md spec §3 last bullet: "optionally writes: Suggests additions to CLAUDE.md").
4. **Persist topic vocabulary.** The hardcoded keyword→topic dict at line 98-105 is brittle. Move to a `topics` SQLite table that grows with usage and gets ranked by frequency.

## `daemon/executors/claude_code.py`

1. **Confirm caching engages.** Add a debug-mode log line that parses `claude -p`'s stderr for cache hit/miss counts (Claude Code emits these). Without telemetry, you cannot verify caching is working.
2. **Pass `--output-format json`** if it exists (Claude Code supports structured output) so token counts are precise rather than `len // 4` (lines 51-52). This fixes budget accounting.
3. **Reuse worktree path across revisions.** Today each revision is a fresh `claude -p` subprocess in the same worktree. The CLAUDE.md and tool defs cache for free, but conversation history doesn't carry. Consider migrating to the Claude Agent SDK Python bindings for a sticky in-process session per sprint — revisions then share full prompt cache.
4. **Sanitisation already correct** (lines 14-18): control-char strip, length cap. Matches CLAUDE.md security rule §5.
5. **Add a `model: claude-opus-4-7` (or `claude-sonnet-4-7`) full-ID fallback** so the executor works against API endpoints not just the alias resolver.

## `daemon/executors/ollama.py`

1. **Migrate to vLLM `openai_compatible` for prefix caching.** Ollama doesn't expose explicit prefix caching controls; vLLM with `--enable-prefix-caching` does. For the open-weight path (Qwen3-Coder, Devstral, gpt-oss), vLLM is the deployment target per the Forge hardening direction. The executor's interface stays the same.
2. **Stable prompt prefix.** Mirror the recommendation in §A.generator.1: `[stable system] + [stable memory] + [variable task]`. vLLM's automatic prefix caching activates on identical prefix tokens.
3. **Honor `temperature` per agent role.** Today temperature is hardcoded `0.2` (line 28). Generators benefit from 0.2; evaluators want 0.0 for determinism; planners want 0.4-0.6 for creative decomposition.
4. **Capture `eval_count` / `prompt_eval_count`** (lines 34-35, already done — good). Add latency metrics so the procedural store can route by speed too.
5. **Add a `keep_alive` parameter.** Ollama unloads models on idle; setting `"keep_alive": "30m"` in the request body keeps the model warm across sprints in a session, eliminating model-load latency on every call.

---

# B. MCP server skeleton for Forge KB-out

This file lives at `daemon/mcp_server.py`. Run via `python -m daemon.mcp_server` and register in any Claude Code project's `.claude/settings.json`. Uses the `mcp` (FastMCP) Python SDK.

```python
"""Forge KB exposed as an MCP server.

Lets any Claude Code session call into Forge's persistent knowledge base
without running the full Forge daemon. Just-in-time retrieval per the
context-engineering pattern.

Run: python -m daemon.mcp_server
Register in .claude/settings.json:
  "mcpServers": {
    "forge": {"command": "python", "args": ["-m", "daemon.mcp_server"]}
  }
"""
from __future__ import annotations

from pathlib import Path
from mcp.server.fastmcp import FastMCP

from .db import ForgeDB
from .memory.knowledge import KnowledgeBase
from .memory.episodic import EpisodicStore
from .memory.research import ResearchCache
from .config import DB_PATH

mcp = FastMCP("forge-kb")
_db = ForgeDB(Path(DB_PATH))
_kb = KnowledgeBase(_db)
_episodic = EpisodicStore(_db)
_research = ResearchCache(_db)


# --- Tools (callable by the agent) ---

@mcp.tool()
def forge_kb_search(query: str, topic: str | None = None,
                    category: str | None = None, limit: int = 5) -> str:
    """Search Forge's knowledge base for gotchas, solutions, and patterns.

    Returns up to `limit` items as a markdown list, ranked by confidence and
    recent usage. Use this BEFORE writing code touching unfamiliar territory.
    """
    items = _kb.search(query=query, topic=topic, category=category, limit=limit)
    if not items:
        return "No matching knowledge items."
    return "\n".join(
        f"- [{i['category']}/{i['topic']}] {i['content']} "
        f"(conf={i['confidence']:.2f}, src={i['source']})"
        for i in items
    )


@mcp.tool()
def forge_kb_add(category: str, topic: str, content: str,
                 source: str = "agent") -> str:
    """Record a new gotcha, solution, or pattern in Forge's KB.

    Use sparingly — only for reusable, non-obvious lessons. One imperative
    sentence. Returns the new item ID.
    """
    item_id = _kb.add(category=category, topic=topic, content=content,
                      source=source, confidence=0.5)
    return f"Stored item id={item_id}."


@mcp.tool()
def forge_episode_search(error_pattern: str, limit: int = 3) -> str:
    """Look up past task failures matching an error pattern, with resolutions."""
    eps = _episodic.search_failures(error_pattern, limit=limit)
    if not eps:
        return "No matching past failures."
    return "\n\n".join(
        f"Task: {e['task_description'][:120]}\n"
        f"Error: {e.get('error', '')[:200]}\n"
        f"Resolution: {e.get('resolution', '(none)')[:200]}"
        for e in eps
    )


@mcp.tool()
def forge_research_lookup(query: str, max_age_days: int = 30) -> str:
    """Check Forge's research cache before triggering a fresh web search."""
    hits = _research.search(query, max_age_days=max_age_days, limit=2)
    if not hits:
        return "No cached research."
    return "\n\n".join(
        f"[{h['url']}]\n{h['extracted_content'][:600]}" for h in hits
    )


# --- Resources (read-only context for the agent) ---

@mcp.resource("forge://stats")
def kb_stats() -> str:
    """Summary of the KB: counts by category, top topics, recent additions."""
    s = _db.kb_summary()
    return (
        f"KB items: {s['total']} | gotchas: {s['gotchas']} | "
        f"solutions: {s['solutions']} | patterns: {s['patterns']}\n"
        f"Top topics: {', '.join(s['top_topics'][:10])}\n"
        f"Recent: {', '.join(s['recent_topics'][:5])}"
    )


@mcp.resource("forge://session/{session_id}/summary")
def session_summary(session_id: str) -> str:
    """Per-session summary: sprints, costs, learnings."""
    return _db.session_markdown(session_id)


# --- Prompts (reusable templates the user can invoke) ---

@mcp.prompt()
def review_with_forge_kb(file_path: str) -> str:
    """Review a file using Forge's accumulated patterns and gotchas."""
    return (
        f"Read {file_path}. Use forge_kb_search to find relevant gotchas "
        f"and patterns for this file's domain. Cite each KB item ID you apply. "
        f"Flag any code that contradicts a high-confidence KB item."
    )


if __name__ == "__main__":
    mcp.run()
```

This skeleton is ~80 lines, exposes 4 tools + 2 resources + 1 prompt, follows §4's namespacing (`forge_*`) and semantic-return (markdown lists, not raw rows) recommendations.

---

# C. Sub-agent file definitions

Forge should ship optional `.claude/agents/*.md` files. They do NOT replace the daemon — they let interactive Claude Code users invoke Forge-style behaviour without spinning up the whole orchestrator.

### Trade-offs

**Pro**: Zero-friction adoption, works in any Claude Code session, inherits the parent's MCP servers and CLAUDE.md, supports `isolation: worktree` natively.

**Con**: No cross-model evaluation (sub-agents inherit one model unless hardcoded), no multi-process parallelism, no Forge dashboard, and they can't spawn other sub-agents (per the Anthropic doc: *"Subagents cannot spawn other subagents"*).

**Recommendation**: ship them. Three files.

### `.claude/agents/forge-evaluator.md`

```markdown
---
name: forge-evaluator
description: Strict cross-model code reviewer. Use proactively after any
  feature implementation, especially before merging. Verifies each acceptance
  criterion independently with evidence.
tools: Read, Glob, Grep, Bash
model: sonnet
permissionMode: default
memory: project
color: red
---

You are a strict code reviewer and QA engineer modelled on the Forge
evaluator. Your job is to verify that EVERY done criterion is met.

Procedure:
1. Read the git diff (Bash: git diff main...HEAD).
2. For EACH stated criterion, grade independently:
   - PASS: <criterion> — <specific evidence from the diff>
   - FAIL: <criterion> — <what is missing or wrong> — <specific fix>
3. Do NOT give the benefit of the doubt. If something looks incomplete, FAIL it.
4. Test what is testable. Run unit tests with the project's test command.
5. Final line: "VERDICT: APPROVED" or "VERDICT: REVISE".

If memory is enabled, after grading, record any new failure patterns you
observed under `MEMORY.md` so future evaluations catch them faster.
```

### `.claude/agents/forge-reviewer.md`

```markdown
---
name: forge-reviewer
description: Multi-perspective review. Use when a change is large, security-
  sensitive, or touches multiple subsystems. Focuses on security, correctness,
  and maintainability simultaneously.
tools: Read, Glob, Grep, Bash
model: sonnet
memory: project
color: orange
---

Review the current change from THREE perspectives, in order:

1. SECURITY — injection, auth, secrets in code, data exposure, RLS bypasses,
   race conditions in privileged paths.
2. CORRECTNESS — edge cases, off-by-one, null handling, error paths.
3. MAINTAINABILITY — naming, types, coupling, missing tests.

For each perspective, output a section with: critical (must-fix), warnings
(should-fix), suggestions (nice-to-have). Synthesise at the end into one
overall verdict and a prioritised action list.

Cite line numbers. Be specific. If you find a CRITICAL security issue,
say so on a leading line: `CRITICAL: <one-line description>`.
```

### `.claude/agents/forge-research.md`

```markdown
---
name: forge-research
description: Web research for unfamiliar errors or libraries. Use when an
  error has no known solution in the codebase or memory.
tools: WebFetch, WebSearch, Read
model: haiku
memory: user
color: cyan
---

Research procedure:
1. Generate 1-3 focused queries from the error and context.
2. Fetch the top results. Prefer official docs, GitHub issues, recent
   Stack Overflow answers.
3. Extract ONE actionable solution paragraph per source. Cite URLs.
4. If memory is enabled, record any solution that worked under MEMORY.md
   so it short-circuits future searches.

Return: a short markdown summary with cited sources. Never invent URLs.
```

These ship in the Forge repo under a top-level `.claude-templates/agents/` and `forge init` copies them into the user's project on request (with confirmation, never automatically — security rule §12).

---

# D. Performance optimization checklist

Mapping Anthropic's recommendations onto specific Forge files:

| Optimisation | Anthropic source | Forge code change |
| --- | --- | --- |
| Prompt caching engaged on stable prelude | prompt-caching docs | `executors/claude_code.py`: confirm via stderr telemetry; structure prompt as stable+variable |
| Per-agent token budget tracked | context-engineering | `models.py`: add `token_budget` to SprintContract; scheduler enforces |
| Batch API for non-urgent work | batch-processing docs | `learner.py`: switch `_extract_gotcha` loop to `executors/batch.py` |
| Streaming enabled where latency matters | agent SDK blog | `executors/claude_code.py`: pass `--stream` and forward chunks via WS |
| Compaction trigger before context limit | context-engineering | `scheduler.py`: add a Haiku-based compaction step when prompt > 80% of context window |
| Cross-model evaluator | harness-design | `evaluator.py:120`: replace hardcoded `"sonnet"` with cross-model selector |
| One LLM call per criterion | demystifying-evals | `evaluator.py`: `asyncio.gather` over criteria |
| Just-in-time KB tool surface | context-engineering / memory tool | `daemon/mcp_server.py` (new file, §B) |
| vLLM prefix caching for open-weight path | (extrapolated from prompt-caching) | `executors/ollama.py`: structure prompts; add vLLM endpoint variant |
| Calibration few-shot for evaluator | harness-design | `evaluator.py`: add EVALUATOR_FEW_SHOT block |
| Progress-file artefacts for cross-revision continuity | effective-harnesses | `scheduler.py`: emit `.forge/sprint-progress/<id>.json` |
| Ollama model warm via keep_alive | (Ollama API) | `executors/ollama.py`: pass `"keep_alive": "30m"` |

Quick wins (≤1 day each): the `keep_alive` flag, the cross-model selector, the per-section retriever budgets, the few-shot evaluator block, removing the prompt-`+=` revision append.

Bigger lifts (≥1 week): structured `done_criteria` schema, MCP server, sub-agent files, batch-API integration, compaction step.

---

# E. Citations

All Anthropic URLs used in this research:

- https://www.anthropic.com/engineering/harness-design-long-running-apps — *Harness design for long-running application development*. The foundational harness post; generator/evaluator separation, sprint contracts, context resets, the Sonnet 4.5 → Opus 4.6 finding.
- https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents — *Effective harnesses for long-running agents*. Initialiser session pattern, feature-list JSON, `init.sh`, `claude-progress.txt`.
- https://www.anthropic.com/engineering/building-effective-agents — *Building effective agents*. Workflow vs agent taxonomy: prompt chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer.
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents — *Effective context engineering for AI agents*. Token-budget thinking, just-in-time vs upfront, persistent project files, compaction, sub-agent context isolation.
- https://www.anthropic.com/engineering/writing-tools-for-agents — *Writing effective tools for AI agents*. Consolidation (`schedule_event`), namespacing (`asana_search`), semantic returns, `response_format` enums.
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching — Prompt caching reference. TTLs, pricing math, breakpoints, invalidation cascade, 20-block lookback.
- https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents — *Demystifying evals for AI agents*. 20-50 task starting size, isolated LLM-as-judge per dimension, transcript reading discipline.
- https://www.claude.com/blog/building-agents-with-the-claude-agent-sdk — Agent SDK overview. The gather→act→verify→repeat loop, agentic vs semantic search, MCPs.
- https://code.claude.com/docs/en/sub-agents — Sub-agents reference. Frontmatter schema, `isolation: worktree`, `memory` scopes, permission modes.
- https://code.claude.com/docs/en/hooks — Hooks reference. PreToolUse, PostToolUse, PreCompact, SessionStart, Stop, SubagentStop, output JSON schema.
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool — Memory tool reference. `view`/`create`/`str_replace`/`insert`/`delete`/`rename` commands, the auto-injected memory protocol prompt, path traversal warnings.
- https://platform.claude.com/docs/en/build-with-claude/batch-processing — Batch API. 50% discount, async, ≤1 hour completion, large-scale eval use case.
- https://modelcontextprotocol.io/introduction — MCP introduction. Tools/resources/prompts capability split, ecosystem context.
- https://modelcontextprotocol.io/quickstart/server — MCP server quickstart. FastMCP Python SDK API surface used in the §B skeleton.

---

End of note.
