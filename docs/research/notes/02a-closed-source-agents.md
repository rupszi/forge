# Part 2A — Closed-Source Coding Agents: Reverse-Engineering the Designs

This note reverse-engineers the architecture of major closed-source (and a few open-but-comparable) coding agents based on engineering blog posts, official docs, third-party deep-dives, and source where it exists. Where a claim is not verifiable in primary sources, it is marked `[unverified]`.

The dimensions covered for each product:

- Agent loop architecture
- Tool / function-calling schema
- Context-window strategy (compaction, retrieval, scratchpads)
- Memory model (session, project, user)
- Sandboxing approach
- Multi-file editing strategy
- Planning vs. execution split
- Published harness details

---

## 1. Claude Code (Anthropic)

Claude Code is Anthropic's CLI + IDE-plugin coding agent. Its architecture is the most thoroughly documented of any closed-source agent, because Anthropic uses Claude Code itself as the canonical example in its "harness design," "context engineering," "writing tools for agents," and "Claude Agent SDK" engineering posts. The `@anthropic-ai/claude-code` package is partially observable, and the public Claude Agent SDK exposes the same loop, tools, and permissions that drive Claude Code internally.

**Agent loop architecture.** The loop is "gather context -> take action -> verify work -> repeat" and is single-threaded by default. Each turn consists of (1) Claude receives system prompt + tool defs + history; (2) Claude emits text and/or tool calls; (3) the SDK executes those calls and returns results; (4) loop until a turn produces text with no tool calls. Read-only tools (`Read`, `Glob`, `Grep`, MCP tools marked read-only) run **concurrently**; state-mutating tools (`Edit`, `Write`, `Bash`) run **sequentially** to avoid conflicts. Loops can be capped by `maxTurns` or `maxBudgetUsd`.

**Tool schema.** JSON-schema function-calling. Built-in tools fall into six categories: file (`Read`, `Edit`, `Write`), search (`Glob`, `Grep`), execution (`Bash`), web (`WebSearch`, `WebFetch`), discovery (`ToolSearch` for on-demand tool loading), and orchestration (`Agent`, `Skill`, `AskUserQuestion`, `TodoWrite`). External tools come in via MCP. Tool definitions follow Anthropic's "Writing Tools for Agents" guidance: prefer a small number of high-value, consolidated tools (e.g. one `schedule_event` instead of `list_users`+`list_events`+`create_event`); namespace them (`asana_search`); have them return semantically meaningful strings (resolve UUIDs to human-readable references); expose a `response_format` enum so the agent can pick concise vs. detailed payloads.

**Context-window strategy.** Hybrid retrieval, not pure RAG. `CLAUDE.md` files load up-front and are prompt-cached on every request. `Glob` and `Grep` provide just-in-time file access, deliberately bypassing "stale indexing and complex syntax trees." When the window approaches the limit, the SDK runs **automatic compaction**: it summarizes older messages while preserving recent exchanges and key decisions. A `compact_boundary` system message is emitted; a `PreCompact` hook can archive the full transcript first; users can trigger `/compact` manually. Anthropic's "harness for long-running apps" post adds that for Sonnet 4.5, compaction alone wasn't enough — they used full **context resets** (start a fresh agent with a structured handoff: feature-list JSON, `claude-progress.txt`, git log). With Opus 4.6 those resets were no longer required, illustrating that "every component in a harness encodes an assumption about what the model can't do on its own."

**Memory model.**
- *Session* — conversation history, prompt-cached system prompt, tool defs.
- *Project* — `CLAUDE.md` (re-injected every request) plus `.claude/` directory containing rules, skills, sub-agents, hooks, MCP config.
- *Auto-memory* — Claude Code maintains files under `~/.claude/projects/<project-hash>/memory/` across sessions.
- *Persistent agent memory* — Anthropic shipped a memory tool that lets agents build a knowledge base "across sessions without consuming context window space."

