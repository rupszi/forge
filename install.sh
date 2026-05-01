#!/usr/bin/env bash
# Forge — one-shot installer for macOS and Linux.
#
# Run from your project's root directory:
#     curl -fsSL https://raw.githubusercontent.com/<org>/forge/main/install.sh -o install.sh
#     bash install.sh
#
# Or from a clone:
#     bash install.sh
#
# Modes:
#     bash install.sh             interactive install (default)
#     bash install.sh --check     dry-run; verify environment, change nothing
#     bash install.sh --yes       non-interactive; accept all defaults (CI / Docker)
#     bash install.sh upgrade     reuse existing venv, pull latest, run migrations
#
# Exit codes:
#     0  ok
#     1  user input needed
#     2  hardware / environment gate failed
#     3  network gate failed
#     4  ollama gate failed
#     5  forge install failed

set -euo pipefail
IFS=$'\n\t'

# ──────────────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────────────

readonly FORGE_VERSION="0.1.0-alpha"
readonly LOG_DIR="/tmp"
readonly LOG_FILE="${LOG_DIR}/forge-install-$(date +%Y%m%d-%H%M%S).log"
readonly MIN_RAM_GB=16
readonly RECOMMENDED_RAM_GB=24
readonly MIN_DISK_GB=120  # Default 5 models = ~93 GB; 120 GB safety margin
readonly MIN_PYTHON="3.10"
readonly OLLAMA_HOST="${OLLAMA_BASE_URL:-http://localhost:11434}"

# Default models — keep in sync with daemon/config.py
readonly REQUIRED_MODELS=(
  "gpt-oss:20b|14|planner"
  "qwen3-coder-next|50|cheap-tier generator (MoE; first download is large)"
  "qwen3.6:27b|16|medium-tier generator"
  "deepseek-v4-flash|13|premium-tier generator"
  "nomic-embed-text|0.3|episodic vector recall"
)

readonly OPTIONAL_EXTRAS=(
  "robust|BAML tolerant JSON parser for messy open-weight outputs"
  "batch|Anthropic batch API executor (50% cheaper, higher latency)"
  "vector|sqlite-vec for episodic vector recall"
  "mcp|KB-as-MCP server (export KB to other agents)"
)

# ──────────────────────────────────────────────────────────────────────
#  Color / logging
# ──────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && [[ "${TERM:-}" != "dumb" ]]; then
  readonly C_RESET="\033[0m"
  readonly C_BOLD="\033[1m"
  readonly C_DIM="\033[2m"
  readonly C_RED="\033[31m"
  readonly C_GREEN="\033[32m"
  readonly C_YELLOW="\033[33m"
  readonly C_BLUE="\033[34m"
  readonly C_MAGENTA="\033[35m"
  readonly C_CYAN="\033[36m"
else
  readonly C_RESET="" C_BOLD="" C_DIM="" C_RED="" C_GREEN="" C_YELLOW="" C_BLUE="" C_MAGENTA="" C_CYAN=""
fi

log()  { printf '%s\n' "$*" | tee -a "$LOG_FILE"; }
info() { printf "${C_CYAN}ℹ${C_RESET}  %s\n" "$*" | tee -a "$LOG_FILE"; }
ok()   { printf "${C_GREEN}✓${C_RESET}  %s\n" "$*" | tee -a "$LOG_FILE"; }
warn() { printf "${C_YELLOW}⚠${C_RESET}  %s\n" "$*" | tee -a "$LOG_FILE" >&2; }
err()  { printf "${C_RED}✗${C_RESET}  %s\n" "$*" | tee -a "$LOG_FILE" >&2; }
die()  { err "$*"; exit "${2:-1}"; }
header() {
  printf "\n${C_BOLD}${C_BLUE}━━ %s ━━${C_RESET}\n" "$*" | tee -a "$LOG_FILE"
}
ask() {
  local prompt="$1" default="${2:-}" answer
  if [[ "$NON_INTERACTIVE" == "1" ]]; then
    printf '%s' "$default"; return 0
  fi
  if [[ -n "$default" ]]; then
    printf "${C_YELLOW}?${C_RESET} %s [%s]: " "$prompt" "$default" >&2
  else
    printf "${C_YELLOW}?${C_RESET} %s: " "$prompt" >&2
  fi
  read -r answer || true
  printf '%s' "${answer:-$default}"
}
confirm() {
  local prompt="$1" default="${2:-Y}"
  local response
  response="$(ask "$prompt (Y/n)" "$default")"
  [[ "$response" =~ ^[Yy] ]]
}

