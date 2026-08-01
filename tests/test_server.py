"""
Server-level tests: capability registration, the write gate, and the
unauthenticated routes probes rely on.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from starlette.testclient import TestClient

from cisco_sdwan_mcp.mcp import LOCALHOST_ORIGIN, _render_readme_html, mcp

# Import the capability packages so all decorators run (mirrors cisco_sdwan_mcp/server.py)
import cisco_sdwan_mcp.prompts  # noqa: F401
import cisco_sdwan_mcp.resources  # noqa: F401
import cisco_sdwan_mcp.tools  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[1]

READ_TOOLS = {
    "list_devices", "get_device", "get_fabric_summary", "list_inventory",
    "get_control_connections", "get_bfd_sessions", "get_omp_peers",
    "get_interfaces", "get_system_status", "check_device_health",
    "list_alarms", "get_alarm_summary", "list_events",
    "get_tunnel_statistics", "find_degraded_tunnels", "get_interface_statistics",
    "list_device_templates", "get_device_template", "list_feature_templates",
    "list_policies", "get_template_input_variables",
}
WRITE_TOOLS = {"attach_device_template", "activate_vsmart_policy", "get_task_status"}


# ---------------------------------------------------------------------------
# Capability registration
# ---------------------------------------------------------------------------
async def test_all_read_tools_are_registered():
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}

    assert READ_TOOLS <= names


async def test_resources_and_prompts_are_registered():
    async with Client(mcp) as client:
        resource_uris = {str(r.uri) for r in await client.list_resources()}
        template_uris = {str(t.uriTemplate) for t in await client.list_resource_templates()}
        prompt_names = {p.name for p in await client.list_prompts()}

    assert {"sdwan://config", "sdwan://devices"} <= resource_uris
    assert "sdwan://device/{identifier}" in template_uris
    assert {"troubleshoot_device", "fabric_health_report", "analyse_path_quality",
            "review_template_change"} <= prompt_names


async def test_every_tool_documents_itself_for_the_model():
    async with Client(mcp) as client:
        tools = await client.list_tools()

    undocumented = [t.name for t in tools if not (t.description or "").strip()]
    assert undocumented == []


# ---------------------------------------------------------------------------
# The write gate — verified in a fresh interpreter, since tool registration is
# a one-time import side effect that other tests in this session have already
# triggered.
# ---------------------------------------------------------------------------
def _registered_tools(**env_overrides: str) -> set[str]:
    code = (
        "import asyncio, json\n"
        "from fastmcp import Client\n"
        "import cisco_sdwan_mcp.tools\n"
        "from cisco_sdwan_mcp.mcp import mcp\n"
        "async def main():\n"
        "    async with Client(mcp) as c:\n"
        "        print(json.dumps(sorted(t.name for t in await c.list_tools())))\n"
        "asyncio.run(main())\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("SDWAN_")}
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.update(env_overrides)

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"subprocess failed:\n{result.stdout}\n{result.stderr}")
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


def test_write_tools_are_absent_by_default():
    names = _registered_tools()

    assert READ_TOOLS <= names
    assert names & WRITE_TOOLS == set(), (
        "Configuration-changing tools must not be registered without "
        "SDWAN_ENABLE_WRITES=true."
    )


def test_write_tools_appear_when_explicitly_enabled():
    names = _registered_tools(SDWAN_ENABLE_WRITES="true")

    assert WRITE_TOOLS <= names


def test_write_gate_ignores_ambiguous_values():
    assert _registered_tools(SDWAN_ENABLE_WRITES="maybe") & WRITE_TOOLS == set()
    assert _registered_tools(SDWAN_ENABLE_WRITES="0") & WRITE_TOOLS == set()
    assert WRITE_TOOLS <= _registered_tools(SDWAN_ENABLE_WRITES="yes")


# ---------------------------------------------------------------------------
# Unauthenticated routes
# ---------------------------------------------------------------------------
def test_healthz_route():
    client = TestClient(mcp.http_app(path="/mcp"))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_render_readme_html():
    readme_markdown = "# Title\n\n| A | B |\n|---|---|\n| http://localhost:8000/mcp | ok |"

    result = _render_readme_html(readme_markdown)

    assert result.startswith("<!doctype html>")
    assert "<h1>Title</h1>" in result
    assert "<table>" in result
    assert "window.location.origin" in result
    assert LOCALHOST_ORIGIN in result


def test_root_route_serves_the_readme():
    client = TestClient(mcp.http_app(path="/mcp"))

    response = client.get("/")

    assert response.status_code == 200
    assert "http://localhost:8000/mcp" in response.text
