"""
Prompt registrations.

Import each prompt module here so its ``@mcp.prompt`` decorators run when the
package is imported. Add a new module → add one import line.
"""

from cisco_sdwan_mcp.prompts import sdwan_prompts  # noqa: F401