# ──────────────────────────────────────────────────────────────────────
#  Mode parsing
# ──────────────────────────────────────────────────────────────────────

CHECK_ONLY=0
NON_INTERACTIVE=0
UPGRADE=0

for arg in "$@"; do
  case "$arg" in
    --check)   CHECK_ONLY=1 ;;
    --yes|-y)  NON_INTERACTIVE=1 ;;
    upgrade)   UPGRADE=1 ;;
    --help|-h)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) die "Unknown argument: $arg. Run with --help." 1 ;;
  esac
done

# ──────────────────────────────────────────────────────────────────────
#  0. Privacy banner + anti-corruption contract
# ──────────────────────────────────────────────────────────────────────

cat <<'BANNER'

  ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
  ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
  █████╗  ██║   ██║██████╔╝██║  ███╗█████╗
  ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
  ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
  ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝

  Multi-agent coding orchestrator. MIT. Local-first. No telemetry.

BANNER

cat <<'CONTRACT'
  Anti-corruption contract — what Forge does to your project:

    ✓ Writes to .forge/ ONLY (db, traces, worktrees go here)
    ✓ Appends ONE line to .gitignore (.forge/) — never edits anything else
    ✓ Worktrees live under .forge/worktrees/ — never mixed with your source
    ✓ The agent CAN edit your source code via the generator,
      but only inside an isolated worktree branch you review before merge
    ✓ No background daemons survive Ctrl-C
    ✓ No telemetry, no signup, no API key required for local-only operation
    ✓ Verifiable: grep -rn 'http://' daemon/ | grep -v localhost = 0 matches

CONTRACT

if [[ "$NON_INTERACTIVE" != "1" ]] && [[ "$CHECK_ONLY" != "1" ]]; then
  printf "  Press Enter to continue, Ctrl-C to abort." >&2
  read -r _ || die "Aborted." 1
  printf '\n'
fi

info "Install log: $LOG_FILE"

# ──────────────────────────────────────────────────────────────────────
#  1. Refuse-to-run preflight
# ──────────────────────────────────────────────────────────────────────

header "1/9  Preflight"

# Refuse root
if [[ "$EUID" -eq 0 ]]; then
  die "Refuse to run as root. Forge installs into a venv; sudo is a footgun." 2
fi

# Refuse if pwd == $HOME
if [[ "$PWD" == "$HOME" ]]; then
  die "Refusing to install in \$HOME directly. Run from a project directory." 2
fi

# Refuse if no git repo (Forge needs git for worktrees)
if [[ ! -d .git ]] && [[ ! -f .git ]]; then
  warn "Not a git repo. Forge requires git for worktree isolation."
  if ! confirm "Initialize git repo here?" "N"; then
    die "Cannot proceed without git." 2
  fi
  git init -q
  ok "Initialized empty git repo"
fi

# Detect existing .forge owned by another user
if [[ -d .forge ]]; then
  local_owner="$(stat -c '%U' .forge 2>/dev/null || stat -f '%Su' .forge 2>/dev/null || echo "?")"
  if [[ "$local_owner" != "$(id -un)" ]] && [[ "$local_owner" != "?" ]]; then
    die ".forge/ exists and is owned by '$local_owner', not '$(id -un)'. Refusing to clobber." 2
  fi
fi

ok "Refuse-to-run gates passed"

# ──────────────────────────────────────────────────────────────────────
#  2. OS + arch detection
# ──────────────────────────────────────────────────────────────────────

header "2/9  Environment"

OS_KIND=""
DISTRO=""
ARCH="$(uname -m)"

