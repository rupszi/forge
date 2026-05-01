# Parts 2E and 2F — Memory & Retrieval, Sandboxing & the Desktop Surface

Research notes for Forge v2. The goal is to validate or challenge two of Forge's most opinionated decisions: (a) "SQLite + LIKE + topic filter, no embeddings, no external memory services" and (b) "git worktrees as the only sandbox, browser-only UI, no IDE surface." Each section ends with an explicit Forge-fit verdict.

---

## Part 2E — Memory, retrieval, and context engineering

Forge's CLAUDE.md takes a hard line: no vector embeddings, no external memory services, SQLite is sufficient, knowledge items are one-line imperative statements with confidence scores. The retrieval budget is capped at ~500 tokens. This part stress-tests that position against the state of the art.

### 2E.1 Memory systems compared

The "agent memory" space in 2026 is crowded. Most products converge on three building blocks: (1) an LLM-driven *extraction* step that turns a transcript into atomic facts, (2) some combination of vector + graph + keyword *retrieval*, and (3) a *temporal* layer that invalidates rather than overwrites old facts. Below is what each project actually ships.

**Letta (formerly MemGPT).** The original "OS for LLMs" framing. Letta's memory model is split into three tiers: *core memory blocks* that sit permanently in the context window in an XML-like prepended format, *recall memory* (full message history, retrievable on demand), and *archival memory* (long-term store, retrievable on demand). The crucial insight is that core memory is not retrieved at all — it's structured text the agent reads every turn and self-edits via tool calls. There is no vector lookup for the "always-on" memory; vectors are only used for archival recall. Storage is Postgres + pgvector or SQLite. Apache 2.0. Letta's recent "MemFS" release frames memory as a git-tracked filesystem the agent edits.

**Mem0.** A managed memory layer that takes raw conversations, runs an LLM-driven extraction step ("single-pass ADD-only extraction" in the April 2026 release), and stores the resulting facts with embeddings + BM25 + entity links. Retrieval is *hybrid*: semantic similarity, keyword match, and entity graph traversal all combine. Defaults to OpenAI's `gpt-5-mini` for extraction and `text-embedding-3-small` for vectors. Apache 2.0 OSS, with a managed cloud tier. The cloud version is the lock-in vector — self-hosted requires running your own vector store (Qdrant, Weaviate, Chroma, etc.).

