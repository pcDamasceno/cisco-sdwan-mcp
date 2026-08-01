"""
Authentication provider factory.

The server's auth is selected at startup with the ``MCP_AUTH`` environment
variable, so the same image runs unauthenticated on a laptop and fully
OAuth-protected in production without code changes.

Supported modes (see README → Authentication for full examples):

| MCP_AUTH        | What it does                                                    |
|-----------------|-----------------------------------------------------------------|
| none (default)  | No authentication.                                              |
| static          | Fixed bearer tokens from env — development/testing only.        |
| jwt             | Verify JWT bearer tokens against a JWKS URI or PEM public key.  |
| introspection   | Validate opaque tokens via RFC 7662 token introspection.        |
| oauth-proxy     | Full OAuth 2.1 flow proxied to any upstream identity provider.  |
| github          | "Login with GitHub" via FastMCP's built-in provider.            |
| google          | "Login with Google" via FastMCP's built-in provider.            |
| azure           | Microsoft Entra ID (Azure AD).                                  |
| auth0           | Auth0.                                                          |
| workos          | WorkOS AuthKit.                                                 |

Authentication applies to the HTTP transport only. stdio runs as a local
subprocess of the client and is secured by the operating system instead.

To add a custom mode, write a builder returning a FastMCP ``AuthProvider``
(or ``TokenVerifier``) and register it in ``_BUILDERS`` below.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from fastmcp.server.auth import AuthProvider


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------
def _mode() -> str:
    return os.getenv("MCP_AUTH", "none").strip().lower()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(
            f"MCP_AUTH={_mode()!r} requires the {name} environment variable to be set."
        )
    return value


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _required_scopes() -> list[str] | None:
    """Parse MCP_AUTH_REQUIRED_SCOPES as a comma-separated list."""
    raw = os.getenv("MCP_AUTH_REQUIRED_SCOPES", "")
    scopes = [s.strip() for s in raw.split(",") if s.strip()]
    return scopes or None


# ---------------------------------------------------------------------------
# Token verifiers (server validates tokens issued elsewhere)
# ---------------------------------------------------------------------------
def _build_static() -> "AuthProvider":
    """Fixed bearer tokens — DEVELOPMENT ONLY, tokens live in plain env vars.

    MCP_AUTH_STATIC_TOKENS accepts either:
      - a comma-separated list:   "token-one,token-two"
      - a JSON object:            {"token-one": ["read", "write"]}
        (values are the scopes granted to that token)
    """
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    raw = _require("MCP_AUTH_STATIC_TOKENS")
    tokens: dict[str, dict[str, Any]] = {}

    if raw.lstrip().startswith("{"):
        for index, (token, value) in enumerate(json.loads(raw).items()):
            if isinstance(value, dict):
                config = {"client_id": value.get("client_id", f"static-{index}"), **value}
            else:
                config = {"client_id": f"static-{index}", "scopes": list(value)}
            tokens[token] = config
    else:
        for index, token in enumerate(t.strip() for t in raw.split(",") if t.strip()):
            tokens[token] = {"client_id": f"static-{index}", "scopes": []}

    return StaticTokenVerifier(tokens=tokens, required_scopes=_required_scopes())


def _build_jwt() -> "AuthProvider":
    """Verify JWTs issued by an external identity provider.

    Works with any IdP that exposes a JWKS endpoint (Keycloak, Auth0, Okta,
    Entra ID, Cognito, …) or a static PEM public key.
    """
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    jwks_uri = _optional("MCP_AUTH_JWKS_URI")
    public_key = _optional("MCP_AUTH_PUBLIC_KEY")
    if not jwks_uri and not public_key:
        raise ValueError(
            "MCP_AUTH='jwt' requires MCP_AUTH_JWKS_URI or MCP_AUTH_PUBLIC_KEY to be set."
        )

    return JWTVerifier(
        jwks_uri=jwks_uri,
        public_key=public_key,
        issuer=_optional("MCP_AUTH_ISSUER"),
        audience=_optional("MCP_AUTH_AUDIENCE"),
        algorithm=_optional("MCP_AUTH_ALGORITHM"),
        required_scopes=_required_scopes(),
    )


def _build_introspection() -> "AuthProvider":
    """Validate opaque tokens by calling the IdP's RFC 7662 introspection endpoint."""
    from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier

    return IntrospectionTokenVerifier(
        introspection_url=_require("MCP_AUTH_INTROSPECTION_URL"),
        client_id=_require("MCP_AUTH_CLIENT_ID"),
        client_secret=_require("MCP_AUTH_CLIENT_SECRET"),
        required_scopes=_required_scopes(),
    )


