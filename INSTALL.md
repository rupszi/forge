# Installing Forge

Detailed install guide. For the quick path, see [README.md](README.md#quickstart--one-shot-install).

## Supported environments

| OS | Status | Notes |
|---|---|---|
| **macOS 13+ (Apple Silicon)** | ✅ Primary target | M3 Pro / M4 Pro / M4 Max |
| macOS 13+ (Intel) | ⚠️ Slow | 5–15 s/token on Intel; planner-only realistic |
| **Ubuntu 22.04+ / Debian 12+** | ✅ Supported | apt-based; works on x86_64 and ARM |
| Fedora 39+ | ✅ Supported | dnf-based |
| Arch / Manjaro | ✅ Supported | pacman-based |
| **WSL2 (Windows)** | ✅ Supported | Use the WSL filesystem, not /mnt/c |
| Native Windows | ❌ Not supported | Use WSL2 |

## Hardware floor

| Resource | Minimum | Recommended | Notes |
|---|---|---|---|
| **RAM** | 16 GB | 24 GB+ | Below 16 GB the install script refuses |
| **Free disk** | 30 GB | 120 GB | Default 5 models = ~93 GB |
| **CPU** | Apple Silicon or x86_64 | Apple Silicon / RTX 4090 | Intel Mac functionally too slow |
| **GPU** (Linux) | Optional | NVIDIA with CUDA | vLLM endpoint via `OPENAI_BASE_URL` |
| **Python** | 3.10 | 3.11+ | Install via `uv`, `pyenv`, or distro package |
| **Git** | any recent | latest | Required for worktree isolation |

## One-shot install

```bash
cd ~/projects/my-webapp                      # YOUR existing project, not Forge's source
bash install.sh                              # interactive
```

What runs (9 phases):

1. **Privacy banner + anti-corruption contract** — explicit list of what Forge will and won't write
2. **Refuse-to-run gates** — won't run as root, won't install in `$HOME`, won't clobber a `.forge/` owned by another user
3. **OS + Python + git detection**
4. **Hardware preflight** — RAM, disk, GPU
5. **Network preflight** — DNS resolution to ollama.com / pypi.org / github.com
6. **Ollama install + start** — `brew` on macOS, official script on Linux; offers to install if missing; starts the daemon if not running
7. **Model presence check** — lists required models with sizes; offers `all / select / none` for downloads
8. **Forge install** — `uv` (preferred) or pip fallback; optional extras prompt; symlink to `~/.local/bin/forge`
9. **`.gitignore` + `forge doctor` validation**

Re-running is **idempotent** — only does what's missing.

## Modes

```bash
bash install.sh                # interactive
bash install.sh --check        # dry-run; verify environment, change nothing
bash install.sh --yes          # non-interactive; accept all defaults (CI / Docker)
bash install.sh upgrade        # reuse existing .venv, pull latest, run migrations
bash install.sh --help         # show usage
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | User input needed (or aborted) |
| 2 | Hardware / environment gate failed |
| 3 | Network gate failed |
| 4 | Ollama gate failed |
| 5 | Forge install failed |

## Anti-corruption contract — what Forge writes

Forge **only** writes to:
- `.forge/forge.db` — SQLite knowledge base + episodic + procedural + research stores
- `.forge/sessions/<session-id>/trace.jsonl` — append-only audit log per session
- `.forge/worktrees/<sprint-id>/` — isolated git worktree for each sprint
- `.forge/config.toml` — optional user config (only if you opt in via the wizard)
- `.gitignore` — appends one line: `.forge/`

Forge **never** edits:
- Any source file outside an isolated worktree
- `package.json`, `pyproject.toml`, `Cargo.toml`, etc.
- `.claude/settings.json` (read-only)
- `CLAUDE.md` (read-only — Forge can _suggest_ additions, but you accept them)

The agent **can** edit your source code via the generator role — but **only inside an isolated worktree branch** that you review at the merge gate before it touches `main`.

## Privacy verification

Forge sends **zero telemetry**. Verify yourself after install:

```bash
# Should produce 0 lines:
grep -rn 'http://' daemon/ | grep -v localhost | grep -v '127.0.0.1'

# Should produce 0 lines (no calls to remote analytics):
grep -rn 'analytics\|telemetry\|posthog\|datadog\|sentry' daemon/ | grep -v test_

# All HTTP code paths point to user-controlled hosts (Ollama localhost, OpenAI base URL set by you, etc.)
```

The KB lives in `.forge/forge.db`. It never leaves your machine unless you explicitly export it.

## Troubleshooting

### `python3 not found` or wrong version

Install via `uv` (recommended) or `pyenv`:

```bash
# uv (fastest)
curl -LsSf https://astral.sh/uv/install.sh | sh

# pyenv
curl https://pyenv.run | bash
pyenv install 3.12
pyenv local 3.12
```

### Ollama daemon won't start

```bash
# Check if it's running
curl http://localhost:11434/api/tags

# Start manually
ollama serve

# On macOS, set up as a service:
brew services start ollama

# On Linux with systemd:
sudo systemctl enable --now ollama
```

### Model pull fails midway

Ollama's `pull` is resume-friendly. Re-run:

```bash
ollama pull qwen3-coder-next
```

### Out of disk during pull

The default 5 models = ~93 GB. Free up space, or skip the heavyweight tier:

```bash
# Skip qwen3-coder-next (50 GB MoE) — Forge will fall back to qwen3.6:27b
ollama pull gpt-oss:20b
ollama pull qwen3.6:27b
ollama pull deepseek-v4-flash
ollama pull nomic-embed-text
```

### `forge doctor` fails

Re-run with verbose:

```bash
.venv/bin/forge doctor --verbose
```

Common issues:

- **`Ollama not responding`** — start it with `ollama serve`
- **`Claude Code CLI not found`** — install via `npm install -g @anthropic-ai/claude-code` (only needed for `claude_code` executor; Ollama-only is fine without it)
- **`MCP server X not configured`** — check `.claude/settings.json`; not a hard error
- **`Knowledge base locked`** — kill any stale `forge serve` process: `pkill -f "forge serve"`

### Behind a corporate proxy

```bash
export HTTPS_PROXY=http://your-proxy:8080
export HTTP_PROXY=http://your-proxy:8080
export NO_PROXY=localhost,127.0.0.1
bash install.sh
```

### Air-gapped install

Forge itself has only two pip dependencies (`httpx`, `websockets`). Pre-download:

```bash
# On a connected machine:
pip download httpx websockets -d ./forge-deps/
# Pull all required Ollama models with: ollama pull <each>
# Export models: copy ~/.ollama/models to USB

# On the air-gapped machine:
pip install --no-index --find-links ./forge-deps/ httpx websockets
# Restore models to ~/.ollama/models
ollama list  # verify
```

## Updating

```bash
bash install.sh upgrade      # reuses .venv, pulls latest from git, re-installs
```

If the install was via `git clone`:

```bash
cd /path/to/forge
git pull
bash install.sh upgrade
```

## Uninstalling

```bash
bash uninstall.sh                  # remove .venv + symlink, KEEP your KB
bash uninstall.sh --with-data      # also remove .forge/ (KB, traces, worktrees)
bash uninstall.sh --models         # also remove all Ollama models Forge installed
bash uninstall.sh --all            # everything (--with-data + --models)
bash uninstall.sh --check          # dry-run
```

The default never touches `.forge/forge.db` so your accumulated knowledge survives.

## Manual install (if `install.sh` fails)

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &  # background

# 2. Pull models
for m in gpt-oss:20b qwen3-coder-next qwen3.6:27b deepseek-v4-flash nomic-embed-text; do
  ollama pull "$m"
done

# 3. Set up venv + Forge
python3 -m venv .venv
.venv/bin/pip install -e .

# 4. Optional: extras
.venv/bin/pip install -e '.[robust,batch,vector,mcp]'

# 5. Add to .gitignore
echo ".forge/" >> .gitignore

# 6. Validate
.venv/bin/forge doctor

# 7. Initialize the project
.venv/bin/forge init
```

## Docker fallback

For users who prefer a container:

```bash
docker compose up   # starts Forge daemon + UI + Ollama in one shot
```

See [docker-compose.yml](docker-compose.yml). Mounts your project as `/workspace`; Ollama models live in a named volume so they persist across container rebuilds.

## What gets logged where

| File | Purpose | Persisted? |
|---|---|---|
| `/tmp/forge-install-<timestamp>.log` | Install script output | until reboot |
| `.forge/forge.log` | Daemon log (with credential redaction) | yes |
| `.forge/sessions/<id>/trace.jsonl` | Per-session audit log (append-only, redacted) | yes |
| `.forge/forge.db` | SQLite KB + episodic + procedural + research | yes |
| `.forge/worktrees/<id>/` | Isolated worktree per sprint | until you remove |

## Next steps

- `forge init` — scan your project, build the context window
- `forge plan "your objective"` — get a sprint breakdown
- `forge serve` — open the browser dashboard
- See [docs/CONNECTORS.md](docs/CONNECTORS.md) to wire up GitHub / Vercel / Supabase / etc.
