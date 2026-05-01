"""Connector base class and tool decorator for native plugins.

Plugin authors subclass ``Connector`` and decorate methods with ``@Tool``
to expose them to the planner / generator. The runtime introspects
``@Tool``-decorated methods to build the tool list seen by the model.

Example
-------

    from forge_plugin_api import Connector, Tool, ToolResult

    class GitHubConnector(Connector):
        name = "github"

        def __init__(self, secrets, session):
            self.token = secrets["GITHUB_TOKEN"]

        @Tool(name="create_issue", side_effects="external")
        async def create_issue(self, repo: str, title: str, body: str) -> ToolResult:
            ...
            return ToolResult(ok=True, data={"issue_number": 42})

The ``side_effects`` field is consumed by the lethal-trifecta gate at
scheduler level — see ``daemon/skills/lethal_trifecta.py``.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

SideEffect = Literal["readonly", "local", "external"]


@dataclass
class ToolResult:
    """Return type for connector tool methods.

    Plugin authors return this dataclass; the runtime translates to the
    wire format the planner consumes. ``data`` should be JSON-serializable.
    """

    ok: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] | None = None


def Tool(
    *,
    name: str,
    description: str = "",
    side_effects: SideEffect = "readonly",
    idempotent: bool = False,
):
    """Decorator marking a method as a tool exposed to Forge.

    Captures metadata used by the connector registry and the
    lethal-trifecta gate. The decorator does not itself enforce
    capabilities — that happens in the sandbox runtime.

    ``side_effects`` semantics:

      - ``"readonly"`` — never modifies external state; safe to call
        speculatively
      - ``"local"`` — modifies state inside the worktree only
      - ``"external"`` — has effects outside the worktree (network
        POST, external file write, etc.); subject to lethal-trifecta
        composition gate
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        wrapper._forge_tool_meta = {  # type: ignore[attr-defined]
            "name": name,
            "description": description or (func.__doc__ or "").strip().split("\n")[0],
            "side_effects": side_effects,
            "idempotent": idempotent,
        }
        return wrapper

    return decorator


class Connector:
    """Base class for native connectors.

    Subclasses define ``name`` (matches manifest.toml plugin.name) and
    methods decorated with ``@Tool``. The runtime instantiates the class
    with two args:

      - ``secrets``: dict of env var name → value, filtered to the
        plugin's declared ``[capabilities].secrets_read``
      - ``session``: dict with project_path, sprint_id, worktree_path

    Subclass-supplied ``http_client`` factory returns an httpx.AsyncClient
    pre-configured with the network allow-list. The sandbox runtime
    injects a wrapped factory at instantiation time.
    """

    name: str = ""

    def __init__(self, secrets: dict[str, str], session: dict[str, Any]):
        self.secrets = secrets
        self.session = session

    def http_client(self):
        """Return an httpx.AsyncClient enforcing the network allow-list.

        Default implementation is a placeholder; the sandbox runtime
        overrides this with a hardened factory before the connector
        runs. If a plugin author overrides ``http_client`` directly,
        the override MUST also enforce the allow-list — failing to do
        so is a capability violation logged to the audit trail.
        """
        import httpx

        return httpx.AsyncClient(timeout=30.0)

    @classmethod
    def _list_tools(cls) -> list[dict[str, Any]]:
        """Introspect ``@Tool``-decorated methods. Used by the registry."""
        tools = []
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            meta = getattr(attr, "_forge_tool_meta", None)
            if meta is not None:
                tools.append({**meta, "method": attr_name})
        return tools