**Zep.** Built on top of Graphiti (Zep's own framework, see below). Zep treats memory as a *temporal knowledge graph* — every fact has `valid_at` and `invalid_at` metadata, and old facts are invalidated rather than deleted. Retrieval is "Graph RAG": semantic embeddings + BM25 + graph traversal. Cloud claims sub-200ms p90. Apache 2.0 for the OSS core; cloud is paid.

**Graphiti.** The library underneath Zep. A temporal-graph engine where nodes are entities (people, products, concepts), edges are relationships with validity windows, and *episodes* (raw inputs) provide provenance for every derived fact. Backed by Neo4j, FalkorDB, Kuzu, or Amazon Neptune. Hybrid retrieval combining semantic embeddings, BM25, and graph traversal. Apache 2.0. The "temporal knowledge graph" framing is the differentiator — Mem0 doesn't natively track when a fact stopped being true.

**Cognee.** ECL pipeline (Extract-Cognify-Load) — the marketing term for ingest → graph + vector indexing → query routing. Supports vector and graph backends (Neo4j is referenced explicitly). Operations are framed as Remember/Recall/Forget/Improve. Apache 2.0. Less mature than Zep/Mem0 but more flexible on backends.

**SQLite-vec.** A pure-C SQLite extension by Alex Garcia (asg017). Runs anywhere SQLite runs — Linux, macOS, Windows, browsers via WASM. Stores float, int8, and binary vectors in virtual tables. KNN via SQL. Successor to the older sqlite-vss. Pre-v1, breaking changes possible. Dual-licensed Apache 2.0 / MIT. Critically: it's a compiled `.so`/`.dylib`/`.dll` extension that has to be loaded into SQLite at runtime — it's *not* pure Python. So adding it to Forge breaks the "two pip dependencies, httpx + websockets" rule unless you ship the binary as a wheel.

**LanceDB.** Embedded vector DB built on the Lance columnar format. Multimodal (text, image, video, point clouds). Billion-vector scale, GPU-accelerated index building. Python/Node/Rust SDKs, plus REST. Apache 2.0. More heavyweight than sqlite-vec — you'd be embedding a real DB.

**Turbopuffer.** Serverless vector + BM25 search on object storage. Cold p90 ~444ms for 1M vectors, warm p50 ~8ms. Up to 94% cheaper than traditional vector DBs because data lives on S3 with NVMe cache for hot reads. Hosted-only. The cheap end of the managed-vector spectrum, but it's still a network hop and a vendor.

#### Comparison table

| System        | Storage backend                       | Retrieval mode                               | Hosted/Local         | License    | Forge fit                               |
| ------------- | ------------------------------------- | -------------------------------------------- | -------------------- | ---------- | --------------------------------------- |
| Letta         | Postgres / SQLite + pgvector          | Block-based context + vector recall          | Both                 | Apache 2.0 | Conceptual fit, infra overkill          |
| Mem0          | Vector + BM25 + entity graph          | Hybrid (semantic + keyword + entity)         | OSS or managed cloud | Apache 2.0 | Wrong abstraction (chat memory, not KB) |
| Zep           | Graphiti (graph DB) + vector          | Graph RAG (temporal)                         | OSS + cloud          | Apache 2.0 | Too heavy; useful pattern               |
| Graphiti      | Neo4j / FalkorDB / Kuzu / Neptune     | Hybrid (semantic + BM25 + graph traversal)   | Local (BYO graph DB) | Apache 2.0 | Pattern worth borrowing, infra not      |
| Cognee        | Vector + graph (pluggable)            | Routed (graph or vector by query)            | Both                 | Apache 2.0 | Closest to Forge philosophy             |
| sqlite-vec    | SQLite virtual table                  | KNN via SQL                                  | Local only           | Apache/MIT | Very tempting; binary extension caveat  |
| LanceDB       | Lance columnar files                  | Vector + full-text + SQL                     | Both                 | Apache 2.0 | Heavy; for billion-scale not 200 items  |
| Turbopuffer   | S3 + NVMe cache                       | Vector + BM25 + hybrid                       | Hosted only          | Proprietary| Violates "no external services" rule    |

#### Verdict: does Forge's stance hold up?

For the use case CLAUDE.md describes — a per-project knowledge base capped at 200 one-line items, retrieval budget of ~500 tokens, mostly searching for "what gotcha applies to this Supabase task" — **the no-embeddings stance is defensible at small scale, and arguably correct**. SQLite LIKE on a topic-filtered subset of <=200 rows runs in microseconds. Embeddings would add a model dependency, a vector store, and ~768-1536 floats per item with no measurable retrieval-quality gain at this scale. The 200-item cap is doing the heavy lifting: at that size, *any* search algorithm works, and the bottleneck is curation quality (the learner) not retrieval algorithm.

Where the stance is shakier:

1. **Episodic store, not knowledge store.** The episodes table will grow without bound — every task execution logs an episode. After a few months, "find similar past failures" via SQL LIKE on a multi-thousand-row corpus becomes the weak link. Past task descriptions don't share keywords with the current task even when they're conceptually similar. This is exactly where embeddings earn their keep.
2. **Cross-project retrieval.** Forge's KB is per-project (`.forge/forge.db`). If a developer wants "what has this developer learned across all their projects," a global index would benefit from embeddings.
3. **Content-shape mismatch.** One-line imperative statements ("Supabase RLS: test with service_role key") are *designed* to be findable by keyword. That's a deliberate authoring choice that makes LIKE work. Drop the constraint and you'd need vectors.

The closest external system to Forge's philosophy is **Letta's core memory blocks** — structured text that the agent self-edits and that lives permanently in context, with retrieval-based recall as a separate layer. Forge's `memory_context` injection is essentially the same idea, just split across knowledge.py + retriever.py instead of a single block primitive.

**Recommendation.** Hold the line on no-embeddings *for the knowledge base*. But add **sqlite-vec as an optional extension for the episodic store**, gated behind a config flag. The two-deps rule is preserved if sqlite-vec ships as a Python wheel (it does). This gets you vector recall over episodes without adding a vector DB to the architecture diagram. Mem0/Zep/Cognee are wrong abstractions for Forge — they're built for chat-history memory, not for a curated developer-learning corpus.

### 2E.2 Repo-level retrieval — the part that matters for coding agents

The KB stores gotchas. But the bigger context-engineering problem for a coding agent is: *given a task, what slice of the user's codebase should the agent see?* This is where the field has converged on a few patterns.

**Aider's repo map.** Aider builds a tree-sitter-parsed map of the entire repo, then ranks files using PageRank on a directed graph where files are nodes and edges connect files that reference each other's identifiers. From `aider/repomap.py`:

- Tree-sitter `.scm` query files extract `def` and `ref` tags (function/class definitions and references) for every supported language.
- Identifiers become graph nodes; reference edges are weighted by frequency. Edges originating from files already in the chat get a 50× boost; edges to identifiers the user mentioned get 10×.
- `nx.pagerank(G, weight='weight', **pers_args)` computes file importance.
- A binary search fits the highest-ranked subset into the `--map-tokens` budget (default 1000), with a 15% error tolerance, scaled up 8× when no chat files are open.

The repo map is sent to the LLM with every request. This is the strongest pattern in the open source for coding agents because it's *deterministic, cheap, and semantically meaningful* — PageRank on the symbol graph is a remarkably good proxy for "what's important in this codebase."

**Cursor's indexing.** Public docs describe a more conventional pipeline: chunking by syntactic boundaries (functions, classes, logical blocks), embedding each chunk with a custom model, storing in a vector DB. Re-indexes every 5 minutes incrementally. Privacy-preserving — chunks are decrypted client-side at retrieval time, file paths are encrypted in transit. This is the standard "RAG over code" approach. Works at scale (multi-million-LOC repos) but loses the symbolic precision Aider's PageRank provides.

**Tree-sitter.** The substrate underneath Aider's repo map and many other tools. Tree-sitter parses to a concrete syntax tree with incremental updates and error recovery. Symbol queries via `.scm` files are the lingua franca for "extract definitions and references." Forge could lift Aider's `repomap.py` directly — it's MIT-licensed and self-contained.

**ctags.** The classic. Universal-ctags emits a flat tag file with one line per symbol. No graph, no ranking, just an index. The fallback when tree-sitter doesn't have a grammar. Useful as a sanity-check baseline.

**SCIP (Sourcegraph Code Intelligence Protocol).** A language-agnostic protobuf format for code intelligence — "go to definition, find references, find implementations." SCIP indexers exist for Java, TypeScript, Rust, C++, Ruby, Python, C#, Dart, PHP. SCIP supersedes LSIF (the older Microsoft format). Apache 2.0. Used by Sourcegraph and increasingly by AI-native code search tools. SCIP is *richer* than ctags (precise symbol IDs that work across repos, hover docs, type info) and *more standardized* than tree-sitter queries (you don't write a query per language — the indexer does it for you).

**Greptile.** AI-native code search built on a *graph* of files, functions, and dependencies. Crucially, public docs say the system "doesn't explicitly mention embeddings" — it focuses on explicit dependency mapping plus agent-based reasoning. This is closer to Aider's PageRank than to Cursor's vector RAG. Sells "swarm of agents" review for PRs.

**Continue's `@codebase`.** OSS IDE assistant, supports embeddings + repo-wide search. Pluggable retrievers. Less innovative than Aider on the algorithmic side but a nice reference implementation.

#### What Forge should actually build

Forge currently has nothing for repo-level retrieval. Every generator agent gets a memory context (the KB injection) but no codebase map. This is a real gap. The recommendation is:

1. Lift Aider's `repomap.py` (MIT) into `daemon/scanner/repomap.py`. Compute it once at session start, refresh on file changes.
2. Inject the repo map into generator prompts alongside the memory context. Token budget ~1500 (vs Aider's 1000 default) — this is much higher leverage than dumping more KB items.
3. Optionally add a SCIP indexer step for typed languages where it exists; use the SCIP graph as a higher-precision overlay on top of the tree-sitter map.
4. Skip embeddings on code chunks. Aider's results show PageRank-on-symbol-graph is competitive with vector RAG at much lower complexity, and it composes better with the no-embeddings KB stance.

### 2E.3 Long-horizon context strategies

The shared problem across all of these tools: LLM context windows fill, performance degrades, and long-running sessions become unreliable. The patterns:

**Compaction.** Anthropic's Claude Code auto-compacts when the context fills, summarizing what matters most while preserving "code patterns, file states, and key decisions." Manual `/compact <instructions>` lets the user focus the summary ("focus on the API changes"). `/rewind` lets you summarize from a chosen checkpoint forward. The CLAUDE.md best-practices guide is explicit: *"Claude's context window holds your entire conversation… performance degrades as it fills."* Compaction is the single most important runtime defense.

**Scratchpads.** Anthropic's multi-agent research engineering blog calls extended-thinking mode "a controllable scratchpad." The model writes structured intermediate reasoning that doesn't pollute the main message stream. Forge's evaluator/generator separation already implements a coarser version of this: each agent has its own context window and only summaries cross the boundary.

**Episodic→semantic distillation.** This is exactly what Forge's `learner.py` does: at session end, scan failure-resolution pairs, ask a local LLM to extract one-line gotchas, store with confidence 0.7. Letta and Mem0 both do something similar but framed as "memory consolidation" — periodic background passes that summarize episodic memory into semantic facts. Mem0's "single-pass ADD-only extraction" runs on every conversation turn, not at session end. Forge's once-per-session extraction is cheaper and probably sufficient given the small KB cap.

**Subagent context isolation.** Anthropic's multi-agent research system (orchestrator + workers) found that "three factors explained 95% of the performance variance" — token usage 80%, tool calls, model selection. Distributing work across subagents with independent context windows is the lever. The blog notes: parallel tool-calling — subagents using 3+ tools simultaneously — reduced research time up to 90%. Forge's planner/generator/evaluator triad maps to this exactly, with worktrees adding filesystem isolation that the research feature didn't need.

**Validation of `learner.py`.** The literature supports the design. The key tweak: Mem0's "ADD-only" lesson is worth borrowing — *don't overwrite existing knowledge items, accumulate and let the confidence/decay logic prune*. Forge's deduplication step in `knowledge.add` should be additive (raise confidence on near-duplicates) rather than replacing, which it appears to already do.

The Letta/Mem0 patterns Forge does *not* implement: continuous in-conversation extraction (vs end-of-session). This is probably right for a coding agent — extracting facts after every tool call would be expensive and noisy, since most tool calls are routine file reads. End-of-session extraction over the full transcript gives the local LLM enough context to identify what's actually a gotcha vs noise.

---

## Part 2F — Sandboxing, execution, and the AI desktop surface

### 2F.1 Sandboxing options

Forge's choice is git worktrees. This is *not* a sandbox in the security sense — a worktree shares the repo, the OS, the user's home directory, and full filesystem access. It's an *isolation* mechanism for parallel work, not a security boundary against malicious or runaway code. The question is: should Forge add a real sandbox?

**Git worktrees.** Native git feature: multiple working directories pointing at the same `.git`, each on a different branch. Zero startup cost (~10ms to create), zero overhead at runtime. *No security isolation* — a `claude -p` agent in a worktree can `rm -rf $HOME` just as easily as it could without one. The failure modes: (1) agent runs a destructive command outside the worktree (dependency install scripts, `npm install` running postinstall hooks), (2) agent cd's out of the worktree and edits files in the main checkout, (3) test runs hit shared resources (the dev database). For trusted code that the developer intends to run, worktrees are fine. For *untrusted* generated code, they're not enough.

**Docker.** OpenHands' choice. Container-level isolation (namespaces, cgroups, optionally seccomp). Startup ~1-2 seconds for a warm image. Filesystem isolation is real; network isolation requires explicit config. Heavy: each agent needs an image, build/cache management, volume mounts for the repo. Good security if the image is locked down; the typical "Ubuntu + Node + Python" dev image is wide-open.

**Firecracker microVMs.** KVM-based VMM, designed for AWS Lambda/Fargate. Initiates user-space code in ~125ms. Less than 5 MiB memory overhead per microVM. Excludes "unnecessary devices and guest functionality to reduce the memory footprint and attack surface area." Ships with `jailer` for defense-in-depth. Used by Fly.io. Strongest isolation in the list (real KVM hypervisor) at near-container startup speed. The catch: KVM means Linux-only on a host with hardware virtualization, and standing up Firecracker in a developer machine workflow is non-trivial.

**gVisor.** Google's userspace kernel (Sentry intercepts syscalls; Gofer mediates filesystem via 9P). Runs as the `runsc` OCI runtime — Docker/Kubernetes compatible. Trades performance for security: syscall-heavy workloads slow down noticeably; memory-safe Go core means the entire kernel is fuzz-resistant. Middle ground between Docker and Firecracker. Useful when you want VM-grade isolation without VM overhead.

**Apple sandbox-exec (macOS Seatbelt).** Codex CLI's macOS choice. Profiles written in Sandbox Profile Language (SBPL), a Scheme-like dialect. Codex generates SBPL dynamically based on requested permissions. *Officially deprecated by Apple* on macOS 15.4 — still works, but Apple has stopped guaranteeing future support. Reports from developers (e.g., the jhartman.pl blog post) say that "deny by default + poke holes" profiles abort spuriously and that sandbox-exec is "too brittle for this use case." This is a problem for any cross-platform tool that wants real macOS sandboxing — there is no good replacement Apple ships for command-line use.

**Linux Landlock.** Codex's Linux primitive. Unprivileged, kernel-level filesystem and (in 6.7+) network access restrictions per process. Codex's `landlock.rs` delegates to a `codex-linux-sandbox` helper that uses bubblewrap for the actual confinement, with seccomp filters added for network. The architecture is interesting: Landlock alone isn't enough (it can't restrict everything you want), so even Codex-on-Linux ends up with a bubblewrap + Landlock + seccomp stack.

**Bubblewrap (bwrap).** The unprivileged Linux sandbox that Flatpak uses. New mount namespace with tmpfs root; user, IPC, PID, network, UTS namespaces; seccomp filters. Composes well with Landlock. Used by rpm-ostree and now Codex. Requires unprivileged user-namespace creation (which not all distros enable by default — RHEL 8 famously didn't).

**E2B.** Hosted sandboxes for AI code execution. Each sandbox is a fast Linux VM. SDKs in Python and JS. Templates define the initial environment. Sub-second startup, designed for "give an LLM a Python REPL." Hosted-only — adds a network hop and a vendor.

**Daytona.** Sub-90ms sandbox creation, designed explicitly for AI-generated code execution. Snapshot/restore for stateful long-running agents. Self-hostable on customer-managed compute. HIPAA, SOC 2, GDPR. Open source core. The "fastest sandbox on the market" claim is real — sub-100ms is in the same ballpark as a worktree create.

**Modal sandboxes.** Sandboxes are first-class in Modal: `Sandbox.create` spawns an isolated container with custom images, volumes, env vars. Default 5-minute lifetime, configurable to 24h. Named sandboxes for reuse across function calls. `from_id`/`from_name` for stateful agent flows. `exec()` for dynamic command execution. Cloud-only. Good fit for cloud-side coding agents (the Replit Agent / v0 flavor); poor fit for a local dev tool.

**Coder, Gitpod, GitHub Codespaces.** The "remote dev environment" category. Devcontainer-based. Heavy (a full VM/container per session, minutes to start). Designed for human developers; agent integration is bolted-on. Not really a sandbox in the security-isolation sense — they're remote workspaces.

#### Comparison table

| Sandbox            | Isolation level                       | Startup latency    | Ease of integration                    | Forge fit                          |
| ------------------ | ------------------------------------- | ------------------ | -------------------------------------- | ---------------------------------- |
| Git worktrees      | None (filesystem layout only)         | ~10ms              | Trivial (already in plan)              | Current choice; OK for trusted code |
| Docker             | Namespace + cgroup                    | 1-2s warm          | Heavy: image management                | Optional escalation tier           |
| Firecracker        | KVM hypervisor                        | ~125ms             | Hard (Linux + KVM only)                | Wrong layer for a desktop tool     |
| gVisor             | Userspace kernel (Sentry/Gofer)       | ~1s                | Docker-runtime drop-in                 | Server-side, not desktop           |
| sandbox-exec (mac) | Apple Seatbelt (deprecated)           | Negligible         | Brittle, poor docs, deprecated         | Risky — Apple may break it         |
| Landlock (Linux)   | Kernel filesystem/network restrictions | Negligible        | Needs helper + seccomp                 | Composable with bwrap              |
| bubblewrap         | Linux namespaces + seccomp            | <100ms             | Strong on Linux only                   | Best free Linux option             |
| E2B                | Hosted Linux VMs                      | Sub-second         | API-driven; cloud only                 | Violates "all local" rule          |
| Daytona            | Sandbox VMs, self-hostable            | <90ms              | API-driven; OSS core                   | Good cloud-side option             |
| Modal sandboxes    | Container in cloud                    | Seconds            | API-driven; cloud only                 | Wrong deployment shape             |
| Codespaces/Gitpod  | Full remote dev VM                    | Minutes            | Devcontainer-based                     | Wrong abstraction                  |

#### Forge's sandbox roadmap

The honest answer: **worktrees are good enough for v1**, because Forge runs trusted code that the developer intentionally invoked. The agents running inside a worktree are the same Claude Code sessions the user already trusts to run on their machine. The threat model is "agent makes a mistake," not "agent is malicious."

But there are two real risks:

1. **Generator agents that run `npm install` (or pip, cargo, etc.) execute arbitrary postinstall scripts.** This is the same threat any developer faces with `npm install` — but agents are more likely to run install commands than humans are.
2. **Long-running parallel agents can exhaust shared resources** (database connections, ports, disk). Worktrees don't isolate any of this.

The right tiered design:

- **Default**: git worktree. Covers 95% of tasks.
- **Optional (`--sandbox=bwrap` on Linux)**: bubblewrap with read-only mounts of the home directory, write access to the worktree only. Composes with Codex's existing helper if the user has Codex installed.
- **Optional (`--sandbox=docker`)**: thin Docker wrapper for users who want container-level isolation. Provide a default image; let users override.
- **Skip macOS native sandboxing.** sandbox-exec is deprecated and brittle. Document the limitation honestly: macOS users get worktree-only isolation. Recommend Docker for higher isolation on macOS.

Crucially: do *not* make sandboxing mandatory. The CLAUDE.md spec is explicit that Forge should run lightly inside a developer's project. A heavyweight sandbox layer would violate that.

### 2F.2 Desktop integration patterns — what makes a "native AI desktop"

Forge is currently browser-only. Is that the right surface?

**Claude Desktop + MCP.** Anthropic's Model Context Protocol is the de facto standard because it solves the M×N integration problem: every AI app speaks MCP, every tool exposes MCP, and the matrix collapses to M+N. Claude Desktop ships an MCP client built in, and the ecosystem includes VS Code, Cursor, ChatGPT, Zed, MCPJam, and many others. The architecture is JSON-RPC over stdio or HTTP+SSE; servers expose *tools* (callable functions), *resources* (readable content), and *prompts* (parameterized templates). MCP's win is *interoperability* — once you build an MCP server, every MCP-aware client can use it.

**Raycast.** Extension model is React-based TypeScript. Extensions get global hotkeys, command palette integration, system-level UI primitives. The pattern: a "command" is a React component that renders into Raycast's native window. AI features layer on top. The key UX win is the *floating launcher* — a global hotkey opens a search-driven command palette that's faster than any browser UI.

**Pieces.** Local-first AI dev assistant. Runs as an OS-level daemon on Windows/macOS/Linux with browser/IDE plugins. Captures developer activity (snippets, docs, chat) and indexes into LTM-2 (their long-term memory engine), preserving up to 9 months of context. Privacy-first by default. The architectural insight: a *system tray daemon* with editor plugins is a more durable shape than a browser tab, because it can survive across sessions and observe across applications.

**Warp.** AI-native terminal. Markets itself as "agentic development environment" — combines a modern terminal UX with cloud agent orchestration ("Oz"). The main innovation: blocks (each command + output is a structured unit), AI-suggested completions inline, and natural-language-to-command translation. Warp's success shows that *replacing* the terminal is viable when the AI integration is deep enough.

**Zed's agent panel.** A side panel in the editor that hosts agent conversations, with the agent's edits appearing in the editor and reviewable as diffs. Zed treats the agent as a peer collaborator — agent edits are visible in the same buffer view as your edits, with attribution. This is the strongest *editor-native* UX in the market.

**Zed's Agent Client Protocol (ACP).** Apache 2.0. Standardizes the editor↔agent boundary. SDKs in Kotlin, Java, Python, Rust, TypeScript. ACP and MCP solve different problems: MCP is *agent → tools* (how does the agent talk to GitHub, Slack, Postgres); ACP is *editor ↔ agent* (how does the editor render the agent's progress, accept its edits, send it user input). They're complementary. ACP is much newer and not yet standardized across editors — VS Code has its own Language Model API; JetBrains has its plugin model.

**The "desktop AI" pattern.** What separates a real desktop experience from a CLI bolt-on:

1. **Global hotkey / launcher.** Cmd+Space-style activation. Raycast nailed this.
2. **System tray persistence.** The agent process keeps running and observes/notifies even when no window is focused.
3. **Notifications.** OS-native toast for "sprint failed," "merge ready," "budget exhausted" beats a browser tab the user has to look at.
4. **Screenshot / clipboard / OS automation.** The agent can take a screenshot to verify UI work, paste from clipboard, drive the system. Claude Desktop's computer-use model and Pieces both lean into this.
5. **Editor integration.** Diffs viewed in the user's editor (not a separate browser diff viewer) reduce context-switching.

### 2F.3 IDE surfaces

**LSP-as-agent-transport.** Some experiments (Continue, etc.) use LSP as the wire format for agent ↔ editor. Works but feels awkward — LSP was designed for language servers, not agents.

**JetBrains plugin model.** Requires Kotlin/Java, runs in the IDE's JVM. Heavy. Powerful, but a high investment.

**VS Code Language Model API.** `selectChatModels()` + `sendRequest()` with a `LanguageModelChatRequest`. Streaming responses via `LanguageModelChatResponse`. Models include GPT-4o, o1, Claude Sonnet. Extensions can query Copilot's models with user consent. The API is more "use a model" than "be an agent" — it's not a full agent surface, just LLM access for extensions.

**Zed ACP.** The most modern attempt at standardizing the editor↔agent boundary. Apache 2.0. SDKs across major languages. Still early but the cleanest abstraction.

### Should Forge stay browser-only or grow a desktop/IDE surface?

**Opinion: stay browser-only for v1, but plan a v2 surface that is a system-tray daemon + ACP-speaking IDE plugin, not a full desktop app.**

The browser dashboard is the right shape for the *control* surface — sprint-level visualization, multi-worktree dashboards, KB browser, cost meter. None of that fits in a sidebar. A browser tab is the natural home for a "mission control" view of multiple parallel agents. Cursor and v0 prove this isn't dated; their primary surfaces are full-screen too.

What's missing is the *participation* surface. The user wants to:

- See evaluator feedback inline with the diff in their editor, not in a browser tab.
- Approve a merge from a system tray icon, not by switching to localhost:3000.
- Get a notification when a sprint fails, not by watching the dashboard.

The right v2 architecture:

1. **Keep the daemon.** It's already a long-running process on 127.0.0.1:9111. Extend it with a system-tray icon (Tauri or pystray) for status + quick actions (cancel session, open dashboard, view last result).
2. **Keep the browser dashboard.** Mission control. Don't try to cram this into a sidebar.
3. **Add an ACP-speaking sidecar.** Implement Forge as an ACP agent so any ACP-aware editor (Zed today, plausibly more later) gets the participation surface for free. Cost: a few hundred lines of glue code over the existing daemon.
4. **Skip the VS Code-specific extension** unless adoption demands it. ACP is the bet — VS Code Language Model API is for "use a model from an extension," not "be an agent the editor talks to."
5. **Skip macOS-style "agent in the menubar" computer-use unless the threat model changes.** Forge's value is in code generation + evaluation, not in screen-driving. Computer-use UIs are a different product.
6. **Definitely add MCP server export.** Forge's KB and episodic store should be queryable as MCP resources/tools so other agents (Claude Desktop, Cursor) can read what Forge has learned. This is one-way interop — Forge already *consumes* MCP via Claude Code; exposing the KB *as* MCP closes the loop. Low cost, high leverage.

The asymmetric bet: **MCP server export is the highest-ROI desktop-integration move available**. It costs ~a day of work, requires zero new UI, and immediately makes Forge's KB visible to every other AI tool in the user's stack. Do that before any IDE plugin work.

---

## Citations

Memory systems
- Letta docs — agent-memory and memory-blocks: https://docs.letta.com/concepts/agent-memory and https://docs.letta.com/guides/agents/memory-blocks
- Letta GitHub: https://github.com/letta-ai/letta
- Mem0 GitHub: https://github.com/mem0ai/mem0
- Mem0 docs: https://docs.mem0.ai/overview
- Zep GitHub: https://github.com/getzep/zep
- Graphiti GitHub: https://github.com/getzep/graphiti
- Cognee GitHub: https://github.com/topoteretes/cognee
- sqlite-vec: https://github.com/asg017/sqlite-vec
- LanceDB: https://github.com/lancedb/lancedb
- Turbopuffer: https://turbopuffer.com/docs

Repo-level retrieval
- Aider repo map docs: https://aider.chat/docs/repomap.html
- Aider repomap.py source: https://github.com/Aider-AI/aider/blob/main/aider/repomap.py
- Cursor codebase indexing: https://cursor.com/docs/context/codebase-indexing
- SCIP: https://github.com/sourcegraph/scip
- scip-typescript: https://github.com/sourcegraph/scip-typescript
- Greptile: https://greptile.com/

Context engineering
- Anthropic multi-agent research engineering blog: https://www.anthropic.com/engineering/multi-agent-research-system
- Claude Code best practices: https://code.claude.com/docs/en/best-practices

Sandboxing
- Codex sandboxing concepts: https://developers.openai.com/codex/concepts/sandboxing
- Codex landlock.rs: https://github.com/openai/codex/blob/main/codex-rs/core/src/landlock.rs
- Codex source tree: https://github.com/openai/codex/tree/main/codex-rs/core/src
- "Codex in the Jail" macOS sandbox-exec experience: https://jhartman.pl/posts/macos/2026-02-02-codex-in-the-jail/
- Firecracker: https://firecracker-microvm.github.io/ and https://en.wikipedia.org/wiki/Firecracker_(virtualization)
- gVisor: https://gvisor.dev/docs/
- Bubblewrap: https://github.com/containers/bubblewrap
- E2B: https://e2b.dev/docs
- Daytona: https://www.daytona.io/
- Modal sandboxes: https://modal.com/docs/guide/sandbox

Desktop and IDE surfaces
- Model Context Protocol: https://modelcontextprotocol.io/introduction
- Zed Agent Client Protocol: https://github.com/zed-industries/agent-client-protocol
- Pieces: https://pieces.app/
- Warp: https://www.warp.dev/
- Raycast extensions repo: https://github.com/raycast/extensions
- VS Code Language Model API: https://code.visualstudio.com/api/extension-guides/language-model
