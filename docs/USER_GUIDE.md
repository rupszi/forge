---
status: live
owner: pal.megyes
last_reviewed: 2026-06-02
---

# Forge — User Guide

Everything you need to install, run, connect models, and orchestrate agents —
**100% local and free by default**. No API keys, no cloud, no telemetry unless
you explicitly turn it on.

> New here? Read [§1 What Forge is](#1-what-forge-is) → [§3 Install](#3-install)
> → [§4 Pull models](#4-pull-models) → [§5 Start the app](#5-start-the-app).
> The architecture/decisions live in [FORGE_STUDIO_BUILD.md](FORGE_STUDIO_BUILD.md);
> build status in [FORGE_STUDIO_TRACKER.md](FORGE_STUDIO_TRACKER.md).

---

## 1. What Forge is

Forge is a **multi-agent coding-and-documents orchestrator that runs on your
machine**. You point it at a project folder and a git branch; a small local
**orchestrator** model plans the work and **spawns specialist local models on
demand** to write code, grade it, and produce documents. Everything — your
code, the models, the memory database — stays on your laptop.

The core idea: **the agent that writes the work never grades it.** A *generator*
produces code in an isolated git worktree; a separate *evaluator* running on a
**different model family** checks it against explicit "done" criteria. Forge
also keeps a **memory** that compounds across sessions, so it gets faster and
makes fewer mistakes over time.

**The loop:** `plan → generate (in a worktree) → evaluate (cross-family) →
revise (≤2×) → merge`, with a learner extracting lessons afterward.

---

## 2. Requirements

| Need | Why | Notes |
|---|---|---|
| **macOS (Apple Silicon)** or **Linux** | runs the models | M-series Mac or x86_64/ARM Linux. Native Windows → use WSL2. |
| **~24–48 GB RAM** | local models | 48 GB lets you run an orchestrator + a 32B coder. 16 GB works for small models. |
| **Free disk** | model weights | The default set is ~15 GB; larger coders add more. |
| **Python 3.11+** | the daemon | 3.10 minimum. |
| **Git** | worktree isolation | any recent version. |
| **[Ollama](https://ollama.com)** | the local model runtime | Install separately (Forge doesn't bundle it). `forge doctor` checks for it. |
| **Node 18+ / pnpm** *(optional)* | the web dashboard | Only needed for the browser UI; the CLI works without it. |

Run `forge doctor` any time to see what's present and what's missing.

---

## 3. Install

Forge runs **inside an existing project**. Clone it once, then use it from any
project folder.

```bash
# 1. Get Forge
git clone <your-forge-repo-url> ~/Development/forge
cd ~/Development/forge
bash setup.sh                 # creates .venv, installs deps (prefers `uv`)

# 2. Install Ollama (the model runtime) if you don't have it
#    macOS: download from ollama.com  ·  Linux: curl -fsSL https://ollama.com/install.sh | sh
ollama --version

# 3. (optional) the dashboard deps
cd ui && pnpm install && cd ..
```

The `forge` command lives in the venv (`source .venv/bin/activate` → `forge …`,
or call `.venv/bin/forge`). To use Forge in another project, run `forge` commands
from that project's directory — Forge writes its state to that project's
`.forge/`.

---

## 4. Pull models

Forge's defaults are real, Apple-Silicon-friendly Ollama tags. Pull the starter
set (a complete offline harness — orchestrator + coder + cross-family evaluator
+ embeddings, ~15 GB):

```bash
forge models            # show the lineup + which are already pulled + free disk
forge models pull       # download the missing ones (refuses if disk is tight)
forge models pull --dry-run   # preview sizes without downloading
```

The default set:

| Role | Model | ~Size |
|---|---|---|
| Orchestrator | `qwen2.5:7b` | 4.7 GB |
| Generator (coder) | `qwen2.5-coder:7b` | 4.7 GB |
| Evaluator (different family) | `llama3.1:8b` | 4.9 GB |
| Embeddings (memory) | `nomic-embed-text` | 0.3 GB |

Bigger coders (`qwen2.5-coder:14b` / `:32b`) are pulled on demand for harder
tasks. **Disk guard:** `forge models pull` refuses any download that would leave
less than `FORGE_MODEL_DISK_HEADROOM_GB` (default 10) free — point
`OLLAMA_MODELS` at an external volume if you're tight on space.

---

## 5. Start the app

### Option A — the dashboard (one command)

```bash
forge serve            # starts the daemon AND the web dashboard
# → http://localhost:3000
```

`forge serve` launches the Python daemon (WebSocket on `127.0.0.1:9111`) **and**
the Next.js dashboard as a managed subprocess; Ctrl-C stops both. If the UI deps
aren't installed it prints a note and runs the daemon alone. Use `--no-ui` for
headless/CI.

The dashboard header shows the **● Local-only** badge (turns **▲ Cloud enabled**
only if you opt into cloud) and a live **model-RAM meter** showing which models
are loaded.

### Option B — headless, from the terminal

```bash
forge plan "add a /health endpoint with a test"   # decompose into sprints
forge run                                          # execute them (plan→gen→eval→revise→merge)
forge add "fix the flaky login test"               # queue a single task (skips the planner)
forge review sprint-ab12                            # multi-perspective review of a sprint's diff
forge merge --show                                  # list finished worktrees
forge merge --approve                               # merge them into your branch
forge doc "write a README for this project" --format md   # generate a document
```

---

## 6. Connecting models

Forge picks an **executor** per model automatically (`daemon/routing.py`). You
control the lineup with environment variables — no config files.

### 6.1 Local via Ollama (the default)

Anything not matching another rule routes to Ollama on `localhost:11434`.
Override which models Forge uses:

```bash
export LOCAL_CODE_MODEL=qwen2.5-coder:14b     # the default generator
export LOCAL_PLAN_MODEL=qwen2.5:7b            # the orchestrator
export LOCAL_BACKUP_MID_MODEL=llama3.1:8b     # the cross-family evaluator
export OLLAMA_BASE_URL=http://localhost:11434 # change if Ollama is remote
```

### 6.2 Local via MLX (Apple Silicon)

For Hugging Face weights Ollama can't host, prefix the model with `mlx:` and
Forge serves it through Apple's MLX on the Metal GPU:

```bash
# requires: pip install mlx-lm
export LOCAL_CODE_MODEL="mlx:mlx-community/Qwen2.5-Coder-14B-Instruct-4bit"
```

### 6.3 Any OpenAI-compatible endpoint (vLLM, Together, OpenRouter, …)

Set `OPENAI_BASE_URL` and every non-cloud model routes there:

```bash
export OPENAI_BASE_URL=http://localhost:8000/v1   # your vLLM/SGLang server
export OPENAI_API_KEY=...                          # if the endpoint needs one
```

### 6.4 Cloud models (opt-in only)

By default Forge makes **zero** outbound inference calls. Cloud models (Claude
via the `claude` CLI, the Anthropic batch endpoint) are gated:

```bash
export FORGE_CLOUD_ENABLED=1     # the only switch that lets cloud run
# then assign a cloud model to a sprint, e.g. claude-sonnet-4
```

With cloud off, assigning a cloud model fails loudly (`CloudDisabledError`)
rather than silently dialing out — and the dashboard badge stays **● Local-only**.

### 6.5 How routing decides

| Model looks like | Executor | Local? |
|---|---|---|
| `mlx:…` / `mlx-…` | MLX | ✅ |
| Anthropic (`claude-…`, `opus`, `sonnet`, `haiku`) | `claude_code` | ☁️ needs `FORGE_CLOUD_ENABLED` |
| anything, with `OPENAI_BASE_URL` set | `openai_compatible` | ✅ if your endpoint is local |
| everything else | Ollama | ✅ |

---

## 7. Orchestrating agents

### 7.1 The harness

When you run a task, Forge:

1. **Plans** — the orchestrator decomposes your objective into *sprints*, each
   with explicit, testable `done_criteria` (the "contract").
2. **Generates** — for each sprint, a generator writes code in an isolated git
   **worktree**. It's told *not* to grade its own work.
3. **Evaluates** — a separate model from a **different family** checks each
   criterion PASS/FAIL with evidence. (Generator=Qwen ⇒ evaluator=Llama, etc.)
4. **Revises** — on FAIL, the evaluator's feedback is fed back to the generator,
   up to 2 times, then it escalates (ADaPT decomposition / self-consistency for
   `[critical]` sprints).
5. **Merges** — you review the diff at the merge gate and approve.
6. **Learns** — a learner extracts gotchas into memory for next time.

### 7.2 The model pool (spawn on demand)

Forge keeps the orchestrator + embeddings **pinned** in RAM and **spawns coder /
evaluator models on demand**, evicting the least-recently-used one when memory
is tight — so it never exceeds your RAM budget:

```bash
export FORGE_LOCAL_RAM_BUDGET_GB=36     # of 48 GB, leaving headroom (default)
```

Two large models that don't fit together are run one-after-another, never
overcommitted. The dashboard's RAM meter shows this live.

### 7.3 Modes

Control how much autonomy the harness has (set in the dashboard, or via the WS
`set_mode`): `plan` (plan only, you review before any code runs) · `ask` ·
`auto` (run end-to-end) · `accept_edits` · `bypass`.

### 7.4 Memory that compounds

Four local stores in one SQLite file (`.forge/forge.db`): **knowledge** (gotchas
/ patterns, confidence-scored), **episodic** (task history), **procedural**
(which model works for which task), **research** (cached web findings). Before
each task Forge injects the 3–5 most relevant items; after each task it nudges
their confidence up (helped) or down (didn't). Re-running a similar task hits the
cache and skips revisions.

```bash
forge memory                       # KB summary
forge memory search "supabase"     # search learned items
forge memory add gotcha auth "validate JWTs server-side"
forge memory import                # pull in Claude Code auto-memory
```

### 7.5 Extending context

The model's window is finite; Forge keeps the agent from needing all of it at
once and pushes the rest to disk. On top of context isolation (worktree per
sprint), retrieval (the KB above), and the repo map, you have three explicit
levers:

- **Attach files/folders** — the dashboard's **Attach** button asks for a file
  or folder path; the daemon reads the text and injects it into the agent's
  context for the next plan/run (binary skipped, large files clipped, budget-
  capped). Use it to hand the agent a spec, a log, or a reference file.
- **Working memory scratchpad** — a notebook at `.forge/memories/` that persists
  across the context window and is re-injected into later sprints. Path-scoped
  (nothing escapes the folder). Anything written here survives even when the
  live window is full.
- **Auto-compaction** — when the assembled context grows large, Forge
  summarizes it with a local model instead of chopping the tail off, so long
  sessions don't lose the earlier context. On by default; `FORGE_AUTO_COMPACT=0`
  to disable.

**Context window size** — the top-bar `ctx … ▾` dropdown sets the model's window
(`num_ctx`): presets **4K → 2M** plus **Auto** (largest that safely fits the model
+ RAM). Presets above the model's trained max or your RAM-safe ceiling are greyed
out with the reason.

**KV-cache quantization** — at the bottom of that dropdown, **f16 / q8 / q4**.
Storing the attention cache at q8/q4 holds **2–4× more context** per GB, unlocking
larger windows. To make it real, start Ollama with
`OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0` (Forge mirrors the choice so
the ceiling math is honest).

**`forge digest <file>`** — map-reduce a file larger than the window into a concise
digest (saved under `.forge/artifacts/`), so a small-window model can still
process it. The chunker + `file.fetch` also let the agent lazy-load big inputs.

And the simplest lever: **pick a long-context model** from the top-right model
picker (e.g. a 128K-window model) when a task genuinely needs more room.

---

## 8. Documents

The document agent turns a brief into a local Markdown document, graded against
its criteria, exported to your project's `.forge/artifacts/`:

```bash
forge doc "write a deployment runbook covering rollback" --name runbook --format md
forge doc "API reference for the /users endpoints" --format html
# formats: md (default), txt, html, docx (docx needs `pip install python-docx`)
```

Runs on a local model — free and offline by default, same as coding.

---

## 9. Configuration reference (key env vars)

| Variable | Default | What it does |
|---|---|---|
| `FORGE_CLOUD_ENABLED` | `0` | Master switch for cloud models. Off = fully local. |
| `FORGE_LOCAL_RAM_BUDGET_GB` | `36` | Model-pool RAM ceiling. |
| `FORGE_MODEL_DISK_HEADROOM_GB` | `10` | Free disk `forge models pull` must preserve. |
| `LOCAL_CODE_MODEL` | `qwen2.5-coder:7b` | Default generator. |
| `LOCAL_PLAN_MODEL` | `qwen2.5:7b` | Orchestrator / planner. |
| `LOCAL_BACKUP_MID_MODEL` | `llama3.1:8b` | Cross-family evaluator. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama host. |
| `OPENAI_BASE_URL` | *(unset)* | Route non-cloud models to an OpenAI-compatible server. |
| `SESSION_BUDGET_USD` | `5.00` | Hard $ cap (only matters with cloud on). |
| `FORGE_VECTOR_EPISODES` | `0` | Enable sqlite-vec semantic recall (`pip install sqlite-vec`). |
| `MAX_REVISIONS` | `2` | Generate↔evaluate revision cap. |

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `forge: command not found` | `source .venv/bin/activate`, or run `.venv/bin/forge`. |
| Dashboard doesn't load at :3000 | UI deps missing — `cd ui && pnpm install`, then `forge serve`. |
| "recommended model … not pulled" | `forge models pull`. |
| A model won't pull | Check the tag exists on [ollama.com/library](https://ollama.com/library); override `LOCAL_*_MODEL`. |
| `CloudDisabledError` | You assigned a cloud model with cloud off. Set `FORGE_CLOUD_ENABLED=1` or pick a local model. |
| Pool error "cannot fit … budget" | Raise `FORGE_LOCAL_RAM_BUDGET_GB` or use a smaller model. |
| Out of disk pulling models | Set `OLLAMA_MODELS=/Volumes/ext/ollama` or raise `FORGE_MODEL_DISK_HEADROOM_GB`. |
| Verify everything | `forge doctor`. |

---

*Local-first. Free by default. Your code and memory never leave your machine
unless you explicitly opt into cloud.*
