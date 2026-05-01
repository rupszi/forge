# Parts 2C & 2G — Swarms, Emergent Multi-Agent Paradigms, and Decision-Making

Research notes for Forge v2 design. Compiled 2026-04-30.

---

## Part 2C — Swarm & Emergent Multi-Agent Paradigms

### 2C.1 OpenAI Swarm and the OpenAI Agents SDK

**OpenAI Swarm** (github.com/openai/swarm) is positioned by OpenAI as "an educational framework exploring ergonomic, lightweight multi-agent orchestration." It is explicitly *not* production-ready; the README points users to the OpenAI Agents SDK for production. Its two core abstractions are minimal:

- **Agent**: bundle of `instructions` + callable `functions`.
- **Handoff**: an agent transfers control by *returning another Agent* from a function call. Plus `context_variables` for state across turns. The framework runs client-side over Chat Completions and is stateless server-side.

The handoff primitive shines when: (a) the workflow is a directed graph of specialists (intake → triage → billing-specialist → refund-agent), (b) routing is dynamic (decided by content, not flowchart), and (c) conversation is single-threaded — exactly one agent holds the mic at a time. Swarm's deliberate design choice is *no parallelism*; control is single-threaded and passed like a baton.

**OpenAI Agents SDK** (github.com/openai/openai-agents-python) is the production successor. It keeps the handoff metaphor but adds: typed tools, MCP tool support, hosted/sandboxed agents, **guardrails** (input/output validation), **Sessions** (auto conversation history), and built-in **tracing** for debug/observability. Agents-as-tools means a parent agent can `tool_call(other_agent)` and treat the response as a function return — equivalent to a hierarchical handoff. Compared to Swarm: same primitive, much more production scaffolding, and provider-agnostic so it can run against non-OpenAI models.

**Forge takeaway**: Forge's planner → generator → evaluator flow is a *handoff chain* with a critical twist — the evaluator is not an equal participant, it is a gate. The Agents SDK abstraction would model this naturally (`planner.handoff(generator)`, `generator.handoff(evaluator)`), but Forge has a stronger commitment that the evaluator runs on a *different model* than the generator, which Swarm/SDK do not enforce.

### 2C.2 AgentVerse and JARVIS / HuggingGPT

