"""
Connection settings for Cisco Catalyst SD-WAN Manager (vManage).

Everything is read from the environment so the same image runs against a lab
controller on a laptop and against production from Kubernetes. Nothing here
is MCP-specific — :class:`VManageSettings` is a plain value object the client
consumes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cisco_sdwan_mcp.sdwan.errors import ConfigurationError

DEFAULT_PORT = 443
DEFAULT_TIMEOUT = 60.0
DEFAULT_PAGE_SIZE = 100


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}.") from exc


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}.") from exc


def _normalise_base_url(url: str) -> str:
    """Accept ``vmanage.example.com``, ``host:8443`` or a full URL."""
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


@dataclass(frozen=True)
class VManageSettings:
    """Resolved vManage connection settings."""

    base_url: str
    username: str
    password: str
    #: ``True`` to verify against the system trust store, ``False`` to skip
    #: verification, or a path to a CA bundle.
    verify: bool | str
    timeout: float
    enable_writes: bool
    page_size: int

    @property
    def host(self) -> str:
        """Host portion of the base URL — safe to expose (no credentials)."""
        return self.base_url.split("://", 1)[-1]


def load_settings() -> VManageSettings:
    """Build settings from the environment.

    Raises:
        ConfigurationError: when a required variable is missing. Tools surface
            the message so the user learns exactly which variable to set.
    """
    url = _env("SDWAN_VMANAGE_URL")
    if not url:
        host = _env("SDWAN_VMANAGE_HOST")
        if not host:
            raise ConfigurationError(
                "No controller configured. Set SDWAN_VMANAGE_URL "
                "(e.g. https://vmanage.example.com:8443) or SDWAN_VMANAGE_HOST."
            )
        port = _env_int("SDWAN_VMANAGE_PORT", DEFAULT_PORT)
        url = f"{host}:{port}" if port != DEFAULT_PORT else host

    username = _env("SDWAN_USERNAME")
    password = os.getenv("SDWAN_PASSWORD", "")
    if not username or not password:
        raise ConfigurationError(
            "Missing credentials. Set SDWAN_USERNAME and SDWAN_PASSWORD."
        )

    ca_bundle = _env("SDWAN_CA_BUNDLE")
    verify: bool | str
    if ca_bundle:
        verify = ca_bundle
    else:
        verify = _env_bool("SDWAN_VERIFY_SSL", True)

    return VManageSettings(
        base_url=_normalise_base_url(url),
        username=username,
        password=password,
        verify=verify,
        timeout=_env_float("SDWAN_TIMEOUT", DEFAULT_TIMEOUT),
        enable_writes=_env_bool("SDWAN_ENABLE_WRITES", False),
        page_size=_env_int("SDWAN_PAGE_SIZE", DEFAULT_PAGE_SIZE),
    )


def writes_enabled() -> bool:
    """Whether configuration-changing tools should be registered.

    Read directly from the environment rather than from :func:`load_settings`
    so it can be evaluated at import time, before credentials are required.
    """
    return _env_bool("SDWAN_ENABLE_WRITES", False)
