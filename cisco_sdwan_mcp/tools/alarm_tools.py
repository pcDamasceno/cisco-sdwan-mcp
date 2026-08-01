"""
Alarms and events.

Both endpoints take vManage's JSON ``query`` parameter rather than plain
query-string filters, so the look-back window and severity filters are built
by :func:`~cisco_sdwan_mcp.sdwan.formatting.build_query`. Without a window vManage
defaults to a narrow slice of recent history, which is why every tool here
takes an explicit ``hours``.
"""

from __future__ import annotations

from cisco_sdwan_mcp.sdwan.client import get_client
from cisco_sdwan_mcp.sdwan.formatting import (
    ALARM_FIELDS,
    DEFAULT_LIMIT,
    EVENT_FIELDS,
    build_query,
    count_by,
    envelope,
    project,
    string_rule,
)
from cisco_sdwan_mcp.tools._helpers import sdwan_tool

SEVERITIES = ("critical", "major", "medium", "minor")


@sdwan_tool
async def list_alarms(
    hours: float = 24,
    severity: str = "",
    active_only: bool = False,
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """List fabric alarms raised in a recent time window.

    Args:
        hours: How far back to look. Defaults to the last 24 hours.
        severity: Comma-separated severities to include — any of
            "critical", "major", "medium", "minor". Empty means all.
        active_only: Only return alarms that are still active (not cleared).
        detailed: Return every field vManage reports.
        limit: Maximum alarms to return.
    """
    rules = []
    if severity:
        wanted = [s.strip().lower() for s in severity.split(",") if s.strip()]
        invalid = [s for s in wanted if s not in SEVERITIES]
        if invalid:
            return {
                "error": "InvalidSeverity",
                "message": f"Unknown severity {invalid}. Valid values: {list(SEVERITIES)}.",
            }
        # Alarm severities are case-sensitive in vManage's query API and are
        # stored as ``Critical``, ``Major``, etc. Keep accepting ergonomic,
        # case-insensitive tool input, but send the controller's canonical form.
        rules.append(string_rule("severity", [severity.title() for severity in wanted]))

    client = await get_client()
    records = await client.get_data(
        "/dataservice/alarms",
        {"query": build_query(hours=hours, rules=rules, size=max(limit, DEFAULT_LIMIT))},
    )

    if active_only:
        records = [r for r in records if r.get("active") is True]

    return envelope(
        project(records, ALARM_FIELDS, detailed=detailed),
        limit=limit,
        window_hours=hours,
        by_severity=count_by(records, "severity"),
        by_component=count_by(records, "component"),
    )


@sdwan_tool
async def get_alarm_summary(hours: float = 24) -> dict:
    """Summarise alarm counts by severity and component without listing them.

    Cheap situational awareness — call this before ``list_alarms`` to decide
    which severity is worth pulling in full.

    Args:
        hours: How far back to look. Defaults to the last 24 hours.
    """
    client = await get_client()
    records = await client.get_data(
        "/dataservice/alarms", {"query": build_query(hours=hours, size=1000)}
    )

    active = [r for r in records if r.get("active") is True]
    return {
        "window_hours": hours,
        "total_alarms": len(records),
        "active_alarms": len(active),
        "by_severity": count_by(records, "severity"),
        "by_component": count_by(records, "component"),
        "top_rules": dict(list(count_by(records, "rule_name_display").items())[:10]),
        "most_affected_devices": dict(list(count_by(records, "host_name").items())[:10]),
    }


@sdwan_tool
async def list_events(
    hours: float = 6,
    severity: str = "",
    component: str = "",
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """List fabric events in a recent time window.

    Events are the raw log stream behind alarms — noisier, but they show
    transitions (interface flaps, BFD state changes, reboots) that never
    become alarms.

    Args:
        hours: How far back to look. Defaults to the last 6 hours, since
            events are high volume.
        severity: Comma-separated levels — "critical", "major", "minor". Empty
            means all.
        component: Filter by component, e.g. "BFD", "OMP", "System".
        detailed: Return every field vManage reports.
        limit: Maximum events to return.
    """
    rules = []
    if severity:
        wanted = [s.strip().lower() for s in severity.split(",") if s.strip()]
        rules.append(string_rule("severity_level", wanted))
    if component:
        rules.append(string_rule("component", [component.strip()]))

    client = await get_client()
    records = await client.get_data(
        "/dataservice/event",
        {"query": build_query(hours=hours, rules=rules, size=max(limit, DEFAULT_LIMIT))},
    )

    return envelope(
        project(records, EVENT_FIELDS, detailed=detailed),
        limit=limit,
        window_hours=hours,
        by_severity=count_by(records, "severity_level"),
        by_component=count_by(records, "component"),
    )
