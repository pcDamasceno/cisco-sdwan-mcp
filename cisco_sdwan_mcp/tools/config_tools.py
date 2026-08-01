"""
Configuration-changing tools — guarded.

Two independent gates stand in front of every write, because an LLM pushing a
template to a production WAN is the failure mode that matters here:

1. **Registration gate.** This module is imported only when
   ``SDWAN_ENABLE_WRITES=true``. With writes off the tools do not exist — the
   model never sees them, so it cannot call them by mistake.
2. **Confirmation gate.** Each write elicits an explicit approval from the
   user through the MCP client before it runs. Clients that do not implement
   elicitation must instead pass ``confirm=True``, which forces the decision
   into the caller's hands rather than silently proceeding.

vManage applies these changes asynchronously and returns a task ID. Use
``get_task_status`` to follow one to completion — a returned ID means
"accepted", not "applied".
"""

from __future__ import annotations

import logging

from fastmcp import Context
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation

from cisco_sdwan_mcp.sdwan.client import get_client
from cisco_sdwan_mcp.tools._helpers import sdwan_tool

logger = logging.getLogger(__name__)


async def _confirmed(ctx: Context, prompt: str, confirm: bool) -> tuple[bool, str]:
    """Get the user's approval for a write.

    Prefers MCP elicitation, so the human sees exactly what is about to
    happen. Falls back to the caller-supplied ``confirm`` flag only when the
    client cannot elicit.
    """
    try:
        result = await ctx.elicit(prompt, response_type=None)
    except Exception as exc:  # client does not support elicitation
        logger.info("Elicitation unavailable (%s) — falling back to confirm flag.", exc)
        if confirm:
            return True, "Approved via confirm=True (client cannot prompt interactively)."
        return False, (
            "This change needs approval, and this MCP client does not support "
            "interactive prompts. Re-run with confirm=True to proceed."
        )

    if isinstance(result, AcceptedElicitation):
        return True, "Approved by the user."
    if isinstance(result, DeclinedElicitation):
        return False, "Declined by the user — no change was made."
    return False, "Cancelled by the user — no change was made."


@sdwan_tool
async def attach_device_template(
    template_id: str,
    device_variables: list[dict],
    ctx: Context,
    confirm: bool = False,
) -> dict:
    """Attach a device template to devices, pushing configuration to them.

    This changes production configuration. Call
    ``get_template_input_variables`` first to build and review
    ``device_variables``, then pass its ``device_values`` here unchanged.

    Args:
        template_id: The device template's ID.
        device_variables: One entry per device, from
            ``get_template_input_variables``'s ``device_values``.
        confirm: Approve the change when the client cannot prompt
            interactively. Ignored when elicitation is available.
    """
    if not device_variables:
        return {
            "error": "NoDevices",
            "message": "device_variables is empty — nothing to attach.",
        }

    hostnames = [
        str(d.get("csv-host-name") or d.get("csv-deviceId") or "?")
        for d in device_variables
    ]
    approved, reason = await _confirmed(
        ctx,
        f"Attach device template {template_id} to {len(device_variables)} device(s): "
        f"{', '.join(hostnames)}. This pushes configuration to production devices. Proceed?",
        confirm,
    )
    if not approved:
        return {"applied": False, "reason": reason, "template_id": template_id}

    client = await get_client()
    payload = await client.post(
        "/dataservice/template/device/config/attachfeature",
        {
            "deviceTemplateList": [
                {
                    "templateId": template_id,
                    "device": device_variables,
                    "isEdited": False,
                    "isMasterEdited": False,
                }
            ]
        },
    )

    task_id = payload.get("id") if isinstance(payload, dict) else None
    logger.info("Template %s attach accepted as task %s", template_id, task_id)
    return {
        "applied": True,
        "reason": reason,
        "template_id": template_id,
        "devices": hostnames,
        "task_id": task_id,
        "note": "vManage accepted the request. Poll get_task_status(task_id) "
                "until it reports done before treating the push as complete.",
    }


@sdwan_tool
async def activate_vsmart_policy(
    policy_id: str,
    ctx: Context,
    confirm: bool = False,
) -> dict:
    """Activate a centralized (vSmart) policy across the fabric.

    This changes production traffic handling fabric-wide — activating a policy
    deactivates whichever one is currently live. Review the target with
    ``list_policies`` first.

    Args:
        policy_id: The vSmart policy's ID, from ``list_policies``.
        confirm: Approve the change when the client cannot prompt
            interactively. Ignored when elicitation is available.
    """
    client = await get_client()

    policies = await client.get_data("/dataservice/template/policy/vsmart")
    target = next((p for p in policies if p.get("policyId") == policy_id), None)
    if target is None:
        return {
            "error": "PolicyNotFound",
            "message": f"No vSmart policy with ID {policy_id!r}.",
            "known_policies": [
                {"policyId": p.get("policyId"), "policyName": p.get("policyName")}
                for p in policies[:25]
            ],
        }
    currently_active = [p.get("policyName") for p in policies if p.get("isPolicyActivated")]

    approved, reason = await _confirmed(
        ctx,
        f"Activate centralized policy {target.get('policyName')!r} ({policy_id}) "
        f"across the fabric"
        + (f", replacing the active policy {currently_active}" if currently_active else "")
        + ". This changes traffic handling on every vSmart. Proceed?",
        confirm,
    )
    if not approved:
        return {"applied": False, "reason": reason, "policy_id": policy_id}

    payload = await client.post(
        f"/dataservice/template/policy/vsmart/activate/{policy_id}", {}
    )
    task_id = payload.get("id") if isinstance(payload, dict) else None
    logger.info("vSmart policy %s activation accepted as task %s", policy_id, task_id)
    return {
        "applied": True,
        "reason": reason,
        "policy_id": policy_id,
        "policy_name": target.get("policyName"),
        "replaced": currently_active,
        "task_id": task_id,
        "note": "vManage accepted the request. Poll get_task_status(task_id) "
                "until it reports done before treating the activation as complete.",
    }


@sdwan_tool
async def get_task_status(task_id: str) -> dict:
    """Check whether an asynchronous vManage task has finished.

    Args:
        task_id: The task ID returned by a configuration-changing tool.
    """
    client = await get_client()
    payload = await client.get(f"/dataservice/device/action/status/{task_id}")

    if not isinstance(payload, dict):
        return {"task_id": task_id, "status": "unknown", "raw": payload}

    summary = payload.get("summary") or {}
    devices = payload.get("data") or []
    return {
        "task_id": task_id,
        "status": summary.get("status"),
        "total": summary.get("total"),
        "count": summary.get("count"),
        "devices": [
            {
                "host-name": d.get("host-name"),
                "deviceID": d.get("deviceID"),
                "status": d.get("status"),
                "currentActivity": d.get("currentActivity"),
                "activity": d.get("activity"),
            }
            for d in devices
            if isinstance(d, dict)
        ][:50],
    }