case "$(uname -s)" in
  Darwin)
    OS_KIND="macos"
    if [[ "$ARCH" != "arm64" ]]; then
      warn "Intel Mac detected. Open-weight tier requires Apple Silicon."
      warn "You can still install but expect 5-15 s/token on Intel."
      if ! confirm "Continue anyway?" "N"; then
        die "Aborted on Intel Mac." 2
      fi
    fi
    ;;
  Linux)
    OS_KIND="linux"
    if [[ -f /etc/os-release ]]; then
      # shellcheck disable=SC1091
      . /etc/os-release
      DISTRO="$ID"
    fi
    if grep -qi microsoft /proc/version 2>/dev/null; then
      OS_KIND="wsl"
      warn "WSL detected — Forge works but expect:"
      warn "  - Slower file I/O on /mnt/c (use the WSL filesystem)"
      warn "  - Clock-skew issues if Windows time drifts (sudo hwclock -s)"
    fi
    ;;
  *)
    die "Unsupported OS: $(uname -s). Forge supports macOS and Linux." 2
    ;;
esac

ok "OS: $OS_KIND${DISTRO:+ ($DISTRO)} on $ARCH"

# Python check
if ! command -v python3 >/dev/null 2>&1; then
  die "python3 not found. Install Python ${MIN_PYTHON}+ first." 2
fi

py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
py_major="${py_ver%%.*}"
py_minor="${py_ver##*.}"
if [[ "$py_major" -lt 3 ]] || { [[ "$py_major" -eq 3 ]] && [[ "$py_minor" -lt 10 ]]; }; then
  err "Python ${py_ver} found; ${MIN_PYTHON}+ required."
  cat >&2 <<EOM

  Three quick fixes (pick one — Option 3 is the safest):

    Option 1 — homebrew global symlink (fastest; touches /opt/homebrew)
      brew install python@3.12
      brew link --force --overwrite python@3.12

    Option 2 — alias only (no filesystem changes; affects interactive shells)
      brew install python@3.12
      echo 'alias python3=python3.12' >> ~/.zshrc
      echo 'alias python=python3.12' >> ~/.zshrc
      source ~/.zshrc

    Option 3 — local symlink (recommended; reversible, no system pollution)
      brew install python@3.12
      mkdir -p ~/.local/bin
      ln -sf "\$(brew --prefix python@3.12)/bin/python3.12" ~/.local/bin/python3
      ln -sf "\$(brew --prefix python@3.12)/bin/python3.12" ~/.local/bin/python
      echo 'export PATH="\$HOME/.local/bin:\$PATH"' >> ~/.zshrc
      source ~/.zshrc

  Then re-run: bash install.sh

EOM
  exit 2
fi
ok "Python: $py_ver"

# Git check
if ! command -v git >/dev/null 2>&1; then
  die "git not found. Forge requires git for worktree isolation." 2
fi
ok "git: $(git --version | head -1)"

# ──────────────────────────────────────────────────────────────────────
#  3. Hardware preflight
# ──────────────────────────────────────────────────────────────────────

header "3/9  Hardware"

# RAM detection
ram_gb=0
case "$OS_KIND" in
  macos)
    ram_bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
    ram_gb=$(( ram_bytes / 1024 / 1024 / 1024 ))
    ;;
  linux|wsl)
    ram_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
    ram_gb=$(( ram_kb / 1024 / 1024 ))
    ;;
esac

if [[ "$ram_gb" -lt "$MIN_RAM_GB" ]]; then
  err "RAM: ${ram_gb} GB — below minimum ${MIN_RAM_GB} GB."
  err "Forge cannot run the open-weight tier here. Try OpenCode or Continue.dev."
  exit 2
elif [[ "$ram_gb" -lt "$RECOMMENDED_RAM_GB" ]]; then
  warn "RAM: ${ram_gb} GB — below recommended ${RECOMMENDED_RAM_GB} GB."
  warn "Planner runs locally; generation needs an API key (Anthropic/OpenAI)."
else
  ok "RAM: ${ram_gb} GB (recommended tier)"
fi

