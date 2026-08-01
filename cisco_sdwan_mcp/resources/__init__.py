"""
Resource registrations.

Import each resource module here so its ``@mcp.resource`` decorators run when
the package is imported. Add a new module → add one import line.
"""

from cisco_sdwan_mcp.resources import sdwan_resources  # noqa: F401
