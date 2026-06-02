"""All configuration via environment variables with sensible defaults.

Forge follows a strict no-magic-config rule: every knob is here, every knob
has an env-var override, and the default is documented inline. See
docs/DECISIONS.md and docs/ENGINEERING_STANDARDS.md for the rationale behind
specific defaults (especially model lineup — see ADR-003).
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env var. Accepts 1/true/yes/on (case-insensitive)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ---- Forge Studio: locality + local resource budgets ----
#
# Forge Studio is local-first and free by default. Cloud executors (claude_code,
# the Anthropic batch endpoint, any API-key path) are gated behind an explicit
# opt-in so the default path never dials out (guardrail G-LOC-1/G-LOC-2). The
# module-level constants are import-time snapshots for cheap reads; the
# ``*()`` helpers re-read the environment live so callers (and tests) see
# changes without reimporting.
CLOUD_ENABLED = _env_bool("FORGE_CLOUD_ENABLED", False)

# Model-pool RAM budget (GB). On a 48 GB Apple Silicon machine the default
# leaves ~12 GB for the OS, the daemon, and (later) ComfyUI (guardrail
# G-RAM-1). The pool evicts LRU non-pinned models before exceeding this.
LOCAL_RAM_BUDGET_GB = _env_float("FORGE_LOCAL_RAM_BUDGET_GB", 36.0)

# Disk headroom (GB) that ``forge models pull`` must preserve. It refuses a
# download that would leave less than this free (guardrail G-RAM-2).
MODEL_DISK_HEADROOM_GB = _env_float("FORGE_MODEL_DISK_HEADROOM_GB", 10.0)


def cloud_enabled() -> bool:
    """True only when the user has explicitly opted into cloud models.

    Every cloud executor selection routes through this. Default is False so a
    fresh install makes zero outbound inference calls.
    """
    return _env_bool("FORGE_CLOUD_ENABLED", False)


def local_ram_budget_gb() -> float:
    """Live read of the model-pool RAM budget in GB."""
    return _env_float("FORGE_LOCAL_RAM_BUDGET_GB", 36.0)


def model_disk_headroom_gb() -> float:
    """Live read of the disk headroom (GB) preserved by ``forge models pull``."""
    return _env_float("FORGE_MODEL_DISK_HEADROOM_GB", 10.0)


# ---- Ollama ----
# Ollama is Forge's primary local-model backend. Runs on the user's machine,
# free, fast on Apple Silicon. Set OLLAMA_BASE_URL if Ollama is on a remote
# host or non-default port.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# ---- Model defaults (see ADR-003) ----
#
# As of 2026-04-30, the open-weight SWE-bench Verified ceiling moved from
# ~72% (Devstral-Medium) to ~80%+ (MiniMax M2.5, DeepSeek V4-Flash). The
# defaults below reflect the April-22/23 releases. Update when the leaderboard
# meaningfully shifts; revisit each release.
#
# All defaults are Apache 2.0 / MIT — no commercial-license traps.

# Planner — small reasoner with native tool-call support. gpt-oss:20b is
# OpenAI's open-weight release; Apache 2.0; ~14 GB; native function calling
# via the harmony format. Configurable reasoning effort (low/medium/high).
LOCAL_PLAN_MODEL = os.environ.get("LOCAL_PLAN_MODEL", "gpt-oss:20b")

# Cheap-tier generator — fast, MoE for low active-param footprint.
# Qwen3-Coder-Next is 3B-active / 80B MoE, Apache 2.0, 256K context, native
# tool-call via Hermes parser. Best price/perf for routine sprints.
LOCAL_CODE_MODEL = os.environ.get("LOCAL_CODE_MODEL", "qwen3-coder-next")

# Medium-tier generator — dense 27B for harder tasks. Qwen3.6-27B (Apr 22 2026)
# advertises "flagship-level agentic coding"; Apache 2.0; ~16 GB at Q4.
LOCAL_MID_MODEL = os.environ.get("LOCAL_MID_MODEL", "qwen3.6:27b")

# Premium-tier generator — DeepSeek V4-Flash (Apr 23 2026) has the highest
# open-weight SWE-bench Verified score (~79%); MIT license; 13B active.
LOCAL_PREMIUM_MODEL = os.environ.get("LOCAL_PREMIUM_MODEL", "deepseek-v4-flash")

# Backup medium-tier — Devstral-Small-2507 is OpenHands-validated at 53.6%
# SWE-bench Verified; Apache 2.0; useful when Qwen3.6 isn't available locally.
LOCAL_BACKUP_MID_MODEL = os.environ.get("LOCAL_BACKUP_MID_MODEL", "devstral-small-2507")

# Reasoner (no tools) — DeepSeek-R1 distill is good for hard reasoning passes
# (planner with-thinking, hard-debug research) but is documented as "reluctant
# to call tools." Use for non-tool reasoning steps only.
LOCAL_REASONER_MODEL = os.environ.get("LOCAL_REASONER_MODEL", "deepseek-r1-distill-qwen-32b")

# Embeddings (for the optional sqlite-vec episodic recall, ADR-012). Small,
# fast, Apache 2.0.
LOCAL_EMBED_MODEL = os.environ.get("LOCAL_EMBED_MODEL", "nomic-embed-text")

# Classifier — uses the same small model as the planner for cost. Could be
# pointed at a tiny dedicated model in the future.
LOCAL_CLASSIFY_MODEL = os.environ.get("LOCAL_CLASSIFY_MODEL", "gpt-oss:20b")

# Legacy alias for backwards compatibility with code/tests written before the
# Phase 1 model bump. Will be deprecated after Phase 1 Week 4 stabilizes.
LOCAL_GENERAL_MODEL = os.environ.get("LOCAL_GENERAL_MODEL", LOCAL_MID_MODEL)


# ---- Model family registry (see ADR-003 / ADR-006) ----
#
# The classifier uses this to enforce the cross-family-evaluator invariant:
# the evaluator must run on a model from a different family than the generator.
# The harness research (Anthropic) and MT-Bench self-bias data both support
# this: same-family evaluators share blind spots and rate their own work too
# generously.
#
# Match is prefix-based and case-insensitive. The first match wins. Add new
# families here when new model lineages launch (e.g., a future "kimi" or
# "minimax" line).
MODEL_FAMILIES: dict[str, str] = {
    # Anthropic — closed
    "claude-": "anthropic",
    "opus": "anthropic",
    "sonnet": "anthropic",
    "haiku": "anthropic",
    # OpenAI — closed and open-weight
    "gpt-oss": "openai",  # open-weight
    "gpt-4": "openai",
    "gpt-5": "openai",
    "gpt-6": "openai",
    "o1-": "openai",
    "o3-": "openai",
    # Qwen line — Alibaba; covers Qwen2.5, Qwen3, Qwen3-Coder, Qwen3.6
    "qwen": "qwen",
    # Mistral line — covers Mistral, Devstral, Codestral
    "mistral": "mistral",
    "devstral": "mistral",
    "codestral": "mistral",
    # DeepSeek
    "deepseek": "deepseek",
    # Meta Llama
    "llama-": "llama",
    "llama3": "llama",
    "llama4": "llama",
    "meta-llama": "llama",
    # IBM Granite
    "granite": "granite",
    # Zhipu / GLM
    "glm-": "zhipu",
    "glm4": "zhipu",
    "glm5": "zhipu",
    # MiniMax
    "minimax": "minimax",
    # Moonshot Kimi
    "kimi": "moonshot",
    # Hugging Face SmolLM
    "smol": "hf",
}


def model_family(model: str) -> str:
    """Return the family identifier for a model name.

    Matches the longest prefix in ``MODEL_FAMILIES``; falls back to "unknown"
    when no prefix matches. The classifier uses this to ensure the evaluator
    runs on a different family than the generator (ADR-006).
    """
    m = model.lower().strip()
    # Sort prefixes longest-first so e.g. "llama3" beats "llama-"
    for prefix in sorted(MODEL_FAMILIES.keys(), key=len, reverse=True):
        if m.startswith(prefix):
            return MODEL_FAMILIES[prefix]
    return "unknown"


# ---- Claude Code CLI ----
CLAUDE_CODE_PATH = os.environ.get("CLAUDE_CODE_PATH", "claude")

# ---- Execution ----
MAX_PARALLEL_AGENTS = int(os.environ.get("MAX_PARALLEL_AGENTS", "5"))
TASK_TIMEOUT_SECONDS = int(os.environ.get("TASK_TIMEOUT_SECONDS", "300"))
MAX_REVISIONS = int(os.environ.get("MAX_REVISIONS", "2"))

# ---- Budget ----
SESSION_BUDGET_USD = float(os.environ.get("SESSION_BUDGET_USD", "5.00"))

# ---- WebSocket — 127.0.0.1 ONLY, never 0.0.0.0 (security requirement) ----
# Hardcoded by ADR-007. Do not make this configurable; binding to a non-loopback
# address turns Forge into a remote code execution surface.
WS_HOST = "127.0.0.1"
WS_PORT = int(os.environ.get("WS_PORT", "9111"))

# ---- Persistence ----
FORGE_DIR = ".forge"
DB_PATH = os.environ.get("FORGE_DB_PATH", os.path.join(FORGE_DIR, "forge.db"))

# ---- Knowledge base limits (ADR-012) ----
KB_MAX_ITEMS = 200  # 200-item cap forces curation quality over retrieval algo
KB_MIN_CONFIDENCE = 0.2
KB_MAX_AGE_DAYS = 90
KB_MAX_CONTEXT_ITEMS = 5
KB_MAX_CONTEXT_TOKENS = 500

# ---- Input sanitization ----
MAX_TASK_DESCRIPTION_LENGTH = 10000
MAX_DIFF_LENGTH = 12000
WORKTREE_NAME_PATTERN = r"^[a-zA-Z0-9\-]+$"

# ---- Per-model context-window limits (Phase 1 Week 3) ----
#
# Used by ``daemon/agents/generator.py`` to size the prompt before dispatch.
# Forge enforces an 80% input / 20% output split so the model has room to
# emit a meaningful response. When the assembled prompt would exceed 80% of
# the window, generator.py trims the stable prefix (memory + repomap) first,
# preserving the task description and revision feedback.
#
# Numbers reflect the model's *advertised* native context. Some models can
# extend further via YaRN / RoPE scaling but those modes degrade quality;
# we use the conservative native window by default. Users can override via
# ``MODEL_CONTEXT_LIMITS_OVERRIDE`` JSON env var if they need to push it.
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # Anthropic
    "opus": 200_000,
    "sonnet": 200_000,
    "haiku": 200_000,
    "claude-opus-4-7": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-sonnet-4-7": 200_000,
    # OpenAI open-weight
    "gpt-oss:20b": 32_000,
    "gpt-oss:120b": 32_000,
    # Qwen line — long-context champions
    "qwen3-coder-next": 256_000,
    "qwen3.6:27b": 128_000,
    "qwen3-coder:30b": 256_000,
    "qwen3-coder:480b": 256_000,
    "qwen2.5-coder-32b": 32_000,
    # Mistral / Devstral
    "devstral-small-2507": 128_000,
    "devstral-small-2505": 128_000,
    "mistral-large-2411": 128_000,
    "codestral-22b": 32_000,
    # DeepSeek
    "deepseek-v4-flash": 128_000,
    "deepseek-v3": 128_000,
    "deepseek-r1": 128_000,
    "deepseek-r1-distill-qwen-32b": 128_000,
    "deepseek-coder-v2": 128_000,
    # Llama
    "llama-3.3-70b-instruct": 128_000,
    "llama-4-scout": 10_000_000,  # Scout's headline 10M context
    "llama-4-maverick": 1_000_000,
    # Granite
    "granite3.3:8b": 128_000,
    "granite-code-34b": 8_000,
    # Other
    "minimax-m2.5": 1_000_000,
    "kimi-k2": 200_000,
}


# ---- Cost per 1M tokens (USD) — used for budget estimation ----
# Open-weight defaults are 0.0 for self-hosted; users with a paid endpoint
# (OpenRouter / Together / Anthropic API) should override per-call via the
# executor's ``cost_per_million_in`` / ``cost_per_million_out`` parameters.
MODEL_COSTS = {
    # Anthropic
    "opus": {"input": 15.0, "output": 75.0},
    "sonnet": {"input": 3.0, "output": 15.0},
    "haiku": {"input": 0.80, "output": 4.0},
    # Self-hosted open-weight — no marginal cost
    "ollama": {"input": 0.0, "output": 0.0},
    "qwen3-coder-next": {"input": 0.0, "output": 0.0},
    "qwen3.6:27b": {"input": 0.0, "output": 0.0},
    "deepseek-v4-flash": {"input": 0.0, "output": 0.0},
    "devstral-small-2507": {"input": 0.0, "output": 0.0},
    "gpt-oss:20b": {"input": 0.0, "output": 0.0},
}
