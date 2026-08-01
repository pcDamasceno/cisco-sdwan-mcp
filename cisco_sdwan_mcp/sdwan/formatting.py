"""
Shaping vManage payloads for an LLM.

vManage records are wide — a single device object carries 60+ fields, and a
fabric of 200 devices easily exceeds a model's context window. Every tool
therefore projects responses down to the fields that answer the question and
offers a ``detailed`` escape hatch for the full record.

This module also builds vManage's ``query`` parameter, the JSON rule structure
its alarm, event and statistics endpoints expect.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Sequence

#: Cap on records returned by a single tool call, so one broad question cannot
#: flood the model's context. Tools expose it as a ``limit`` argument.
DEFAULT_LIMIT = 100


def project(
    records: Iterable[dict],
    fields: Sequence[str],
    *,
    detailed: bool = False,
) -> list[dict]:
    """Keep only ``fields`` from each record, dropping keys that are absent.

    Passing ``detailed=True`` returns the records untouched — used by tools
    that let the caller ask for everything vManage knows.
    """
    if detailed:
        return list(records)
    projected = []
    for record in records:
        slim = {field: record[field] for field in fields if record.get(field) is not None}
        if slim:
            projected.append(slim)
    return projected


def truncate(records: list[dict], limit: int) -> tuple[list[dict], bool]:
    """Cut a result set to ``limit`` records, reporting whether it was cut."""
    if limit <= 0 or len(records) <= limit:
        return records, False
    return records[:limit], True


def envelope(
    records: list[dict],
    *,
    limit: int = DEFAULT_LIMIT,
    total: int | None = None,
    **context: Any,
) -> dict:
    """Wrap results with the counts and context a model needs to reason.

    Always reporting ``total`` alongside ``returned`` keeps the model honest:
    it can tell "3 devices are down" from "3 devices are down in the first 100
    I looked at".
    """
    total = len(records) if total is None else total
    rows, was_truncated = truncate(records, limit)
    result: dict[str, Any] = {"count": total, "returned": len(rows)}
    result.update(context)
    result["data"] = rows
    if was_truncated:
        result["truncated"] = True
        result["note"] = (
            f"Showing the first {len(rows)} of {total} records. "
            "Raise `limit` or narrow the filters to see more."
        )
    return result


def build_query(
    *,
    hours: float | None = None,
    rules: Sequence[dict] | None = None,
    size: int | None = None,
) -> str:
    """Build the JSON ``query`` parameter vManage expects.

    Args:
        hours: Look-back window, expressed as vManage's ``last_n_hours`` rule.
        rules: Extra rule dicts, already in vManage's rule format.
        size: Maximum records vManage itself should return.

    Returns:
        A compact JSON string, ready to pass as the ``query`` request param.
    """
    all_rules: list[dict] = []
    if hours is not None:
        all_rules.append(
            {
                "value": [str(int(hours))],
                "field": "entry_time",
                "type": "date",
                "operator": "last_n_hours",
            }
        )
    all_rules.extend(rules or [])

    query: dict[str, Any] = {}
    if all_rules:
        query["query"] = {"condition": "AND", "rules": all_rules}
    if size is not None:
        query["size"] = size
    return json.dumps(query, separators=(",", ":"))


def string_rule(field: str, values: Sequence[str]) -> dict:
    """A vManage ``in`` rule matching ``field`` against any of ``values``."""
    return {
        "value": list(values),
        "field": field,
        "type": "string",
        "operator": "in",
    }


def count_by(records: Iterable[dict], field: str) -> dict[str, int]:
    """Tally records by a field — turns a device list into a status summary."""
    counts: dict[str, int] = {}
    for record in records:
        key = str(record.get(field, "unknown"))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def match_device(record: dict, needle: str) -> bool:
    """Case-insensitive match of a device record against a user's identifier.

    Users refer to devices by hostname, system IP or chassis number
    interchangeably; tools accept any of them.
    """
    needle = needle.strip().lower()
    if not needle:
        return False
    for field in ("host-name", "hostname", "system-ip", "deviceId", "chasisNumber",
                  "uuid", "deviceIP"):
        value = record.get(field)
        if value is not None and str(value).strip().lower() == needle:
            return True
    return False


# ---------------------------------------------------------------------------
# Field sets — the projection each tool applies by default.
# ---------------------------------------------------------------------------
DEVICE_FIELDS = (
    "host-name", "system-ip", "site-id", "device-type", "device-model",
    "reachability", "status", "version", "uptime-date", "personality",
    "board-serial", "device-groups", "controlConnections", "bfdSessionsUp",
)

INVENTORY_FIELDS = (
    "host-name", "system-ip", "site-id", "deviceType", "deviceModel",
    "validity", "vedgeCertificateState", "uuid", "chasisNumber",
    "configStatusMessage", "template", "version",
)

CONTROL_CONNECTION_FIELDS = (
    "system-ip", "peer-type", "peer-system-ip", "site-id", "state",
    "local-color", "remote-color", "protocol", "private-ip", "public-ip",
    "uptime", "behind-proxy",
)

BFD_SESSION_FIELDS = (
    "system-ip", "site-id", "state", "local-color", "color", "src-ip",
    "dst-ip", "proto", "uptime", "transitions", "detect-multiplier",
)

OMP_PEER_FIELDS = (
    "peer", "type", "site-id", "state", "domain-id", "up-time",
    "refresh", "region-id",
)

INTERFACE_FIELDS = (
    "ifname", "vpn-id", "af-type", "ip-address", "ipv6-address", "if-admin-status",
    "if-oper-status", "port-type", "speed-mbps", "duplex", "encap-type",
    "rx-packets", "tx-packets", "rx-errors", "tx-errors", "rx-drops", "tx-drops",
)

ALARM_FIELDS = (
    "severity", "severity_number", "component", "rule_name_display",
    "entry_time", "devices", "message", "acknowledged", "active", "uuid",
    "system_ip", "host_name", "values_short_display",
)

EVENT_FIELDS = (
    "severity_level", "component", "eventname", "entry_time", "system_ip",
    "host_name", "details", "vpnid", "eventname_tag",
)

APPROUTE_FIELDS = (
    "name", "vdevice_name", "local_system_ip", "remote_system_ip", "local_color",
    "remote_color", "latency", "loss_percentage", "jitter", "vqoe_score",
    "total_packets", "tunnel_color", "state", "entry_time", "src_ip", "dest_ip",
)

DEVICE_TEMPLATE_FIELDS = (
    "templateId", "templateName", "templateDescription", "deviceType",
    "devicesAttached", "templateAttached", "lastUpdatedBy", "lastUpdatedOn",
    "configType", "factoryDefault",
)

FEATURE_TEMPLATE_FIELDS = (
    "templateId", "templateName", "templateDescription", "templateType",
    "deviceType", "devicesAttached", "lastUpdatedBy", "lastUpdatedOn",
    "factoryDefault",
)

POLICY_FIELDS = (
    "policyId", "policyName", "policyDescription", "policyType",
    "isPolicyActivated", "lastUpdatedBy", "lastUpdatedOn", "policyVersion",
)

SYSTEM_STATUS_FIELDS = (
    "vdevice-host-name", "vdevice-name", "state", "uptime", "reboot_reason",
    "mem_used", "mem_free", "mem_total", "disk_avail", "cpu_user", "cpu_system",
    "cpu_idle", "total_cpu_count", "version", "personality",
)
