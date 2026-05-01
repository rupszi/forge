"""``forge_plugin_api`` — public author API for connectors / skills / LLM adapters.

Plugin authors install ``forge_plugin_api`` and import:

    from forge_plugin_api import Connector, Tool, ToolResult         # connectors
    from forge_plugin_api import LLMAdapter, GenerationRequest, GenerationResult   # llm
    from forge_plugin_api.testing import MockSandbox, FakeHttpClient  # tests

The runtime side lives in ``daemon.connectors``, ``daemon.skills``, and
``daemon.llms``. This package is the **author-facing contract**: stable,
versioned, never imports from ``daemon`` (so plugins don't depend on
Forge internals).

Schema version: 1.

Versioning policy: any breaking change to a public symbol bumps the
``forge_min_version`` users must declare in their manifest.toml.
"""

from __future__ import annotations

from .connector import Connector, Tool, ToolResult
from .llm import GenerationRequest, GenerationResult, LLMAdapter

__version__ = "0.1.0"
__schema_version__ = 1

__all__ = [
    "Connector",
    "GenerationRequest",
    "GenerationResult",
    "LLMAdapter",
    "Tool",
    "ToolResult",
    "__schema_version__",
    "__version__",
]
