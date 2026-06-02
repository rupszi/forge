"""Context-window (``num_ctx``) sizing — presets, RAM-safe ceiling, resolution.

The model's context window is how many tokens it attends to in one call. Two
ceilings bound it: the model's *trained* max, and the RAM left for the KV cache
after the model weights load. This module computes both, offers a preset list
for the UI dropdown, and resolves the user's choice (or "auto") into a concrete
``num_ctx`` that the Ollama executor receives.

KV-cache cost is estimated, not exact (it varies by architecture / GQA / cache
quantization). The estimate is deliberately conservative so "auto" won't push
the machine into swap.
"""

from __future__ import annotations

from .config import MODEL_CONTEXT_LIMITS, local_ram_budget_gb

# Dropdown presets (tokens). The large ones (256K–2M) only become selectable
# for models whose trained max reaches them AND when RAM allows — otherwise the
# UI shows them disabled with the reason. Useful for long-context models
# (Llama-4, MiniMax, Kimi) and cloud / big-GPU setups.
PRESETS = [
    4096,
    8192,
    16384,
    32768,
    65536,
    131072,
    262144,  # 256K
    524288,  # 512K
    1048576,  # 1M
    2097152,  # 2M
]

_DEFAULT_MODEL_MAX = 32_000
_OVERHEAD_GB = 2.0  # OS + daemon + activation headroom beyond weights + KV
# Rough KV-cache cost: MB per token per billion params (fp16-ish, GQA-typical).
# 8B @128K ≈ 0.12 MB/tok × 8 ≈ ~15 GB, which matches observed ballparks.
_KV_MB_PER_TOKEN_PER_B = 0.015

# Process-global preference: "auto" or an int token count.
_setting: str | int = "auto"


def get_setting() -> str | int:
    return _setting


def set_setting(value: str | int) -> None:
    """Set the context preference. Accepts ``"auto"`` or a positive int."""
    global _setting
    if value == "auto":
        _setting = "auto"
        return
    try:
        n = int(value)
    except (TypeError, ValueError) as e:
        msg = f"context setting must be 'auto' or an int, got {value!r}"
        raise ValueError(msg) from e
    if n <= 0:
        msg = f"context size must be positive, got {n}"
        raise ValueError(msg)
    _setting = n


def model_max(model: str) -> int:
    return MODEL_CONTEXT_LIMITS.get(model, _DEFAULT_MODEL_MAX)


def _params_billion(model: str) -> float:
    from .model_setup import estimate_size_gb

    # estimate_size_gb ≈ params_billion × 0.6 for dense Q4 models.
    return max(0.5, estimate_size_gb(model) / 0.6)


def kv_cache_gb(model: str, ctx_tokens: int) -> float:
    """Approximate KV-cache footprint (GB) for ``ctx_tokens`` on ``model``."""
    return _KV_MB_PER_TOKEN_PER_B * _params_billion(model) * ctx_tokens / 1024


def ram_safe_ceiling(model: str, ram_budget_gb: float | None = None) -> int:
    """Largest context (tokens) that fits the RAM budget, capped at model max."""
    from .model_setup import estimate_size_gb

    ram = ram_budget_gb if ram_budget_gb is not None else local_ram_budget_gb()
    available = ram - estimate_size_gb(model) - _OVERHEAD_GB
    if available <= 0:
        return 4096
    per_token_gb = _KV_MB_PER_TOKEN_PER_B * _params_billion(model) / 1024
    max_tokens = int(available / per_token_gb) if per_token_gb > 0 else _DEFAULT_MODEL_MAX
    return max(4096, min(max_tokens, model_max(model)))


def resolve_num_ctx(
    model: str, ram_budget_gb: float | None = None, requested: str | int | None = None
) -> int:
    """Resolve the effective ``num_ctx`` for ``model``: clamp to the RAM-safe
    ceiling; "auto" picks the largest preset that fits."""
    req = requested if requested is not None else get_setting()
    ceiling = ram_safe_ceiling(model, ram_budget_gb)
    if req == "auto":
        fitting = [p for p in PRESETS if p <= ceiling]
        return fitting[-1] if fitting else 4096
    return max(4096, min(int(req), ceiling))


def _human(tokens: int) -> str:
    if tokens % (1024 * 1024) == 0:
        return f"{tokens // (1024 * 1024)}M"
    if tokens % 1024 == 0:
        return f"{tokens // 1024}K"
    return str(tokens)


def options_for(model: str, ram_budget_gb: float | None = None) -> dict:
    """Dropdown payload for a model: presets with fit flags + KV estimate."""
    ceiling = ram_safe_ceiling(model, ram_budget_gb)
    mx = model_max(model)
    presets = [
        {
            "tokens": p,
            "label": _human(p),
            "fits": p <= ceiling,
            "exceeds_model": p > mx,
            "kv_gb": round(kv_cache_gb(model, p), 1),
        }
        for p in PRESETS
    ]
    return {
        "presets": presets,
        "auto": resolve_num_ctx(model, ram_budget_gb, "auto"),
        "model_max": mx,
        "ceiling": ceiling,
        "setting": get_setting(),
    }
