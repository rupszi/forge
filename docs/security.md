# Security

Seventeen non-negotiable security requirements.

## 1. No curl-pipe-bash install

`setup.sh` is a local script that creates a Python venv and installs two dependencies. It does not download or execute remote scripts.

## 2. No --dangerously-skip-permissions

All Claude Code sessions spawned by Forge run with default permission mode. No permission bypasses.

## 3. WebSocket binds to 127.0.0.1 only

The WebSocket server is hardcoded to bind to `127.0.0.1:9111`. Never `0.0.0.0`. This is not configurable. The port number is configurable via `WS_PORT`, but the bind address is not.

## 4. No shell=True in subprocess calls

All subprocess execution uses `asyncio.create_subprocess_exec` with explicit argument lists. No `shell=True` anywhere in the codebase.

## 5. Input sanitization

All user inputs are sanitized before use:
- **Worktree names:** Alphanumeric characters and hyphens only, validated with regex. Anything else is rejected.
- **Task descriptions:** Null bytes and control characters stripped, length capped at 10,000 characters.
- **Prompts sent to executors:** Sanitized before passing to `claude -p` or Ollama.

## 6. Budget hard cap

Sessions cannot exceed `SESSION_BUDGET_USD` (default: $5.00). When the budget is exhausted:
1. Remaining Opus tasks downgrade to Sonnet
2. Remaining Sonnet tasks downgrade to Ollama
3. If still over budget, remaining tasks are cancelled

The budget controller tracks cost per model per task in real time.

## 7. No secrets in code

API keys come from environment variables or Claude Code's own authentication. No hardcoded keys, tokens, or credentials anywhere in the codebase.

## 8. SQLite WAL mode

The database uses Write-Ahead Logging for safe concurrent reads from the UI and daemon. No corruption risk from simultaneous access.

## 9. Git worktree cleanup on exit

`atexit` handlers and `SIGINT`/`SIGTERM` signal handlers ensure all worktrees are removed even on crash. The worktree manager tracks all active worktrees and cleans up on process exit.

## 10. Two pip dependencies only

`httpx` and `websockets`. Both are widely used, actively maintained, and have minimal transitive dependencies. No framework bloat.

## 11. Research content is context only

Web search results and extracted content are injected as informational context for agents. They are never executed as code or commands.

## 12. Knowledge base is user-editable

Users can view, add, edit, and delete any knowledge base item via the CLI (`forge memory`) or the browser dashboard. The system never overrides user edits.

## 13. Confidence decay

Knowledge items that are not reinforced by successful use lose confidence over time. Items below 0.2 confidence or unused for 90 days are automatically pruned. This prevents stale or incorrect knowledge from accumulating.

## 14. Source tracking

Every knowledge item records its origin: session ID (for items learned during execution), URL (for items from web research), "user" (for manually added items), or "claude-memory" (for items imported from Claude Code auto-memory).

## 15. No external memory services

All data is stored locally in `.forge/forge.db`. No cloud APIs, no external databases, no third-party memory services.

## 16. .forge/ is gitignored

`forge init` adds `.forge/` to `.gitignore`. The knowledge base, execution history, and routing patterns stay local to the developer and are never committed to the repository.

## 17. Evaluator isolation

The evaluator never runs in the same worktree as the generator. Evaluation is read-only against the git diff. The evaluator cannot modify the generator's output.