# Disk space
disk_avail_gb=0
case "$OS_KIND" in
  macos)
    disk_avail_gb=$(df -g . 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)
    ;;
  linux|wsl)
    disk_avail_gb=$(df -BG . 2>/dev/null | awk 'NR==2 {gsub(/G/,"",$4); print $4}' || echo 0)
    ;;
esac

if [[ "$disk_avail_gb" -lt "$MIN_DISK_GB" ]]; then
  warn "Disk free: ${disk_avail_gb} GB — below ${MIN_DISK_GB} GB."
  warn "You may not have room for all default models (~93 GB)."
  if ! confirm "Continue anyway?" "N"; then
    die "Aborted on insufficient disk." 2
  fi
else
  ok "Disk free: ${disk_avail_gb} GB"
fi

# GPU detection (Linux only — Mac uses Metal automatically)
if [[ "$OS_KIND" == "linux" ]] || [[ "$OS_KIND" == "wsl" ]]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    gpu_info="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1 || true)"
    if [[ -n "$gpu_info" ]]; then
      ok "GPU: $gpu_info"
      info "Tip: set OPENAI_BASE_URL to a vLLM endpoint for prefix caching"
    fi
  else
    info "No CUDA GPU detected — Ollama will use CPU"
  fi
fi

# ──────────────────────────────────────────────────────────────────────
#  4. Network preflight
# ──────────────────────────────────────────────────────────────────────

header "4/9  Network"

network_check() {
  local host="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --max-time 5 -o /dev/null "https://${host}" 2>/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -q --timeout=5 -O /dev/null "https://${host}" 2>/dev/null
  else
    return 1
  fi
}

network_failures=0
for host in ollama.com pypi.org github.com; do
  if network_check "$host"; then
    ok "Reachable: $host"
  else
    err "Unreachable: $host"
    network_failures=$((network_failures + 1))
  fi
done

if [[ "$network_failures" -gt 0 ]]; then
  warn "Network unreachable. Check DNS, corporate proxy, or VPN."
  warn "Set HTTPS_PROXY env var if behind a proxy."
  if ! confirm "Continue anyway? (model pulls will fail)" "N"; then
    exit 3
  fi
fi

# ──────────────────────────────────────────────────────────────────────
#  5. Ollama install + start + model check
# ──────────────────────────────────────────────────────────────────────

header "5/9  Ollama"

install_ollama_macos() {
  if command -v brew >/dev/null 2>&1; then
    info "Installing Ollama via brew…"
    brew install --cask ollama 2>&1 | tee -a "$LOG_FILE"
  else
    info "Downloading Ollama installer for macOS…"
    curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tee -a "$LOG_FILE"
  fi
}

install_ollama_linux() {
  info "Installing Ollama via official script…"
  curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tee -a "$LOG_FILE"
}

if ! command -v ollama >/dev/null 2>&1; then
  warn "Ollama not installed."
  if [[ "$CHECK_ONLY" == "1" ]]; then
    err "Ollama missing (--check mode)"
    exit 4
  fi
  if confirm "Install Ollama now?" "Y"; then
    case "$OS_KIND" in
      macos) install_ollama_macos ;;
      linux|wsl) install_ollama_linux ;;
    esac
  else
    die "Cannot proceed without Ollama. Install manually: https://ollama.com/download" 4
  fi
fi
ok "Ollama: $(ollama --version 2>/dev/null | head -1 || echo 'installed')"

# Check Ollama is running
if ! curl -fsSL --max-time 3 "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
  warn "Ollama daemon not responding at ${OLLAMA_HOST}"
  if [[ "$CHECK_ONLY" == "1" ]]; then exit 4; fi
  if confirm "Start Ollama in the background?" "Y"; then
    ollama serve >/dev/null 2>&1 &
    OLLAMA_PID=$!
    info "Ollama starting (PID $OLLAMA_PID)… waiting up to 10s"
    for _ in $(seq 1 10); do
      sleep 1
      if curl -fsSL --max-time 2 "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
        ok "Ollama responding"
        break
      fi
    done
  else
    die "Cannot proceed without Ollama running. Run 'ollama serve' and re-run." 4
  fi
fi

# Model presence check
header "6/9  Models"

declare -a missing_models=()
declare -a missing_sizes=()
declare -a missing_descs=()
total_missing_gb=0

