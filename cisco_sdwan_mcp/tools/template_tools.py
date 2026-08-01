"""
Device templates, feature templates and policies — read-only.

Everything here inspects intended configuration. The tools that *change* it
live in ``config_tools.py`` and are registered only when writes are enabled.
"""

from __future__ import annotations

from cisco_sdwan_mcp.sdwan.client import get_client
from cisco_sdwan_mcp.sdwan.formatting import (
    DEFAULT_LIMIT,
    DEVICE_TEMPLATE_FIELDS,
    FEATURE_TEMPLATE_FIELDS,
    POLICY_FIELDS,
    count_by,
    envelope,
    project,
)
from cisco_sdwan_mcp.tools._helpers import sdwan_tool


@sdwan_tool
async def list_device_templates(
    device_type: str = "",
    attached_only: bool = False,
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """List device templates and how many devices each one is attached to.

    Args:
        device_type: Filter by device type, e.g. "vedge-C8000V".
        attached_only: Only return templates with at least one attached device.
        detailed: Return every field vManage reports.
        limit: Maximum templates to return.
    """
    client = await get_client()
    records = await client.get_data("/dataservice/template/device")

    if device_type:
        wanted = device_type.strip().lower()
        records = [r for r in records if wanted in str(r.get("deviceType", "")).lower()]
    if attached_only:
        records = [r for r in records if int(r.get("devicesAttached") or 0) > 0]

    return envelope(
        project(records, DEVICE_TEMPLATE_FIELDS, detailed=detailed),
        limit=limit,
        by_device_type=count_by(records, "deviceType"),
    )


@sdwan_tool
async def get_device_template(template_id: str, detailed: bool = False) -> dict:
    """Get one device template's definition and the devices attached to it.

    Args:
        template_id: The template's ID, as returned by ``list_device_templates``.
        detailed: Include the full template definition rather than a summary.
    """
    client = await get_client()
    definition = await client.get(f"/dataservice/template/device/object/{template_id}")
    attached = await client.get_data(
        f"/dataservice/template/device/config/attached/{template_id}"
    )

    attached_fields = ("host-name", "deviceIP", "uuid", "personality",
                       "configStatusMessage", "template")
    summary = definition if detailed else {
        key: definition.get(key)
        for key in ("templateId", "templateName", "templateDescription", "deviceType",
                    "configType", "factoryDefault", "policyId", "securityPolicyId")
        if isinstance(definition, dict) and definition.get(key) is not None
    }

    return {
        "template": summary,
        "attached_device_count": len(attached),
        "attached_devices": project(attached, attached_fields)[:50],
    }


@sdwan_tool
async def list_feature_templates(
    template_type: str = "",
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """List feature templates — the building blocks of device templates.

    Args:
        template_type: Filter by type, e.g. "vpn-vedge", "cisco_system", "aaa".
        detailed: Return every field vManage reports.
        limit: Maximum templates to return.
    """
    client = await get_client()
    records = await client.get_data("/dataservice/template/feature")

    if template_type:
        wanted = template_type.strip().lower()
        records = [r for r in records if wanted in str(r.get("templateType", "")).lower()]

    return envelope(
        project(records, FEATURE_TEMPLATE_FIELDS, detailed=detailed),
        limit=limit,
        by_type=dict(list(count_by(records, "templateType").items())[:20]),
    )


@sdwan_tool
async def list_policies(
    policy_scope: str = "centralized",
    detailed: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """List configured policies and which one is currently active.

    Args:
        policy_scope: "centralized" for vSmart policies (traffic engineering,
            app-route, data policy) or "localized" for vEdge/cEdge policies
            (QoS, ACLs, route policy).
        detailed: Return every field vManage reports.
        limit: Maximum policies to return.
    """
    scope = policy_scope.strip().lower()
    if scope.startswith("local"):
        path = "/dataservice/template/policy/vedge"
    elif scope.startswith("cent") or scope.startswith("vsmart"):
        path = "/dataservice/template/policy/vsmart"
    else:
        return {
            "error": "InvalidPolicyScope",
            "message": "policy_scope must be 'centralized' or 'localized'.",
        }

    client = await get_client()
    records = await client.get_data(path)
    active = [r.get("policyName") for r in records if r.get("isPolicyActivated")]

    return envelope(
        project(records, POLICY_FIELDS, detailed=detailed),
        limit=limit,
        policy_scope=scope,
        active_policies=active,
    )


@sdwan_tool
async def get_template_input_variables(template_id: str, device_ids: list[str]) -> dict:
    """Show the per-device variable values a template attachment would use.

    Read-only preview of what ``attach_device_template`` needs. Call this
    first: it returns the variable payload vManage expects, already filled in
    with current values, so the attachment can be reviewed before it runs.

    Args:
        template_id: The device template's ID.
        device_ids: Device UUIDs (chassis numbers) to generate variables for.
    """
    client = await get_client()
    payload = await client.post(
        "/dataservice/template/device/config/input",
        {
            "templateId": template_id,
            "deviceIds": device_ids,
            "isEdited": False,
            "isMasterEdited": False,
        },
    )

    rows = payload.get("data", []) if isinstance(payload, dict) else []
    columns = payload.get("header", {}).get("columns", []) if isinstance(payload, dict) else []

    return {
        "template_id": template_id,
        "device_count": len(rows),
        "variables": [
            {"property": c.get("property"), "title": c.get("title"),
             "editable": c.get("editable")}
            for c in columns
            if isinstance(c, dict)
        ],
        "device_values": rows,
    }
