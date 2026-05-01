"""Claude API batch endpoint executor. 50% cheaper, higher latency."""

import logging
import os
import time

import httpx

from ..config import MODEL_COSTS, TASK_TIMEOUT_SECONDS
from ..models import ExecutionResult

logger = logging.getLogger(__name__)

MODEL_MAP = {
    "opus": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}


async def execute(prompt: str, model: str = "sonnet") -> ExecutionResult:
    """Submit to Claude API Messages endpoint."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ExecutionResult(
            success=False,
            error="ANTHROPIC_API_KEY not set. Set it or use claude -p instead.",
        )

    model_id = MODEL_MAP.get(model, model)
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=TASK_TIMEOUT_SECONDS) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": model_id,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            r.raise_for_status()
            data = r.json()
            content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content += block.get("text", "")

            usage = data.get("usage", {})
            tokens_in = usage.get("input_tokens", 0)
            tokens_out = usage.get("output_tokens", 0)
            costs = MODEL_COSTS.get(model, MODEL_COSTS["sonnet"])
            cost = (tokens_in * costs["input"] + tokens_out * costs["output"]) / 1_000_000

            return ExecutionResult(
                success=True,
                output=content,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                duration_seconds=time.time() - start,
            )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
        )
