"""
Async HTTP client for the Cisco Catalyst SD-WAN Manager (vManage) REST API.

vManage authentication is a two-step dance that trips up most first
integrations:

1. ``POST /j_security_check`` with form-encoded credentials. On success the
   response is **HTTP 200 with an empty body** and a ``JSESSIONID`` cookie. On
   failure it is *also* HTTP 200 — but the body is the HTML login page. Status
   code alone is not a success signal, so :func:`_is_login_page` inspects the
   body.
2. ``GET /dataservice/client/token`` returns a CSRF token that must accompany
   every subsequent request as ``X-XSRF-TOKEN``. Controllers older than 19.2
   have no such endpoint and answer 404 — that is not an error, the session
   cookie is sufficient there.

Sessions expire server-side. Any request that comes back as a login page (or
401/403) triggers exactly one transparent re-authentication and retry, so
long-lived MCP sessions survive vManage's idle timeout without the caller
noticing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from cisco_sdwan_mcp.sdwan.config import VManageSettings, load_settings
from cisco_sdwan_mcp.sdwan.errors import APIError, AuthenticationError

logger = logging.getLogger(__name__)

DATASERVICE = "/dataservice"
_TOKEN_PATH = f"{DATASERVICE}/client/token"
_LOGIN_PATH = "/j_security_check"


def _is_login_page(response: httpx.Response) -> bool:
    """Detect vManage answering with the HTML login form instead of data.

    This is how both a bad password and an expired session present themselves,
    since vManage returns HTTP 200 in each case.
    """
    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type:
        return True
    # Some builds omit the content-type header on the login redirect.
    return "<html" in response.text[:512].lower()


class VManageClient:
    """Authenticated session against a single vManage controller."""

    def __init__(self, settings: VManageSettings | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings or load_settings()
        if self.settings.verify is False:
            logger.warning(
                "SDWAN_VERIFY_SSL=false — TLS certificate verification is disabled "
                "for %s. Use SDWAN_CA_BUNDLE with the controller's CA in production.",
                self.settings.host,
            )
        self._client = httpx.AsyncClient(
            base_url=self.settings.base_url,
            verify=self.settings.verify,
            timeout=self.settings.timeout,
            follow_redirects=False,
            transport=transport,
        )
        self._token: str | None = None
        self._authenticated = False
        self._lock = asyncio.Lock()

    # -- transport ----------------------------------------------------------
    async def _http(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send one request, translating transport failures into APIError.

        Every request — including the login handshake — goes through here, so
        an unreachable controller reads the same whether it fails on the first
        byte or halfway through a session.
        """
        try:
            return await self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise APIError(
                504, method, path,
                f"timed out after {self.settings.timeout}s talking to "
                f"{self.settings.host}",
            ) from exc
        except httpx.TransportError as exc:
            raise APIError(
                502, method, path,
                f"cannot reach {self.settings.host} ({exc}). Check the URL, "
                "network reachability and TLS settings.",
            ) from exc

    # -- session lifecycle --------------------------------------------------
    async def login(self) -> None:
        """Authenticate and capture the session cookie plus CSRF token."""
        response = await self._http(
            "POST",
            _LOGIN_PATH,
            data={
                "j_username": self.settings.username,
                "j_password": self.settings.password,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200 or _is_login_page(response):
            raise AuthenticationError(
                f"vManage at {self.settings.host} rejected the credentials for "
                f"user {self.settings.username!r}. Check SDWAN_USERNAME / "
                "SDWAN_PASSWORD and that the account is not locked."
            )
        if "JSESSIONID" not in self._client.cookies:
            raise AuthenticationError(
                f"vManage at {self.settings.host} accepted the login but issued no "
                "JSESSIONID cookie. Confirm SDWAN_VMANAGE_URL points at the "
                "controller itself and not at a proxy that strips cookies."
            )

        self._token = await self._fetch_token()
        self._authenticated = True
        logger.info(
            "Authenticated to vManage %s as %s (csrf token: %s)",
            self.settings.host,
            self.settings.username,
            "yes" if self._token else "not required",
        )

    async def _fetch_token(self) -> str | None:
        """Fetch the CSRF token; ``None`` on pre-19.2 controllers."""
        response = await self._http("GET", _TOKEN_PATH)
        if response.status_code == 404:
            return None
        if response.status_code != 200 or _is_login_page(response):
            return None
        token = response.text.strip()
        return token or None

    async def _ensure_session(self) -> None:
        if self._authenticated:
            return
        async with self._lock:
            # Another coroutine may have logged in while we waited.
            if not self._authenticated:
                await self.login()

    async def _reauthenticate(self) -> None:
        async with self._lock:
            self._authenticated = False
            self._token = None
            self._client.cookies.clear()
            await self.login()

    async def close(self) -> None:
        await self._client.aclose()
        self._authenticated = False

    async def __aenter__(self) -> "VManageClient":
        await self._ensure_session()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    # -- requests -----------------------------------------------------------
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Send an authenticated request and return the decoded payload.

        Retries once after a transparent re-login when vManage reports the
        session as expired.
        """
        await self._ensure_session()

        response = await self._send(method, path, params=params, json=json)
        if self._session_expired(response):
            logger.info("vManage session expired — re-authenticating and retrying.")
            await self._reauthenticate()
            response = await self._send(method, path, params=params, json=json)

        return self._decode(response, method, path)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json: Any,
    ) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["X-XSRF-TOKEN"] = self._token
        return await self._http(
            method.upper(), path, params=params, json=json, headers=headers
        )

    @staticmethod
    def _session_expired(response: httpx.Response) -> bool:
        if response.status_code in (401, 403):
            return True
        # An expired cookie makes vManage serve the login page with a 200.
        return response.status_code == 200 and _is_login_page(response)

    def _decode(self, response: httpx.Response, method: str, path: str) -> Any:
        if response.status_code in (401, 403):
            raise AuthenticationError(
                f"vManage denied {method.upper()} {path} (HTTP "
                f"{response.status_code}). The account {self.settings.username!r} "
                "may lack the required role for this endpoint."
            )
        if response.status_code >= 400:
            raise APIError(
                response.status_code, method.upper(), path,
                self._error_detail(response),
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise APIError(
                response.status_code, method.upper(), path,
                "response was not valid JSON — the endpoint may not exist on "
                "this controller version",
            ) from exc

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Pull vManage's own error text out of its standard error envelope."""
        try:
            payload = response.json()
        except ValueError:
            return response.text[:200].strip()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            parts = [error.get("message", ""), error.get("details", "")]
            return " — ".join(p for p in parts if p) or str(error)
        return str(payload)[:200]

    # -- convenience --------------------------------------------------------
    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: Any = None,
                   params: dict[str, Any] | None = None) -> Any:
        return await self.request("POST", path, params=params, json=json)

    async def get_data(self, path: str, params: dict[str, Any] | None = None) -> list[dict]:
        """GET an endpoint and unwrap vManage's ``{"data": [...]}`` envelope."""
        payload = await self.get(path, params=params)
        return extract_data(payload)


def extract_data(payload: Any) -> list[dict]:
    """Normalise a vManage payload to a list of records.

    Most endpoints wrap results in ``{"data": [...], "header": {...}}``, a few
    return a bare list, and a handful return a single object.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        if data is None and payload:
            return [payload]
    return []


# ---------------------------------------------------------------------------
# Shared client — one authenticated session per server process.
# ---------------------------------------------------------------------------
_client: VManageClient | None = None
_client_lock = asyncio.Lock()


async def get_client() -> VManageClient:
    """Return the process-wide client, creating and authenticating on demand."""
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = VManageClient()
    await _client._ensure_session()
    return _client


async def reset_client() -> None:
    """Dispose of the shared client (used by tests and on shutdown)."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def set_client(client: VManageClient | None) -> None:
    """Inject a client — the seam tests use to supply a mock transport."""
    global _client
    _client = client
