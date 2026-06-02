"""MLX executor — run Apple-Silicon-native weights locally (M1).

For models Ollama can't host (many raw Hugging Face / MLX-community weights),
Forge serves them through Apple's MLX framework on the Metal GPU. Zero cost,
fully local, no network.

``mlx-lm`` is an optional dependency (Apple Silicon only). We import it lazily
so the daemon — and the whole test suite — runs on machines without it. Models
are addressed with an ``mlx:`` prefix (``mlx:qwen2.5-coder-14b``) or a bare
``mlx-community/...`` repo id; ``daemon.routing.select_executor`` routes both
here.
"""

from __future__ import annotations

import asyncio
import time

from ..config import MAX_TASK_DESCRIPTION_LENGTH, TASK_TIMEOUT_SECONDS
from ..models import ExecutionResult


def _sanitize(prompt: str) -> str:
    """Strip null bytes / control chars and cap length, mirroring the other
    executors' input hygiene."""
    cleaned = prompt.replace("\x00", "")
    cleaned = "".join(c for c in cleaned if c >= " " or c in "\n\r\t")
    return cleaned[: MAX_TASK_DESCRIPTION_LENGTH * 4]


def _strip_prefix(model: str) -> str:
    """Normalize ``mlx:<repo>`` to the bare repo id MLX expects."""
    return model[4:] if model.lower().startswith("mlx:") else model


def _load_mlx():
    """Import mlx_lm lazily. Raises a clear error if it isn't installed."""
    try:
        from mlx_lm import generate as mlx_generate, load as mlx_load
    except ImportError as e:  # pragma: no cover - exercised via monkeypatch
        msg = (
            "MLX executor requires the 'mlx-lm' package (Apple Silicon). "
            "Install with: pip install mlx-lm — or use an Ollama model instead."
        )
        raise RuntimeError(msg) from e
    return mlx_load, mlx_generate


async def execute(
    prompt: str,
    model: str = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    *,
    max_tokens: int = 4096,
) -> ExecutionResult:
    """Generate locally via MLX. Runs the blocking MLX call in a worker thread."""
    clean = _sanitize(prompt)
    repo = _strip_prefix(model)
    started = time.monotonic()

    def _run() -> str:
        mlx_load, mlx_generate = _load_mlx()
        llm, tokenizer = mlx_load(repo)
        return mlx_generate(llm, tokenizer, prompt=clean, max_tokens=max_tokens)

    try:
        output = await asyncio.wait_for(asyncio.to_thread(_run), timeout=TASK_TIMEOUT_SECONDS)
    except TimeoutError:
        return ExecutionResult(
            success=False,
            output="",
            error=f"MLX generation timed out after {TASK_TIMEOUT_SECONDS}s",
            duration_seconds=time.monotonic() - started,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            output="",
            error=str(e),
            duration_seconds=time.monotonic() - started,
        )

    return ExecutionResult(
        success=True,
        output=output,
        tokens_in=len(clean) // 4,
        tokens_out=len(output) // 4,
        duration_seconds=time.monotonic() - started,
    )
