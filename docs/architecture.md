# Architecture

## Daemon structure

The Forge daemon is a single Python asyncio process. It exposes a WebSocket server on `127.0.0.1:9111` for the browser dashboard and handles all orchestration internally.

```
daemon/
    main.py              Entry point: CLI parsing, daemon startup, WebSocket server
    config.py            All configuration via environment variables with defaults
    models.py            Dataclasses: Task, Sprint, Session, ProjectContext, etc.
    db.py                SQLite connection (WAL mode), table creation, migrations

    scanner/
        project.py       Detect git, package.json, pyproject.toml, Cargo.toml, framework
        claude_code.py   Read .claude/settings.json, CLAUDE.md, .claude/rules/, auto-memory
        tools.py         Detect CLIs on PATH: gh, supabase, vercel, stripe, playwright

    memory/
        episodic.py      Task execution history (every run, outcome, error, resolution)
        knowledge.py     Gotchas, solutions, patterns -- one-line imperative statements
        procedural.py    Model routing intelligence (which model works for which task)
        research.py      Web search results with source URLs and expiry
        retriever.py     Unified cross-store retrieval, builds context for agents
        learner.py       Post-session insight extraction

    agents/
        planner.py       Decompose objectives into sprint contracts
        generator.py     Execute code in worktrees with memory context
        evaluator.py     External verification against sprint contracts
        researcher.py    Web search + solution extraction
        reviewer.py      Multi-perspective review panel

    executors/
        claude_code.py   claude -p subprocess in a git worktree
        ollama.py        Ollama REST API (zero cost)
        batch.py         Claude API batch endpoint (50% off, higher latency)

    scheduler.py         Parallel execution with dependency resolution
    budget.py            Cost control + model downgrade cascade
    worktree.py          Git worktree create/remove/list/diff
    ws_server.py         WebSocket server for the browser dashboard
    cli.py               CLI command handlers
```

## Three-agent pattern

Forge separates work into three roles so the agent doing the work never judges it:

1. **Planner** receives the user's objective plus project context (stack, MCP servers, knowledge base items). Produces a list of sprint contracts, each with a description, testable "done" criteria, dependency list, and recommended model. Runs on local Ollama (free) or Sonnet.

2. **Generator** receives one sprint contract plus relevant memory context (max 5 knowledge items, ~500 tokens). Executes in an isolated git worktree via `claude -p`. Returns the result without self-evaluation. Runs on Ollama, Sonnet, or Opus depending on task complexity.

3. **Evaluator** receives the sprint contract and the generator's git diff. Verifies each done criterion independently with evidence. Returns PASS/FAIL per criterion and an overall verdict (APPROVED or REVISE). Always runs on a different model than the generator.

If the evaluator returns REVISE, the generator gets specific feedback and tries again (max 2 revision cycles).

## Worktree isolation

Each generator sprint runs in its own git worktree:

- Created via `git worktree add` with a sanitized branch name
- The worktree shares the repo's `.claude/` directory, so MCP connections and CLAUDE.md carry through
- Generators cannot interfere with each other or the main branch
- After evaluation and approval, worktrees merge through the merge gate
- Cleanup handlers (atexit + signal handlers) ensure worktrees are removed even on crash

## WebSocket protocol

The daemon communicates with the browser dashboard over a single WebSocket connection.

**Client to server:**

| Message | Purpose |
|---------|---------|
| `init` | Trigger project scan, return context |
| `plan` | Submit objective for decomposition |
| `run_all` / `run_sprint` | Start execution |
| `add_task` | Add a single task (skip planner) |
| `merge_approve` / `merge_reject` | Merge gate decisions |
| `cancel` | Cancel a running sprint |
| `search_knowledge` | Query the knowledge base |
| `add_knowledge` / `delete_knowledge` | Edit knowledge base |
| `research` | Manual web search |
| `review` | Run multi-perspective review |
| `status` | Request current state |

**Server to client:**

| Message | Purpose |
|---------|---------|
| `project_context` | Detected stack, MCP servers, tools, KB count |
| `plan_created` | Sprint array with contracts |
| `sprint_started` / `sprint_progress` / `sprint_generated` | Generator lifecycle |
| `sprint_evaluated` | Verdict + feedback |
| `sprint_revised` | Revision number + feedback |
| `sprint_completed` / `sprint_failed` | Final status |
| `merge_ready` / `merge_complete` | Merge gate events |
| `budget_warning` / `budget_downgrade` | Cost alerts |
| `knowledge_updated` | New/modified KB items |
| `research_result` | Web search results |
| `review_complete` | Multi-perspective verdicts |
| `session_learnings` | Post-session knowledge extraction |
| `error_recovery` | Recovery strategy used |

All messages are JSON with a `type` field and a payload.
