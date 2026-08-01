"""
Shared plumbing for the SD-WAN tools.

Two concerns live here so the tool modules stay declarative:

- :func:`sdwan_tool` registers a coroutine with FastMCP and converts SD-WAN
  failures into a structured ``{"error": ..., "message": ...}`` result. A
  wrong password or an unreachable controller is information the model should
  read and relay, not an exception that aborts the tool call.
- :func:`resolve_device_id` turns whatever identifier the user typed into the
  system IP that vManage's real-time endpoints require.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Awaitable, Callable

from cisco_sdwan_mcp.mcp import mcp
from cisco_sdwan_mcp.sdwan.client import get_client
from cisco_sdwan_mcp.sdwan.errors import SDWANError
from cisco_sdwan_mcp.sdwan.formatting import match_device

logger = logging.getLogger(__name__)

DEVICE_PATH = "/dataservice/device"


def sdwan_tool(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Register ``fn`` as an MCP tool with SD-WAN error handling."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except SDWANError as exc:
            logger.warning("%s failed: %s", fn.__name__, exc)
            return {"error": type(exc).__name__, "message": str(exc)}

    return mcp.tool(wrapper)


async def resolve_device_id(device: str) -> str:
    """Resolve a hostname, system IP or chassis number to a system IP.

    vManage's real-time endpoints key on ``deviceId``, which is the device's
    system IP. Users overwhelmingly refer to devices by hostname, so every
    device-scoped tool routes through here first.

    An input that already looks like the system IP of a known device is
    returned unchanged; an unknown identifier raises with the closest
    candidates so the model can suggest a correction.
    """
    client = await get_client()
    devices = await client.get_data(DEVICE_PATH)

    for record in devices:
        if match_device(record, device):
            system_ip = record.get("system-ip") or record.get("deviceId")
            if system_ip:
                return str(system_ip)

    known = sorted(
        str(r.get("host-name")) for r in devices if r.get("host-name")
    )
    hint = ", ".join(known[:10]) if known else "none reported by vManage"
    raise SDWANError(
        f"No device matches {device!r}. Known devices: {hint}"
        + (" …" if len(known) > 10 else "")
    )
