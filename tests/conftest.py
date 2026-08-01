"""
Test fixtures: a fake vManage controller.

Tests run against ``httpx.MockTransport`` rather than a live controller, so the
suite covers the parts that actually break in the field — the login handshake,
CSRF token handling, session expiry and error envelopes — without needing a
lab. :class:`FakeVManage` records every request so tests can assert on the
paths and parameters the client sent.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest

from cisco_sdwan_mcp.sdwan.client import VManageClient, set_client
from cisco_sdwan_mcp.sdwan.config import VManageSettings

LOGIN_PAGE = "<html><body><form id='loginForm'></form></body></html>"


def settings(**overrides: Any) -> VManageSettings:
    base = {
        "base_url": "https://vmanage.test",
        "username": "tester",
        "password": "secret",
        "verify": True,
        "timeout": 5.0,
        "enable_writes": False,
        "page_size": 100,
    }
    base.update(overrides)
    return VManageSettings(**base)


class FakeVManage:
    """A programmable stand-in for the vManage REST API."""

    def __init__(
        self,
        routes: dict[str, Any] | None = None,
        *,
        login_fails: bool = False,
        token: str | None = "csrf-token-123",
        expire_after: int | None = None,
    ) -> None:
        #: path -> payload, or path -> callable(request) -> httpx.Response
        self.routes: dict[str, Any] = routes or {}
        self.login_fails = login_fails
        self.token = token
        #: serve an expired session after this many data requests
        self.expire_after = expire_after
        self.requests: list[httpx.Request] = []
        self.login_count = 0
        self._data_requests = 0

    # -- helpers used by tests ---------------------------------------------
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def last_request_for(self, path: str) -> httpx.Request | None:
        for request in reversed(self.requests):
            if request.url.path == path:
                return request
        return None

    def json_body(self, path: str) -> Any:
        request = self.last_request_for(path)
        return json.loads(request.content) if request and request.content else None

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    # -- request handling ---------------------------------------------------
    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path == "/j_security_check":
            return self._handle_login()
        if path == "/dataservice/client/token":
            if self.token is None:
                return httpx.Response(404)
            return httpx.Response(200, text=self.token)

        self._data_requests += 1
        if self.expire_after is not None and self._data_requests > self.expire_after:
            # vManage serves the login page with a 200 when the cookie expires.
            self._data_requests = 0
            return httpx.Response(
                200, text=LOGIN_PAGE, headers={"content-type": "text/html"}
            )

        handler = self.routes.get(path)
        if handler is None:
            return httpx.Response(
                404, json={"error": {"message": f"no route for {path}"}}
            )
        if isinstance(handler, httpx.Response):
            return handler
        if callable(handler):
            return handler(request)
        return httpx.Response(200, json=handler)

    def _handle_login(self) -> httpx.Response:
        self.login_count += 1
        if self.login_fails:
            return httpx.Response(
                200, text=LOGIN_PAGE, headers={"content-type": "text/html"}
            )
        return httpx.Response(
            200, headers={"set-cookie": "JSESSIONID=session-abc; Path=/"}
        )


def make_client(fake: FakeVManage, **setting_overrides: Any) -> VManageClient:
    return VManageClient(settings(**setting_overrides), transport=fake.transport)


@pytest.fixture
def vmanage_factory() -> Callable[..., tuple[FakeVManage, VManageClient]]:
    """Build a fake controller and install it as the process-wide client."""
    created: list[VManageClient] = []

    def factory(routes: dict[str, Any] | None = None, **kwargs: Any):
        client_kwargs = {k: kwargs.pop(k) for k in ("enable_writes",) if k in kwargs}
        fake = FakeVManage(routes, **kwargs)
        client = make_client(fake, **client_kwargs)
        created.append(client)
        set_client(client)
        return fake, client

    yield factory

    set_client(None)


@pytest.fixture(autouse=True)
def clean_sdwan_env(monkeypatch):
    """Keep ambient SDWAN_*/MCP_AUTH* variables out of the tests."""
    import os

    for key in list(os.environ):
        if key.startswith(("SDWAN_", "MCP_AUTH")):
            monkeypatch.delenv(key, raising=False)
