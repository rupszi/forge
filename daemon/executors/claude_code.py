"""Claude Code CLI executor. Runs claude -p in a git worktree.

Subprocess environment is filtered to an allowlist (per ADR-017 / daemon/redact.py)
so we don't leak unrelated CI tokens, AWS creds, or private SSH keys into a
subprocess that doesn't need them. The allowlist includes the Anthropic and
Ollama-related env vars Claude Code itself reads, plus the standard Unix
runtime context (PATH, HOME, SSH agent socket for git ops, etc.).
"""

import asyncio
import logging
import re
import time

from ..config import (
    CLAUDE_CODE_PATH,
    MAX_TASK_DESCRIPTION_LENGTH,
    MODEL_COSTS,
    TASK_TIMEOUT_SECONDS,
)
from ..models import ExecutionResult
from ..redact import filtered_subprocess_env

logger = logging.getLogger(__name__)


def sanitize_prompt(prompt: str) -> str:
    """Strip null bytes, control chars, cap length."""
    # Remove null bytes and control characters (keep newlines and tabs)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", prompt)
    return cleaned[:MAX_TASK_DESCRIPTION_LENGTH]


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    costs = MODEL_COSTS.get(model, MODEL_COSTS.get("sonnet"))
    return (tokens_in * costs["input"] + tokens_out * costs["output"]) / 1_000_000


async def execute(prompt: str, worktree_path: str = None, model: str = "sonnet") -> ExecutionResult:
    """Run claude -p in a git worktree with memory-enriched prompt."""
    sanitized = sanitize_prompt(prompt)
    cmd = [CLAUDE_CODE_PATH, "-p", sanitized]
    if model in ("opus", "sonnet", "haiku"):
        cmd.extend(["--model", model])

    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=worktree_path,
            # Allowlisted env only (ADR-017). Claude Code needs ANTHROPIC_API_KEY,
            # PATH, HOME, plus a few runtime locale/git/ssh vars; everything
            # else (e.g., AWS_SECRET_ACCESS_KEY, GH_PR_TOKEN) gets dropped.
            env=filtered_subprocess_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TASK_TIMEOUT_SECONDS)
        duration = time.time() - start
        output = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")

        if proc.returncode == 0:
            # Rough token estimation from output length
            est_tokens_in = len(sanitized) // 4
            est_tokens_out = len(output) // 4
            return ExecutionResult(
                success=True,
                output=output,
                tokens_in=est_tokens_in,
                tokens_out=est_tokens_out,
                cost_usd=estimate_cost(model, est_tokens_in, est_tokens_out),
                duration_seconds=duration,
            )
        return ExecutionResult(
            success=False,
            error=err or output or f"Exit code {proc.returncode}",
            duration_seconds=duration,
        )
    except asyncio.TimeoutError:
        # Task 2.4: kill the subprocess so it doesn't linger as a zombie
        # consuming a worktree. ProcessLookupError can fire if the process
        # exited between the wait_for() raising and our kill — that's fine.
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        except Exception as e:  # pragma: no cover — defensive
            logger.warning("subprocess.kill failed during timeout cleanup: %s", e)
        return ExecutionResult(
            success=False,
            error=f"Timeout after {TASK_TIMEOUT_SECONDS}s; process killed",
            duration_seconds=time.time() - start,
        )
    except FileNotFoundError:
        return ExecutionResult(
            success=False,
            error=f"Claude Code CLI not found at '{CLAUDE_CODE_PATH}'. Install with: npm install -g @anthropic-ai/claude-code",
            duration_seconds=time.time() - start,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
        )
