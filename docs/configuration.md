# Configuration

All configuration via environment variables with sensible defaults.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `LOCAL_CODE_MODEL` | `qwen3:8b` | Model for local code tasks |
| `LOCAL_GENERAL_MODEL` | `llama3.2` | Model for general local tasks |
| `LOCAL_CLASSIFY_MODEL` | `qwen3:8b` | Model for task classification |
| `CLAUDE_CODE_PATH` | `claude` | Path to Claude Code CLI |
| `MAX_PARALLEL_AGENTS` | `5` | Maximum concurrent worktrees/agents |
| `TASK_TIMEOUT_SECONDS` | `300` | Timeout per task execution |
| `MAX_REVISIONS` | `2` | Max evaluator revision cycles |
| `SESSION_BUDGET_USD` | `5.00` | Hard spend cap per session |
| `WS_PORT` | `9111` | WebSocket server port |
| `FORGE_DB_PATH` | `.forge/forge.db` | SQLite database path |

## Notes

- `WS_HOST` is hardcoded to `127.0.0.1` and cannot be changed (security requirement).
- Ollama models must be pulled locally before use (`ollama pull qwen3:8b`).
- `ANTHROPIC_API_KEY` is required only for the batch executor (optional).
- Claude Code CLI authentication uses its own credential store.

## Model Cost Rates (per 1M tokens)

| Model | Input | Output |
|-------|-------|--------|
| opus | $15.00 | $75.00 |
| sonnet | $3.00 | $15.00 |
| haiku | $0.80 | $4.00 |
| ollama | $0.00 | $0.00 |
