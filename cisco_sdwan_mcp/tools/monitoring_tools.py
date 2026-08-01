"""
Real-time device state — the control plane, data plane and system health.

Every tool here hits vManage's real-time API, which polls the device on
demand. Responses reflect the device's live state, but each call costs a
round trip to the edge: prefer ``check_device_health`` over three separate
calls when triaging, and expect these to be slower than the inventory tools.
"""

from __future__ import annotations

from cisco_sdwan_mcp.sdwan.client import get_client
from cisco_sdwan_mcp.sdwan.errors import SDWANError
from cisco_sdwan_mcp.sdwan.formatting import (
    BFD_SESSION_FIELDS,
    CONTROL_CONNECTION_FIELDS,
    DEFAULT_LIMIT,
    INTERFACE_FIELDS,
    OMP_PEER_FIELDS,
    SYSTEM_STATUS_FIELDS,
    count_by,
    envelope,
    project,
)
from cisco_sdwan_mcp.tools._helpers import resolve_device_id, sdwan_tool


@sdwan_tool
async def get_control_connections(
    device: str, detailed: bool = False, limit: int = DEFAULT_LIMIT
) -> dict:
    """Show a device's control-plane connections to vSmart, vBond and vManage.

    The first thing to check when a device is unreachable or will not come up:
    without control connections the device has no OMP routes and no policy.

    Args:
        device: Hostname, system IP or chassis number.
        detailed: Return every field vManage reports.
        limit: Maximum connections to return.
    """
    system_ip = await resolve_device_id(device)
    client = await get_client()
    records = await client.get_data(
        "/dataservice/device/control/connections", {"deviceId": system_ip}
    )

    return envelope(
        project(records, CONTROL_CONNECTION_FIELDS, detailed=detailed),
        limit=limit,
        device=device,
        system_ip=system_ip,
        by_state=count_by(records, "state"),
        by_peer_type=count_by(records, "peer-type"),
    )