**Sandboxing.** No process-level sandbox by default. Safety is layered through (1) `permission_mode` (`default`, `acceptEdits`, `plan`, `dontAsk`, `auto`, `bypassPermissions`); (2) `allowedTools` / `disallowedTools` allowlists with rule syntax like `"Bash(npm *)"`; (3) `PreToolUse` hooks that can block or rewrite a call before execution. `bypassPermissions` is reserved for CI / containers and is blocked when running as root.

**Multi-file editing strategy.** `Edit` tool uses old-string/new-string replacement (must be unique in file or `replace_all`). `Write` is full-file. `MultiEdit` (in some surfaces) batches edits per file. There is no whole-repo diff format — the model edits files one at a time, with the harness validating each edit.

**Planning vs. execution split.**
- *Plan mode* — `permissionMode: "plan"` runs the loop with no tool execution; Claude produces a plan for the user to approve.
- *Sub-agents* — defined in `.claude/agents/*.md` with frontmatter (`description`, `prompt`, `tools`, `model`, `permissionMode`, `mcpServers`, `hooks`, etc.) and dispatched via the `Agent` tool. Each sub-agent runs in its own context window with its own system prompt, sees no parent history, and returns only its final response. Anthropic's harness post shows them using a generator/evaluator pair (a "GAN-inspired" feedback loop, in third-party write-ups) where the evaluator runs Playwright against the running app and grades against criteria.

**Published harness details.** The "Harness Design for Long-Running Application Development" post is the most concrete: feature-list JSON of ~200 features, `init.sh` for dev server, `claude-progress.txt` for cross-session handoff, git for rollback, generator/evaluator separation because "agents tend to confidently praise their own work even when it's mediocre."

Sources: [1], [2], [3], [4], [5], [6], [7], [8].

---

## 2. OpenAI Codex CLI (`@openai/codex`)

Codex CLI is OpenAI's Apache-2.0 terminal coding agent, hosted at `github.com/openai/codex`. The repo is ~96% **Rust** (`codex-rs` workspace) with a thin `codex-cli` shell. It is the closest mainstream peer to Claude Code in scope.

**Agent loop architecture.** Single agent loop with tool calls. Codex runs locally and ships a "Codex Web" remote variant; it also supports sub-agents and code-review as separate agent invocations. The loop is not as deeply documented as Claude Code's, but the public CLI reference shows the standard prompt -> tool-call -> tool-result -> repeat pattern.

**Tool schema.** OpenAI function-calling JSON schema. Tools include code inspection/editing, local command execution (the shell), web search, image input (screenshots, design specs), image generation/editing, MCP integration, and "cloud task launching."

**Context-window strategy.** Less publicly documented than Anthropic's. Codex relies on the AGENTS.md convention as its persistent project context (analogous to CLAUDE.md). Beyond that, the docs mention compaction in passing but don't publish the algorithm.

**Memory model.**
- *Session* — conversation in a single CLI session.
- *Project* — `AGENTS.md` at the repo root: a Markdown style guide / dev guide that the agent reads to learn project conventions (build commands, test invocations, architecture rules). The format is now a cross-vendor convention — Cursor, Cline, and Aider also recognize variants.
- *User* — `~/.codex/` config directory.

**Sandboxing.** This is the area Codex is **most distinct on**. The sandbox is OS-native and multi-platform:

- *macOS* — Apple's **Seatbelt** (`sandbox-exec`) with a profile per sandbox mode.
- *Linux/WSL2* — **Bubblewrap** (`bwrap`) for user-namespace isolation, with **Landlock** as a fallback / supplementary LSM. Namespace isolation covers user, PID, and network. Sensitive paths (`.git`, `.codex`) are re-mounted read-only even inside writable roots.
- *Windows* — native Windows sandbox in PowerShell (provisions `CodexSandboxOffline` and `CodexSandboxOnline` local users with ACLs).

The sandbox constrains *spawned* commands too (git, package managers, test runners), not just Codex's own file ops. Two orthogonal axes:

1. **Sandbox mode** (filesystem/network capabilities): `read-only`, `workspace-write` (read repo, write inside project), `danger-full-access`. Network managed via domain/socket allowlists.
2. **Approval policy** (when Codex must ask): `untrusted` (pause before commands outside trusted set), `on-request` (default — ask when sandbox limits are exceeded), `never` (no prompts).

