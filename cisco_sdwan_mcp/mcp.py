"""
Shared FastMCP server instance.
"""

import os
from html import escape
from pathlib import Path

from fastmcp import FastMCP
from markdown import markdown
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from cisco_sdwan_mcp.auth import build_auth_provider

README_PATH = Path(__file__).resolve().parents[1] / "README.md"
README_TEMPLATE_PATH = Path(__file__).with_name("readme_template.html")
LOCALHOST_ORIGIN = "http://localhost:8000"

mcp = FastMCP(
    name=os.getenv("MCP_SERVER_NAME", "cisco-sdwan-mcp"),
    auth=build_auth_provider(),
)


# Custom routes are served outside the authenticated MCP endpoint, so probes
# and load balancers can reach /healthz without a bearer token.
@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def health(_request: Request) -> Response:
    return JSONResponse({"status": "ok", "server": mcp.name})


def _render_readme_html(readme_markdown: str) -> str:
    body = markdown(
        readme_markdown,
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )
    template = README_TEMPLATE_PATH.read_text(encoding="utf-8")

    return template.replace("{{ title }}", escape(f"{mcp.name} README")).replace(
        "{{ body }}", body
    ).replace(
        "{{ local_origin }}", LOCALHOST_ORIGIN
    )


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def readme_home(_request: Request) -> Response:
    if not README_PATH.exists():
        return HTMLResponse("<h1>README.md not found</h1>", status_code=404)

    readme_markdown = README_PATH.read_text(encoding="utf-8")
    return HTMLResponse(_render_readme_html(readme_markdown))
