"""
Tests for the read-only SD-WAN tools, driven through FastMCP's in-memory
client so they exercise the same path a real MCP client takes.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastmcp import Client

from cisco_sdwan_mcp.mcp import mcp
from tests.sample_data import DEVICES, READ_ROUTES

# Importing the packages registers every capability (mirrors cisco_sdwan_mcp/server.py).
import cisco_sdwan_mcp.prompts  # noqa: F401
import cisco_sdwan_mcp.resources  # noqa: F401
import cisco_sdwan_mcp.tools  # noqa: F401


async def call(name: str, args: dict | None = None):
    """Invoke a tool and return its structured result."""
    async with Client(mcp) as client:
        result = await client.call_tool(name, args or {})
    if getattr(result, "data", None) is not None:
        return result.data
    return json.loads(result.content[0].text)


@pytest.fixture
def vmanage(vmanage_factory):
    """A fake controller serving the full read-only route set."""
    return vmanage_factory(dict(READ_ROUTES))


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
async def test_list_devices_returns_all_devices(vmanage):
    result = await call("list_devices")

    assert result["count"] == 3
    assert {d["host-name"] for d in result["data"]} == {"BR1-EDGE1", "BR2-EDGE1", "VSMART1"}


async def test_list_devices_filters_by_type_and_reachability(vmanage):
    edges = await call("list_devices", {"device_type": "vedge"})
    assert edges["count"] == 2

    down = await call("list_devices", {"reachability": "unreachable"})
    assert down["count"] == 1
    assert down["data"][0]["host-name"] == "BR2-EDGE1"


async def test_list_devices_projects_to_summary_fields_by_default(vmanage):
    result = await call("list_devices")

    assert "uuid" not in result["data"][0]
    detailed = await call("list_devices", {"detailed": True})
    assert "uuid" in detailed["data"][0]


async def test_list_devices_limit_truncates_and_says_so(vmanage):
    result = await call("list_devices", {"limit": 1})

    assert result["count"] == 3
    assert result["returned"] == 1
    assert result["truncated"] is True


async def test_get_device_accepts_hostname_or_system_ip(vmanage):
    by_name = await call("get_device", {"device": "BR1-EDGE1"})
    by_ip = await call("get_device", {"device": "10.0.0.11"})

    assert by_name["device"]["system-ip"] == "10.0.0.11"
    assert by_ip["device"]["host-name"] == "BR1-EDGE1"


async def test_get_device_unknown_lists_candidates(vmanage):
    result = await call("get_device", {"device": "NOPE"})

    assert result["error"] == "DeviceNotFound"
    assert "BR1-EDGE1" in result["known_devices"]


async def test_get_fabric_summary_highlights_unreachable_devices(vmanage):
    result = await call("get_fabric_summary")

    assert result["total_devices"] == 3
    assert result["by_type"] == {"vedge": 2, "vsmart": 1}
    assert result["unreachable_count"] == 1
    assert result["unreachable_devices"][0]["host-name"] == "BR2-EDGE1"


async def test_list_inventory_can_filter_unattached_devices(vmanage):
    result = await call("list_inventory", {"category": "vedges", "unattached_only": True})

    # No sample device carries a template, so all of them come back.
    assert result["count"] == 2


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------
async def test_get_control_connections_resolves_hostname_to_device_id(vmanage):
    fake, _ = vmanage

    result = await call("get_control_connections", {"device": "BR1-EDGE1"})

    assert result["system_ip"] == "10.0.0.11"
    assert result["by_state"] == {"connect": 1, "up": 1}
    request = fake.last_request_for("/dataservice/device/control/connections")
    assert request.url.params["deviceId"] == "10.0.0.11"


async def test_unknown_device_returns_an_error_with_candidates(vmanage):
    result = await call("get_control_connections", {"device": "GHOST"})

    assert result["error"] == "SDWANError"
    assert "BR1-EDGE1" in result["message"]


async def test_get_bfd_sessions_filters_by_state(vmanage):
    result = await call("get_bfd_sessions", {"device": "BR1-EDGE1", "state": "down"})

    assert result["count"] == 1
    assert result["data"][0]["local-color"] == "biz-internet"
    # The summary still reflects every session, not just the filtered ones.
    assert result["by_state"] == {"down": 1, "up": 1}


async def test_get_interfaces_filters_vpn_locally(vmanage_factory):
    routes = dict(READ_ROUTES)
    routes["/dataservice/device/interface"] = {
        "data": [
            {"ifname": "ge0/0", "vpn-id": "0"},
            {"ifname": "ge0/1", "vpn-id": "10"},
        ]
    }
    fake, _ = vmanage_factory(routes)

    result = await call("get_interfaces", {"device": "BR1-EDGE1", "vpn_id": "0"})

    request = fake.last_request_for("/dataservice/device/interface")
    assert "vpn-id" not in request.url.params
    assert request.url.params["deviceId"] == "10.0.0.11"
    assert result["count"] == 1
    assert result["data"][0]["ifname"] == "ge0/0"


async def test_check_device_health_reports_specific_problems(vmanage):
    result = await call("check_device_health", {"device": "BR1-EDGE1"})

    assert result["healthy"] is False
    assert any("control connections are not up" in p for p in result["problems"])
    assert any("BFD sessions are down" in p for p in result["problems"])
    assert result["control_connections"]["total"] == 2


async def test_check_device_health_survives_a_failing_subsystem(vmanage_factory):
    routes = dict(READ_ROUTES)
    routes["/dataservice/device/bfd/sessions"] = httpx.Response(500, json={})
    vmanage_factory(routes)

    result = await call("check_device_health", {"device": "BR1-EDGE1"})

    # The BFD poll failed, but system status and control connections still report.
    assert result["control_connections"]["total"] == 2
    assert result["bfd_sessions"]["total"] == 0


async def test_get_system_status_without_data_explains_why(vmanage_factory):
    routes = dict(READ_ROUTES)
    routes["/dataservice/device/system/status"] = {"data": []}
    vmanage_factory(routes)

    result = await call("get_system_status", {"device": "BR1-EDGE1"})

    assert result["error"] == "SDWANError"
    assert "likely unreachable" in result["message"]


# ---------------------------------------------------------------------------
# Alarms and events
# ---------------------------------------------------------------------------
async def test_list_alarms_sends_the_lookback_window(vmanage):
    fake, _ = vmanage

    result = await call("list_alarms", {"hours": 12})

    query = json.loads(fake.last_request_for("/dataservice/alarms").url.params["query"])
    assert query["query"]["rules"][0]["value"] == ["12"]
    assert result["by_severity"] == {"critical": 1, "major": 1}


async def test_list_alarms_severity_filter_reaches_vmanage(vmanage):
    fake, _ = vmanage

    await call("list_alarms", {"severity": "critical, major"})

    query = json.loads(fake.last_request_for("/dataservice/alarms").url.params["query"])
    assert query["query"]["rules"][1]["value"] == ["Critical", "Major"]


async def test_list_alarms_rejects_an_unknown_severity(vmanage):
    result = await call("list_alarms", {"severity": "catastrophic"})

    assert result["error"] == "InvalidSeverity"


async def test_list_alarms_active_only(vmanage):
    result = await call("list_alarms", {"active_only": True})

    assert result["count"] == 1
    assert result["data"][0]["component"] == "BFD"


async def test_get_alarm_summary_ranks_affected_devices(vmanage):
    result = await call("get_alarm_summary", {"hours": 24})

    assert result["total_alarms"] == 2
    assert result["active_alarms"] == 1
    assert result["most_affected_devices"] == {"BR2-EDGE1": 2}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
async def test_find_degraded_tunnels_flags_breaches_worst_first(vmanage):
    result = await call("find_degraded_tunnels", {"hours": 1})

    assert result["count"] == 1
    worst = result["data"][0]
    assert worst["local_color"] == "biz-internet"
    assert worst["loss_percentage"] == 7.5
    assert any("loss 7.50%" in b for b in worst["breaches"])
    assert any("latency 310.0ms" in b for b in worst["breaches"])
    assert result["tunnels_examined"] == 2


async def test_find_degraded_tunnels_respects_custom_thresholds(vmanage):
    result = await call(
        "find_degraded_tunnels",
        {"max_loss_percent": 10.0, "max_latency_ms": 500.0, "max_jitter_ms": 100.0},
    )

    assert result["count"] == 0


async def test_get_tunnel_statistics_scopes_to_one_device(vmanage):
    fake, _ = vmanage

    await call("get_tunnel_statistics", {"device": "BR1-EDGE1"})

    query = json.loads(
        fake.last_request_for("/dataservice/statistics/approute").url.params["query"]
    )
    assert query["query"]["rules"][1]["value"] == ["10.0.0.11"]


# ---------------------------------------------------------------------------
# Templates and policies
# ---------------------------------------------------------------------------
async def test_list_device_templates_can_hide_unused_ones(vmanage):
    everything = await call("list_device_templates")
    attached = await call("list_device_templates", {"attached_only": True})

    assert everything["count"] == 2
    assert attached["count"] == 1
    assert attached["data"][0]["templateName"] == "Branch-C8000V"


async def test_list_policies_reports_the_active_policy(vmanage):
    result = await call("list_policies", {"policy_scope": "centralized"})

    assert result["active_policies"] == ["Prod-Central-Policy"]
    assert result["count"] == 2


async def test_list_policies_rejects_an_unknown_scope(vmanage):
    result = await call("list_policies", {"policy_scope": "sideways"})

    assert result["error"] == "InvalidPolicyScope"


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------
async def test_devices_resource_lists_the_fabric(vmanage):
    async with Client(mcp) as client:
        result = await client.read_resource("sdwan://devices")

    payload = json.loads(result[0].text)
    assert payload["count"] == len(DEVICES)
    assert payload["by_reachability"] == {"reachable": 2, "unreachable": 1}


async def test_device_resource_template_addresses_one_device(vmanage):
    async with Client(mcp) as client:
        result = await client.read_resource("sdwan://device/BR1-EDGE1")

    assert json.loads(result[0].text)["system-ip"] == "10.0.0.11"


async def test_config_resource_never_exposes_the_password(vmanage, monkeypatch):
    monkeypatch.setenv("SDWAN_VMANAGE_URL", "https://vmanage.example.com:8443")
    monkeypatch.setenv("SDWAN_USERNAME", "tester")
    monkeypatch.setenv("SDWAN_PASSWORD", "super-secret")

    async with Client(mcp) as client:
        result = await client.read_resource("sdwan://config")

    assert "super-secret" not in result[0].text
    payload = json.loads(result[0].text)
    assert payload["controller"] == "vmanage.example.com:8443"
    assert payload["writes_enabled"] is False


# ---------------------------------------------------------------------------
# Configuration errors reach the user as guidance, not stack traces
# ---------------------------------------------------------------------------
async def test_missing_configuration_is_reported_as_a_readable_error():
    from cisco_sdwan_mcp.sdwan.client import set_client

    set_client(None)  # force the client to build from the (cleaned) environment

    result = await call("list_devices")

    assert result["error"] == "ConfigurationError"
    assert "SDWAN_VMANAGE_URL" in result["message"]