Earlier UI surfaced these as three friendlier modes: **suggest** / **auto-edit** / **full-auto**.

**Multi-file editing strategy.** Diff/patch-based edits applied in the sandbox; details of the patch format are not extensively documented publicly. `[unverified]` exact diff schema — would need to read `codex-rs/core` source to confirm.

**Planning vs. execution split.** Codex CLI supports **subagents** for parallelization and a **code-review** agent. There is no formal "plan mode" the way Claude Code has it, but interactive approval flows give a similar effect.

**Published harness details.** Public docs cover the sandbox in depth (the most thorough of any agent), and AGENTS.md is now widely adopted. Internal loop / context-management details are less public than Anthropic's.

Sources: [9], [10], [11], [12], [13].

---

## 3. Cursor

Cursor is a VS Code fork; its agent (originally Composer / "Agent mode," now Composer 1 native model since Nov 2025) is the productized form. Architecture details come from the Cursor blog, founder interviews, and third-party deep-dives.

**Agent loop architecture.** Tool-use loop on top of selectable models (proprietary Composer 1, plus Claude/GPT/Gemini variants). Cursor 2.0 introduced a **multi-agent** workspace: up to 8 agents working in parallel, each in its own git worktree or remote VM, "modifying the same files simultaneously in separate workspaces."

**Tool schema.** JSON tool calls (model-dependent). LSP integration is first-class; MCP is supported for external tools.

