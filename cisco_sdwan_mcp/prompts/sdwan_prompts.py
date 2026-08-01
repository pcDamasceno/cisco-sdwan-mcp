"""
Prompt templates for common SD-WAN operational workflows.

Each one encodes the order a network engineer actually works in — control
plane before data plane, evidence before conclusions — so the model does not
have to rediscover the methodology on every call.
"""

from __future__ import annotations

from cisco_sdwan_mcp.mcp import mcp


@mcp.prompt()
def troubleshoot_device(device: str, symptom: str = "unreachable") -> str:
    """Build a structured troubleshooting plan for one SD-WAN device."""
    return f"""Troubleshoot the Cisco SD-WAN device `{device}`. Reported symptom: {symptom}.

Work through this in order, using the SD-WAN tools, and stop early if you find the cause:

1. `check_device_health("{device}")` — one call covering system status, control
   connections and BFD. Read its `problems` list first.
2. If control connections are down or incomplete: `get_control_connections("{device}")`.
   Note which peer types (vsmart / vbond / vmanage) are missing and the local/remote
   colors involved — a missing vSmart connection explains missing routes and policy.
3. If control is healthy but sites cannot reach each other:
   `get_bfd_sessions("{device}", state="down")` to see which tunnels are dead, then
   `get_omp_peers("{device}")` to confirm routes are being exchanged.
4. Check the physical layer: `get_interfaces("{device}", vpn_id="0")` for transport
   interfaces that are down or accumulating errors.
5. Correlate with history: `list_events(hours=6)` filtered to the relevant component
   (BFD, OMP, System), and `list_alarms(hours=24, severity="critical,major")`.

Then report:
- **Root cause** — what is actually broken, with the specific evidence that shows it.
- **Blast radius** — which other sites or tunnels this affects.
- **Next steps** — concrete remediation, flagging anything that needs a config change.

State clearly when the evidence is inconclusive rather than guessing."""


@mcp.prompt()
def fabric_health_report(hours: float = 24) -> str:
    """Build a whole-fabric health report covering the last N hours."""
    return f"""Produce a health report for the Cisco SD-WAN fabric covering the last {hours} hours.

Gather:
1. `get_fabric_summary()` — device counts by type, reachability and software version.
2. `get_alarm_summary(hours={hours})` — alarm volume by severity and component, plus
   the most affected devices.
3. `find_degraded_tunnels(hours=1)` — paths currently breaching loss/latency/jitter.
4. For any unreachable device from step 1, `check_device_health(<device>)`.

Write the report as:
- **Executive summary** — is the fabric healthy, in one or two sentences.
- **Devices** — totals, and every unreachable device with what is wrong.
- **Alarms** — what fired, what is still active, and which are worth acting on.
- **Path quality** — degraded tunnels and the sites they connect.
- **Software consistency** — call out version spread across the fleet.
- **Recommended actions** — prioritised, each tied to a specific finding.

Distinguish sharply between what you verified and what you are inferring. Give
counts rather than vague quantities, and say when a check returned no data
instead of treating that as success."""


@mcp.prompt()
def analyse_path_quality(hours: float = 1, site: str = "") -> str:
    """Analyse tunnel performance and recommend where to look next."""
    scope = f" for site {site}" if site else " across the fabric"
    return f"""Analyse SD-WAN path quality{scope} over the last {hours} hours.

1. `find_degraded_tunnels(hours={hours})` — start with what is already breaching
   thresholds, worst first.
2. `get_tunnel_statistics(hours={hours})` for the affected devices, to see whether the
   degradation is sustained or a spike.
3. For endpoints of the worst tunnels, `get_interfaces(<device>, vpn_id="0")` — check
   for interface errors or drops on the transport side.

Report:
- Which tunnels are degraded, by how much, and against which threshold.
- Whether the problem clusters by **color** (transport, e.g. mpls vs biz-internet),
  by **site**, or by **device** — that distinction usually points at the cause:
  a single circuit, a site's local issue, or a device fault.
- Whether interface errors corroborate the loss figures.
- What to do next: raise with the transport provider, shift traffic with an
  app-route policy, or investigate the device.

If nothing breaches the thresholds, say so plainly and give the observed
best/worst figures so the reader can judge the margin."""


@mcp.prompt()
def review_template_change(template_id: str) -> str:
    """Review a device template and the impact of attaching it, before any change."""
    return f"""Review Cisco SD-WAN device template `{template_id}` ahead of a change.

1. `get_device_template("{template_id}", detailed=True)` — the definition and every
   device currently attached.
2. `get_template_input_variables("{template_id}", device_ids=[...])` for the target
   devices — the exact per-device values an attachment would push.
3. `list_policies(policy_scope="centralized")` — check whether an active policy
   interacts with what this template changes.
4. `check_device_health(<device>)` for each target — never push to a device that is
   already unhealthy.

Report:
- **What this template configures** and which devices it already governs.
- **What would change** on each target device, variable by variable.
- **Risk** — specifically, anything touching transport interfaces, system settings,
  tunnel colors or control-plane parameters, since those can strand a device.
- **Go / no-go recommendation**, with the pre-checks to run first and the rollback
  path if it goes wrong.

Do not attach the template as part of this review. Recommend only; attachment is a
separate, explicitly confirmed step."""
