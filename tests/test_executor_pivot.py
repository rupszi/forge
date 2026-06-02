"""M1 — executor pivot: local is the default, cloud is explicit (G-LOC-2).

Covers the routing gate (cloud executors only run when opted in), MLX routing,
and an egress assertion proving the Ollama path targets loopback only.
"""

from __future__ import annotations

import pytest

from daemon import routing
from daemon.models import SprintContract
from tests.egress_guard import ExternalEgressError, assert_no_external_egress


def _sprint(model: str) -> SprintContract:
    return SprintContract(
        id="sprint-test01",
        session_id="sess-test01",
        description="do a thing",
        done_criteria=["it works"],
        assigned_model=model,
    )


class TestSelectExecutorString:
    def test_local_models_route_to_ollama_by_default(self, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        assert routing.select_executor("qwen3-coder-next") == "ollama"
        assert routing.select_executor("deepseek-v4-flash") == "ollama"

    def test_anthropic_models_map_to_claude_code_string(self):
        # The string mapping is unchanged (procedural memory records it); the
        # *gate* happens at dispatch, not here.
        assert routing.select_executor("claude-sonnet-4-7") == "claude_code"

    def test_openai_base_url_routes_compatible(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
        assert routing.select_executor("qwen3-coder-next") == "openai_compatible"

    def test_mlx_prefixed_models_route_to_mlx(self, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        assert routing.select_executor("mlx:qwen2.5-coder-14b") == "mlx"
        assert routing.select_executor("mlx-community/Qwen2.5") == "mlx"


class TestCloudClassification:
    def test_is_cloud_executor(self):
        assert routing.is_cloud_executor("claude_code") is True
        assert routing.is_cloud_executor("batch") is True
        assert routing.is_cloud_executor("ollama") is False
        assert routing.is_cloud_executor("openai_compatible") is False
        assert routing.is_cloud_executor("mlx") is False


class TestDispatchCloudGate:
    """Generator dispatch must refuse a cloud executor unless opted in."""

    @pytest.mark.asyncio
    async def test_cloud_model_blocked_when_disabled(self, monkeypatch):
        from daemon.agents import generator

        monkeypatch.delenv("FORGE_CLOUD_ENABLED", raising=False)
        with pytest.raises(routing.CloudDisabledError):
            await generator.generate(_sprint("claude-sonnet-4-7"))

    @pytest.mark.asyncio
    async def test_legacy_short_anthropic_names_blocked_when_disabled(self, monkeypatch):
        from daemon.agents import generator

        monkeypatch.delenv("FORGE_CLOUD_ENABLED", raising=False)
        for name in ("opus", "sonnet", "haiku"):
            with pytest.raises(routing.CloudDisabledError):
                await generator.generate(_sprint(name))

    @pytest.mark.asyncio
    async def test_cloud_model_allowed_when_enabled(self, monkeypatch):
        from daemon.agents import generator
        from daemon.executors import claude_code as claude_executor
        from daemon.models import ExecutionResult

        monkeypatch.setenv("FORGE_CLOUD_ENABLED", "1")

        async def fake_execute(prompt, worktree_path, model):
            return ExecutionResult(success=True, output="ok")

        monkeypatch.setattr(claude_executor, "execute", fake_execute)
        result = await generator.generate(_sprint("claude-sonnet-4-7"))
        assert result.success is True

    @pytest.mark.asyncio
    async def test_local_model_never_gated(self, monkeypatch):
        from daemon.agents import generator
        from daemon.executors import ollama as ollama_executor
        from daemon.models import ExecutionResult

        monkeypatch.delenv("FORGE_CLOUD_ENABLED", raising=False)

        async def fake_execute(prompt, model=None, **kwargs):
            # The generator now also passes num_ctx for the ollama path.
            return ExecutionResult(success=True, output="ok")

        monkeypatch.setattr(ollama_executor, "execute", fake_execute)
        result = await generator.generate(_sprint("qwen3-coder-next"))
        assert result.success is True


class TestOllamaPathStaysLocal:
    @pytest.mark.asyncio
    async def test_ollama_executor_makes_no_external_connection(self):
        # The real executor against the default localhost base URL must never
        # dial out. Whether Ollama is up (success) or down (local refusal),
        # the only forbidden outcome is ExternalEgressError.
        from daemon.executors import ollama as ollama_executor

        with assert_no_external_egress():
            try:
                await ollama_executor.execute("ping", model="qwen3-coder-next")
            except ExternalEgressError:
                raise
            except (OSError, Exception) as e:
                assert not isinstance(e, ExternalEgressError)
