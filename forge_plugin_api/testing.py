"""Testing helpers for plugin authors.

Plugins write tests using these utilities to:
  - Mock the sandbox (so plugin code runs in pytest without a subprocess)
  - Fake httpx responses (so plugin code doesn't hit the real network)
  - Assert capability scopes (the test fails if the plugin tries to
    call a non-allowlisted host)

Example
-------

    import pytest
    from forge_plugin_api.testing import MockSandbox, FakeHttpClient
    from plugin import MyConnector

    @pytest.mark.asyncio
    async def test_my_connector():
        sandbox = MockSandbox(
            secrets={"MY_API_KEY": "test"},
            http=FakeHttpClient({
                "POST https://api.example.com/v1/widgets": {"status": 200, "body": {"id": 1}}
            }),
        )
        connector = MyConnector(sandbox.secrets, sandbox.session)
        connector.http_client = sandbox.http_client_factory  # type: ignore

        result = await connector.do_thing()
        assert result.ok
        sandbox.assert_only_called(["https://api.example.com"])

The shape mirrors httpx-respx but is dependency-free so plugin authors
don't pull respx into their plugin's runtime requirements.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


class CapabilityViolation(AssertionError):
    """Raised when a plugin under test tries to access a non-allowlisted host."""


@dataclass
class FakeResponse:
    """httpx.Response stand-in for FakeHttpClient."""

    status_code: int
    body: Any

    def json(self) -> Any:
        return self.body

    @property
    def text(self) -> str:
        if isinstance(self.body, str):
            return self.body
        return json.dumps(self.body)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise FakeHttpError(f"HTTP {self.status_code}", self)


class FakeHttpError(Exception):
    def __init__(self, msg: str, response: FakeResponse):
        super().__init__(msg)
        self.response = response


@dataclass
class FakeHttpClient:
    """Pretend httpx client. Indexed by 'METHOD URL' string keys.

    Each value is a dict like {"status": 200, "body": {...}}.
    Calls to URLs not in the routing table return 404.
    """

    routes: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def request(self, method: str, url: str, **kwargs) -> FakeResponse:
        key = f"{method.upper()} {url}"
        self.calls.append(url)
        route = self.routes.get(key)
        if route is None:
            return FakeResponse(status_code=404, body={"error": f"no route for {key}"})
        return FakeResponse(status_code=route.get("status", 200), body=route.get("body"))

    async def get(self, url: str, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs):
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs):
        return await self.request("DELETE", url, **kwargs)

    async def patch(self, url: str, **kwargs):
        return await self.request("PATCH", url, **kwargs)


@dataclass
class MockSandbox:
    """Stand-in for the runtime sandbox. Used by plugin tests."""

    secrets: dict[str, str] = field(default_factory=dict)
    # Note: paths inside ${TMPDIR} are deliberate test fixtures — Ruff S108
    # warns about /tmp; our usage is OK because this is the testing helper
    # surface for plugin authors and never runs in production. Tests can
    # override these defaults by passing ``session=`` explicitly.
    session: dict[str, Any] = field(
        default_factory=lambda: {
            "project_path": "/tmp/fake-project",  # noqa: S108
            "sprint_id": "sprint-test",
            "worktree_path": "/tmp/fake-project/.forge/worktrees/test",  # noqa: S108
        }
    )
    http: FakeHttpClient = field(default_factory=FakeHttpClient)

    def http_client_factory(self) -> FakeHttpClient:
        return self.http

    def assert_only_called(self, allowed_origins: list[str]) -> None:
        """Fail the test if any HTTP call escaped the allow-list."""
        for url in self.http.calls:
            origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            if not any(allowed in origin for allowed in allowed_origins):
                raise CapabilityViolation(
                    f"plugin called {url} but allow-list is {allowed_origins}"
                )
