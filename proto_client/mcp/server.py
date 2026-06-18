"""FastMCP server exposing Proto Bio APIs to MCP-compatible AI clients.

Wraps :class:`~proto_client.AsyncProtoClient` and exposes its methods as MCP
tools, prompts, and resources. Both stdio and HTTP transports are supported
via the CLI in ``__main__.py``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from proto_client._async.client import AsyncProtoClient
from proto_client.mcp.prompts import register_prompts
from proto_client.mcp.resources import register_resources
from proto_client.mcp.tools import register_tools


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Create an :class:`AsyncProtoClient` on startup and close it on shutdown.

    The client reads ``PROTO_API_KEY`` from the environment — no arguments needed.
    """
    client = AsyncProtoClient()
    try:
        yield {"client": client}
    finally:
        await client.aclose()


mcp = FastMCP(
    name="proto-bio",
    instructions=(
        "Proto Bio: a platform for bioinformatics tool execution and biological "
        "sequence optimization. "
        "Call whoami to confirm the calling key's workspace, scopes, and remaining credits. "
        "Discover tools with list_tools (optionally filtered by category / uses_gpu) "
        "or search_tools; inspect with get_tool_schema or get_tool_example; execute "
        "with run_tool (citations via the proto-tools://citations/{key} resource). "
        "Read any asset referenced in a result with fetch_asset (run_tool inlines small assets). "
        "Discover proto-language components with list_components; design with "
        "create_run / run_stage / get_run_status / cancel_run; fetch results with "
        "get_run_metrics (decimated chart series), get_run_timepoints (paginated "
        "full rows), or get_run_timepoint (single row); validate JSON with "
        "validate_program. "
        "Prompts: design_program, implement_constraint, implement_generator, "
        "find_tool, tool_walkthrough. "
        "Resources: bio://constraints/{key}, bio://generators/{key}, "
        "bio://optimizers/{key}, proto-tools://tools/{key}, "
        "proto-tools://schemas/{key}, proto-tools://citations/{key}."
    ),
    lifespan=_lifespan,
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Liveness probe for HTTP deployments."""
    return JSONResponse({"status": "healthy"})


def _register_all() -> None:
    """Register tools, prompts, and resources on the ``mcp`` instance."""
    register_tools(mcp)
    register_prompts(mcp)
    register_resources(mcp)


_register_all()