# ---------------------------------------------------------------------------
# Full OAuth flows (server participates in the authorization dance)
# ---------------------------------------------------------------------------
def _build_oauth_proxy() -> "AuthProvider":
    """Generic OAuth 2.1 proxy for any upstream provider.

    The server presents MCP-compliant OAuth endpoints (including Dynamic
    Client Registration) to clients and proxies the flow to an upstream IdP
    that doesn't support DCR itself. Upstream access tokens are verified
    with the JWT settings (MCP_AUTH_JWKS_URI etc.).
    """
    from fastmcp.server.auth.oauth_proxy import OAuthProxy

    return OAuthProxy(
        upstream_authorization_endpoint=_require("MCP_AUTH_UPSTREAM_AUTHORIZATION_ENDPOINT"),
        upstream_token_endpoint=_require("MCP_AUTH_UPSTREAM_TOKEN_ENDPOINT"),
        upstream_client_id=_require("MCP_AUTH_CLIENT_ID"),
        upstream_client_secret=_require("MCP_AUTH_CLIENT_SECRET"),
        token_verifier=_build_jwt(),
        base_url=_require("MCP_AUTH_BASE_URL"),
    )


def _build_github() -> "AuthProvider":
    from fastmcp.server.auth.providers.github import GitHubProvider

    return GitHubProvider(
        client_id=_require("MCP_AUTH_CLIENT_ID"),
        client_secret=_require("MCP_AUTH_CLIENT_SECRET"),
        base_url=_require("MCP_AUTH_BASE_URL"),
        required_scopes=_required_scopes(),
    )


def _build_google() -> "AuthProvider":
    from fastmcp.server.auth.providers.google import GoogleProvider

    return GoogleProvider(
        client_id=_require("MCP_AUTH_CLIENT_ID"),
        client_secret=_require("MCP_AUTH_CLIENT_SECRET"),
        base_url=_require("MCP_AUTH_BASE_URL"),
        required_scopes=_required_scopes(),
    )


def _build_azure() -> "AuthProvider":
    from fastmcp.server.auth.providers.azure import AzureProvider

    scopes = _required_scopes()
    if not scopes:
        raise ValueError(
            "MCP_AUTH='azure' requires MCP_AUTH_REQUIRED_SCOPES "
            "(e.g. 'User.Read' or your app's exposed API scopes)."
        )
    return AzureProvider(
        client_id=_require("MCP_AUTH_CLIENT_ID"),
        client_secret=_require("MCP_AUTH_CLIENT_SECRET"),
        tenant_id=_require("MCP_AUTH_AZURE_TENANT_ID"),
        base_url=_require("MCP_AUTH_BASE_URL"),
        required_scopes=scopes,
    )


def _build_auth0() -> "AuthProvider":
    from fastmcp.server.auth.providers.auth0 import Auth0Provider

    return Auth0Provider(
        config_url=_require("MCP_AUTH_AUTH0_CONFIG_URL"),
        client_id=_require("MCP_AUTH_CLIENT_ID"),
        client_secret=_require("MCP_AUTH_CLIENT_SECRET"),
        audience=_require("MCP_AUTH_AUDIENCE"),
        base_url=_require("MCP_AUTH_BASE_URL"),
        required_scopes=_required_scopes(),
    )


def _build_workos() -> "AuthProvider":
    from fastmcp.server.auth.providers.workos import AuthKitProvider

    return AuthKitProvider(
        authkit_domain=_require("MCP_AUTH_AUTHKIT_DOMAIN"),
        base_url=_require("MCP_AUTH_BASE_URL"),
        required_scopes=_required_scopes(),
    )


_BUILDERS: dict[str, Callable[[], "AuthProvider"]] = {
    "static": _build_static,
    "jwt": _build_jwt,
    "introspection": _build_introspection,
    "oauth-proxy": _build_oauth_proxy,
    "github": _build_github,
    "google": _build_google,
    "azure": _build_azure,
    "auth0": _build_auth0,
    "workos": _build_workos,
}

SUPPORTED_MODES = ("none", *_BUILDERS)


def build_auth_provider() -> "AuthProvider | None":
    """Build the auth provider selected by MCP_AUTH, or None when disabled."""
    mode = _mode()
    if mode in ("", "none"):
        return None

    builder = _BUILDERS.get(mode)
    if builder is None:
        raise ValueError(
            f"Unknown MCP_AUTH mode {mode!r}. Supported modes: {', '.join(SUPPORTED_MODES)}."
        )
    return builder()
