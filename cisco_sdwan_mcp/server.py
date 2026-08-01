"""
Cisco Catalyst SD-WAN MCP Server – Main Entry Point

Exposes a Cisco Catalyst SD-WAN (vManage) fabric to MCP clients: inventory,
real-time device health, alarms and events, path-quality statistics, and
templates and policies. Configuration-changing tools are registered only when
``SDWAN_ENABLE_WRITES=true``.

Transport is selected with MCP_TRANSPORT:
  - "http"  (default) – streamable HTTP on MCP_HOST:MCP_PORT, MCP endpoint at /mcp.
    This is the deployment transport: it supports authentication (MCP_AUTH),
    multiple concurrent clients, and runs behind load balancers.
  - "stdio" – speaks MCP over stdin/stdout for local, single-user clients that
    spawn the server as a subprocess (Claude Desktop, IDEs). Authentication
    does not apply here: the process inherits the caller's OS permissions.

vManage credentials come from the SDWAN_* variables; see .env.example.
"""

import logging
import os
import sys

from cisco_sdwan_mcp.env import loaded_env_file
from cisco_sdwan_mcp.mcp import mcp
from cisco_sdwan_mcp.sdwan.config import load_settings, writes_enabled
from cisco_sdwan_mcp.sdwan.errors import SDWANError

# ---------------------------------------------------------------------------
# Register capabilities – importing the packages runs the decorators.
# Add new modules to the packages' __init__.py, not here.
# ---------------------------------------------------------------------------
import cisco_sdwan_mcp.prompts  # noqa: F401, E402
import cisco_sdwan_mcp.resources  # noqa: F401, E402
import cisco_sdwan_mcp.tools  # noqa: F401, E402

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    # stdio speaks MCP on stdout, so logs go to stderr on every transport.
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _log_startup() -> None:
    """Report what the server will talk to, without touching credentials.

    Deliberately non-fatal: a missing controller URL surfaces as a clear
    message on the first tool call rather than stopping the server. That keeps
    /healthz answering, so a container does not crash-loop while an operator
    fixes a secret.
    """
    if loaded_env_file:
        logger.info("Loaded environment from %s", loaded_env_file)

    try:
        settings = load_settings()
        logger.info(
            "vManage controller: %s (user %s, TLS verify: %s)",
            settings.host,
            settings.username,
            settings.verify,
        )
    except SDWANError as exc:
        logger.warning("vManage is not configured yet: %s", exc)

    logger.info(
        "Write tools: %s", "ENABLED" if writes_enabled() else "disabled (read-only)"
    )


def main() -> None:
    _configure_logging()
    transport = os.getenv("MCP_TRANSPORT", "http").strip().lower()
    _log_startup()

    if transport == "stdio":
        if os.getenv("MCP_AUTH", "none").strip().lower() not in ("", "none"):
            logger.warning(
                "MCP_AUTH is set but the stdio transport has no HTTP layer; "
                "authentication only applies when MCP_TRANSPORT=http."
            )
        mcp.run(transport="stdio")
        return

    mcp.run(
        transport=transport,
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
