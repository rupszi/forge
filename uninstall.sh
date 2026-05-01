#!/usr/bin/env bash
# Forge uninstaller — removes the venv + symlink. Never touches .forge/ data
# without --with-data.
#
# Usage:
#     bash uninstall.sh                  remove venv + symlink, keep KB
#     bash uninstall.sh --with-data      ALSO remove .forge/ (KB, traces, worktrees)
#     bash uninstall.sh --models         ALSO remove all Forge-default Ollama models
#     bash uninstall.sh --all            everything (--with-data + --models)
#     bash uninstall.sh --check          dry-run

set -euo pipefail

C_RESET="\033[0m"; C_BOLD="\033[1m"; C_RED="\033[31m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"
[[ -t 1 ]] || { C_RESET=""; C_BOLD=""; C_RED=""; C_GREEN=""; C_YELLOW=""; }

WITH_DATA=0; WITH_MODELS=0; CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --with-data) WITH_DATA=1 ;;
    --models)    WITH_MODELS=1 ;;
    --all)       WITH_DATA=1; WITH_MODELS=1 ;;
    --check)     CHECK_ONLY=1 ;;
    *) echo "Unknown: $arg"; exit 1 ;;
  esac
done

confirm() {
  local prompt="$1"
  printf "${C_YELLOW}?${C_RESET} %s (y/N): " "$prompt"
  read -r ans
  [[ "$ans" =~ ^[Yy] ]]
}

echo
echo "${C_BOLD}Forge uninstall${C_RESET}"
echo "==============="
echo

# What will be removed
echo "Will remove:"
echo "  - .venv/                    (Python virtualenv)"
[[ -L "$HOME/.local/bin/forge" ]] && echo "  - $HOME/.local/bin/forge    (symlink)"

if [[ "$WITH_DATA" == "1" ]]; then
  echo "  ${C_RED}- .forge/                   (knowledge base, traces, worktrees)${C_RESET}"
fi

if [[ "$WITH_MODELS" == "1" ]]; then
  echo "  ${C_RED}- Ollama models             (gpt-oss:20b, qwen3-coder-next, qwen3.6:27b, deepseek-v4-flash, nomic-embed-text)${C_RESET}"
fi

echo
echo "Will KEEP:"
[[ "$WITH_DATA" != "1" ]] && echo "  - .forge/                   (your accumulated KB stays)"
[[ "$WITH_MODELS" != "1" ]] && echo "  - Ollama models             (~93 GB stays available)"
echo "  - Source files              (we never edit your project source)"
echo "  - .gitignore                (the .forge/ entry stays)"
echo

if [[ "$CHECK_ONLY" == "1" ]]; then
  echo "${C_GREEN}--check mode: nothing changed.${C_RESET}"
  exit 0
fi

confirm "Proceed?" || { echo "Aborted."; exit 0; }

# Remove venv
if [[ -d .venv ]]; then
  rm -rf .venv
  echo "${C_GREEN}✓${C_RESET} Removed .venv/"
fi

# Remove symlink
if [[ -L "$HOME/.local/bin/forge" ]]; then
  rm -f "$HOME/.local/bin/forge"
  echo "${C_GREEN}✓${C_RESET} Removed symlink"
fi

# Remove .forge/ (only with --with-data)
if [[ "$WITH_DATA" == "1" ]] && [[ -d .forge ]]; then
  if confirm "${C_RED}REALLY remove .forge/? Your knowledge base will be lost.${C_RESET}"; then
    rm -rf .forge
    echo "${C_GREEN}✓${C_RESET} Removed .forge/"
  fi
fi

# Remove Ollama models
if [[ "$WITH_MODELS" == "1" ]]; then
  if command -v ollama >/dev/null 2>&1; then
    for model in gpt-oss:20b qwen3-coder-next qwen3.6:27b deepseek-v4-flash nomic-embed-text; do
      ollama rm "$model" 2>/dev/null && echo "${C_GREEN}✓${C_RESET} Removed model $model" || true
    done
  fi
fi

echo
echo "${C_GREEN}Forge uninstalled.${C_RESET}"
echo "Logs from past sessions (if any) are at: /tmp/forge-install-*.log"