@sdwan_tool
async def get_bfd_sessions(
    device: str,
    state: str = "",
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Show a device's BFD sessions — the data-plane tunnels to other edges.

    A BFD session in any state other than "up" means traffic cannot use that
    tunnel. Check this when sites can reach the controllers but not each other.

    Args:
        device: Hostname, system IP or chassis number.
        state: Filter by session state, e.g. "up" or "down".
        detailed: Return every field vManage reports.
        limit: Maximum sessions to return.
    """
    system_ip = await resolve_device_id(device)
    client = await get_client()
    records = await client.get_data(
        "/dataservice/device/bfd/sessions", {"deviceId": system_ip}
    )

    by_state = count_by(records, "state")
    if state:
        wanted = state.strip().lower()
        records = [r for r in records if str(r.get("state", "")).lower() == wanted]

    return envelope(
        project(records, BFD_SESSION_FIELDS, detailed=detailed),
        limit=limit,
        device=device,
        system_ip=system_ip,
        by_state=by_state,
    )


@sdwan_tool
async def get_omp_peers(
    device: str, detailed: bool = False, limit: int = DEFAULT_LIMIT
) -> dict:
    """Show a device's OMP peering sessions and their state.

    OMP is how SD-WAN distributes routes. Control connections up but OMP peers
    down means the overlay has no reachability information.

    Args:
        device: Hostname, system IP or chassis number.
        detailed: Return every field vManage reports.
        limit: Maximum peers to return.
    """
    system_ip = await resolve_device_id(device)
    client = await get_client()
    records = await client.get_data(
        "/dataservice/device/omp/peers", {"deviceId": system_ip}
    )

    return envelope(
        project(records, OMP_PEER_FIELDS, detailed=detailed),
        limit=limit,
        device=device,
        system_ip=system_ip,
        by_state=count_by(records, "state"),
    )


@sdwan_tool
async def get_interfaces(
    device: str,
    vpn_id: str = "",
    interface_name: str = "",
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Show a device's interfaces with status, addressing and error counters.

    Args:
        device: Hostname, system IP or chassis number.
        vpn_id: Restrict to one VPN, e.g. "0" for the transport VPN.
        interface_name: Restrict to one interface, e.g. "GigabitEthernet1".
        detailed: Return every field vManage reports.
        limit: Maximum interfaces to return.
    """
    system_ip = await resolve_device_id(device)
    params: dict[str, str] = {"deviceId": system_ip}
    if interface_name:
        params["ifname"] = interface_name.strip()

    client = await get_client()
    records = await client.get_data("/dataservice/device/interface", params)
    # The real-time interface endpoint returns an empty data set when
    # ``vpn-id`` is supplied (including on current 20.15 controllers), even
    # though the same VPN is present in the unfiltered response. Filter the
    # returned records locally instead.
    if vpn_id:
        wanted_vpn = vpn_id.strip()
        records = [r for r in records if str(r.get("vpn-id", "")) == wanted_vpn]

    return envelope(
        project(records, INTERFACE_FIELDS, detailed=detailed),
        limit=limit,
        device=device,
        system_ip=system_ip,
        by_oper_status=count_by(records, "if-oper-status"),
    )


@sdwan_tool
async def get_system_status(device: str, detailed: bool = False) -> dict:
    """Show a device's system health: uptime, CPU, memory, disk and last reboot.

    Args:
        device: Hostname, system IP or chassis number.
        detailed: Return every field vManage reports.
    """
    system_ip = await resolve_device_id(device)
    client = await get_client()
    records = await client.get_data(
        "/dataservice/device/system/status", {"deviceId": system_ip}
    )
    if not records:
        raise SDWANError(
            f"vManage returned no system status for {device!r} ({system_ip}). "
            "The device is likely unreachable — check control connections."
        )

    return {
        "device": device,
        "system_ip": system_ip,
        "status": project(records, SYSTEM_STATUS_FIELDS, detailed=detailed)[0],
    }


@sdwan_tool
async def check_device_health(device: str) -> dict:
    """Triage one device in a single call: system health, control plane, data plane.

    Aggregates system status, control connections and BFD sessions, then
    reports what is wrong rather than making the caller compare three result
    sets. Use this as the entry point for "why is site X down".

    Args:
        device: Hostname, system IP or chassis number.
    """
    system_ip = await resolve_device_id(device)
    client = await get_client()

    async def safe(path: str) -> list[dict]:
        """One subsystem being unreachable should not sink the whole report."""
        try:
            return await client.get_data(path, {"deviceId": system_ip})
        except SDWANError:
            return []

    status = await safe("/dataservice/device/system/status")
    control = await safe("/dataservice/device/control/connections")
    bfd = await safe("/dataservice/device/bfd/sessions")

    control_states = count_by(control, "state")
    bfd_states = count_by(bfd, "state")
    control_up = control_states.get("up", 0)
    bfd_up = bfd_states.get("up", 0)

    problems: list[str] = []
    if not status:
        problems.append("Device did not answer the system status poll — likely unreachable.")
    if not control:
        problems.append("No control connections reported — device is isolated from the controllers.")
    elif control_up < len(control):
        problems.append(
            f"{len(control) - control_up} of {len(control)} control connections are not up."
        )
    if bfd and bfd_up < len(bfd):
        problems.append(
            f"{len(bfd) - bfd_up} of {len(bfd)} BFD sessions are down — "
            "some site-to-site paths are unusable."
        )
    if not bfd:
        problems.append("No BFD sessions reported — no data-plane tunnels are established.")

    return {
        "device": device,
        "system_ip": system_ip,
        "healthy": not problems,
        "problems": problems,
        "system_status": project(status, SYSTEM_STATUS_FIELDS)[0] if status else None,
        "control_connections": {"total": len(control), "by_state": control_states},
        "bfd_sessions": {"total": len(bfd), "by_state": bfd_states},
    }
