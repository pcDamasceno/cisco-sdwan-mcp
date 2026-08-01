"""
Tests for the guarded write tools.

The point of these tests is the *gate*, not the payload: a write must not
reach vManage unless a human approved it, and a client that cannot prompt must
not be treated as approval.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from cisco_sdwan_mcp.mcp import mcp
from tests.sample_data import DEVICE_TEMPLATES, VSMART_POLICIES

# Write tools register on import; the server only imports this module when
# SDWAN_ENABLE_WRITES is true.
import cisco_sdwan_mcp.tools.config_tools  # noqa: F401

ATTACH_PATH = "/dataservice/template/device/config/attachfeature"
ACTIVATE_PATH = "/dataservice/template/policy/vsmart/activate/pol-002"

WRITE_ROUTES = {
    "/dataservice/template/device": {"data": DEVICE_TEMPLATES},
    "/dataservice/template/policy/vsmart": {"data": VSMART_POLICIES},
    ATTACH_PATH: {"id": "task-abc"},
    ACTIVATE_PATH: {"id": "task-def"},
    "/dataservice/device/action/status/task-abc": {
        "summary": {"status": "done", "total": 1, "count": 1},
        "data": [{"host-name": "BR1-EDGE1", "status": "Success",
                  "activity": ["Configuration applied"]}],
    },
}

DEVICE_VARIABLES = [
    {"csv-deviceId": "C8K-AAAA-0001", "csv-host-name": "BR1-EDGE1",
     "csv-status": "complete", "//system/host-name": "BR1-EDGE1"}
]


async def call(name: str, args: dict, *, elicit=None):
    async with Client(mcp, elicitation_handler=elicit) as client:
        result = await client.call_tool(name, args)
    if getattr(result, "data", None) is not None:
        return result.data
    return json.loads(result.content[0].text)


async def accept(message, response_type, params, ctx):
    return None  # plain accept


async def decline(message, response_type, params, ctx):
    return ElicitResult(action="decline")


@pytest.fixture
def vmanage(vmanage_factory):
    return vmanage_factory(dict(WRITE_ROUTES))


# ---------------------------------------------------------------------------
# attach_device_template
# ---------------------------------------------------------------------------
async def test_attach_applies_after_the_user_approves(vmanage):
    fake, _ = vmanage

    result = await call(
        "attach_device_template",
        {"template_id": "tmpl-001", "device_variables": DEVICE_VARIABLES},
        elicit=accept,
    )

    assert result["applied"] is True
    assert result["task_id"] == "task-abc"
    body = fake.json_body(ATTACH_PATH)
    assert body["deviceTemplateList"][0]["templateId"] == "tmpl-001"
    assert body["deviceTemplateList"][0]["device"] == DEVICE_VARIABLES


async def test_attach_does_not_call_vmanage_when_declined(vmanage):
    fake, _ = vmanage

    result = await call(
        "attach_device_template",
        {"template_id": "tmpl-001", "device_variables": DEVICE_VARIABLES},
        elicit=decline,
    )

    assert result["applied"] is False
    assert "Declined" in result["reason"]
    assert ATTACH_PATH not in fake.paths()


async def test_attach_refuses_when_the_client_cannot_prompt(vmanage):
    fake, _ = vmanage

    # No elicitation handler — the client cannot ask the user.
    result = await call(
        "attach_device_template",
        {"template_id": "tmpl-001", "device_variables": DEVICE_VARIABLES},
    )

    assert result["applied"] is False
    assert "confirm=True" in result["reason"]
    assert ATTACH_PATH not in fake.paths()


async def test_attach_accepts_the_explicit_confirm_fallback(vmanage):
    fake, _ = vmanage

    result = await call(
        "attach_device_template",
        {"template_id": "tmpl-001", "device_variables": DEVICE_VARIABLES,
         "confirm": True},
    )

    assert result["applied"] is True
    assert ATTACH_PATH in fake.paths()


async def test_attach_rejects_an_empty_device_list(vmanage):
    result = await call(
        "attach_device_template",
        {"template_id": "tmpl-001", "device_variables": [], "confirm": True},
    )

    assert result["error"] == "NoDevices"


# ---------------------------------------------------------------------------
# activate_vsmart_policy
# ---------------------------------------------------------------------------
async def test_activate_reports_the_policy_it_replaces(vmanage):
    fake, _ = vmanage

    result = await call("activate_vsmart_policy", {"policy_id": "pol-002"},
                        elicit=accept)

    assert result["applied"] is True
    assert result["policy_name"] == "Maintenance-Policy"
    assert result["replaced"] == ["Prod-Central-Policy"]
    assert result["task_id"] == "task-def"
    assert ACTIVATE_PATH in fake.paths()


async def test_activate_unknown_policy_lists_the_real_ones(vmanage):
    fake, _ = vmanage

    result = await call("activate_vsmart_policy", {"policy_id": "nope"},
                        elicit=accept)

    assert result["error"] == "PolicyNotFound"
    assert {p["policyId"] for p in result["known_policies"]} == {"pol-001", "pol-002"}
    assert not any("activate" in p for p in fake.paths())


async def test_activate_does_not_call_vmanage_when_declined(vmanage):
    fake, _ = vmanage

    result = await call("activate_vsmart_policy", {"policy_id": "pol-002"},
                        elicit=decline)

    assert result["applied"] is False
    assert ACTIVATE_PATH not in fake.paths()


# ---------------------------------------------------------------------------
# get_task_status
# ---------------------------------------------------------------------------
async def test_get_task_status_summarises_the_task(vmanage):
    result = await call("get_task_status", {"task_id": "task-abc"})

    assert result["status"] == "done"
    assert result["total"] == 1
    assert result["devices"][0]["host-name"] == "BR1-EDGE1"