**Context-window strategy — the Cursor-specific stack.**
- **Codebase indexing**: each file is split into syntactic chunks (tree-sitter for boundaries), each chunk embedded with Cursor's proprietary embedding model, embeddings cached by chunk content. Initial index uploads files once; ongoing sync transfers only changed-file hashes (~3.2 MB for 50k files). Indexes are protected by a Merkle tree — server stores hashes; clients prove possession of files before search results are returned, so users only see results for code they actually have. Team indexes use a similarity hash (simhash) to find shareable indexes.
- **Retrieval at query time**: vector search over the index plus filename/symbol filters; the planner drafts a change plan before edits.
- **Shadow workspace**: a hidden VS Code instance the AI uses to test edits and consume language-server diagnostics. Agent proposes change → shadow workspace runs LSP/typecheck/lint → if it fails, agent gets the diagnostics back and revises before showing the user. Cursor runs the shadow workspace **on demand** with idle teardown to limit CPU.
- **Tab completion** uses a separate, latency-optimized pipeline (Cursor's "Copilot++") with speculative-decoding-accelerated apply via a 70B-class fast-apply model serving >1000 tok/s.

**Memory model.** Project-level via **Cursor Rules** (`.cursor/rules/`) — the equivalent of CLAUDE.md / AGENTS.md. Conversation memory across sessions is a feature ("Memories"). User-level config in Cursor settings.

**Sandboxing.** Local agent runs in the user's environment. Multi-agent mode uses **git worktrees or remote VMs** as the isolation unit — not OS sandboxing. Cursor Background Agents run in cloud VMs.

**Multi-file editing strategy.** Edit-then-apply: the planner emits intent; the fast-apply model translates intent into a concrete patch against the current file; edits are streamed and the user sees a diff to accept/reject. Granularity is per-file diffs, not whole-repo patches.

**Planning vs. execution split.** Composer presents a plan, then executes. The Tab/Cmd-K inline-edit path is direct execution, no plan. Cursor 2.0 added **Tasks**: short-running parallelizable work units handed to background agents.

**Published harness details.** "Securely indexing large codebases" (Merkle proofs of file possession) is the strongest published architecture document. Internal loop details come mostly from founder interviews and reverse-engineering.

Sources: [14], [15], [16].

---

## 4. Windsurf / Cascade (Codeium)

Windsurf is Codeium's VS Code-fork IDE; **Cascade** is its agent, framed as the "Flow paradigm" — the AI maintains continuous awareness of user actions, codebase, and history rather than re-asking for context.

**Agent loop architecture.** Documented as a **dual-agent system**: "a specialized planning agent continuously refines the long-term plan while your selected model focuses on taking short-term actions based on that plan." Plans update automatically as new info emerges. Up to 20 tool calls per prompt with continuation when the cap is hit. Two top-level modes: **Code mode** (write/modify) and **Chat mode** (Q&A/suggestion).

**Tool schema.** Standard tool-use. Tool ecosystem: search, web search, package detection/install, terminal, MCP, linter analysis & auto-fix.

**Context-window strategy — the Cascade pipeline.** Documented in Codeium docs and third-party deep-dives. Five-stage assembly:

1. Load **rules** (global `.windsurfrules`, then project-level).
2. Load relevant **memories** from prior sessions.
3. Read open files (active file weighted highest, other tabs included).
4. Run **M-Query** retrieval — a proprietary retrieval method "to improve precision over basic cosine similarity," using 768-dim embeddings, claimed to reduce hallucination vs. plain RAG.
5. Read **recent actions** — file edits, terminal commands, navigation history from the current session.

The pipeline merges, weighs, and trims to fit the window.

**Memory model.**
- *Rules* (`.windsurfrules` global + project) — stable conventions.
- *Memories* — evolving knowledge that persists across sessions; capture decisions with rationale.
- *Per-session action history* — file/terminal/nav events fed into the next turn automatically (the "Flow" claim).
- Workspace ignore via `.codeiumignore` plus enterprise-level ignores in `~/.codeium/`.

**Sandboxing.** Local IDE; no special sandbox. Tab completion runs through a separate, latency-optimized pipeline distinct from Cascade.

**Multi-file editing strategy.** Tool-mediated edits with diff preview; specifics of the patch format are not deeply documented. `[unverified]` exact diff schema — would search Codeium engineering blog.

**Planning vs. execution split.** Explicit planner agent ↔ executor model split — the documented architecture is closest to Cognition's Devin among IDE products.

Sources: [17], [18], [19].

---

## 5. Devin (Cognition Labs)

Devin is a cloud-hosted autonomous engineer running in an isolated VM-sandbox per task. Cognition published two key engineering posts: the original "Introducing Devin" and the influential "Don't Build Multi-Agents."

**Agent loop architecture.** Single-threaded linear agent. Cognition's stated principle: **don't build multi-agent systems**. Their argument: parallel agents make implicit, conflicting decisions ("one agent builds Super Mario backgrounds while another builds non-game-like birds"); the cost of reconciling those decisions exceeds the parallelism win. Their fix: a **single agent with continuous context, supplemented by a compression model for arbitrarily long tasks**. They specifically critique Claude Code (as of June 2025) for spawning sub-tasks that "never do work in parallel" and exist mainly to answer questions — i.e. they think even Claude Code's sub-agent approach is more limited than it looks.

Devin internally still has a **planner** (interactive, user-editable) plus an executor; but those are sequential phases of *one* agent, not parallel agents.

**Tool schema.** Tools: shell, code editor (VS-Code-style), Chromium browser. Plus Devin Search (codebase Q&A with citations + "Deep Mode") and Devin Wiki (auto-generated codebase wiki refreshed every few hours, with architecture diagrams).

**Context-window strategy.** "Context engineering is everything." Cognition emphasizes:
- **Sharing full agent traces, not isolated messages** — sub-agents (when used at all) get the parent's full trace.
- **Continuous context across all decisions** — never split a task into sub-tasks that lose shared assumptions.
- **Compression** — when context overflows, summarize via a dedicated compression model rather than rotate agents.

A persistent **memory layer** stores vectorized snapshots of the codebase and a full replay timeline of every command, file diff, and browser tab.

**Memory model.**
- *Project* — Devin Wiki (auto-indexed every few hours).
- *Session* — full replay timeline.
- *User* — Knowledge entries (rules / project notes the user adds and Devin reuses).

**Sandboxing.** Each Devin task runs in a **dedicated cloud VM** ("a cloud laptop") with its own shell, browser, editor, and working directory. Credentials are isolated to the VM. "Devin can manage Devins" — a parent Devin can spawn child VMs for parallel work, each fully isolated. This is the heaviest sandbox of any agent surveyed (full VM, not container or seatbelt).

**Multi-file editing strategy.** Direct file editing inside the VM via the editor tool; diffs surface to the user via Devin's UI.

**Planning vs. execution split.** Devin 2.0 added an **interactive planner** — Devin first researches the codebase and produces a plan the user reviews and edits before autonomous execution begins. This is closer to "human-approves-spec" than the generator/evaluator pattern Anthropic uses.

**Published harness details.** "Don't Build Multi-Agents" is the canonical doc. Architecture details (memory layer, replay timeline, multiple parallel Devins) come from the Devin 2.0 post and "Devin can now Manage Devins."

Sources: [20], [21], [22], [23].

---

## 6. Aider (open source, but architecturally instructive)

Aider is open-source (`Aider-AI/aider`) but is the most-studied terminal coder and pairs well with closed-source comparisons. Its `aider/coders/` directory is the cleanest example of multiple edit formats coexisting.

**Agent loop architecture.** Single-agent REPL loop in `aider/coders/base_coder.py`. Each turn: build prompt (with repo map + chat history + user message) → call LLM → parse edits in the configured format → apply → run tests if `--auto-test`.

**Tool schema.** Aider does not use JSON function-calling. It uses **prompt-encoded edit formats** — the LLM emits a specific text format inside its reply, which Aider parses.

**Context-window strategy — the repo map.**
- Tree-sitter (`py-tree-sitter-languages`) parses every source file into an AST and extracts symbol definitions (functions, classes, methods, types).
- A **PageRank-style graph** weights symbols by how often they're referenced from other files.
- A **token budget** (`--map-tokens`, default 1k) caps the map size.
- The map is sent inline with the user prompt, giving GPT a "concise, symbol-focused overview" of the project without sending whole files.

**Memory model.** No persistent memory across sessions by default. The repo map is recomputed; chat history is maintained for the session. `.aider*` files in the project root keep some state; `CONVENTIONS.md` can be loaded as a system message.

**Sandboxing.** None at the agent level. Aider edits files directly; commits to git per change so every edit is reversible.

**Multi-file editing strategy — the cleanest taxonomy.** From `aider/coders/`:

| Coder | Format | Used with |
| :--- | :--- | :--- |
| `wholefile_coder` | LLM returns full updated file content | Simple/legacy models, Llama-style |
| `editblock_coder` | Search/Replace blocks (git merge-conflict style markers) | Default for most models |
| `editblock_fenced_coder` | Edit-block format with file path **inside** the fence | Gemini family (which struggles with standard fencing) |
| `editblock_func_coder` | Edit blocks via function calls | Function-calling-capable models |
| `udiff_coder` / `udiff_simple` | Unified diff (modified/simplified) | GPT-4 Turbo (originally added to fight "lazy coding"), Gemini 2.5 Pro for the simple variant |
| `patch_coder` | OpenAI patch format | GPT-4.1 |
| `architect_coder` | Plain-text instructions, then handed to an editor coder | Architect mode |
| `ask_coder` | Read-only Q&A | `aider --chat-mode ask` |
| `context_coder` | Selecting relevant files | Pre-edit context selection |

**Planning vs. execution split.** **Architect mode** is the canonical two-model split: a strong reasoning model (e.g. o1-preview) outputs plain-text intent; a cheap fast model (e.g. gpt-4o) translates that into the chosen edit format. Aider reports SOTA benchmarks with this split — and it's the same shape Cursor uses (planner emits intent, fast-apply model materializes edits).

**Published harness details.** Aider blog has multiple deep posts: "Building a better repo map with tree-sitter," "Improving GPT-4's codebase understanding with ctags" (the predecessor approach), and the polyglot benchmark methodology. The Aider polyglot leaderboard (Exercism-derived, multi-language) is one of the few public coding-agent benchmarks that tests the full edit pipeline, not just function-completion.

Sources: [24], [25], [26], [27].

---

## 7. Continue.dev

Continue is open-source (`continuedev/continue`, primarily TypeScript ~84%) with VS Code, JetBrains, and CLI (`cn`) front-ends. Its model has shifted: from a customizable IDE assistant to a CI-enforceable AI checks platform.

**Agent loop architecture.** Standard tool-use loop. The `cn` CLI is described as "an open-source, modular coding agent for the command line that provides a battle-tested agent loop so you can simply plug in your model, rules, and tools."

**Tool schema.** Continue auto-detects whether to use the model's native tool-calling or to inject system-message tool descriptions, based on a `tool_use` capability flag. Custom tools are added via MCP.

**Context-window strategy.** Configurable retrieval (`@codebase`, `@docs`, `@file`, `@open` context providers); embedding-based codebase indexing; per-message context selection by the user.

**Memory model.**
- *Project* — agents stored as Markdown files at `.continue/checks/` or via `config.yaml`.
- Continue Hub — sharable agents, models, rules, prompts.
- `baseAgentSystemMessage` and `basePlanSystemMessage` override default system prompts for Agent mode and Plan mode respectively.

**Sandboxing.** None at the agent layer; agent-mode tool use defaults to **asking permission per tool**, and tool policies can auto-approve or block specific tools.

**Multi-file editing strategy.** Standard tool-mediated `edit_file`/`write_file` style edits; diff previews surface in the IDE.

**Planning vs. execution split.** Explicit **Plan mode** vs. **Agent mode**, each with its own system prompt override. CI-style "checks" are agents that run on PRs as GitHub status checks.

Sources: [28], [29].

---

## 8. Brief Coverage: Sweep, Cody, Tabby, Plandex v2

**Sweep (`sweepai/sweep`).** GitHub-App-first coding agent (Python). Agent flow: GitHub issue label → analyze repo → multi-step plan → branch + commit + PR. Notable engineering insight from their blog: **decisions degrade past ~20k tokens** ("lost in the middle"); they target ~10–15k tokens for the decision-point and dynamically prune/expand context to stay there. Sandboxed execution for build/test verification. Now positioned as an AI coding assistant for JetBrains.

**Cody (Sourcegraph).** Cody pairs an IDE-side chat/agent with **Sourcegraph's Search API** as the retrieval backend. Where Cursor builds its own embedding/index, Cody outsources retrieval to Sourcegraph code search — already-deployed across the user's repos. Available in VS Code, JetBrains, Visual Studio (experimental), web, and CLI. Auto-edit feature uses cursor-position context. Context filters allow excluding repos (data-governance friendly).

**Tabby (`TabbyML/tabby`).** Self-hosted Rust (~93%) Copilot alternative. Single-binary, no DBMS required, runs on consumer GPUs via Docker. Repository-level context for completion drawn from "locally relevant snippets (declarations from local LSP, recently modified code)." Recent additions: an "Answer Engine" (team knowledge Q&A), Pochi task connector for GitHub issues, GitLab MR indexing, and OpenAPI integration.

**Plandex v2 (`plandex-ai/plandex`).** Open-source, terminal-based, designed explicitly for **large tasks**. Distinguishing features: (1) up to **2M effective context window** with a default model pack; (2) **tree-sitter project maps** for indexing 20M+-token directories; (3) cumulative-diff **review sandbox** that holds AI changes separate from the working tree until accepted; (4) version-controlled branches for exploring multiple approaches; (5) cross-vendor model packs (Anthropic + OpenAI + Google + OSS); (6) automated debugging of terminal commands and (with Chrome) browser apps. Architecturally it's the open-source closest in spirit to Devin.

Sources: [30], [31], [32], [33], [34], [35].

---

## Patterns Observed Across Closed Agents

1. **Hybrid retrieval > pure RAG.** Every production agent now combines (a) up-front project context (`CLAUDE.md` / `AGENTS.md` / `.cursorrules` / `.windsurfrules`) with (b) just-in-time tools (Glob/Grep, Sourcegraph Search) and (c) some indexed/embedded retrieval over chunks. Anthropic explicitly calls out tree-sitter-based indexing as inferior to JIT search for Claude Code; Cursor and Windsurf still maintain embeddings but treat them as one signal among several. Aider's tree-sitter PageRank repo map remains a strong baseline.

2. **Agent loops have converged.** Prompt → tool call → tool result → repeat → final text. The differences are at the periphery: which tools, which permission model, what JSON schema. Read-only-concurrent / write-sequential parallelism (Claude Code's rule) is becoming standard.

3. **Compaction is now table stakes** — Claude Code automatic compaction, Cognition's compression model, Cursor's context trimming, Windsurf's pipeline assembly that "trims to fit the context window." Every long-running agent has an answer for context overflow.

4. **Context resets vs. compaction is an active debate.** Anthropic's Sonnet 4.5 harness used **context resets** (start fresh agent, structured handoff via feature-list + progress file). Cognition argues the opposite: **never reset**, always carry full traces forward, compress instead. The choice depends on model behavior — Anthropic dropped resets when Opus 4.6 stopped exhibiting "context anxiety."

5. **Sub-agent dispatch is split.** Anthropic and Cursor invest heavily in sub-agent / multi-agent dispatch (sub-agents with isolated context windows; up to 8 parallel agents on git worktrees). Cognition rejects it ("Don't Build Multi-Agents") on the grounds that parallel agents accumulate conflicting implicit decisions. Windsurf uses a *small* multi-agent system (planner ↔ executor) but explicitly calls it dual-agent, not many-agent. The empirical question — does parallelism win net of merge cost? — is unresolved.

6. **Planner/executor splits are everywhere, but at different granularities.**
   - Aider's **Architect mode** (reasoning model writes intent, cheap model materializes edits) — sequential, two-model.
   - Cursor's **planner + fast-apply** — sequential, two-model, optimized for latency.
   - Windsurf's **Cascade dual-agent** — concurrent, planner runs continuously alongside executor.
   - Devin's **interactive planner** — human-in-the-loop before autonomous execution.
   - Anthropic's **generator/evaluator** — sequential, cross-model, evaluator on a *different* model than generator (deliberate to prevent self-praise bias).

7. **Sandboxing diverges sharply by deployment model.**
   - Local IDE/CLI agents (Claude Code, Cursor, Windsurf, Continue, Aider, Plandex) → **permission systems**, not OS sandboxes. Git worktrees are the most common isolation unit for parallel work.
   - Codex CLI → **OS-native sandbox** (Seatbelt/Bubblewrap/Landlock/Windows Sandbox) plus orthogonal approval policy. The most paranoid local design.
   - Devin → **dedicated cloud VM per task** with isolated credentials and replay timeline. The heaviest, made possible by the fully-cloud deployment.

8. **The persistent project file has standardized.** `CLAUDE.md` (Anthropic), `AGENTS.md` (OpenAI Codex, now cross-vendor), `.cursorrules` / `.cursor/rules/` (Cursor), `.windsurfrules` (Windsurf), `CONVENTIONS.md` (Aider), `.continue/` (Continue). Same idea: a checked-in Markdown file that is re-injected on every request (and prompt-cached). This is the closest thing the field has to a portable agent-context standard.

9. **Edit format taxonomy is still split** between (a) whole-file rewrites, (b) search/replace blocks, (c) unified diffs, (d) JSON tool-call patches, and (e) two-model architect-then-edit. Aider's `coders/` directory is the public reference for which format works best per model; closed-source agents likely run similar selection logic internally `[unverified]` for Claude Code/Cursor specifically.

10. **Memory tooling is the next frontier.** Anthropic shipped a memory tool that survives across sessions without consuming context. Cognition stores a full replay timeline plus vectorized codebase snapshots. Windsurf has explicit "Memories" with rationale capture. Cursor has "Memories" too. The pattern: separate the *durable* knowledge layer (file system, sidecar DB, or dedicated tool) from the *transient* conversation context, and swap items in/out as the agent decides.

The implication for Forge: the strongest local-first design crosses Anthropic's harness (planner/generator/evaluator on different models, generator-runs-in-worktree for isolation), Aider's edit-format taxonomy (right format per model, architect/editor split available), Cursor's shadow-workspace idea (use LSP/typecheck/lint signals as evaluator inputs), Codex's sandbox layering (OS-level when stronger isolation is needed), and Cognition's continuous-context discipline (don't shard sub-tasks that need shared assumptions; compress, don't reset, until the model can no longer cope).

---

## Citations

1. Anthropic Engineering — Harness design for long-running application development. <https://www.anthropic.com/engineering/harness-design-long-running-apps>
2. Anthropic Engineering — Effective context engineering for AI agents. <https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
3. Anthropic Engineering — Effective harnesses for long-running agents. <https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents>
4. Anthropic Engineering — Writing effective tools for AI agents. <https://www.anthropic.com/engineering/writing-tools-for-agents>
5. Anthropic / claude.com — Building agents with the Claude Agent SDK. <https://claude.com/blog/building-agents-with-the-claude-agent-sdk>
6. Claude Code Docs — How the agent loop works. <https://code.claude.com/docs/en/agent-sdk/agent-loop>
7. Claude Code Docs — Create custom subagents. <https://code.claude.com/docs/en/sub-agents>
8. Anthropic — Building Effective AI Agents. <https://www.anthropic.com/research/building-effective-agents>
9. OpenAI Developers — Codex Sandbox concept. <https://developers.openai.com/codex/concepts/sandboxing>
10. OpenAI Developers — Codex Agent approvals & security. <https://developers.openai.com/codex/agent-approvals-security>
11. OpenAI Developers — Codex CLI overview. <https://developers.openai.com/codex/cli>
12. GitHub — `openai/codex`. <https://github.com/openai/codex>
13. DeepWiki — `openai/codex` Sandboxing Implementation. <https://deepwiki.com/openai/codex/5.6-sandboxing-implementation>
14. Cursor Blog — Securely indexing large codebases. <https://cursor.com/blog/secure-codebase-indexing>
15. Aditya Rohilla — How Cursor Works Internally. <https://adityarohilla.com/2025/05/08/how-cursor-works-internally/>
16. Grow Fast Blog — Cursor 2.0: Composer and Multi-Agent Coding (Nov 2025). <https://www.grow-fast.co.uk/blog/cursor-composer-tasks-30-seconds-not-hours-november-2025>
17. Windsurf Docs — Cascade. <https://docs.windsurf.com/windsurf/cascade>
18. Markaicode — Understand Windsurf Flow: How the Context Engine Works. <https://markaicode.com/windsurf-flow-context-engine/>
19. DeepWiki — Windsurf Agent (Cascade). <https://deepwiki.com/hussainasghar/system-prompts-and-models-of-ai-tools/2.6-windsurf-agent-(cascade)>
20. Cognition — Don't Build Multi-Agents. <https://cognition.ai/blog/dont-build-multi-agents>
21. Cognition — Introducing Devin, the first AI software engineer. <https://cognition.ai/blog/introducing-devin>
22. Cognition — Devin 2.0. <https://cognition.ai/blog/devin-2>
23. Cognition — Devin can now Manage Devins. <https://cognition.ai/blog/devin-can-now-manage-devins>
24. Aider — Building a better repository map with tree-sitter. <https://aider.chat/2023/10/22/repomap.html>
25. Aider — Repository map docs. <https://aider.chat/docs/repomap.html>
26. Aider — Edit formats. <https://aider.chat/docs/more/edit-formats.html>
27. Aider — `aider/coders/` source. <https://github.com/Aider-AI/aider/tree/main/aider/coders>
28. Continue.dev — GitHub repo. <https://github.com/continuedev/continue>
29. Continue Docs — Agent mode and config.yaml. <https://docs.continue.dev/>
30. Sweep AI — Code planning blog. <https://github.com/sweepai/sweep/blob/main/docs/pages/blogs/ai-code-planning.mdx>
31. Sweep AI — GitHub repo. <https://github.com/sweepai/sweep>
32. Sourcegraph — Cody docs. <https://sourcegraph.com/docs/cody>
33. Tabby — GitHub repo. <https://github.com/TabbyML/tabby>
34. Plandex v2 — GitHub repo. <https://github.com/plandex-ai/plandex>
35. Hacker News — Show HN: Plandex v2. <https://news.ycombinator.com/item?id=43710576>
