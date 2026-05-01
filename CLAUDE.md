# Forge v2 — Complete Build Specification

## What this is

Forge is a multi-agent orchestrator that runs inside existing project folders. It reads your .claude/ directory, discovers your MCP connections (Supabase, Vercel, Stripe, GitHub, etc.), inherits your CLAUDE.md instructions and Claude Code auto-memory, then orchestrates parallel Claude Code sessions and local Ollama LLMs to execute development work with a persistent, growing knowledge base.

You do not install Forge as a separate tool. You run forge init inside a project that already has Claude Code configured. Forge becomes a layer on top of Claude Code, not a replacement for it.

The core architecture is inspired by Anthropic's harness design for long-running applications (anthropic.com/engineering/harness-design-long-running-apps). Instead of a single agent doing everything, Forge uses three agent roles: a planner that decomposes work, generators that write code in isolated git worktrees, and evaluators that verify the work from the outside. This GAN-inspired separation — where the agent doing the work is never the agent judging it — is what makes Forge reliable over multi-hour autonomous sessions.

Every session feeds a persistent memory system that accumulates gotchas, solutions, patterns, and web research. Every session makes the next session smarter.

Repository name: forge. MIT license. Two Python dependencies: httpx, websockets. No frameworks. No langchain.

---

## Core philosophy

### 1. Forge runs inside your project

When you run forge init in a project folder, Forge does not create a new project. It detects what already exists:

- Reads .claude/settings.json for MCP server configurations
- Reads CLAUDE.md and .claude/rules/ for project instructions
- Reads ~/.claude/projects/<project>/memory/ for Claude Code auto-memory
- Reads package.json, pyproject.toml, Cargo.toml, etc. to detect the tech stack
- Checks which CLIs are available: gh, supabase, vercel, stripe, playwright
- Creates .forge/ alongside .claude/ for its own persistent memory

Every agent Forge spawns is a real Claude Code session (claude -p) running in a git worktree. Because it runs inside your project, every agent inherits all your MCP connections, CLAUDE.md instructions, and auto-memory. No separate configuration needed.

### 2. Three-agent architecture (from Anthropic harness research)

Anthropic's research showed that self-evaluation is unreliable — agents confidently praise their own mediocre work. The fix is separation: the agent doing the work never judges it.

Forge uses three roles:

- Planner: Decomposes objectives into sprint-sized tasks. Negotiates "done" criteria with the evaluator before any code is written. Runs on local Ollama (free) or Claude Sonnet.
- Generator: Writes code in an isolated git worktree. One generator per task. Runs on Sonnet (medium tasks) or Opus (complex tasks) or Ollama (simple tasks).
- Evaluator: Reviews the generator's work from outside. Runs tests, checks for regressions, uses Playwright MCP to click through running apps. Can fail a sprint and send feedback to the generator for revision. Runs on a different model than the generator.

This means every non-trivial task goes through: plan -> contract -> generate -> evaluate -> (revise if needed) -> merge.

### 3. Memory that compounds

Four types of persistent memory in one SQLite database:

- Episodic: Raw history of every task, outcome, error, resolution, duration, model used.
- Semantic (the knowledge base): Gotchas, solutions, patterns. One-line imperative statements. "Supabase RLS: test with service_role key, not anon key." Confidence scores that increase with reinforcement and decay without use.
- Procedural: Which model works for which task pattern. Updated after every execution. Improves routing over time.
- Research: Web search results, documentation excerpts, Stack Overflow solutions. Cached with source URLs and expiry dates.

Memory injection is surgical. Before a task runs, Forge retrieves only the 3-5 most relevant items from the knowledge base and injects them into the agent's system prompt. Not a dump of everything — just what matters for this specific task. Context windows are precious.

### 4. Memory interop with Claude Code

Forge does not replace Claude Code's native memory. It extends it:

