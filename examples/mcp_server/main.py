"""Illustrates the auth integration point for an MCP server: a 401 challenge
pointing at this server's own Protected Resource Metadata, and per-request
token validation via authservice-client.

This is deliberately transport-agnostic (plain FastAPI routes standing in for
MCP tool calls). Real MCP servers built on the official Python/TypeScript SDKs
expose their own auth hook (e.g. FastMCP's `auth` parameter) -- wire the same
TokenValidator / require_auth pattern into that hook instead of these routes.

Run it with:
    uv sync
    uv run uvicorn main:app --reload --port 9002
"""

from fastapi import Depends, FastAPI

from authservice_client import TokenValidator
from authservice_client.fastapi import make_auth_dependency
from authservice_client.protected_resource import protected_resource_router

ISSUER = "http://localhost:8000"
RESOURCE_ID = "https://mcp.example.com"

validator = TokenValidator(issuer=ISSUER, resource_id=RESOURCE_ID)
require_auth = make_auth_dependency(validator)

app = FastAPI(title="Example MCP server (protected resource)")
app.include_router(protected_resource_router(RESOURCE_ID, ISSUER, resource_name="Example MCP Server"))


@app.post("/mcp/tools/call")
async def call_tool(claims: dict = Depends(require_auth)):
    return {"result": "ok", "called_by": claims["sub"]}
