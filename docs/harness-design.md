# Harness Design

How the planner, generator, and evaluator work together. Based on Anthropic's research on harness design for long-running applications.

## The core problem

Self-evaluation is unreliable. An agent will confidently praise its own mediocre work. The fix is separation: the agent doing the work never judges it.

## Agent roles

### Planner

**Input:** User's natural language objective + project context (stack, framework, MCP servers, relevant knowledge base items, Claude Code auto-memory).

**Output:** A list of sprint contracts in JSON. Each contract contains:
- `id`: Unique sprint identifier
- `description`: What to build
- `done_criteria`: Array of testable criteria (the contract)
- `depends_on`: Sprint IDs that must complete first
- `files_scope`: Expected file paths
- `recommended_model`: opus / sonnet / ollama
- `estimated_tokens`: Cost estimate

**Model:** Local Ollama for simple objectives (3-4 tasks), Sonnet for complex ones (5+ tasks). Planning on Ollama is free.

The done criteria list is the sprint contract. The evaluator tests against exactly these criteria. This contract is negotiated before any code runs.

### Generator

**Input:** One sprint contract + memory context from the retriever (max 5 knowledge items, ~500 tokens) + evaluator feedback (on revision attempts).

**Output:** Code changes in an isolated git worktree.

**Behavior:**
1. Receives memory context (gotchas, past failures, relevant research)
2. Receives sprint description and done criteria
3. Executes via `claude -p` in a worktree or via Ollama REST API
4. Returns result without self-evaluation

The generator is explicitly instructed: "Do not evaluate your own work." Judgment is the evaluator's job.

**Model:** Opus for complex tasks, Sonnet for medium, Ollama for simple. Determined by the classifier using heuristics + procedural memory.

### Evaluator

**Input:** Sprint contract (done criteria) + git diff from the generator's worktree + project context.

**Output:** Per-criterion verdicts and an overall verdict.

**Behavior:**
1. Receives the contract and the diff
2. For each done criterion, independently verifies: PASS with evidence, or FAIL with what is wrong and the specific fix needed
3. If the project is a web app and Playwright is available, starts the dev server and clicks through the UI
4. Returns overall verdict: APPROVED (all pass) or REVISE (any fail)

**Model:** Always a different model than the generator. Cross-model verification reduces blind spots.

## The generate-evaluate-revise loop

```
for each sprint:
    create worktree
    build memory context (max 5 KB items)

    for attempt in range(MAX_REVISIONS + 1):   # MAX_REVISIONS = 2
        generator executes in worktree
        if generator failed:
            try error recovery (KB lookup, web search)
            if recovery found: add to context, retry
            else: mark sprint failed, break

        evaluator reviews the diff
        if APPROVED:
            mark sprint completed, break
        elif attempt < MAX_REVISIONS:
            add evaluator feedback to generator context
            increment revision count
        else:
            mark sprint failed (exhausted revisions)
```

Key properties:
- Max 2 revision cycles per sprint. If the evaluator still fails it after 2 revisions, the sprint is marked failed and escalated to the user.
- Each revision injects the evaluator's specific feedback into the generator's next attempt. This creates a focused improvement cycle rather than blind retries.
- Error recovery between attempts checks the knowledge base first (free), then web search (also free if using Claude Code's built-in search).

## Cross-model verification

The evaluator always runs on a different model than the generator. This is not configurable. If the generator used Opus, the evaluator uses Sonnet. If the generator used Sonnet, the evaluator uses Sonnet on a fresh context (no shared state).

Different models have different blind spots. Cross-model review catches issues that self-review misses.

## Dependency waves

Sprints with no dependencies run in parallel. The scheduler computes dependency waves:

```
Wave 1: [sprint-1, sprint-2]     # no dependencies, run in parallel
Wave 2: [sprint-3]               # depends on sprint-1
Wave 3: [sprint-4]               # depends on sprint-2 and sprint-3
```

Within each wave, sprints execute concurrently up to `MAX_PARALLEL_AGENTS`.

## Merge gate

After all sprints complete, the merge gate:
1. Checks each worktree for conflicts with the main branch
2. Runs the multi-perspective review panel for large changes (security + correctness + maintainability)
3. Presents diffs in the dashboard for user approval
4. On approval, merges worktrees to the main branch in dependency order
5. Cleans up all worktrees

## Recovery strategies

When a generator fails:
1. Check the knowledge base for known solutions to this error category
2. If nothing found, search the web for the specific error
3. If research yields a solution, inject it as recovery context and retry
4. If no recovery is possible, fail the sprint with full error context for the user