- Reads: ~/.claude/projects/<project>/memory/ (Claude Code auto-memory)
- Reads: CLAUDE.md, .claude/rules/*.md (project instructions)
- Writes: .forge/forge.db (Forge's own knowledge base and execution history)
- Optionally writes: Suggests additions to CLAUDE.md when it learns something the project should know permanently

This means Forge benefits from what Claude Code has already learned about your project, and Claude Code benefits from what Forge learns.

---

## Architecture

```
Browser (localhost:3000)
    | WebSocket (127.0.0.1:9111)
    v
Forge Daemon (Python, asyncio)
    |
    |-- Project Scanner        -> reads .claude/, package.json, detects stack + MCP
    |-- Memory System          -> SQLite (.forge/forge.db)
    |   |-- Episodic Store     -> task history, errors, resolutions
    |   |-- Knowledge Base     -> gotchas, solutions, patterns
    |   |-- Procedural Store   -> routing intelligence
    |   +-- Research Cache     -> web search results
    |
    |-- Planner Agent          -> decomposes objectives into sprints (local LLM or Sonnet)
    |-- Generator Agents       -> write code in git worktrees (Ollama / Sonnet / Opus)
    |-- Evaluator Agent        -> reviews work externally, uses Playwright MCP (Sonnet)
    |-- Research Agent         -> web search + extract + store
    |-- Learner                -> post-session insight extraction
    |
    |-- Classifier             -> routes tasks by complexity (heuristic + procedural + LLM)
    |-- Scheduler              -> parallel execution with dependency resolution
    |-- Budget Controller      -> hard spend cap, model downgrade cascade
    |-- Worktree Manager       -> git worktree lifecycle
    +-- Merge Gate             -> diff review + evaluator sign-off + conflict resolution

Each Generator runs as: claude -p "<prompt with memory context>" --model <model> --worktree <name>
Each agent inherits: .claude/settings.json MCP configs, CLAUDE.md, auto-memory
```

---

## Repository structure

```
forge/
|-- README.md
|-- LICENSE                              # MIT
|-- setup.sh                             # Local setup (venv, deps, forge wrapper)
|
|-- daemon/                              # Python backend
|   |-- __init__.py
|   |-- main.py                          # Entry: CLI + daemon + WebSocket server
|   |-- config.py                        # All config via env vars with defaults
|   |-- models.py                        # Dataclasses: Task, Sprint, Session, etc.
|   |-- db.py                            # SQLite with all memory tables
|   |
|   |-- scanner/                         # Project detection (runs at forge init)
|   |   |-- __init__.py
|   |   |-- project.py                   # Detect git, package.json, stack, framework
|   |   |-- claude_code.py              # Read .claude/, CLAUDE.md, settings.json, MCP
|   |   +-- tools.py                     # Detect CLIs: gh, supabase, vercel, stripe, etc.
|   |
|   |-- memory/                          # Persistent knowledge system
|   |   |-- __init__.py
|   |   |-- episodic.py                  # Task execution history
|   |   |-- knowledge.py                 # Gotchas, solutions, patterns (the KB)
|   |   |-- procedural.py               # Routing patterns, model performance
|   |   |-- research.py                  # Web search cache + extraction
|   |   |-- retriever.py                # Unified cross-store retrieval + context builder
|   |   +-- learner.py                   # Post-session insight extraction
|   |
|   |-- agents/                          # Agent roles (planner/generator/evaluator)
|   |   |-- __init__.py
|   |   |-- planner.py                  # Decompose + negotiate sprint contracts
|   |   |-- generator.py               # Code execution in worktrees
|   |   |-- evaluator.py               # External review, Playwright, test runner
|   |   |-- researcher.py              # Web search + solution extraction
|   |   +-- reviewer.py                # Multi-perspective review panel
|   |
|   |-- executors/                       # Low-level execution engines
|   |   |-- __init__.py
|   |   |-- claude_code.py             # claude -p subprocess in worktree
|   |   |-- ollama.py                   # Ollama REST API
|   |   +-- batch.py                    # Claude API batch endpoint (50% off)
|   |
|   |-- scheduler.py                     # Parallel execution + dependency resolution
|   |-- budget.py                        # Cost control + model downgrade cascade
|   |-- worktree.py                      # Git worktree create/remove/list/diff
|   |-- ws_server.py                     # WebSocket server for UI
|   +-- cli.py                           # CLI commands
|
|-- daemon/requirements.txt              # httpx, websockets (that is it)
|
|-- ui/                                  # Next.js web dashboard
|   |-- package.json
|   |-- next.config.js
|   |-- tsconfig.json
|   |-- tailwind.config.ts
|   |-- app/
|   |   |-- layout.tsx
|   |   |-- page.tsx                     # Main dashboard
|   |   +-- globals.css
|   |-- components/
|   |   |-- PromptInput.tsx              # Prompt box with project context badges
|   |   |-- PlanView.tsx                # Sprint decomposition + contracts
|   |   |-- TaskDashboard.tsx           # Live grid of agent cards
|   |   |-- WorktreeCard.tsx            # Individual agent progress
|   |   |-- EvaluatorPanel.tsx          # Evaluator feedback + verdicts
|   |   |-- MergeGate.tsx               # Diff review + approve/reject
|   |   |-- CostMeter.tsx              # Token/cost/time metrics + budget bar
|   |   |-- MemoryBrowser.tsx           # Search/browse the knowledge base
|   |   |-- ResearchPanel.tsx           # Web search activity + results
|   |   |-- ReviewPanel.tsx             # Multi-perspective review cards
|   |   |-- LearningLog.tsx            # What Forge learned this session
|   |   +-- SessionHistory.tsx          # Past sessions with cost + knowledge
|   |-- hooks/
|   |   +-- useForgeSocket.ts           # WebSocket connection + state
|   +-- lib/
|       +-- types.ts                     # TS types matching daemon models
|
|-- tests/
|   |-- test_scanner.py
|   |-- test_knowledge.py
|   |-- test_retriever.py
|   |-- test_learner.py
|   |-- test_researcher.py
|   |-- test_planner.py
|   |-- test_evaluator.py
|   |-- test_reviewer.py
|   |-- test_classifier.py
|   |-- test_scheduler.py
|   |-- test_worktree.py
|   |-- test_merge_gate.py
|   +-- test_budget.py
|
+-- docs/
    |-- architecture.md
    |-- memory-system.md
    |-- harness-design.md                # How planner/generator/evaluator work
    |-- security.md
    +-- configuration.md
```

---

## Memory system

### Database schema (SQLite, WAL mode)

```sql
CREATE TABLE episodes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sprint_id TEXT,
    task_description TEXT NOT NULL,
    task_type TEXT,
    model TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    agent_role TEXT,                      -- "generator" | "evaluator" | "planner"
    status TEXT NOT NULL,                 -- completed | failed | revised
    result TEXT,
    error TEXT,
    error_category TEXT,                  -- dependency | syntax | runtime | timeout | permission
    resolution TEXT,
    evaluator_verdict TEXT,               -- approved | failed | revised
    evaluator_feedback TEXT,
    revision_count INTEGER DEFAULT 0,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    duration_seconds REAL,
    files_changed TEXT,                   -- JSON array
    created_at TEXT NOT NULL
);

CREATE TABLE knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,              -- gotcha | solution | pattern | rule | preference
    topic TEXT NOT NULL,                 -- supabase | vercel | next.js | auth | testing | etc.
    content TEXT NOT NULL,               -- One imperative line
    source TEXT,                         -- learned:session-X | research:url | user | claude-memory
    confidence REAL DEFAULT 0.5,
    times_applied INTEGER DEFAULT 0,
    times_helpful INTEGER DEFAULT 0,
    superseded_by INTEGER,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE procedures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_pattern TEXT NOT NULL,
    recommended_model TEXT NOT NULL,
    recommended_agent TEXT NOT NULL,
    success_rate REAL DEFAULT 0.0,
    avg_duration REAL DEFAULT 0.0,
    sample_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    url TEXT,
    title TEXT,
    extracted_content TEXT,
    relevance_score REAL DEFAULT 0.5,
    used_in_task TEXT,
    led_to_success INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE sprint_contracts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    description TEXT NOT NULL,
    done_criteria TEXT NOT NULL,          -- JSON array of testable criteria
    assigned_model TEXT,
    assigned_worktree TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    objective TEXT,
    detected_stack TEXT,                  -- JSON: framework, language, MCP servers
    started_at TEXT NOT NULL,
    ended_at TEXT,
    total_sprints INTEGER DEFAULT 0,
    completed_sprints INTEGER DEFAULT 0,
    failed_sprints INTEGER DEFAULT 0,
    total_cost REAL DEFAULT 0.0,
    knowledge_items_created INTEGER DEFAULT 0,
    knowledge_items_applied INTEGER DEFAULT 0
);

CREATE INDEX idx_knowledge_topic ON knowledge(topic);
CREATE INDEX idx_knowledge_category ON knowledge(category);
CREATE INDEX idx_knowledge_confidence ON knowledge(confidence);
CREATE INDEX idx_episodes_session ON episodes(session_id);
CREATE INDEX idx_episodes_type ON episodes(task_type);
CREATE INDEX idx_research_query ON research(query);
CREATE INDEX idx_procedures_pattern ON procedures(task_pattern);
```

### memory/knowledge.py

The knowledge base stores one-line imperative statements. Deduplicates on add. Confidence increases when a knowledge item is injected and the task succeeds, decreases when injected and the task fails. Items below 0.2 confidence or unused for 90 days get pruned. Max 200 items per project (forces quality over quantity).

Key methods:
- add(category, topic, content, source, confidence) with deduplication
- search(query, topic, category, limit) using SQLite LIKE and topic filter
- get_context_for_task(task_description) returns max 5 relevant items formatted as agent context
- mark_helpful(item_id) and mark_unhelpful(item_id) for confidence adjustment
- prune(max_items, min_confidence, max_age_days)
- import_from_claude_memory(project_path) reads Claude Code auto-memory files and imports relevant items

### memory/retriever.py

Unified retrieval across all stores. Given a task description:
1. Extract topics from description using local LLM (or keyword extraction)
2. Query knowledge base for relevant gotchas/solutions (max 5)
3. Query episodic store for past failures on similar tasks (max 3)
4. Query research cache for recent relevant research (max 2)
5. Return formatted context string (max ~500 tokens) for agent injection

The 500 token budget for memory context is deliberate. Context windows are the most important resource. Dumping the full KB wastes tokens and degrades performance.

### memory/learner.py

Post-session extraction runs after every session or after every failed-then-recovered task.

From failure + resolution pairs: Ask local LLM to distill a one-line gotcha. Prompt: "Extract ONE imperative sentence from this failure and resolution. If too generic, respond SKIP." Store with confidence 0.7.

From successful routing: Update the procedures table with the model, duration, and success for that task pattern.

From successful research: When web research was injected and the task succeeded, extract the key insight and store as a solution with the source URL.

Confidence reinforcement: After each task, check which knowledge items were injected into context. If the task succeeded, call mark_helpful on each. If it failed, call mark_unhelpful.

## Project detection (forge init)

### scanner/project.py

When the user runs forge init in a directory, the scanner runs automatically:

```python
async def scan_project(path: str) -> ProjectContext:
    """Scan the project directory and build a complete context."""
    ctx = ProjectContext(path=path)

    # 1. Git detection
    ctx.is_git = (Path(path) / ".git").exists()
    if ctx.is_git:
        ctx.default_branch = await get_default_branch(path)
        ctx.remote_url = await get_remote_url(path)

    # 2. Stack detection (read manifest files)
    if (Path(path) / "package.json").exists():
        pkg = json.loads((Path(path) / "package.json").read_text())
        ctx.language = "typescript" if (Path(path) / "tsconfig.json").exists() else "javascript"
        ctx.framework = detect_framework(pkg)  # next, react, vue, express, etc.
        ctx.package_manager = detect_pm(path)  # npm, yarn, pnpm, bun
    elif (Path(path) / "pyproject.toml").exists():
        ctx.language = "python"
        ctx.framework = detect_python_framework(path)  # fastapi, django, flask
    elif (Path(path) / "Cargo.toml").exists():
        ctx.language = "rust"
    # ... more detectors

    # 3. Claude Code detection
    ctx.has_claude = (Path(path) / ".claude").exists()
    if ctx.has_claude:
        ctx.claude_md = read_claude_md(path)
        ctx.mcp_servers = read_mcp_config(path)
        ctx.claude_rules = read_claude_rules(path)

    # 4. Claude Code auto-memory
    project_hash = get_project_hash(path)  # same hash Claude Code uses
    memory_path = Path.home() / ".claude" / "projects" / project_hash / "memory"
    if memory_path.exists():
        ctx.claude_auto_memory = read_auto_memory(memory_path)

    # 5. Available CLIs
    ctx.available_tools = detect_tools()  # gh, supabase, vercel, stripe, playwright

    return ctx
```

### scanner/claude_code.py

Reads .claude/settings.json to discover MCP servers:

```python
def read_mcp_config(project_path: str) -> list[MCPServer]:
    """Discover configured MCP servers from Claude Code settings."""
    settings_path = Path(project_path) / ".claude" / "settings.json"
    if not settings_path.exists():
        return []
    settings = json.loads(settings_path.read_text())
    servers = []
    for name, config in settings.get("mcpServers", {}).items():
        servers.append(MCPServer(
            name=name,
            command=config.get("command"),
            args=config.get("args", []),
        ))
    return servers
```

This is critical: Forge does not configure MCP. It discovers what Claude Code already has configured. When agents run claude -p in worktrees, they inherit these MCP connections automatically.

### scanner/tools.py

```python
def detect_tools() -> dict[str, bool]:
    """Check which CLIs are available on PATH."""
    tools = {}
    for tool in ["gh", "supabase", "vercel", "stripe", "playwright", "docker", "kubectl"]:
        tools[tool] = shutil.which(tool) is not None
    return tools
```

### forge init output

After scanning, forge init creates .forge/ and displays:

```
Forge initialized in /Users/dev/myproject

  Git:        main branch, github.com/user/myproject
  Stack:      Next.js 14 + TypeScript + Tailwind
  Claude:     CLAUDE.md found, 3 rules files
  MCP:        supabase, vercel, stripe (3 servers)
  Auto-memory: 12 items from past Claude Code sessions
  CLIs:       gh, supabase, vercel, playwright

  Created: .forge/forge.db (empty, ready to learn)
  Added:   .forge/ to .gitignore
```

---

## Agent specifications

### agents/planner.py — Sprint decomposition + contract negotiation

The planner takes a natural language objective and produces sprint-sized tasks with explicit "done" criteria. This follows the Anthropic harness pattern where the planner expands a 1-4 sentence prompt into a full spec.

The planner receives:
- The user's objective
- Project context from the scanner (stack, framework, available MCP)
- Relevant knowledge from the KB (gotchas, patterns for this type of work)
- Claude Code auto-memory (what the project has learned before)

It produces a JSON plan:
```json
[
  {
    "id": "sprint-1",
    "description": "Design Supabase schema with RLS policies",
    "done_criteria": [
      "Tables created: users, profiles, posts",
      "RLS policies applied for authenticated users",
      "Service role can bypass RLS for admin operations",
      "Migration file created and tested"
    ],
    "depends_on": [],
    "files_scope": ["supabase/migrations/"],
    "recommended_model": "opus",
    "estimated_tokens": 15000
  },
  ...
]
```

The done_criteria list is the sprint contract. The evaluator will test against exactly these criteria.

The planner runs on local Ollama for simple objectives (3-4 tasks) or Sonnet for complex ones (5+ tasks). Planning cost is $0 when local.

### agents/generator.py — Code execution in worktrees

The generator receives a sprint contract and executes code in an isolated git worktree. It is a thin wrapper that:

1. Gets memory context from the retriever (max 5 KB items + past failures)
2. Formats the full prompt: memory context + sprint description + done criteria
3. Calls the appropriate executor (claude -p in a worktree, or Ollama)
4. Returns the result without self-evaluation (that is the evaluator's job)

```python
async def generate(sprint: SprintContract, memory_context: str,
                   worktree_path: str) -> GeneratorResult:
    """Execute a sprint in a worktree. Do NOT self-evaluate."""
    prompt_parts = []

    if memory_context:
        prompt_parts.append(memory_context)

    prompt_parts.append(f"## Task\n{sprint.description}")
    prompt_parts.append(f"## Done criteria (you must satisfy ALL of these)")
    for i, criterion in enumerate(sprint.done_criteria, 1):
        prompt_parts.append(f"{i}. {criterion}")
    prompt_parts.append("\nImplement this. Run tests if applicable. Do not evaluate your own work.")

    full_prompt = "\n\n".join(prompt_parts)

    if sprint.recommended_model in ("opus", "sonnet"):
        return await claude_executor.execute(full_prompt, worktree_path, sprint.recommended_model)
    else:
        return await ollama_executor.execute(full_prompt, sprint.recommended_model)
```

The instruction "Do not evaluate your own work" is deliberate. Anthropic's research showed self-evaluation is unreliable. The evaluator handles judgment.

### agents/evaluator.py — External verification

The evaluator is the most important agent. It runs after every generator sprint, on a different model, and its job is to be skeptical.

The evaluator receives:
- The sprint contract (done criteria)
- The git diff from the generator's worktree
- Access to the running application (via Playwright MCP if it is a web project)
- The project context

It verifies each done criterion independently and returns a verdict.

```python
async def evaluate(sprint: SprintContract, diff: str,
                   project_context: ProjectContext) -> EvaluatorResult:
    """Evaluate generator's work against sprint contract. Be skeptical."""

    system = """You are a strict code reviewer and QA engineer.
Your job is to verify that EVERY done criterion is met.
Do NOT give the benefit of the doubt. If something looks incomplete or wrong, FAIL it.
Test criteria that are testable. Read the diff carefully for regressions."""

    prompt_parts = [
        f"## Sprint contract\n{sprint.description}",
        f"## Done criteria to verify",
    ]
    for i, c in enumerate(sprint.done_criteria, 1):
        prompt_parts.append(f"{i}. {c}")

    prompt_parts.append(f"\n## Git diff from generator\n```\n{diff[:12000]}\n```")

    if project_context.framework in ("next", "react", "vue") and "playwright" in project_context.available_tools:
        prompt_parts.append("\nYou have Playwright MCP available. Start the dev server and click through the UI to verify visual/functional criteria.")

    prompt_parts.append("""
For each criterion, respond:
- PASS: <criterion> — <evidence>
- FAIL: <criterion> — <what is wrong> — <specific fix needed>

Then give overall verdict: APPROVED (all pass) or REVISE (any fail).
If REVISE, list the specific changes the generator must make.""")

    # Always run evaluator on a DIFFERENT model than generator
    eval_model = "sonnet" if sprint.recommended_model == "opus" else "sonnet"

    result = await claude_executor.execute(
        "\n\n".join(prompt_parts),
        worktree_path=None,  # evaluator reads diff, does not edit files
        model=eval_model
    )

    return parse_evaluator_result(result)
```

Key design decisions:
- Evaluator runs on a DIFFERENT model than generator (cross-model verification)
- Evaluator is prompted to be skeptical, not generous
- Each done criterion is verified independently with evidence
- If any criterion fails, the sprint fails and generator gets specific feedback
- Max 2 revision cycles per sprint (then escalate to user)

### agents/researcher.py — Web search + knowledge extraction

Searches the web when:
- A task fails and the KB has no known solution
- A complex task is about to execute (proactive research)
- User explicitly requests research from the UI or CLI

Uses claude -p with a search-oriented prompt (Claude Code has web search capability), or the Claude API with web_search tool.

```python
async def search_for_error(self, error: str, context: str) -> Optional[ResearchResult]:
    """Search web for a solution to a specific error."""
    # Generate 1-3 focused search queries using local LLM
    queries = await self._generate_queries(error, context)

    for query in queries[:3]:
        results = await self._web_search(query)
        if results:
            extracted = await self._extract_relevant_content(results[0], error)
            await self.db.store_research(query=query, url=results[0].url,
                title=results[0].title, extracted_content=extracted)
            return ResearchResult(content=extracted, url=results[0].url)
    return None

async def research_before_task(self, task_description: str) -> Optional[str]:
    """Proactive research for complex tasks. Checks cache first."""
    cached = await self.db.get_recent_research(task_description, max_age_days=30)
    if cached:
        return self._format(cached)
    # Only research if task is HIGH complexity
    results = await self._web_search(task_description[:100])
    if results:
        extracted = await self._extract_relevant_content(results[0], task_description)
        await self.db.store_research(query=task_description[:100],
            url=results[0].url, extracted_content=extracted)
        return extracted
    return None
```

### agents/reviewer.py — Multi-perspective review panel

Spawns 2-5 parallel agents, each with a different review perspective. Used for:
- Merge gate (automatic, for large changes)
- Error diagnosis (when a task fails)
- On-demand review (user clicks Review in UI)

Perspectives:
- security: vulnerabilities, injection, auth, data exposure (Sonnet)
- performance: N+1, indexes, bundle size, algorithms (local Ollama)
- maintainability: naming, types, coupling, tests (local Ollama)
- correctness: edge cases, off-by-one, null handling, races (Sonnet)
- architecture: design, separation, scalability (Opus)

Default for code review: security + correctness + maintainability (2 local + 1 Sonnet = cheap).

Each reviewer gets relevant KB context injected. After all complete, a local LLM synthesizes into: overall verdict, critical issues (flagged by 2+ reviewers), and action items.

---

## Executors

### executors/claude_code.py

```python
async def execute(prompt: str, worktree_path: str, model: str = "sonnet") -> ExecutionResult:
    """Run claude -p in a git worktree with memory-enriched prompt."""
    sanitized = sanitize_prompt(prompt)  # strip null bytes, control chars, cap length
    cmd = ["claude", "-p", sanitized]
    if model in ("opus", "sonnet", "haiku"):
        cmd.extend(["--model", model])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=worktree_path,  # isolated worktree — fresh context, inherits MCP
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TASK_TIMEOUT)
    ...
```

The cwd=worktree_path is what makes everything work. Claude Code reads .claude/ from the repo root (which the worktree shares), so MCP connections, CLAUDE.md, and auto-memory all carry through.

### executors/ollama.py

```python
async def execute(prompt: str, model: str = "qwen3:8b") -> ExecutionResult:
    """Run via Ollama REST API. Zero cost."""
    async with httpx.AsyncClient(timeout=TASK_TIMEOUT) as client:
        r = await client.post(f"{OLLAMA_BASE}/api/chat", json={
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a precise software development assistant."},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {"temperature": 0.2}
        })
        ...
```

### executors/batch.py

For non-urgent tasks (documentation, analysis), uses the Claude API batch endpoint at 50% off:

```python
async def execute(prompt: str, model: str = "sonnet") -> ExecutionResult:
    """Submit to Claude API batch endpoint. 50% cheaper, higher latency."""
    async with httpx.AsyncClient() as client:
        r = await client.post("https://api.anthropic.com/v1/messages", json={
            "model": f"claude-{model}-4-6" if model in ("opus","sonnet") else model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]
        }, headers={"x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                     "anthropic-version": "2023-06-01"})
        ...
```

Requires ANTHROPIC_API_KEY env var. Optional — Forge works fine without it (uses claude -p instead).

---

## Scheduler — the execution loop

### scheduler.py

The scheduler orchestrates the full planner -> generator -> evaluator cycle:

```python
async def execute_session(objective: str):
    """Full session: plan -> generate -> evaluate -> learn."""
    session = create_session(objective)
    project_ctx = await scan_project(os.getcwd())

    # Phase 1: Plan (free on Ollama)
    sprints = await planner.plan(objective, project_ctx)
    broadcast_ws({"type": "plan_created", "sprints": sprints})

    # Phase 2: Execute sprints respecting dependencies
    completed = set()
    for wave in dependency_waves(sprints):
        # Run independent sprints in parallel
        tasks = []
        for sprint in wave:
            if not budget.can_afford(sprint):
                sprint = budget.downgrade(sprint)
            tasks.append(execute_sprint(sprint, project_ctx, session.id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for sprint, result in zip(wave, results):
            if isinstance(result, Exception):
                sprint.status = "failed"
            completed.add(sprint.id)

    # Phase 3: Merge gate (review panel for large changes)
    await merge_gate(session, project_ctx)

    # Phase 4: Learn from this session
    await learner.learn_from_session(session.id)


async def execute_sprint(sprint: SprintContract, ctx: ProjectContext, session_id: str):
    """Execute one sprint: generate -> evaluate -> (revise up to 2x) -> done."""

    # Create worktree for this sprint
    wt_path = await worktree.create(sprint.id)

    # Build memory context (max ~500 tokens)
    memory = await retriever.get_context_for_task(sprint.description)

    for attempt in range(MAX_REVISIONS + 1):
        # Generate
        gen_result = await generator.generate(sprint, memory, wt_path)
        broadcast_ws({"type": "sprint_generated", "sprint_id": sprint.id})

        if not gen_result.success:
            # Try recovery: KB lookup -> web search -> retry
            recovery = await recover_from_error(sprint, gen_result.error)
            if recovery:
                memory += f"\n\n## Recovery context\n{recovery}"
                continue
            else:
                sprint.status = "failed"
                break

        # Evaluate (on different model, from outside)
        diff = await worktree.get_diff(sprint.id)
        eval_result = await evaluator.evaluate(sprint, diff, ctx)
        broadcast_ws({"type": "sprint_evaluated", "sprint_id": sprint.id,
                       "verdict": eval_result.verdict})

        if eval_result.verdict == "APPROVED":
            sprint.status = "completed"
            await episodic.store(sprint, gen_result, eval_result)
            break
        elif attempt < MAX_REVISIONS:
            # Feed evaluator feedback to generator for revision
            memory += f"\n\n## Evaluator feedback (revision {attempt+1})\n{eval_result.feedback}"
            sprint.revision_count += 1
        else:
            sprint.status = "failed"
            sprint.error = f"Failed after {MAX_REVISIONS} revisions: {eval_result.feedback}"

    return sprint
```

The generate -> evaluate -> revise loop is the core mechanism from the Anthropic harness paper. Each revision gets the evaluator's specific feedback injected into the generator's next attempt, creating a focused improvement cycle.

## Web UI specification (Next.js)

Tech stack: Next.js 14+ App Router, TypeScript, Tailwind CSS, native WebSocket. No UI library.

Design direction: Dark theme default with light toggle. JetBrains Mono for code/IDs. System font stack for everything else. Dashboard aesthetic — clean, dense, functional. Teal for Ollama/local, purple for Claude, coral for evaluator feedback, amber for warnings, red for failures, gray for pending.

### Components

PromptInput.tsx: Large textarea at the top. On submit, sends plan command via WebSocket. Below the input, shows context badges auto-detected from project scan: git repo name, framework, detected MCP servers (supabase, vercel, stripe), Ollama status, knowledge base item count.

PlanView.tsx: Renders the sprint decomposition. Each sprint card shows: description, done criteria (expandable), assigned model badge, dependency links, estimated cost. "Run all" button at the bottom. User can click individual sprints to edit the done criteria before execution.

TaskDashboard.tsx: Grid of WorktreeCards during execution. Shows running sprints first, then pending, completed, failed. Updates in real-time via WebSocket.

WorktreeCard.tsx: One card per active sprint/worktree. Shows: sprint ID, description (truncated), model badge with color, status indicator (animated for running), progress messages from the generator. When the evaluator runs, shows verdict badge (APPROVED in green, REVISE in amber, FAIL in red). Expandable to show evaluator feedback and revision history.

EvaluatorPanel.tsx: Dedicated panel that appears during evaluation. Shows each done criterion with PASS/FAIL status and evidence. Shows the evaluator's specific feedback for failed criteria. Shows revision count if in a revision loop.

MergeGate.tsx: Appears after all sprints complete. Lists each worktree with file count, conflict status, and diff preview. If the review panel ran, shows the multi-perspective verdicts. Approve/reject buttons per worktree and globally.

CostMeter.tsx: Three inline metric cards: tokens used (in/out breakdown), cost (USD with per-model breakdown), time elapsed. Budget progress bar showing spent vs session cap. Highlights when budget downgrade occurs.

MemoryBrowser.tsx: Searchable, filterable view of the knowledge base. Filter by category (gotcha/solution/pattern/rule), filter by topic. Confidence meter per item. Usage stats (times applied, times helpful). Add/edit/delete buttons. Search box queries across all items.

ResearchPanel.tsx: Shows research activity. Active searches with status. Results with source URLs and relevance scores. "Save to KB" button per result.

ReviewPanel.tsx: Multi-perspective review visualization. Card per perspective (security/performance/correctness/maintainability/architecture) with verdict badge. Expandable issues and suggestions. Synthesized recommendation at top.

LearningLog.tsx: What Forge learned this session. New knowledge items with source. Updated routing patterns. Confidence changes. Summary line: "This session: 4 gotchas learned, 2 patterns updated, 1 web solution cached."

SessionHistory.tsx: Past sessions from SQLite. Click to expand: objective, sprint breakdown, cost, knowledge items created, what was learned.

### useForgeSocket.ts

WebSocket hook managing all state. Connects to ws://127.0.0.1:9111. Handles all message types. Exposes: sprints, tasks, metrics, mergeState, connected, send().

### WebSocket protocol

Client to server:
- init: trigger project scan + display context
- plan: objective string
- run_all / run_sprint: sprint IDs
- add_task: description + optional force_model
- merge_approve / merge_reject: worktree names
- cancel: sprint_id
- search_knowledge: query
- add_knowledge: category, topic, content
- delete_knowledge: item_id
- research: query (manual research request)
- review: sprint_id + perspectives list
- status

Server to client:
- project_context: detected stack, MCP servers, tools, KB count
- plan_created: sprints array with contracts
- sprint_started / sprint_progress / sprint_generated
- sprint_evaluated: verdict + feedback
- sprint_revised: revision number + feedback
- sprint_completed / sprint_failed
- merge_ready: worktrees + conflicts + review results
- merge_complete
- budget_warning / budget_downgrade
- knowledge_updated: new/modified items
- research_result: query + results
- review_complete: perspectives + synthesis
- session_learnings: new knowledge + updated patterns
- error_recovery: sprint_id + strategy used

---

## CLI specification

```
forge init                               # Scan project, create .forge/, display context
forge plan "Build auth API with tests"   # Decompose into sprints with contracts
forge run                                # Execute all pending sprints
forge run sprint-a1f3                    # Execute specific sprint
forge add "Fix login bug" --claude       # Add single task (skip planner)
forge status                             # Show dashboard in terminal
forge doctor                             # Check Claude Code, Ollama, git, MCP
forge models                             # List Ollama models
forge merge --approve                    # Approve all clean merges
forge merge --show                       # Show pending diffs
forge budget                             # Show spend vs cap
forge memory                             # Show KB summary + stats
forge memory search "supabase"           # Search knowledge base
forge memory add "gotcha" "supabase" "RLS requires service_role for testing"
forge memory import                      # Import from Claude Code auto-memory
forge research "next.js middleware auth" # Manual web research
forge review sprint-a1f3                 # Run multi-perspective review
forge reset                              # Clear tasks (keep KB and patterns)
forge serve                              # Start daemon + open browser dashboard
```

forge serve starts the Python daemon (WebSocket on 127.0.0.1:9111) and the Next.js dev server (localhost:3000), then opens the browser.

---

## Security requirements

Non-negotiable:

1. No curl-pipe-bash install. setup.sh is local, readable, uses venv.
2. No --dangerously-skip-permissions. Claude Code sessions run with default permission mode.
3. WebSocket binds to 127.0.0.1 ONLY. Never 0.0.0.0. This is hardcoded, not configurable.
4. No shell=True in any subprocess call. All use asyncio.create_subprocess_exec with argument lists.
5. Input sanitization on all user inputs. Worktree names: alphanumeric + hyphens only (regex validated). Task descriptions: strip null bytes and control chars, cap at 10000 chars.
6. Budget hard cap. Session cannot exceed SESSION_BUDGET_USD. When exhausted, remaining tasks downgrade (opus->sonnet->ollama) or cancel.
7. No secrets in code. API keys from environment variables or Claude Code's own authentication.
8. SQLite WAL mode for safe concurrent reads from UI and daemon.
9. Git worktree cleanup on exit. atexit handler + SIGINT/SIGTERM handlers ensure worktrees are removed even on crash.
10. Two pip dependencies only (httpx, websockets). Both widely used, actively maintained.
11. Research content is context only, never executed as code or commands.
12. Knowledge base is user-editable. Users can delete, modify, or override any learned item via UI or CLI.
13. Confidence decay. Unreinforced knowledge items lose confidence over time and get pruned automatically.
14. Source tracking. Every knowledge item records where it came from (session ID, URL, or manual entry).
15. No external memory services. All data local in .forge/forge.db. No cloud APIs for memory.
16. .forge/ is added to .gitignore at init. Knowledge stays local to the developer, not committed to repo.
17. Evaluator never runs in the same worktree as the generator. Evaluation is read-only against the diff.

---

## Testing requirements

Use pytest. Tests must run without Ollama or Claude Code installed (mock executors).

- test_scanner.py: Detect git, package.json, .claude/, MCP configs, available CLIs. Test with mock file structures.
- test_knowledge.py: Add, search, deduplicate, reinforce, decay, prune, get_context_for_task (verify max 5 items, max ~500 tokens).
- test_retriever.py: Cross-store retrieval, context formatting, token budget enforcement.
- test_learner.py: Extract gotcha from failure+resolution. Skip generic items. Update routing patterns. Confidence reinforcement/decay.
- test_researcher.py: Generate search queries from errors. Cache lookup before search. Store results. Expiry.
- test_planner.py: JSON plan parsing. Dependency chain creation. Fallback to single task on parse failure. Sprint contract format.
- test_evaluator.py: Parse PASS/FAIL per criterion. Overall verdict logic. Revision feedback format.
- test_reviewer.py: Parallel perspective execution. Synthesis logic. Default perspective selection.
- test_classifier.py: Heuristic regex routing. Procedural lookup (mock DB). LLM fallback (mock Ollama).
- test_scheduler.py: Dependency wave calculation. Parallel execution. Timeout handling. Generate->evaluate->revise loop. Max revision cap.
- test_worktree.py: Create, remove, list, diff. Name sanitization. Cleanup on failure. Concurrent worktree limit.
- test_merge_gate.py: Conflict detection between worktrees. Clean merge path. Rejection. Review panel integration.
- test_budget.py: Cost estimation per model. Downgrade cascade (opus->sonnet->ollama). Hard cap enforcement. Partial session budget tracking.

---

## Build order

Build sequentially so each piece is testable before the next:

1. daemon/config.py + daemon/models.py + daemon/db.py (all tables including sprint_contracts)
2. daemon/scanner/ (project.py, claude_code.py, tools.py) + test_scanner.py
3. daemon/memory/knowledge.py + daemon/memory/episodic.py + test_knowledge.py
4. daemon/memory/procedural.py + daemon/memory/retriever.py + test_retriever.py
5. daemon/agents/classifier.py + test_classifier.py
6. daemon/executors/ollama.py + daemon/executors/claude_code.py
7. daemon/agents/planner.py + test_planner.py (uses scanner context + KB)
8. daemon/agents/generator.py (thin wrapper over executors + memory context)
9. daemon/agents/evaluator.py + test_evaluator.py (reads diffs, verifies contracts)
10. daemon/agents/researcher.py + daemon/memory/research.py + test_researcher.py
11. daemon/agents/reviewer.py + test_reviewer.py
12. daemon/scheduler.py + test_scheduler.py (generate->evaluate->revise loop)
13. daemon/budget.py + test_budget.py
14. daemon/worktree.py + test_worktree.py
15. daemon/memory/learner.py + test_learner.py (post-session extraction)
16. daemon/ws_server.py (WebSocket with all event types)
17. daemon/cli.py + daemon/main.py (CLI + forge serve)
18. setup.sh (safe local installer)
19. ui/ — Next.js dashboard (all components, useForgeSocket hook)
20. README.md + docs/ (architecture, memory-system, harness-design, security, configuration)
21. Integration test: forge init -> forge plan -> forge run -> verify memory persists to next session

---

## Success criteria

```bash
# Setup in an existing project
cd ~/projects/my-webapp    # already has .claude/, package.json, MCP configured
forge init                  # Scans project, finds Next.js + Supabase + Vercel MCP
forge doctor                # Claude Code OK, Ollama OK, Git OK, 3 MCP servers

# Session 1: First run, empty knowledge base
forge serve                 # Opens browser dashboard
# In browser: "Build user authentication with Supabase RLS, login/signup pages, and tests"
# See: Plan with 4 sprints, done criteria per sprint, model assignments, $1.20 estimate
# Click: "Run all"
# Watch: Generator creates auth schema in worktree-1 (Opus)
# Watch: Evaluator verifies RLS policies — FAILS criterion 3 (service_role bypass missing)
# Watch: Generator revises with evaluator feedback — APPROVED on attempt 2
# Watch: 2 more sprints run in parallel (Sonnet), evaluator approves both
# Watch: Merge gate shows 3 clean worktrees, review panel flags no security issues
# Click: "Approve all" — branches merge to main
# See: Learning log: "Learned: Supabase RLS requires explicit service_role bypass policy"
#       "Learned: Next.js server actions need 'use server' directive"
#       Routing updated: "supabase schema" -> opus (confirmed)

# Session 2: Memory is active
# In browser: "Add profile management with avatar upload"
# See: Planner receives gotchas from Session 1 in context
# See: Generator receives "Known: Supabase RLS requires service_role bypass" before coding
# Result: No revision needed — evaluator approves first attempt on RLS-related sprint
# Cost: 30% lower than Session 1 for similar scope (fewer revisions + better routing)

# Session 10: Deep institutional knowledge
# 40+ gotchas in KB, routing accuracy 90%+
# Proactive research triggers for unfamiliar topics
# Evaluator catches regressions using knowledge from past sessions
# Total session time: 50% faster than Session 1
```

---

## What NOT to build

- No vector embeddings. SQLite LIKE + topic filtering is sufficient. No embedding models, no vector DBs.
- No external memory services (Mem0, Zep, etc.). Local SQLite only.
- No LangChain, no CrewAI, no agent framework. Raw Python + httpx + websockets.
- No Docker. This runs on the developer's machine inside their project folder.
- No authentication. Localhost only.
- No plugin system. Edit Python files to extend.
- No telemetry. All data stays in .forge/ on the local machine.
- No npm publish. Git clone + setup.sh.
- No custom MCP implementation. Claude Code sessions already speak MCP natively.
- No replacement of Claude Code auto-memory. Read it, extend it, do not replace it.
- No separate tool configurations. Inherit everything from .claude/ directory.
