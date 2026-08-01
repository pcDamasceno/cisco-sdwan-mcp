"""
Performance statistics — tunnel quality and interface throughput.

These read vManage's statistics database rather than polling devices, so they
are fast but only as fresh as the last statistics collection cycle (30 minutes
by default on most deployments). For live state use the monitoring tools.
"""

from __future__ import annotations

from typing import Any

from cisco_sdwan_mcp.sdwan.client import get_client
from cisco_sdwan_mcp.sdwan.formatting import (
    APPROUTE_FIELDS,
    DEFAULT_LIMIT,
    build_query,
    envelope,
    project,
    string_rule,
)
from cisco_sdwan_mcp.tools._helpers import resolve_device_id, sdwan_tool

APPROUTE_PATH = "/dataservice/statistics/approute"


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@sdwan_tool
async def get_tunnel_statistics(
    device: str = "",
    hours: float = 1,
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Get application-aware routing statistics: per-tunnel loss, latency and jitter.

    Args:
        device: Restrict to tunnels originating on one device (hostname or
            system IP). Empty means the whole fabric.
        hours: How far back to look. Defaults to the last hour.
        detailed: Return every field vManage reports.
        limit: Maximum tunnel records to return.
    """
    rules = []
    context: dict[str, Any] = {"window_hours": hours}
    if device:
        system_ip = await resolve_device_id(device)
        rules.append(string_rule("local_system_ip", [system_ip]))
        context.update(device=device, system_ip=system_ip)

    client = await get_client()
    records = await client.get_data(
        APPROUTE_PATH,
        {"query": build_query(hours=hours, rules=rules, size=max(limit, DEFAULT_LIMIT))},
    )

    return envelope(
        project(records, APPROUTE_FIELDS, detailed=detailed), limit=limit, **context
    )


@sdwan_tool
async def find_degraded_tunnels(
    hours: float = 1,
    max_loss_percent: float = 2.0,
    max_latency_ms: float = 150.0,
    max_jitter_ms: float = 30.0,
    limit: int = 25,
) -> dict:
    """Find tunnels breaching loss, latency or jitter thresholds, worst first.

    Answers "which paths are hurting" without the caller post-processing a
    fabric-wide statistics dump. Each result says which thresholds it broke.

    Args:
        hours: How far back to look. Defaults to the last hour.
        max_loss_percent: Loss above this percentage counts as degraded.
        max_latency_ms: Latency above this many milliseconds counts as degraded.
        max_jitter_ms: Jitter above this many milliseconds counts as degraded.
        limit: Maximum degraded tunnels to return.
    """
    client = await get_client()
    records = await client.get_data(
        APPROUTE_PATH, {"query": build_query(hours=hours, size=2000)}
    )

    degraded = []
    for record in records:
        loss = _as_float(record.get("loss_percentage"))
        latency = _as_float(record.get("latency"))
        jitter = _as_float(record.get("jitter"))

        breaches = []
        if loss is not None and loss > max_loss_percent:
            breaches.append(f"loss {loss:.2f}% > {max_loss_percent}%")
        if latency is not None and latency > max_latency_ms:
            breaches.append(f"latency {latency:.1f}ms > {max_latency_ms}ms")
        if jitter is not None and jitter > max_jitter_ms:
            breaches.append(f"jitter {jitter:.1f}ms > {max_jitter_ms}ms")
        if not breaches:
            continue

        degraded.append(
            {
                "tunnel": record.get("name"),
                "local_system_ip": record.get("local_system_ip"),
                "remote_system_ip": record.get("remote_system_ip"),
                "local_color": record.get("local_color"),
                "remote_color": record.get("remote_color"),
                "loss_percentage": loss,
                "latency_ms": latency,
                "jitter_ms": jitter,
                "vqoe_score": _as_float(record.get("vqoe_score")),
                "breaches": breaches,
                # Rank by loss first — it degrades traffic faster than latency.
                "_severity": (loss or 0) * 10 + (latency or 0) / 10 + (jitter or 0) / 10,
            }
        )

    degraded.sort(key=lambda t: t["_severity"], reverse=True)
    for tunnel in degraded:
        del tunnel["_severity"]

    return envelope(
        degraded,
        limit=limit,
        window_hours=hours,
        tunnels_examined=len(records),
        thresholds={
            "max_loss_percent": max_loss_percent,
            "max_latency_ms": max_latency_ms,
            "max_jitter_ms": max_jitter_ms,
        },
    )


@sdwan_tool
async def get_interface_statistics(
    device: str,
    hours: float = 1,
    interface_name: str = "",
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Get historical interface throughput and error counters for a device.

    Args:
        device: Hostname, system IP or chassis number.
        hours: How far back to look. Defaults to the last hour.
        interface_name: Restrict to one interface, e.g. "GigabitEthernet1".
        detailed: Return every field vManage reports.
        limit: Maximum records to return.
    """
    system_ip = await resolve_device_id(device)
    rules = [string_rule("vdevice_name", [system_ip])]
    if interface_name:
        rules.append(string_rule("interface", [interface_name.strip()]))

    client = await get_client()
    records = await client.get_data(
        "/dataservice/statistics/interface",
        {"query": build_query(hours=hours, rules=rules, size=max(limit, DEFAULT_LIMIT))},
    )

    fields = (
        "vdevice_name", "interface", "vpn_id", "entry_time", "rx_kbps", "tx_kbps",
        "rx_pps", "tx_pps", "rx_errors", "tx_errors", "rx_drops", "tx_drops",
        "down_capacity_percentage", "up_capacity_percentage", "oper_status",
    )
    return envelope(
        project(records, fields, detailed=detailed),
        limit=limit,
        device=device,
        system_ip=system_ip,
        window_hours=hours,
    )
