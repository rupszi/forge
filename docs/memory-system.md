# Memory System

All memory is stored in a single SQLite database at `.forge/forge.db` (WAL mode for safe concurrent access). No external services, no vector databases.

## Four memory types

### Episodic memory

Raw history of every task execution. Stores: task description, model used, agent role, status, result, error details, error category, resolution, evaluator verdict, revision count, token usage, cost, duration, and files changed.

Used by the learner to extract patterns and by the retriever to surface past failures on similar tasks.

### Knowledge base (semantic memory)

One-line imperative statements. Examples:
- "Supabase RLS: test with service_role key, not anon key."
- "Next.js server actions require 'use server' directive at top of file."
- "Playwright tests need explicit waits after navigation."

Each item has: category (gotcha / solution / pattern / rule / preference), topic, content, source, confidence score, usage stats.

Max 200 items per project. This forces quality over quantity.

### Procedural memory

Routing intelligence that improves over time. Maps task patterns to: recommended model, recommended agent type, success rate, average duration, and sample count.

Updated after every task execution. Over time, the classifier learns which model works best for which type of work.

### Research cache

Web search results with: query, URL, title, extracted content, relevance score, task association, success flag, and expiry date.

Checked before any new web search to avoid redundant lookups. Results that led to successful task completion are kept longer and scored higher.

## Confidence scoring

Knowledge items start at 0.5 confidence (or 0.7 when extracted from a failure/resolution pair).

**Reinforcement:** After each task, the system checks which knowledge items were injected into the agent's context. If the task succeeded, each injected item gets `mark_helpful` (confidence increases). If the task failed, each gets `mark_unhelpful` (confidence decreases).

**Decay:** Items unused for extended periods lose confidence gradually.

## Pruning

The knowledge base is pruned automatically:
- Items below 0.2 confidence are removed
- Items unused for 90+ days are removed
- If the count exceeds 200, lowest-confidence items are pruned first

Pruning runs after every session.

## Retriever

The retriever (`memory/retriever.py`) provides unified cross-store retrieval. Given a task description, it:

1. Extracts topics from the description (keyword extraction or local LLM)
2. Queries the knowledge base for relevant gotchas and solutions (max 5 items)
3. Queries episodic memory for past failures on similar tasks (max 3 items)
4. Queries the research cache for recent relevant results (max 2 items)
5. Formats everything into a context string capped at ~500 tokens

The 500-token budget is deliberate. Context windows are the most valuable resource. Dumping the full knowledge base wastes tokens and degrades agent performance. Surgical injection of only the most relevant items produces better results.

## Claude Code interop

Forge reads but does not replace Claude Code's native memory:

- Reads `~/.claude/projects/<project>/memory/` (auto-memory)
- Reads `CLAUDE.md` and `.claude/rules/*.md` (project instructions)
- Writes only to `.forge/forge.db`
- Optionally suggests additions to CLAUDE.md when it learns something the project should know permanently

## Learner

Post-session extraction (`memory/learner.py`) runs after every session:

- **From failure + resolution pairs:** Asks local LLM to distill a one-line gotcha. Generic items are skipped. Stored at 0.7 confidence.
- **From successful routing:** Updates the procedures table with model, duration, and success data.
- **From successful research:** Extracts key insights from research that led to task success. Stores as solutions with source URLs.
