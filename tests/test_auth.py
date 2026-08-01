"""
Tests for the authentication provider factory (cisco_sdwan_mcp/auth.py).
"""

import pytest
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier, StaticTokenVerifier
from starlette.testclient import TestClient

from cisco_sdwan_mcp.auth import SUPPORTED_MODES, build_auth_provider


@pytest.fixture(autouse=True)
def clean_auth_env(monkeypatch):
    """Make sure ambient MCP_AUTH* variables never leak into tests."""
    import os

    for key in list(os.environ):
        if key.startswith("MCP_AUTH"):
            monkeypatch.delenv(key, raising=False)


def test_default_is_no_auth():
    assert build_auth_provider() is None


def test_explicit_none(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "none")
    assert build_auth_provider() is None


def test_unknown_mode_raises(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "does-not-exist")
    with pytest.raises(ValueError, match="Unknown MCP_AUTH mode"):
        build_auth_provider()


def test_supported_modes_are_documented():
    assert "none" in SUPPORTED_MODES
    assert {"static", "jwt", "introspection", "oauth-proxy"} <= set(SUPPORTED_MODES)


# ---------------------------------------------------------------------------
# static
# ---------------------------------------------------------------------------
def test_static_requires_tokens(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "static")
    with pytest.raises(ValueError, match="MCP_AUTH_STATIC_TOKENS"):
        build_auth_provider()


def test_static_comma_separated_tokens(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "static")
    monkeypatch.setenv("MCP_AUTH_STATIC_TOKENS", "alpha, beta")

    provider = build_auth_provider()

    assert isinstance(provider, StaticTokenVerifier)
    assert set(provider.tokens) == {"alpha", "beta"}


def test_static_json_tokens_with_scopes(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "static")
    monkeypatch.setenv("MCP_AUTH_STATIC_TOKENS", '{"alpha": ["read", "write"]}')

    provider = build_auth_provider()

    assert isinstance(provider, StaticTokenVerifier)
    assert provider.tokens["alpha"]["scopes"] == ["read", "write"]


# ---------------------------------------------------------------------------
# jwt
# ---------------------------------------------------------------------------
def test_jwt_requires_key_material(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "jwt")
    with pytest.raises(ValueError, match="MCP_AUTH_JWKS_URI or MCP_AUTH_PUBLIC_KEY"):
        build_auth_provider()


def test_jwt_with_jwks_uri(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "jwt")
    monkeypatch.setenv("MCP_AUTH_JWKS_URI", "https://idp.example.com/.well-known/jwks.json")
    monkeypatch.setenv("MCP_AUTH_ISSUER", "https://idp.example.com/")
    monkeypatch.setenv("MCP_AUTH_AUDIENCE", "cisco-sdwan-mcp")
    monkeypatch.setenv("MCP_AUTH_REQUIRED_SCOPES", "mcp:read, mcp:write")

    provider = build_auth_provider()

    assert isinstance(provider, JWTVerifier)
    assert provider.jwks_uri == "https://idp.example.com/.well-known/jwks.json"
    assert provider.issuer == "https://idp.example.com/"
    assert provider.audience == "cisco-sdwan-mcp"
    assert provider.required_scopes == ["mcp:read", "mcp:write"]


# ---------------------------------------------------------------------------
# introspection / oauth-proxy / hosted providers
# ---------------------------------------------------------------------------
def test_introspection(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "introspection")
    monkeypatch.setenv("MCP_AUTH_INTROSPECTION_URL", "https://idp.example.com/introspect")
    monkeypatch.setenv("MCP_AUTH_CLIENT_ID", "mcp-server")
    monkeypatch.setenv("MCP_AUTH_CLIENT_SECRET", "s3cret")

    from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier

    assert isinstance(build_auth_provider(), IntrospectionTokenVerifier)


def test_introspection_missing_config_raises(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "introspection")
    with pytest.raises(ValueError, match="MCP_AUTH_INTROSPECTION_URL"):
        build_auth_provider()


def test_oauth_proxy(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "oauth-proxy")
    monkeypatch.setenv(
        "MCP_AUTH_UPSTREAM_AUTHORIZATION_ENDPOINT", "https://idp.example.com/authorize"
    )
    monkeypatch.setenv("MCP_AUTH_UPSTREAM_TOKEN_ENDPOINT", "https://idp.example.com/token")
    monkeypatch.setenv("MCP_AUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("MCP_AUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("MCP_AUTH_BASE_URL", "https://mcp.example.com")
    monkeypatch.setenv("MCP_AUTH_JWKS_URI", "https://idp.example.com/.well-known/jwks.json")

    from fastmcp.server.auth.oauth_proxy import OAuthProxy

    assert isinstance(build_auth_provider(), OAuthProxy)


def test_github_provider(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "github")
    monkeypatch.setenv("MCP_AUTH_CLIENT_ID", "Iv1.abc")
    monkeypatch.setenv("MCP_AUTH_CLIENT_SECRET", "gh-secret")
    monkeypatch.setenv("MCP_AUTH_BASE_URL", "https://mcp.example.com")

    from fastmcp.server.auth.providers.github import GitHubProvider

    assert isinstance(build_auth_provider(), GitHubProvider)


def test_github_missing_base_url_raises(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "github")
    monkeypatch.setenv("MCP_AUTH_CLIENT_ID", "Iv1.abc")
    monkeypatch.setenv("MCP_AUTH_CLIENT_SECRET", "gh-secret")
    with pytest.raises(ValueError, match="MCP_AUTH_BASE_URL"):
        build_auth_provider()


# ---------------------------------------------------------------------------
# End-to-end: the MCP endpoint is protected, health stays public
# ---------------------------------------------------------------------------
def test_http_app_enforces_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH", "static")
    monkeypatch.setenv("MCP_AUTH_STATIC_TOKENS", "secret-token")

    protected = FastMCP(name="protected", auth=build_auth_provider())
    client = TestClient(protected.http_app(path="/mcp"))

    response = client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )

    assert response.status_code == 401
