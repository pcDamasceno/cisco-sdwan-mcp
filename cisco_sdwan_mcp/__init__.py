"""
Cisco Catalyst SD-WAN MCP server.

The ``.env`` file is loaded here, at package import, because the tool modules
read ``SDWAN_ENABLE_WRITES`` while they are being imported — by the time
``cisco_sdwan_mcp.server.main()`` runs it is already too late. Values already present in
the environment are never overwritten.
"""

from cisco_sdwan_mcp.env import load_env_file

load_env_file()
