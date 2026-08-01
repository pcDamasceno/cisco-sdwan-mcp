"""
Exception hierarchy for vManage interactions.

Tools catch :class:`SDWANError` and return the message to the LLM instead of
raising, so a misconfigured controller or an unreachable device produces an
actionable answer rather than an opaque MCP transport error.
"""

from __future__ import annotations


class SDWANError(Exception):
    """Base class for every error raised by the SD-WAN client."""


class ConfigurationError(SDWANError):
    """Required environment variables are missing or malformed."""


class AuthenticationError(SDWANError):
    """vManage rejected the credentials, or the session could not be renewed."""


class APIError(SDWANError):
    """vManage returned an unsuccessful HTTP status."""

    def __init__(self, status_code: int, method: str, path: str, detail: str = "") -> None:
        self.status_code = status_code
        self.method = method
        self.path = path
        self.detail = detail
        message = f"vManage returned HTTP {status_code} for {method} {path}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class WritesDisabledError(SDWANError):
    """A configuration-changing tool was called while writes are disabled."""
