"""
Fabric inventory — what devices exist and what shape are they in.

These are the orientation tools: an operator's first question is almost always
"what have I got and is any of it broken", and ``get_fabric_summary`` answers
that in one call rather than making the model page through a device list.
"""

from __future__ import annotations

from cisco_sdwan_mcp.sdwan.client import get_client
from cisco_sdwan_mcp.sdwan.formatting import (
    DEFAULT_LIMIT,
    DEVICE_FIELDS,
    INVENTORY_FIELDS,
    count_by,
    envelope,
    match_device,
    project,
)
from cisco_sdwan_mcp.tools._helpers import DEVICE_PATH, sdwan_tool


@sdwan_tool
async def list_devices(
    device_type: str = "",
    reachability: str = "",
    site_id: str = "",
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """List devices in the SD-WAN fabric with their current status.

    Covers both edge routers and controllers as vManage knows them right now,
    including reachability, site, model and software version.

    Args:
        device_type: Filter by type — "vedge" (edge routers, includes cEdge),
            "vsmart", "vbond" or "vmanage". Empty means every type.
        reachability: Filter by state — "reachable" or "unreachable".
        site_id: Filter by site ID.
        detailed: Return every field vManage reports instead of the summary set.
        limit: Maximum devices to return.
    """
    client = await get_client()
    records = await client.get_data(DEVICE_PATH)

    if device_type:
        wanted = device_type.strip().lower()
        records = [r for r in records if str(r.get("device-type", "")).lower() == wanted]
    if reachability:
        wanted = reachability.strip().lower()
        records = [r for r in records if str(r.get("reachability", "")).lower() == wanted]
    if site_id:
        wanted = site_id.strip()
        records = [r for r in records if str(r.get("site-id", "")) == wanted]

    return envelope(
        project(records, DEVICE_FIELDS, detailed=detailed),
        limit=limit,
        filters={"device_type": device_type, "reachability": reachability,
                 "site_id": site_id} if (device_type or reachability or site_id) else None,
    )


@sdwan_tool
async def get_device(device: str, detailed: bool = True) -> dict:
    """Get the full status record for one device.

    Args:
        device: Hostname, system IP or chassis number.
        detailed: Return every field (the default here — a single device is
            small enough that the full record is usually what you want).
    """
    client = await get_client()
    records = await client.get_data(DEVICE_PATH)

    matches = [r for r in records if match_device(r, device)]
    if not matches:
        known = sorted(str(r.get("host-name")) for r in records if r.get("host-name"))
        return {
            "error": "DeviceNotFound",
            "message": f"No device matches {device!r}.",
            "known_devices": known[:25],
        }

    return {"device": project(matches, DEVICE_FIELDS, detailed=detailed)[0]}


@sdwan_tool
async def get_fabric_summary() -> dict:
    """Summarise fabric health in one call: counts by type, state and version.

    Start here when asked an open question about the network — it is one round
    trip and tells you whether to drill into unreachable devices, control
    connections or alarms next.
    """
    client = await get_client()
    records = await client.get_data(DEVICE_PATH)

    unreachable = [
        {
            "host-name": r.get("host-name"),
            "system-ip": r.get("system-ip"),
            "site-id": r.get("site-id"),
            "device-type": r.get("device-type"),
        }
        for r in records
        if str(r.get("reachability", "")).lower() != "reachable"
    ]

    return {
        "total_devices": len(records),
        "by_type": count_by(records, "device-type"),
        "by_reachability": count_by(records, "reachability"),
        "by_version": count_by(records, "version"),
        "unreachable_count": len(unreachable),
        "unreachable_devices": unreachable[:50],
    }


@sdwan_tool
async def list_inventory(
    category: str = "vedges",
    unattached_only: bool = False,
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """List provisioned devices from vManage's inventory, including offline ones.

    Distinct from ``list_devices``: that reports devices vManage is currently
    talking to, while this reports everything provisioned — useful for finding
    devices that were never onboarded, have invalid certificates or carry no
    device template.

    Args:
        category: "vedges" for edge routers or "controllers" for
            vManage/vSmart/vBond.
        unattached_only: Only return devices with no device template attached.
        detailed: Return every field vManage reports.
        limit: Maximum devices to return.
    """
    path = (
        "/dataservice/system/device/controllers"
        if category.strip().lower().startswith("controller")
        else "/dataservice/system/device/vedges"
    )
    client = await get_client()
    records = await client.get_data(path)

    if unattached_only:
        records = [r for r in records if not r.get("template")]

    return envelope(
        project(records, INVENTORY_FIELDS, detailed=detailed),
        limit=limit,
        category=category,
        by_validity=count_by(records, "validity"),
    )