installed_models="$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || echo '')"

for entry in "${REQUIRED_MODELS[@]}"; do
  IFS='|' read -r model size desc <<< "$entry"
  if echo "$installed_models" | grep -q "^${model}\b"; then
    ok "${model} (${size} GB) ✓ present — ${desc}"
  else
    warn "${model} (${size} GB) ✗ missing — ${desc}"
    missing_models+=("$model")
    missing_sizes+=("$size")
    missing_descs+=("$desc")
    total_missing_gb=$(awk "BEGIN{print $total_missing_gb + $size}")
  fi
done

if [[ ${#missing_models[@]} -gt 0 ]]; then
  log ""
  log "  Missing models will use ~${total_missing_gb} GB total."
  log "  Disk free: ${disk_avail_gb} GB."
  log ""
  if [[ "$CHECK_ONLY" == "1" ]]; then
    err "${#missing_models[@]} model(s) missing (--check mode)"
    exit 4
  fi
  pull_choice="$(ask "Pull missing models? (a=all, s=select, n=none)" "a")"
  case "$pull_choice" in
    a|A)
      for m in "${missing_models[@]}"; do
        info "Pulling $m… (resume-friendly; Ctrl-C is safe)"
        if ! ollama pull "$m" 2>&1 | tee -a "$LOG_FILE"; then
          warn "Failed to pull $m — continuing"
        fi
      done
      ;;
    s|S)
      for i in "${!missing_models[@]}"; do
        if confirm "Pull ${missing_models[$i]} (${missing_sizes[$i]} GB)?" "N"; then
          ollama pull "${missing_models[$i]}" 2>&1 | tee -a "$LOG_FILE" || warn "Pull failed"
        fi
      done
      ;;
    *) info "Skipping model pulls. forge doctor will show what's missing." ;;
  esac
fi

# ──────────────────────────────────────────────────────────────────────
#  7. Forge install
# ──────────────────────────────────────────────────────────────────────

header "7/9  Forge"

if [[ "$CHECK_ONLY" == "1" ]]; then
  ok "Check mode — skipping install steps"
  info "Run without --check to install Forge"
  exit 0
fi

# Use uv when available, fall back to pure pip
if ! command -v uv >/dev/null 2>&1; then
  if confirm "Install uv (recommended workflow tool)?" "Y"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>&1 | tee -a "$LOG_FILE"
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  else
    info "Falling back to python3 -m venv + pip"
  fi
fi

# venv creation / reuse
if [[ -d .venv ]] && [[ "$UPGRADE" != "1" ]]; then
  info ".venv/ exists — reusing"
elif [[ "$UPGRADE" == "1" ]] && [[ -d .venv ]]; then
  info "Upgrade mode — reusing .venv/"
else
  info "Creating .venv/"
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv 2>&1 | tee -a "$LOG_FILE"
  else
    python3 -m venv .venv
  fi
fi

# Install Forge with dev dependencies. The dev extra (pytest / ruff /
# pre-commit / editables / hatch-vcs / hatchling) is required for a
# working contributor checkout. End-users not running tests can pass
# --no-dev to skip; default is "include them" because the cost is small
# and the failure mode (missing pytest after install) is bad UX.
INSTALL_TARGET=".[dev]"
if [[ "${FORGE_NO_DEV:-0}" == "1" ]]; then
  INSTALL_TARGET="."
  info "FORGE_NO_DEV=1 — skipping dev extras"
fi

info "Installing Forge ($INSTALL_TARGET)…"
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -e "$INSTALL_TARGET" 2>&1 | tee -a "$LOG_FILE" || die "Forge install failed" 5
else
  .venv/bin/pip install -e "$INSTALL_TARGET" 2>&1 | tee -a "$LOG_FILE" || die "Forge install failed" 5
fi

