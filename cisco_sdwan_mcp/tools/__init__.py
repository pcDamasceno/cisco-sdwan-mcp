"""
Tool registrations.

Importing a module runs its ``@sdwan_tool`` decorators, which register the
tools with the shared FastMCP instance. Add a new module → add one import line.

``config_tools`` is deliberately conditional: with ``SDWAN_ENABLE_WRITES``
unset or false the configuration-changing tools are never imported, so they
are absent from the tool list the model sees and the server is read-only by
construction rather than by policy.
"""

import logging

from cisco_sdwan_mcp.sdwan.config import writes_enabled
from cisco_sdwan_mcp.tools import (  # noqa: F401
    alarm_tools,
    inventory_tools,
    monitoring_tools,
    statistics_tools,
    template_tools,
)

logger = logging.getLogger(__name__)

if writes_enabled():
    from cisco_sdwan_mcp.tools import config_tools  # noqa: F401

    logger.warning(
        "SDWAN_ENABLE_WRITES=true — configuration-changing tools are registered. "
        "Each one still requires explicit user confirmation before it runs."
    )
else:
    logger.info(
        "Read-only mode: configuration-changing tools are not registered. "
        "Set SDWAN_ENABLE_WRITES=true to enable them."
    )
