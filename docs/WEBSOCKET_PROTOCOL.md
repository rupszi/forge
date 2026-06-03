---
status: live
owner: pal.megyes
last_reviewed: 2026-06-04
---

# Forge WebSocket protocol

The daemon exposes a single WebSocket endpoint the dashboard (and TUI) speak to.
This is the complete message reference, generated from `daemon/ws_server.py`
(handlers + broadcasts), `daemon/events.py` (`EventType`), and `ui/lib/types.ts`
(payload shapes). It is the de-facto protocol contract; keep it in sync when you
add or rename a handler or event.

## Transport & limits

| Property | Value | Source |
|---|---|---|
| Bind | `127.0.0.1:9111` (loopback only — never `0.0.0.0`) | `ws_server.start_server` |
| Frame format | one JSON object per text frame, with a `type` field | `_handle_message_inner` |
| Max frame size | `1_000_000` bytes (rejected before `json.loads`) | `_MAX_MESSAGE_BYTES` |
| Rate limit | 10 messages / 1 s sliding window per client | `_RATE_LIMIT_MAX_MSG` |
| Concurrency | ≤ 10 handlers run at once (excess queues) | `_MAX_CONCURRENT_HANDLERS` |
| Origin | allow-list checked on connect | `_origin_allowed` |

Every request returns exactly one response object; some handlers *also*
`broadcast()` a push to all connected clients (noted below). Unknown message
types return `{"type": "error", "error": "..."}`.

## Client → server

| `type` | Key fields | Response `type` | Notes |
|---|---|---|---|
| `init` | `path` | `project_context` | Scans the project; path validated to home/cwd scope |
| `plan` | `objective` | `plan_acknowledged` | Planning runs in the scheduler; progress arrives as broadcasts |
| `status` | — | `ack` | Liveness/echo |
| `get_sessions` | — | `sessions_list` | Past sessions from SQLite |
| `search_knowledge` | `query` | `knowledge_results` | KB `LIKE` search, ≤20 items |
| `add_knowledge` | `category`, `topic`, `content` | `knowledge_updated` | Content passes `kb_guard` (best-effort) |
| `delete_knowledge` | `id` | `knowledge_updated` | |
| `memory_tool` | `command`, `path`/`content`/`old`/`new`/`line`, *(opt)* `project_path`, `session_id` | `memory_tool` | Working-memory scratchpad; scoped per (project, session) — F3 |
| `attach.path` | `path` | `attachments` | Reads text files (skips symlinks/binaries) |
| `attach.list` | — | `attachments` | |
| `attach.clear` | — | `attachments` | |
| `file.fetch` | `path` | `file_content` | Path validated; symlink-safe |
| `pool` | — | `pool` (`PoolState`) | Model-pool RAM/lease state |
| `locality` | — | `locality` (`LocalityState`) | local vs cloud indicator |
| `context.options` | `model` | `context_options` (`ContextOptions`) | num_ctx presets + KV estimate |
| `set_context` | `value` (`"auto"` or int) | `context_options` | Sets the process-wide context size |
| `set_kv_cache` | `value` (`f16`/`q8_0`/`q4_0`) | `context_options` | Sets the assumed KV-cache quant |
| `set_mode` | `mode` (`auto`/`plan`/`ask`/`bypass`) | `mode_changed` | **Also broadcasts** `mode_changed`; invalid → `error` |
| `set_model` | `model` | `model_changed` | |
| `models.installed` | — | `models_installed` | Locally-present Ollama models |
| `llms.list` | — | `llms_list` | Configured LLM adapters |
| `skills.list` | — | `skills_list` | |
| `connectors.list` | — | `connectors_list` | |
| `branches.list` | `path` | `branches` | git branch picker |
| `branch.checkout` | `path`, `branch`, `create` | `branch_checkout` | **Also broadcasts** `branches` |
| `folder.init` | `path` | `folder_init` | `git init` |
| `folder.pick` | `path` | `folder_picked` | |
| `wizard` | — | `wizard_hint` | Points to the terminal `forge wizard` |
| `attach.files`, `attach.folder`, `connector.activate`, `plugins.gallery` | — | `ack` | Stub acks (full plumbing is later sprints) |
| *(slash commands)* | `args` | varies | Forwarded to `dispatch_slash` |

## Server → client

### Request responses

The `type` values handlers return: `project_context`, `plan_acknowledged`,
`ack`, `sessions_list`, `knowledge_results`, `knowledge_updated`, `memory_tool`,
`attachments`, `file_content`, `pool`, `locality`, `context_options`,
`mode_changed`, `model_changed`, `models_installed`, `llms_list`, `skills_list`,
`connectors_list`, `branches`, `branch_checkout`, `folder_init`,
`folder_picked`, `wizard_hint`, `error`.

Typed payloads mirrored in `ui/lib/types.ts`: `ProjectContext`, `Session`,
`KnowledgeItem`, `BudgetState`, `LocalityState`, `PoolState`/`PoolModel`,
`ContextOptions`/`ContextPreset`, `SprintContract`, `EvaluatorResult`,
`ReviewResult`. (`check-schema-parity.py` enforces `SprintContract` and
`Session` parity against `models.py`.)

### Broadcast pushes (unsolicited)

Sent to **all** clients during a run:

| `type` | Emitted by | Payload |
|---|---|---|
| `plan_created` | scheduler | `sprints` array (contracts) |
| `budget_update` | scheduler | spend vs cap |
| `session_complete` | scheduler | session summary |
| `mode_changed` | `set_mode` | `mode` |
| `branches` | `branch.checkout` | branch state |

### Trace events (also broadcast during a session)

Every `EventType` in `daemon/events.py` is emitted to
`.forge/sessions/<id>/trace.jsonl` **and** broadcast as `{"type": <value>,
"sprint_id": ..., ...}`. The wire `value`s:

- **session**: `session.start`, `session.complete`, `session.plan_only`,
  `session.bypass`, `session.hook_blocked`
- **repomap**: `repomap.built`
- **plan**: `plan.created`
- **wave**: `wave.start`, `wave.complete`
- **worktree**: `worktree.created`, `worktree.create_failed`
- **sprint**: `sprint.attempt`, `sprint.evaluated`, `sprint.approved`,
  `sprint.revising`, `sprint.recovered`, `sprint.crashed`
- **recovery (ADaPT)**: `recovery.adapt.start`, `recovery.adapt.decomposed`,
  `recovery.adapt.subsprint_passed`, `recovery.adapt.subsprint_failed`,
  `recovery.adapt.complete`
- **recovery (Self-Consistency)**: `recovery.consistency.start`,
  `recovery.consistency.attempt`, `recovery.consistency.winner`,
  `recovery.consistency.complete`, `recovery.consistency.no_winner`
- **budget**: `budget.downgrade`, `budget.exhausted`

## Keeping this current

When you add a handler: add a `Client → server` row. When you add an
`EventType`: add it to the trace-event list. When you change a `to_dict()`
payload or `ui/lib/types.ts` interface: `scripts/check-schema-parity.py` will
fail the push until both sides match.