# Optional extras
if [[ "$NON_INTERACTIVE" != "1" ]]; then
  log ""
  log "  Optional extras:"
  declare -a chosen_extras=()
  for entry in "${OPTIONAL_EXTRAS[@]}"; do
    IFS='|' read -r extra desc <<< "$entry"
    if confirm "  Install forge[$extra] — $desc?" "N"; then
      chosen_extras+=("$extra")
    fi
  done
  if [[ ${#chosen_extras[@]} -gt 0 ]]; then
    extras_csv="$(IFS=','; echo "${chosen_extras[*]}")"
    info "Installing forge[$extras_csv]…"
    if command -v uv >/dev/null 2>&1; then
      uv pip install --python .venv/bin/python -e ".[${extras_csv}]" 2>&1 | tee -a "$LOG_FILE"
    else
      .venv/bin/pip install -e ".[${extras_csv}]" 2>&1 | tee -a "$LOG_FILE"
    fi
  fi
fi

ok "Forge installed: $(.venv/bin/forge --version 2>/dev/null || echo 'installed')"

# ──────────────────────────────────────────────────────────────────────
#  8. .gitignore + symlink
# ──────────────────────────────────────────────────────────────────────

header "8/9  Project hygiene"

if [[ ! -f .gitignore ]] || ! grep -q '^\.forge/$' .gitignore 2>/dev/null; then
  echo ".forge/" >> .gitignore
  ok "Appended .forge/ to .gitignore"
else
  ok ".gitignore already covers .forge/"
fi

# Symlink to ~/.local/bin if available and on PATH
local_bin="$HOME/.local/bin"
if [[ -d "$local_bin" ]] && echo "$PATH" | tr ':' '\n' | grep -qx "$local_bin"; then
  symlink_path="$local_bin/forge"
  if [[ -L "$symlink_path" ]]; then
    info "Symlink exists: $symlink_path"
  else
    if confirm "Symlink forge → $symlink_path (so 'forge' works anywhere)?" "Y"; then
      ln -sf "$PWD/.venv/bin/forge" "$symlink_path"
      ok "Symlinked $symlink_path"
    fi
  fi
else
  info "Add to PATH (or use full path): $PWD/.venv/bin/forge"
fi

# ──────────────────────────────────────────────────────────────────────
#  9. forge doctor + summary
# ──────────────────────────────────────────────────────────────────────

header "9/9  Validation"

if .venv/bin/forge doctor 2>&1 | tee -a "$LOG_FILE"; then
  ok "forge doctor passed"
else
  warn "forge doctor reported issues — see above"
fi

# ──────────────────────────────────────────────────────────────────────
#  9b. First-run connector wizard
# ──────────────────────────────────────────────────────────────────────

if [[ "$NON_INTERACTIVE" != "1" ]]; then
  log ""
  if confirm "Run the first-run connector setup wizard now?" "Y"; then
    .venv/bin/forge wizard 2>&1 | tee -a "$LOG_FILE" || warn "wizard exited with errors"
  else
    info "Skipped. Run later with: forge wizard"
  fi
fi

# Final summary
header "Summary"

cat <<SUMMARY

  ${C_GREEN}Forge ${FORGE_VERSION} installed.${C_RESET}

  Location:    $PWD/.venv
  Forge dir:   $PWD/.forge      ${C_DIM}(KB, traces, worktrees go here)${C_DIM}
  Log file:    $LOG_FILE
  CLI:         ${C_BOLD}.venv/bin/forge${C_RESET}${local_bin:+ or simply ${C_BOLD}forge${C_RESET}}

  Next steps:
    ${C_CYAN}.venv/bin/forge init${C_RESET}                       Scan project, build context
    ${C_CYAN}.venv/bin/forge plan "Build auth API"${C_RESET}      Decompose into sprints
    ${C_CYAN}.venv/bin/forge serve${C_RESET}                       Start dashboard at localhost:3000

  Privacy verification:
    ${C_DIM}grep -rn 'http://' daemon/ | grep -v localhost${C_RESET}     ${C_GREEN}(should be 0 matches)${C_RESET}

  Documentation:
    INSTALL.md         Detailed install / troubleshooting
    docs/SECURITY.md   Threat model, redaction matrix
    docs/CONNECTORS.md Tool & MCP connector setup
    docs/SKILLS.md     Skills system + sandbox
    README.md          Overview

SUMMARY
