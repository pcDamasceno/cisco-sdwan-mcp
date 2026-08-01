# Cisco SD-WAN MCP Server

<!-- mcp-name: io.github.pcDamasceno/cisco-sdwan-mcp -->

[![PyPI](https://img.shields.io/pypi/v/cisco-sdwan-mcp)](https://pypi.org/project/cisco-sdwan-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/cisco-sdwan-mcp)](https://pypi.org/project/cisco-sdwan-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-cisco--sdwan--mcp-6E56CF)](https://registry.modelcontextprotocol.io/v0/servers?search=cisco-sdwan-mcp)

`cisco-sdwan-mcp` is an [MCP](https://modelcontextprotocol.io) server for
**Cisco Catalyst SD-WAN Manager (vManage)**, built with
[FastMCP](https://github.com/jlowin/fastmcp).

It gives an LLM client a working view of your SD-WAN fabric — inventory,
device health, control and data plane state, alarms, path quality, templates
and policies — so you can ask "why is the Frankfurt branch down?" and get an
answer backed by real controller data instead of a guess.

**Read-only by default.** The configuration-changing tools are not registered
unless you explicitly enable them, and even then every call requires a human to
approve it.

---

## Contents

- [What you get](#what-you-get)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Write protection](#write-protection)
- [Tool reference](#tool-reference)
- [Prompts](#prompts)
- [Resources](#resources)
- [Connecting an MCP client](#connecting-an-mcp-client)
- [Transports](#transports-http-vs-stdio)
- [Authenticating MCP clients](#authenticating-mcp-clients)
- [Docker](#docker)
- [Deploying](#deploying)
- [Adding your own tools](#adding-your-own-tools)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)

---

## What you get

| Area | Tools |
|---|---|
| **Inventory** | `list_devices`, `get_device`, `get_fabric_summary`, `list_inventory` |
| **Device health** | `check_device_health`, `get_system_status`, `get_control_connections`, `get_bfd_sessions`, `get_omp_peers`, `get_interfaces` |
| **Alarms & events** | `get_alarm_summary`, `list_alarms`, `list_events` |
| **Path quality** | `find_degraded_tunnels`, `get_tunnel_statistics`, `get_interface_statistics` |
| **Templates & policy** | `list_device_templates`, `get_device_template`, `list_feature_templates`, `list_policies`, `get_template_input_variables` |
| **Configuration** *(opt-in)* | `attach_device_template`, `activate_vsmart_policy`, `get_task_status` |

Plus four workflow [prompts](#prompts) and three [resources](#resources).

Three design decisions are worth knowing up front, because they shape every
tool:

- **Responses are projected, not dumped.** A vManage device record carries 60+
  fields; a 200-device fabric would bury a model's context. Each tool returns
  the fields that answer the question and accepts `detailed=true` when you want
  everything.
- **Counts always accompany results.** Every list reports `count` (what
  matched) alongside `returned` (what you got), so "3 devices are down" is
  never confused with "3 devices are down in the first 100 I looked at".
- **Failures come back as answers.** A wrong password, an unreachable
  controller or an unknown hostname returns a readable message — often with the
  valid options — rather than raising. The model can then correct itself or
  tell you exactly what to fix.

---

## Quickstart

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) **or** pip
- A reachable Cisco Catalyst SD-WAN Manager (vManage) and an account on it

> **Make a dedicated vManage account.** Give it a read-only role to start.
> The account's privileges are the real security boundary — see
> [Write protection](#write-protection).

### Install

From PyPI, if you only want to run it:

```bash
uvx cisco-sdwan-mcp        # no install, run it straight
pip install cisco-sdwan-mcp
```

From a checkout, if you want to change it:

```bash
git clone https://github.com/pcDamasceno/cisco-sdwan-mcp.git
cd cisco-sdwan-mcp

# with uv (recommended)
uv sync --extra dev

# with pip
pip install -e ".[dev]"
```

### Configure

```bash
cp .env.example .env
```

The three settings you must fill in:

```bash
SDWAN_VMANAGE_URL=https://vmanage.example.com:8443
SDWAN_USERNAME=automation-readonly
SDWAN_PASSWORD=...
```

The server reads `.env` from the repository root at startup — set
`SDWAN_ENV_FILE` to load a different file. Variables already present in the
environment (compose `env_file`, Kubernetes secrets) are never overwritten by
it, and the startup log names the file it used.

### Run

```bash
uv run python -m cisco_sdwan_mcp.server        # or: python -m cisco_sdwan_mcp.server
```

The server starts over **HTTP** on `0.0.0.0:8000`. The MCP endpoint is at
`http://localhost:8000/mcp`, a health probe at `http://localhost:8000/healthz`,
and this README at `http://localhost:8000/`.

Startup logs confirm what it will talk to before any client connects:

```
INFO  cisco_sdwan_mcp.server: vManage controller: vmanage.example.com:8443 (user automation-readonly, TLS verify: True)
INFO  cisco_sdwan_mcp.server: Write tools: disabled (read-only)
```

### First call

Point an MCP client at it (see [Connecting an MCP client](#connecting-an-mcp-client))
and ask for `get_fabric_summary`. It is one round trip and exercises
authentication, TLS and reachability at once:

```json
{
  "total_devices": 42,
  "by_type": {"vedge": 38, "vsmart": 2, "vbond": 1, "vmanage": 1},
  "by_reachability": {"reachable": 40, "unreachable": 2},
  "unreachable_count": 2,
  "unreachable_devices": [{"host-name": "BR2-EDGE1", "system-ip": "10.0.0.12", "site-id": "1002"}]
}
```

---

## Configuration

Everything is environment-driven; `.env.example` is the annotated reference.

### vManage connection

| Variable | Default | Description |
|---|---|---|
| `SDWAN_VMANAGE_URL` | — | Controller URL, e.g. `https://vmanage.example.com:8443`. **Required** (or use `SDWAN_VMANAGE_HOST`) |
| `SDWAN_VMANAGE_HOST` | — | Hostname instead of a full URL |
| `SDWAN_VMANAGE_PORT` | `443` | Port, when using `SDWAN_VMANAGE_HOST` |
| `SDWAN_USERNAME` | — | vManage username. **Required** |
| `SDWAN_PASSWORD` | — | vManage password. **Required** |
| `SDWAN_VERIFY_SSL` | `true` | TLS certificate verification |
| `SDWAN_CA_BUNDLE` | — | Path to a CA bundle — the right answer for a private CA |
| `SDWAN_TIMEOUT` | `60` | Seconds to wait for vManage |
| `SDWAN_PAGE_SIZE` | `100` | Default cap on records per tool call |
| `SDWAN_ENABLE_WRITES` | `false` | Register the configuration tools — see below |

### Server

| Variable | Default | Description |
|---|---|---|
| `MCP_SERVER_NAME` | `cisco-sdwan-mcp` | Name advertised to MCP clients |
| `MCP_TRANSPORT` | `http` | `http` or `stdio` |
| `MCP_HOST` | `0.0.0.0` | Bind address (HTTP only) |
| `MCP_PORT` | `8000` | Bind port (HTTP only) |
| `MCP_AUTH` | `none` | How MCP *clients* authenticate to this server |
| `LOG_LEVEL` | `INFO` | Python log level |

> `SDWAN_USERNAME`/`SDWAN_PASSWORD` authenticate **this server to vManage**.
> `MCP_AUTH` governs how **clients authenticate to this server**. They are
> unrelated, and you generally want both.

### TLS

vManage very often presents a self-signed or private-CA certificate. In
descending order of preference:

1. Point `SDWAN_CA_BUNDLE` at the controller's CA — verification stays on.
2. Add the CA to `certificates/`, which the Docker build installs into the
   container trust store automatically.
3. Only as a last resort, on a lab you control, set `SDWAN_VERIFY_SSL=false`.
   The server logs a warning naming the host each time it does this, because
   it means anything on the path can read the credentials.

---

## Write protection

The tools that change configuration are gated twice.

**Gate 1 — registration.** With `SDWAN_ENABLE_WRITES` unset or `false`, the
module holding them is never imported. They do not appear in the tool list, so
a model cannot call them by mistake, misinterpretation or prompt injection.
The server is read-only by construction, not by policy.

**Gate 2 — confirmation.** With writes enabled, each call still asks the user
through MCP elicitation, naming the template or policy and the devices
affected, before anything reaches vManage. Clients that do not implement
elicitation cannot silently proceed — the call is refused unless the caller
passes `confirm=true`, which puts the decision in a human's hands either way.

```bash
SDWAN_ENABLE_WRITES=true uv run python -m cisco_sdwan_mcp.server
```

```
WARNING cisco_sdwan_mcp.tools: SDWAN_ENABLE_WRITES=true — configuration-changing tools are registered.
                   Each one still requires explicit user confirmation before it runs.
```

> **The vManage account is the real boundary.** `SDWAN_ENABLE_WRITES` controls
> which tools exist in *this* server; it does nothing about what the account
> can do through any other path. If a change must be impossible, use a
> read-only vManage role — do not rely on this flag alone.

vManage applies configuration asynchronously: a write returns a `task_id`,
meaning *accepted*, not *applied*. Poll `get_task_status(task_id)` until it
reports done.

The intended flow for a template push, with a review step in the middle:

```
list_device_templates          → find the template
get_device_template            → see what it configures and who has it
get_template_input_variables   → the exact per-device values (read-only preview)
check_device_health            → never push to an already-broken device
attach_device_template         → asks for approval, returns a task_id
get_task_status                → confirm it actually landed
```

---

## Tool reference

Every tool takes `limit` (cap on records) and most take `detailed` (return all
vManage fields instead of the summary set).

### Inventory

| Tool | What it answers |
|---|---|
| `get_fabric_summary()` | Device counts by type, reachability and version, plus every unreachable device. **Start here** for open questions. |
| `list_devices(device_type, reachability, site_id)` | Devices vManage is currently talking to. |
| `get_device(device)` | One device's full record. Accepts hostname, system IP or chassis number. |
| `list_inventory(category, unattached_only)` | Everything *provisioned*, including devices that never onboarded, have invalid certificates or carry no template. |

### Device health

| Tool | What it answers |
|---|---|
| `check_device_health(device)` | **Triage in one call** — system status, control connections and BFD, with a `problems` list naming what is wrong. |
| `get_system_status(device)` | Uptime, CPU, memory, disk, last reboot reason. |
| `get_control_connections(device)` | Connections to vSmart/vBond/vManage. Check first when a device will not come up. |
| `get_bfd_sessions(device, state)` | Data-plane tunnels to other edges. Check when sites reach controllers but not each other. |
| `get_omp_peers(device)` | OMP peering — control up but OMP down means no overlay routes. |
| `get_interfaces(device, vpn_id, interface_name)` | Interface status, addressing and error counters. |

These poll the device through vManage, so they reflect live state but cost a
round trip to the edge. Prefer `check_device_health` over three separate calls.

### Alarms and events

| Tool | What it answers |
|---|---|
| `get_alarm_summary(hours)` | Counts by severity and component, top rules, most affected devices. Cheap — call before listing. |
| `list_alarms(hours, severity, active_only)` | The alarms themselves. |
| `list_events(hours, severity, component)` | Raw event stream — noisier, but shows flaps and transitions that never became alarms. |

### Path quality

| Tool | What it answers |
|---|---|
| `find_degraded_tunnels(hours, max_loss_percent, max_latency_ms, max_jitter_ms)` | Tunnels breaching thresholds, worst first, each saying which threshold it broke. |
| `get_tunnel_statistics(device, hours)` | Raw per-tunnel loss/latency/jitter/vQoE. |
| `get_interface_statistics(device, hours, interface_name)` | Historical throughput and error counters. |

These read vManage's statistics database — fast, but only as fresh as the last
collection cycle (30 minutes on most deployments). For live state, use the
device health tools.

### Templates and policy

| Tool | What it answers |
|---|---|
| `list_device_templates(device_type, attached_only)` | Templates and their attachment counts. |
| `get_device_template(template_id)` | One template's definition plus attached devices. |
| `list_feature_templates(template_type)` | The building blocks. |
| `list_policies(policy_scope)` | Centralized (vSmart) or localized policies, and which is active. |
| `get_template_input_variables(template_id, device_ids)` | Read-only preview of the values an attachment would push. |

---

## Prompts

Reusable workflows that encode the order an engineer actually works in —
control plane before data plane, evidence before conclusions.

| Prompt | Use it for |
|---|---|
| `troubleshoot_device(device, symptom)` | Structured device triage, stopping at the first real cause |
| `fabric_health_report(hours)` | A whole-fabric report: devices, alarms, path quality, recommendations |
| `analyse_path_quality(hours, site)` | Tunnel performance, clustered by color / site / device to point at the cause |
| `review_template_change(template_id)` | Pre-change review with an explicit go/no-go — recommends only, never attaches |

---

## Resources

| URI | Contents |
|---|---|
| `sdwan://config` | Connection settings in effect — controller, user, TLS mode, whether writes are on. Never includes the password. |
| `sdwan://devices` | Current fabric inventory with per-device status |
| `sdwan://device/{identifier}` | One device's full record, by hostname or system IP |

---

## Connecting an MCP client

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "cisco-sdwan": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### VS Code (GitHub Copilot) — `.vscode/mcp.json`

```json
{
  "servers": {
    "cisco-sdwan": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### With token auth enabled

```json
{
  "mcpServers": {
    "cisco-sdwan": {
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer dev-token" }
    }
  }
}
```

With an OAuth mode (`github`, `google`, `oauth-proxy`, …) no header is needed —
MCP clients discover the flow and open the login screen themselves.

### stdio (local subprocess)

From PyPI — nothing to clone, `uvx` fetches the package on first run:

```json
{
  "mcpServers": {
    "cisco-sdwan": {
      "command": "uvx",
      "args": ["cisco-sdwan-mcp"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "SDWAN_VMANAGE_URL": "https://vmanage.example.com:8443",
        "SDWAN_USERNAME": "automation-readonly",
        "SDWAN_PASSWORD": "..."
      }
    }
  }
}
```

From a checkout:

```json
{
  "mcpServers": {
    "cisco-sdwan": {
      "command": "uv",
      "args": ["run", "python", "-m", "cisco_sdwan_mcp.server"],
      "cwd": "/absolute/path/to/cisco-sdwan-mcp",
      "env": {
        "MCP_TRANSPORT": "stdio",
        "SDWAN_VMANAGE_URL": "https://vmanage.example.com:8443",
        "SDWAN_USERNAME": "automation-readonly",
        "SDWAN_PASSWORD": "..."
      }
    }
  }
}
```

---

## Transports: HTTP vs stdio

- **HTTP (default)** — the deployment transport. Serves many clients
  concurrently, works behind load balancers, and is the only transport where
  `MCP_AUTH` applies. Everything in `deploy/` assumes it.
- **stdio** — for local single-user use where a desktop client spawns the
  server as a subprocess. No network listener, so `MCP_HOST`/`MCP_PORT` and
  `MCP_AUTH` do not apply; the process is secured by your OS user.

```bash
MCP_TRANSPORT=stdio uv run python -m cisco_sdwan_mcp.server
```

Deploying anywhere or serving multiple users → HTTP. One client on your own
machine → either works.

---

## Authenticating MCP clients

Authentication of clients **to this server** is off by default and selected at
startup with `MCP_AUTH`. The factory lives in `cisco_sdwan_mcp/auth.py`; all modes are
backed by FastMCP's built-in providers.

| `MCP_AUTH` | Use case |
|---|---|
| `none` (default) | Local development, or network-level protection (IAM, VPN, mTLS) |
| `static` | Fixed bearer tokens — quick tests only, never production |
| `jwt` | You already have an IdP issuing JWTs (Keycloak, Okta, Entra ID, Cognito…) |
| `introspection` | Your IdP issues opaque tokens (RFC 7662) |
| `oauth-proxy` | Full OAuth 2.1 login flow via any OAuth provider |
| `github`, `google`, `azure`, `auth0`, `workos` | Full login flow via a hosted identity provider, preconfigured |

```bash
# Development tokens (never in production — tokens sit in plain env vars)
MCP_AUTH=static MCP_AUTH_STATIC_TOKENS=dev-token uv run python -m cisco_sdwan_mcp.server

# JWT via your IdP's JWKS endpoint
MCP_AUTH=jwt
MCP_AUTH_JWKS_URI=https://idp.example.com/realms/main/protocol/openid-connect/certs
MCP_AUTH_ISSUER=https://idp.example.com/realms/main
MCP_AUTH_AUDIENCE=cisco-sdwan-mcp
```

The full variable reference for every mode is in [`.env.example`](.env.example).

Notes:

- Auth applies to the **HTTP transport only**.
- `/healthz` and `/` stay public — probes and humans don't carry tokens; the
  MCP endpoint returns `401` without a valid token.
- OAuth flows require HTTPS on the public URL in production.
- To add your own scheme, write a builder in `cisco_sdwan_mcp/auth.py` and register it in
  `_BUILDERS` ([provider docs](https://gofastmcp.com/servers/auth/authentication)).

> A server exposing your WAN topology should not run `MCP_AUTH=none` on a
> reachable network. See [`deploy/README.md`](deploy/README.md).

---

## Docker

```bash
cp .env.example .env      # fill in vManage URL and credentials
docker compose up -d --build
```

Or manually:

```bash
docker build -t cisco-sdwan-mcp .
docker run -p 8000:8000 \
  -e SDWAN_VMANAGE_URL=https://vmanage.example.com:8443 \
  -e SDWAN_USERNAME=automation-readonly \
  -e SDWAN_PASSWORD=... \
  cisco-sdwan-mcp
```

Helper scripts build the image, replace any container of the same name, and
start the server at `http://localhost:8000/mcp`, passing your `.env` through:

```bash
bash scripts/run_docker.sh          # Linux/macOS
.\scripts\run_docker.ps1            # Windows PowerShell
```

The image includes a `HEALTHCHECK` against `/healthz`, so `docker ps` shows
container health out of the box.

### Corporate CA certificates

Drop any `.crt`/`.pem` root CA files into `certificates/`. The build adds them
to the container trust store and runs `update-ca-certificates` automatically —
which covers **both** a TLS-intercepting proxy and a vManage certificate signed
by your internal CA. Leave the directory empty if you don't need it.

For a proxy, `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` are predefined Docker build
args and need no Dockerfile edits:

```bash
docker build --build-arg HTTPS_PROXY=http://proxy.example.com:8080 -t cisco-sdwan-mcp .
docker run -p 8000:8000 -e HTTPS_PROXY=http://proxy.example.com:8080 cisco-sdwan-mcp
```

---

## Deploying

The container is a plain HTTP server on port 8000 with a `/healthz` probe, so
it runs anywhere. `deploy/` ships raw Kubernetes manifests, a Helm chart, a
Styrmin driver and a Cloud Run service definition — see
[`deploy/README.md`](deploy/README.md) for full walkthroughs, including the
SD-WAN-specific parts: reaching a management-network controller from the cloud,
private-CA handling, and vManage's per-account session limits.

```bash
kubectl apply -k deploy/kubernetes
```

```bash
helm install sdwan-mcp oci://ghcr.io/pcdamasceno/charts/cisco-sdwan-mcp \
  --set sdwan.vmanageUrl=https://vmanage.example.com:8443
```

```bash
gcloud run services replace deploy/cloud-run-service.yaml --region europe-west3
```

This repository is also a [Styrmin](https://github.com/opsmill/styrmin)
Application Driver — `driver.styrmin.yml` and `values.j2.yml` at the root are
what Styrmin reads when it clones it. See
[`deploy/styrmin.md`](deploy/styrmin.md).

`/healthz` deliberately does **not** check vManage. A brief controller outage
should not restart pods — tools report the problem per call, and the server
recovers on its own.

---

## Adding your own tools

Capabilities live in three packages, one module per concern. Each package's
`__init__.py` imports its modules so the decorators run — add a module, add one
import line.

```python
# cisco_sdwan_mcp/tools/my_tools.py
from cisco_sdwan_mcp.sdwan.client import get_client
from cisco_sdwan_mcp.sdwan.formatting import envelope, project
from cisco_sdwan_mcp.tools._helpers import resolve_device_id, sdwan_tool


@sdwan_tool
async def get_dhcp_leases(device: str, limit: int = 100) -> dict:
    """Show DHCP leases the device is serving.

    Args:
        device: Hostname, system IP or chassis number.
        limit: Maximum leases to return.
    """
    system_ip = await resolve_device_id(device)
    client = await get_client()
    records = await client.get_data(
        "/dataservice/device/dhcp/server", {"deviceId": system_ip}
    )
    fields = ("ifname", "address", "client-id", "state", "expires")
    return envelope(project(records, fields), limit=limit, device=device)
```

Then add `my_tools` to the import list in `cisco_sdwan_mcp/tools/__init__.py`.

Use `@sdwan_tool` rather than `@mcp.tool` — it registers the tool *and*
converts SD-WAN failures into a readable `{"error", "message"}` result. Reach
for the shared helpers rather than reimplementing them:

| Helper | Purpose |
|---|---|
| `resolve_device_id(device)` | Hostname / system IP / chassis → the system IP vManage's real-time endpoints need |
| `client.get_data(path, params)` | GET and unwrap vManage's `{"data": [...]}` envelope |
| `project(records, fields)` | Trim wide records to what matters |
| `envelope(records, limit=...)` | Add `count`/`returned`/truncation notes |
| `build_query(hours=..., rules=...)` | Build the JSON `query` param alarms/events/statistics need |
| `count_by(records, field)` | Tally a field into a summary |

The docstring is what the model reads to decide whether to call your tool —
say what question it answers, not just which endpoint it hits. Keep write
operations in `config_tools.py` so the registration gate keeps covering them.

---

## Testing

```bash
uv run pytest      # or: pytest
```

The suite runs against a fake vManage (`httpx.MockTransport`) rather than a
live controller, so it covers the things that actually break in the field:

- the login handshake, including vManage answering a **failed** login with
  HTTP 200 and an HTML body
- CSRF token handling, and controllers older than 19.2 that have no token
  endpoint
- session expiry mid-session → one transparent re-login and retry
- error translation: unreachable host, timeout, 403, non-JSON response
- every read tool's filtering, projection and truncation
- the write gate, verified in a fresh interpreter: the configuration tools are
  absent without `SDWAN_ENABLE_WRITES=true` and present with it
- write confirmation: declining, or a client that cannot prompt, must not
  produce an HTTP call to vManage

`tests/conftest.py` holds the fake controller; use it as the pattern for your
own tools.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ConfigurationError: No controller configured` | `SDWAN_VMANAGE_URL` (or `SDWAN_VMANAGE_HOST`) is unset. |
| `AuthenticationError: rejected the credentials` | Wrong username/password, or the account is locked. vManage returns HTTP 200 with the login page for a bad password — the client detects that and reports it as an auth failure. |
| `AuthenticationError: may lack the required role` | Authentication worked but the account lacks privileges for that endpoint. Template and policy endpoints need more than a bare read-only role. |
| `AuthenticationError: issued no JSESSIONID cookie` | The URL points at a proxy that strips cookies, not at vManage itself. |
| `APIError: cannot reach <host>` | DNS, routing, firewall or the wrong port. vManage commonly listens on 8443, not 443. |
| `APIError: timed out after 60s` | Real-time endpoints poll the device itself. Raise `SDWAN_TIMEOUT`, or scope the query to one device. |
| TLS / certificate verify failed | Private CA. Set `SDWAN_CA_BUNDLE` or add the CA to `certificates/`. `SDWAN_VERIFY_SSL=false` is a lab-only last resort. |
| `APIError: response was not valid JSON` | The endpoint doesn't exist on this vManage version — API paths vary across releases. |
| A write tool "doesn't exist" | Expected: `SDWAN_ENABLE_WRITES` is not `true`. |
| A write returns `applied: false` with `confirm=True` guidance | The client doesn't support MCP elicitation, so it cannot ask you to approve. |
| Empty results everywhere, no error | The account may be scoped to a tenant or device group with no devices. Check `sdwan://config` and try `list_inventory`. |

Set `LOG_LEVEL=DEBUG` for more detail. Note that vManage error bodies can be
verbose — check what yours returns before enabling debug logs in a shared
environment.

---

## Project structure

```
.
├── cisco_sdwan_mcp/
│   ├── mcp.py                    ← Shared FastMCP instance, auth wiring, /healthz
│   ├── auth.py                   ← MCP client authentication factory (MCP_AUTH)
│   ├── server.py                 ← Entry point: transport selection, startup logging
│   ├── sdwan/                    ← vManage integration layer (no MCP knowledge)
│   │   ├── config.py             ← SDWAN_* settings
│   │   ├── client.py             ← Async client: login, CSRF, session recovery
│   │   ├── formatting.py         ← Projection, envelopes, vManage query builder
│   │   └── errors.py             ← Exception hierarchy
│   ├── tools/
│   │   ├── _helpers.py           ← @sdwan_tool, device resolution
│   │   ├── inventory_tools.py    ← Devices and fabric summary
│   │   ├── monitoring_tools.py   ← Control plane, BFD, OMP, interfaces, health
│   │   ├── alarm_tools.py        ← Alarms and events
│   │   ├── statistics_tools.py   ← Tunnel and interface statistics
│   │   ├── template_tools.py     ← Templates and policies (read-only)
│   │   └── config_tools.py       ← Writes — imported only when enabled
│   ├── resources/sdwan_resources.py
│   └── prompts/sdwan_prompts.py
├── tests/
│   ├── conftest.py               ← Fake vManage (httpx.MockTransport)
│   ├── sample_data.py            ← Representative vManage payloads
│   ├── test_client.py            ← Login, session recovery, error translation
│   ├── test_formatting.py        ← Projection, envelopes, query building
│   ├── test_tools.py             ← Read tools via the in-memory MCP client
│   ├── test_config_tools.py      ← The write confirmation gate
│   ├── test_server.py            ← Registration, the write gate, public routes
│   └── test_auth.py              ← MCP client auth factory
├── deploy/                       ← Kubernetes + Cloud Run
├── scripts/                      ← Docker helper scripts (bash / PowerShell)
├── certificates/                 ← Drop-in CA certificates for Docker builds
├── .env.example                  ← Annotated reference of every variable
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

---

## Resources

- [Cisco Catalyst SD-WAN Manager API docs](https://developer.cisco.com/docs/sdwan/)
- [FastMCP documentation](https://gofastmcp.com)
- [Model Context Protocol specification](https://modelcontextprotocol.io)

---

## License

[MIT](LICENSE)
