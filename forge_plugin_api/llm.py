"""LLM adapter base class for ``~/.forge/llms/<name>/`` plugins.

Adapters implement a single async method, ``generate(request) -> result``.
The runtime handles dispatch, retries, the cross-family invariant
(ADR-006), and budget reconciliation.

Example
-------

    from forge_plugin_api import LLMAdapter, GenerationRequest, GenerationResult

    class MyProviderAdapter(LLMAdapter):
        name = "myprovider"
        family = "myfamily"

        def __init__(self, secrets):
            self.api_key = secrets["MYPROVIDER_API_KEY"]

        async def generate(self, request: GenerationRequest) -> GenerationResult:
            ...

The ``family`` attribute is consumed by
``daemon/agents/classifier.py::pick_evaluator_model`` to enforce the
cross-family-evaluator invariant: when this adapter is the generator,
Forge picks an evaluator from a *different* family.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class GenerationRequest:
    """A single generation request to an LLM adapter."""

    model: str
    messages: list[dict[str, Any]]  # OpenAI-shape: [{"role": "...", "content": "..."}]
    temperature: float = 0.2
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: Any | None = None  # e.g. {"type": "json_object"} or a JSON schema
    stop: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    """Result of a single generation request."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    stop_reason: Literal["stop", "length", "tool_calls", "content_filter", "error", "unknown"] = (
        "stop"
    )
    tool_calls: list[dict[str, Any]] | None = None
    raw_response: dict[str, Any] | None = None  # provider-specific, for debugging
    error: str | None = None


class LLMAdapter:
    """Base class for LLM-provider plugins.

    Subclasses set:
      - ``name`` (matches manifest.toml ``plugin.name``)
      - ``family`` (used for cross-family-evaluator selection)

    The runtime instantiates with the filtered secrets dict.

    Override ``generate()``, optionally ``supports_tools(model)`` and
    ``supports_json_mode(model)``. The default implementations return
    False (conservative).
    """

    name: str = ""
    family: str = ""

    def __init__(self, secrets: dict[str, str]):
        self.secrets = secrets

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError

    def supports_tools(self, model: str) -> bool:
        return False

    def supports_json_mode(self, model: str) -> bool:
        return False

    def http_client(self):
        """Return an httpx.AsyncClient enforcing the network allow-list.

        See ``forge_plugin_api.connector.Connector.http_client`` for the
        same lifecycle — the sandbox runtime overrides this method
        before the adapter runs.
        """
        import httpx

        return httpx.AsyncClient(timeout=120.0)
