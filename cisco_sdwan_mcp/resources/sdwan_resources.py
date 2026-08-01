"""
Read-only context an MCP client can pull without calling a tool.

Resources are for orientation — what controller am I pointed at, what devices
exist — so a client can prime its context cheaply before deciding which tools
to invoke.
"""

from __future__ import annotations

import json
import os

from cisco_sdwan_mcp.mcp import mcp
from cisco_sdwan_mcp.sdwan.client import get_client
from cisco_sdwan_mcp.sdwan.config import load_settings, writes_enabled
from cisco_sdwan_mcp.sdwan.errors import SDWANError
from cisco_sdwan_mcp.sdwan.formatting import DEVICE_FIELDS, count_by, match_device, project


def _json(payload: object) -> str:
    return json.dumps(payload, indent=2, default=str)


@mcp.resource("sdwan://config", mime_type="application/json")
def sdwan_config() -> str:
    """Connection settings in effect — never includes credentials."""
    try:
        settings = load_settings()
        configured = {
            "controller": settings.host,
            "username": settings.username,
            "tls_verification": settings.verify,
            "timeout_seconds": settings.timeout,
        }
    except SDWANError as exc:
        configured = {"configured": False, "problem": str(exc)}

    return _json(
        {
            **configured,
            "writes_enabled": writes_enabled(),
            "transport": os.getenv("MCP_TRANSPORT", "http"),
            "auth_mode": os.getenv("MCP_AUTH", "none"),
        }
    )


@mcp.resource("sdwan://devices", mime_type="application/json")
async def sdwan_devices() -> str:
    """Current fabric inventory with per-device status."""
    try:
        client = await get_client()
        records = await client.get_data("/dataservice/device")
    except SDWANError as exc:
        return _json({"error": type(exc).__name__, "message": str(exc)})

    return _json(
        {
            "count": len(records),
            "by_reachability": count_by(records, "reachability"),
            "devices": project(records, DEVICE_FIELDS),
        }
    )


@mcp.resource("sdwan://device/{identifier}", mime_type="application/json")
async def sdwan_device(identifier: str) -> str:
    """Full status record for one device, addressed by hostname or system IP."""
    try:
        client = await get_client()
        records = await client.get_data("/dataservice/device")
    except SDWANError as exc:
        return _json({"error": type(exc).__name__, "message": str(exc)})

    match = next((r for r in records if match_device(r, identifier)), None)
    if match is None:
        return _json(
            {
                "error": "DeviceNotFound",
                "message": f"No device matches {identifier!r}.",
                "known_devices": sorted(
                    str(r.get("host-name")) for r in records if r.get("host-name")
                )[:25],
            }
        )
    return _json(match)