**AgentVerse** (Chen et al., arxiv [2308.10848](https://arxiv.org/abs/2308.10848)) frames problem-solving as a four-stage loop: (1) *Expert Recruitment* — dynamically choose which agent personas to assemble for the task, (2) *Collaborative Decision-Making* — agents jointly devise a strategy, (3) *Action Execution*, (4) *Evaluation* — re-evaluate and re-recruit if needed. The key idea is that *team composition is itself a decision the system makes* per task. Greater-than-the-sum-of-its-parts is the empirical claim; their experiments cover reasoning, coding, tool use, and embodied AI.

**JARVIS / HuggingGPT** (Shen et al., arxiv [2303.17580](https://arxiv.org/abs/2303.17580)) is the canonical *model-as-tool* / task-routing pattern: ChatGPT acts as a controller that (1) plans subtasks, (2) selects appropriate Hugging Face models from descriptions, (3) executes each subtask on the chosen model, and (4) summarizes. It is essentially a router whose action space is "the entire Hugging Face Hub." This pattern generalizes to Forge's classifier — pick the right specialized executor for each subtask, where the "models" are now Sonnet, Opus, Ollama variants.

**Forge takeaway**: AgentVerse's *expert recruitment* stage maps onto Forge's classifier choosing model + agent role per sprint. HuggingGPT's *model-as-tool* maps onto Forge's executor abstraction (claude_code / ollama / batch). Neither paper supports parallel-without-coordination — both keep a centralized planner/controller, which matches Forge's design.

### 2C.3 Anthropic's Multi-Agent Research System

The Anthropic engineering post "How we built our multi-agent research system" (anthropic.com/engineering/built-multi-agent-research-system) is the clearest production-multi-agent reference. Key claims, verbatim or near-verbatim:

- **Architecture**: orchestrator-worker. A *lead agent* analyzes the query, decomposes, and spawns specialized *subagents in parallel*; subagents each do focused search and return findings; lead synthesizes.
- **Why multi-agent**: "*Research demands the flexibility to pivot or explore tangential connections as the investigation unfolds.*" Fixed pipelines cannot accommodate this.
- **Headline number**: "*multi-agent systems with Claude Opus 4 leading and Claude Sonnet 4 subagents outperformed single-agent Opus by 90.2%*" on complex breadth-first queries.
- **Cost honesty**: "*multi-agent systems use about 15× more tokens than chats.*" Therefore only justified for high-value queries.
- **Performance variance**: three factors explain ~95% of variance — token usage (~80%), tool-call frequency, and model choice.
- **Speed**: parallel tool calling (3+ simultaneous) plus parallel subagent spawning reduced research time by up to 90%.
- **Where it does NOT work**: domains needing shared context across agents, heavy interdependencies, **and "coding tasks with limited parallelization."**
- **Evaluation**: start with ~20 test queries, not large datasets. LLM-as-judge with clear rubrics scales, but *human evaluation catches what automation misses* — e.g., agents preferring SEO-optimized content over authoritative sources, a bias the LLM judges missed.

**Forge takeaway**: This is *the* validation of orchestrator + parallel subagents + cross-model evaluator. But the Anthropic post explicitly carves out *coding* as a domain where parallelization is limited. That tension is the most important thing for Forge to internalize: code generation is closer to Cognition's domain than Anthropic's research domain. Forge's bet — that *git worktrees* provide enough isolation to recover parallelism *for code* — is the central wager that needs to hold.

### 2C.4 Decision-theoretic patterns

Tournament/debate, reflection, and tree-search methods used in production agents:

- **Multiagent Debate** — Du et al., arxiv [2305.14325](https://arxiv.org/abs/2305.14325). Multiple model instances propose, then debate over rounds; final answer converges. Outperforms zero-shot CoT and single-agent reflection on six reasoning/factuality tasks. *Takeaway*: separation across instances catches errors a single instance misses; this is the same logic as Forge's cross-model evaluator.
- **Reflexion** — Shinn et al., arxiv [2303.11366](https://arxiv.org/abs/2303.11366). Verbal RL: failures get distilled into natural-language self-reflections stored in episodic memory and replayed in the next attempt. *Takeaway*: precise template for Forge's learner — failure + resolution → one-line gotcha → injected on next similar task. Forge's Reflexion-style loop is the generator → evaluator-feedback → generator-revision cycle.
- **Tree of Thoughts (ToT)** — Yao et al., arxiv [2305.10601](https://arxiv.org/abs/2305.10601). Search over thoughts with self-evaluation at each node, look-ahead/backtracking. GPT-4 went from 4% (CoT) to 74% (ToT) on Game of 24. *Takeaway*: search beats greedy when the problem has discrete decision points; expensive at inference time.
- **LATS** — Zhou et al., arxiv [2310.04406](https://arxiv.org/abs/2310.04406). Plugs MCTS into the ReAct loop, with LM-as-value-function and self-reflection guiding rollout. Unifies reasoning, acting, and planning. *Takeaway*: the closest research analog to Forge's planned/branching execution; expensive but powerful for problems where ground-truth feedback is available.
- **Self-Consistency** — Wang et al., arxiv [2203.11171](https://arxiv.org/abs/2203.11171). Sample N reasoning paths, pick the majority answer. +10–24% on math/commonsense benchmarks. *Takeaway*: cheap and effective; Forge could optionally run N=3 generators per sprint and majority-vote, though git worktree merges complicate this.
- **Self-Refine** — Madaan et al., arxiv [2303.17651](https://arxiv.org/abs/2303.17651). Same LLM is generator + critic + refiner, iterating. ~20% gain across 7 tasks. *Takeaway*: Forge explicitly *rejects* this design — the critic must be a different agent. See §2G.2 for why.
- **MCTS for code**: AlphaCode 2 (DeepMind, [2023 tech report](https://storage.googleapis.com/deepmind-media/AlphaCode2/AlphaCode2_Tech_Report.pdf)) samples up to 1M candidates, clusters them, submits cluster representatives — 85th percentile competitive programming. RepoCoder (Zhang et al., arxiv [2303.12570](https://arxiv.org/abs/2303.12570)) does iterative retrieval-then-generate over the whole repo, +10% over in-file baselines. ReST-MCTS* (arxiv [2406.03816](https://arxiv.org/abs/2406.03816)) uses process-reward-guided tree search to self-train. RethinkMCTS (arxiv [2409.09584](https://arxiv.org/abs/2409.09584)) does MCTS over *thoughts* with code-execution feedback used to refine erroneous branches. *Takeaway*: tree search works for code when you have a cheap, automatic verifier (compile + tests). Forge's evaluator + test runs are the closest analog Forge has to a process-reward signal.

### 2C.5 The contrarian view: when swarms beat single agents — and when they don't

#### Cognition's "Don't Build Multi-Agents"

Cognition's essay (cognition.ai/blog/dont-build-multi-agents) is the strongest contrarian voice. Quoted near-verbatim:

> "Running multiple agents in collaboration only results in fragile systems."

The two principles they advocate:

> **Principle 1**: "Share context, and share full agent traces, not just individual messages."
> **Principle 2**: "Actions carry implicit decisions, and conflicting decisions carry bad results."

Their canonical failure example: building a Flappy Bird clone with parallel subagents — one subagent "*mistook your subtask and started building a background that looks like Super Mario Bros*" while another built incompatible components. Parallel subagents "*cannot see what the other was doing and so their work ends up being inconsistent with each other.*"

Their proposed alternative: **single-threaded linear agents** maintaining continuous context. For tasks exceeding context windows, introduce "*a new LLM model whose key purpose is to compress a history of actions & conversation into key details*" — i.e. summarization, not parallelism. They are not anti-multi-agent forever, but: "*at the moment, I don't see anyone putting a dedicated effort to solving this difficult cross-agent context-passing problem.*"

#### "Why Do Multi-Agent LLM Systems Fail?" (MAST)

Cemri, Pan, Yang et al., arxiv [2503.13657](https://arxiv.org/abs/2503.13657) systematically annotated 1,600+ traces across 7 popular MAS frameworks, identifying **14 failure modes** clustered into **3 categories**:

1. **System design issues** (e.g., bad role specification, unclear responsibilities, weak coordination protocols).
2. **Inter-agent misalignment** (e.g., information not propagating, agents pursuing conflicting goals, loss-of-context across handoffs).
3. **Task verification** (e.g., no termination condition, premature termination, no end-to-end check).

The headline finding: "*despite enthusiasm for [MAS], their performance gains on popular benchmarks are often minimal.*" Inter-annotator agreement (kappa = 0.88) gives the taxonomy weight. Related work — "Talk Isn't Always Cheap" (arxiv [2509.05396](https://arxiv.org/pdf/2509.05396)) — identifies sycophancy and conformity as systematic failure modes in multi-agent debate; agents converge on wrong answers because they don't want to disagree.

#### When multi-agent helps vs. doesn't (synthesis)

**Helps** (research, debate, code review, breadth-first information gathering):
- Anthropic's research system: +90.2% over single-agent Opus on breadth-first research.
- Du et al. multi-agent debate: significant gains on factuality and reasoning.
- Code review with multiple perspectives (security/perf/correctness) — conditioned on each reviewer having full diff context.

**Doesn't help / hurts** (single-file edits, tightly coupled work, simple tasks):
- Coding tasks with limited parallelization (Anthropic, explicit).
- Anything where context cannot be cleanly partitioned (Cognition).
- Simple lookups / one-shot edits where coordination overhead exceeds task complexity.
- Latency-sensitive paths — multi-agent adds round-trips.

Empirically, the 15× token cost from Anthropic + the MAST failure rate from Cemri et al. + Cognition's observed fragility converge on the same conclusion: **multi-agent is a high-variance, high-cost lever; pull it only when the task topology genuinely admits independent decomposition with verifiable merges.**

---

## Part 2G — Decision-Making and Autonomy

### 2G.1 Planning algorithms used in production

- **ReAct** — Yao et al., arxiv [2210.03629](https://arxiv.org/abs/2210.03629). Interleave Thought / Action / Observation. *Still the dominant pattern* in production agents (Claude Code, Cursor, Codex CLI all run a ReAct-derivative). On HotpotQA/Fever it reduces hallucination via grounded actions; on ALFWorld/WebShop it beats imitation/RL by 34%/10%. ReAct is "good enough" for the inner loop of any agent; you only reach for the heavier patterns below when ReAct alone gets stuck.
- **Plan-and-Solve (PS)** — Wang et al., arxiv [2305.04091](https://arxiv.org/abs/2305.04091). Force the model to *first* devise a plan, *then* execute. Targets the missing-step error class in zero-shot CoT. Beats zero-shot-CoT and matches few-shot-CoT on math. Forge's planner stage is a project-level Plan-and-Solve.
- **ADaPT** — Prasad et al., arxiv [2311.05772](https://arxiv.org/abs/2311.05772). *As-needed* decomposition: don't pre-plan everything; decompose recursively only when the agent fails to execute. +28% / +27% / +33% on ALFWorld / WebShop / TextCraft. *Takeaway*: pre-planning is expensive and often wrong; lazy decomposition is closer to how senior engineers actually work. Forge currently pre-plans all sprints; ADaPT suggests a *fallback* mode where a stuck sprint triggers recursive sub-decomposition.
- **Tree-of-Thoughts / LATS** — see §2C.4; both are heavyweight *search* over the planning space. Rarely worth it for code unless you have a fast verifier.
- **MCTS-for-code variants** (RethinkMCTS, ReST-MCTS*, SRA-MCTS, RPM-MCTS — see §2C.4) — process-reward-guided search. Useful when test-runs are cheap; expensive at training time but cheap to deploy.

### 2G.2 Self-evaluation reliability

The empirical case against self-evaluation is now well established:

- **Self-enhancement bias** (Zheng et al., arxiv [2306.05685](https://arxiv.org/abs/2306.05685), MT-Bench): "*GPT-4 favors itself with a 10% higher win rate; Claude-v1 favors itself with a 25% higher win rate.*" When a model judges its own output, it systematically rates it higher than a human or peer model would.
- **GPT-4 judges hit ~80% agreement with humans** on MT-Bench / Chatbot Arena — comparable to human-human agreement *on average*, but with the self-bias caveat above. Open-weight judges (e.g., Llama-3-70B-Instruct, Qwen-2-72B) trail GPT-4 by 5–15 points on agreement, varying by domain (factual vs. creative). Per AlpacaEval and follow-up critic studies, smaller open models (under 13B) are unreliable judges for borderline cases.
- **Anthropic on introspection** (alignment.anthropic.com/2026/introspection-adapters/): "*current LLMs often produce unreliable self-reports*"; introspective capability is "*highly unreliable and limited in scope.*" This is at the level of behavior reporting, not evaluation per se, but the same failure of metacognition applies.
- **Talk Isn't Always Cheap** (arxiv [2509.05396](https://arxiv.org/pdf/2509.05396)): in multi-agent *debate* settings, models exhibit sycophancy and conformity — they agree with peers (or with themselves on a previous turn) even when they should push back.

**Forge's response**: planner / generator / evaluator are *separated by role*, and Forge enforces that the evaluator runs on a *different model* than the generator (or at minimum a different prompt and a different system role). This mitigates self-enhancement bias. The literature *supports* this design. Two refinements worth considering:

1. **Cross-family evaluation**: when the generator is Sonnet, ideally the evaluator is *not* a Claude — e.g., use a strong open-weight evaluator (DeepSeek-V3.x, Qwen-2.5-Coder-32B, GPT-4o-mini via API). Same-family evaluators may share blind spots. Anthropic's research system itself uses Opus + Sonnet (same family), so this is a refinement, not a hard requirement.
2. **Evaluator skepticism prompt** (which Forge already uses): explicit instruction to *fail* on doubt. The MT-Bench bias work shows judges default to leniency unless prompted otherwise.

### 2G.3 Cost / latency-aware routing

In an open-weight world where Ollama is free and Opus is $15/Mtok, routing dominates economics. Three reference systems:

- **RouteLLM** — LMSYS (github.com/lm-sys/RouteLLM, paper arxiv [2406.18665](https://arxiv.org/abs/2406.18665)). Trains a binary router (strong vs. weak model) on Chatbot Arena preference data. Headline numbers: "*cost reductions of over 85% on MT Bench, 45% on MMLU, and 35% on GSM8K vs. using only GPT-4, while still achieving 95% of GPT-4's performance.*" Routes between GPT-4 ($24.7/Mtok) and Mixtral-8x7B ($0.24/Mtok). The router itself is small and cheap.
- **FrugalGPT** — Chen, Zaharia, Zou, arxiv [2305.05176](https://arxiv.org/abs/2305.05176). Three strategies: (1) prompt adaptation, (2) LLM approximation, (3) **LLM cascade** — try cheap, if confidence low escalate to expensive. Cascade reportedly matches GPT-4 with up to 98% cost reduction, or improves accuracy +4% at the same cost. The cascade pattern is the production workhorse.
- **Practical pattern: 7B classifier → 70B coder.** A small router classifies task complexity; only complex tasks reach the expensive model. Speculative routing (run cheap and expensive in parallel, return cheap if it's confident, swap to expensive otherwise) trades cost for latency the other way — useful when latency dominates.

**Forge mapping**: Forge's classifier (heuristic + procedural + LLM fallback) is essentially a RouteLLM-style three-class router (Ollama / Sonnet / Opus). Forge's budget downgrade cascade (Opus → Sonnet → Ollama on budget exhaustion) is FrugalGPT's cascade idea applied to a global budget rather than per-query confidence. The procedural memory table (`task_pattern → recommended_model + success_rate`) is essentially a learned router that improves with use — which is what RouteLLM does at training time, except Forge does it online per project.

### 2G.4 Human-in-the-loop checkpoints

**Codex's approval modes** are the cleanest taxonomy in the wild (developers.openai.com/codex/cli/reference):

1. **Suggest** — every action requires explicit approval (default; safest).
2. **Auto-edit** — file edits auto-applied; shell commands still need approval.
3. **Full-auto** — no confirmation; intended only for sandboxed/disposable environments.

The tiering generalizes to any agent: the unit of approval scales with trust (per-action → per-write → per-session). Claude Code's permission system follows the same logic with finer granularity (per tool kind). Cursor's "Yolo mode" is essentially full-auto.

**Where to interrupt** — synthesizing best practice:

- **Per-tool-call approval**: highest safety, lowest throughput. Use when blast radius is unbounded (production deploys, payments, deletes).
- **Per-file-diff approval**: matches developer mental model. Good for medium-trust tasks.
- **Per-sprint approval (merge gate)**: lowest friction, requires strong evaluator. The Anthropic harness pattern.
- **Post-hoc review only**: appropriate only with a reliable rollback path (worktree + branch, never merged to main without review).

**Does Forge's merge gate match best practice?** Yes, with caveats:

- The merge gate operates at the *worktree* level — a sprint's full diff is reviewed before it touches main. This matches per-sprint approval and is the Anthropic harness pattern.
- It is preceded by an *evaluator* sign-off — a soft check before the human sees the diff. This filters obvious failures so humans only see plausible work, similar to how GitHub's required-checks gate PRs before review.
- It includes a *review panel* (multi-perspective reviewers) for large changes — this is the Anthropic + Du et al. multi-agent-where-it-helps pattern applied at the *review* boundary, not the *generation* boundary, which is precisely where the literature says it works best.
- **Risk**: per-sprint approval can rubber-stamp if the human just clicks "approve all." Forge should default to *showing the diff inline* and require deliberate action; one-click "approve all" should be opt-in per session, not default.
- **Missing piece**: per-tool-call approval for *destructive* operations (rm, force-push, schema migrations on prod). Even in full-auto, these should always pause. This is partly inherited from Claude Code's permission system but deserves an explicit allow/deny list in Forge config.

---

## Implications for Forge's Three-Agent Design

**Does the literature support planner / generator / evaluator?** Mostly yes — with three substantive caveats.

**Strong support:**
1. **Cross-model evaluation beats self-evaluation.** MT-Bench self-enhancement bias (Zheng et al.), Reflexion's external feedback channel (Shinn et al.), Anthropic's harness research, and Du et al.'s debate work all converge on the same finding. Forge's evaluator-on-different-model is well-grounded.
2. **Plan → Execute separation helps.** Plan-and-Solve (Wang et al.), AgentVerse's Expert Recruitment + Decision-Making + Execution stages, and HuggingGPT's task-planning controller all validate the planner role. Pre-decomposition reduces missing-step errors.
3. **Verbal-feedback loops beat single-shot generation.** Reflexion + Self-Refine show ~20% gains from a feedback loop. Forge's generate → evaluate → revise (≤2 cycles) is the same mechanism, with the critical Forge-specific tweak that the critic is a *different* agent — addressing Self-Refine's main weakness.

**Caveats and tensions:**

1. **Cognition's critique applies most strongly to *parallel* generators on a *single* coupled task.** Forge mitigates this with two design choices the essay does not foresee: (a) git worktrees give each generator a literal isolated filesystem rather than a shared mental model, and (b) the evaluator + merge gate provide *explicit* coordination at the integration boundary, replacing the implicit coordination Cognition says is missing. But Forge should heed the warning when sprints are *not* genuinely independent: forcing parallelism on tightly coupled work will produce the Flappy Bird / Mario Bros failure mode. The planner needs to be conservative about declaring sprints independent — when in doubt, serialize.

2. **The MAST taxonomy's three failure categories map directly onto Forge risks.** *System design* — sprint contracts must be unambiguous (already addressed via explicit `done_criteria`). *Inter-agent misalignment* — context loss between planner and generator is a real risk; the memory injection (max ~500 tokens) is correct in principle but should always include the evaluator-feedback from prior revision attempts (already addressed in scheduler). *Task verification* — Forge's evaluator + done-criteria contract is the strongest defense; the literature suggests this is the highest-leverage axis to invest in.

3. **The Anthropic post explicitly carves out coding as a domain where parallelization is limited.** Forge bets that *task-level* parallelism (independent sprints) is achievable even though *file-level* parallelism is not. This bet relies on the planner correctly identifying independent work. If a project has high coupling (single-file refactors, tightly woven features), Forge should be willing to fall back to serial execution — and the budget controller / planner should detect this from the dependency graph, not pretend everything parallelizes.

**Concrete refinements suggested by the literature:**

- **ADaPT-style as-needed decomposition** as a *recovery* mode: when a sprint fails after MAX_REVISIONS, rather than escalating to the user, recursively decompose into smaller sprints. Cheap planning is free on Ollama.
- **Self-Consistency for high-stakes sprints** (optional): on a marked-critical sprint, run N=3 generators in parallel worktrees, have the evaluator pick the winner. This is the Anthropic parallel-subagents pattern applied at the sprint level — and it's exactly the kind of breadth-first task where the literature says multi-agent helps.
- **Cross-family evaluator** when the budget allows: a Sonnet-evaluating-Opus pair shares blind spots; a strong open-weight evaluator (DeepSeek-V3.x, Qwen-2.5-Coder) on a separate model family would be more robust. This matters less when the evaluator is checking *test runs* (objective) and more when checking *code quality* (subjective).
- **Tighter coupling between learner and procedural memory**: every evaluator verdict is a labeled training point. Forge's procedural table (task_pattern → model + success_rate) should update automatically on every approved/failed sprint. This is online RouteLLM-without-the-training.
- **Default merge gate to "show diff, require deliberate approval per worktree"** rather than "approve all." Cognition's warning that "actions carry implicit decisions" applies most strongly at the merge boundary, where many decisions land at once.

**Bottom line**: the literature strongly endorses the *separation of roles* across generator/evaluator and the *plan-then-execute* split, and provides extensive evidence that self-evaluation is unreliable. The literature is more cautious about parallel multi-agent execution for *coding*, and Forge's worktree + evaluator design is exactly the right kind of structural answer to that caution — but the planner must be honest about when sprints are independent.

---

## Citations

- [OpenAI Swarm](https://github.com/openai/swarm) — educational handoff library.
- [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) — production successor to Swarm.
- [Anthropic — How we built our multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system) — orchestrator-worker; +90.2% on breadth-first research; 15× tokens.
- [Cognition — Don't Build Multi-Agents](https://cognition.ai/blog/dont-build-multi-agents) — context-sharing principles; against parallel subagents.
- AgentVerse — Chen et al., [arxiv 2308.10848](https://arxiv.org/abs/2308.10848) — Expert Recruitment / Collaborative Decision-Making / Execution.
- HuggingGPT / JARVIS — Shen et al., [arxiv 2303.17580](https://arxiv.org/abs/2303.17580) — model-as-tool task routing.
- Multiagent Debate — Du et al., [arxiv 2305.14325](https://arxiv.org/abs/2305.14325) — debate beats single-agent reflection.
- Reflexion — Shinn et al., [arxiv 2303.11366](https://arxiv.org/abs/2303.11366) — verbal RL via episodic memory of self-reflections.
- Tree of Thoughts — Yao et al., [arxiv 2305.10601](https://arxiv.org/abs/2305.10601) — search beats greedy on Game of 24 (4% → 74%).
- LATS — Zhou et al., [arxiv 2310.04406](https://arxiv.org/abs/2310.04406) — MCTS over ReAct, unified reasoning/acting/planning.
- Self-Consistency — Wang et al., [arxiv 2203.11171](https://arxiv.org/abs/2203.11171) — sample N, majority-vote.
- Self-Refine — Madaan et al., [arxiv 2303.17651](https://arxiv.org/abs/2303.17651) — single-LLM iterative refinement (~20% gain).
- AlphaCode 2 — DeepMind, [tech report (2023-12)](https://storage.googleapis.com/deepmind-media/AlphaCode2/AlphaCode2_Tech_Report.pdf) — sample-and-cluster, 85th-percentile competitive programming.
- RepoCoder — Zhang et al., [arxiv 2303.12570](https://arxiv.org/abs/2303.12570) — iterative retrieval+generation at repo scale.
- ReST-MCTS* — Zhang et al., [arxiv 2406.03816](https://arxiv.org/abs/2406.03816) — process-reward-guided tree search for self-training.
- RethinkMCTS — [arxiv 2409.09584](https://arxiv.org/abs/2409.09584) — MCTS over thoughts with code-execution feedback.
- Why Do Multi-Agent LLM Systems Fail? — Cemri, Pan, Yang et al., [arxiv 2503.13657](https://arxiv.org/abs/2503.13657) — MAST taxonomy: 14 modes / 3 categories.
- Talk Isn't Always Cheap — [arxiv 2509.05396](https://arxiv.org/pdf/2509.05396) — sycophancy and conformity in multi-agent debate.
- Where LLM Agents Fail and How They Can Learn From Failures — [arxiv 2509.25370](https://arxiv.org/abs/2509.25370) — cascading failures and modular error analysis.
- ReAct — Yao et al., [arxiv 2210.03629](https://arxiv.org/abs/2210.03629) — reasoning + acting interleaved; ICLR 2023.
- Plan-and-Solve — Wang et al., [arxiv 2305.04091](https://arxiv.org/abs/2305.04091) — plan-then-execute for zero-shot CoT.
- ADaPT — Prasad et al., [arxiv 2311.05772](https://arxiv.org/abs/2311.05772) — as-needed recursive decomposition.
- Judging LLM-as-a-Judge with MT-Bench — Zheng et al., [arxiv 2306.05685](https://arxiv.org/abs/2306.05685) — self-enhancement bias (GPT-4 +10%, Claude-v1 +25%); ~80% human agreement.
- Anthropic — [Introspection Adapters / Alignment Science Blog](https://alignment.anthropic.com/2026/introspection-adapters/) — self-reports unreliable.
- Anthropic — [Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) — evaluation methodology.
- RouteLLM — Ong et al. (LMSYS), [github.com/lm-sys/RouteLLM](https://github.com/lm-sys/RouteLLM), [arxiv 2406.18665](https://arxiv.org/abs/2406.18665) — preference-trained router; 85% cost reduction at 95% quality.
- FrugalGPT — Chen, Zaharia, Zou, [arxiv 2305.05176](https://arxiv.org/abs/2305.05176) — cascade strategy; up to 98% cost reduction matching GPT-4.
- OpenAI Codex CLI — [Approval Modes documentation](https://developers.openai.com/codex/cli/reference) — suggest / auto-edit / full-auto taxonomy.
