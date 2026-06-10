"""FastMCP server exposing Proto Bio APIs to MCP-compatible AI clients.

Wraps :class:`~proto_client.AsyncProtoClient` and exposes its methods as MCP
tools, prompts, and resources. Both stdio and HTTP transports are supported
via the CLI in ``__main__.py``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from proto_client._async.client import AsyncProtoClient


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Create an :class:`AsyncProtoClient` on startup and close it on shutdown.

    The client reads ``PROTO_API_KEY`` and ``PROTO_RUNS_BASE_URL`` from the
    environment — no arguments needed.
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
        "Discover tools with list_tools, search_tools, list_categories, "
        "list_gpu_tools, or list_cpu_tools; inspect with get_tool_schema, "
        "get_tool_example, get_tool_citation, or list_citations; execute "
        "with run_tool. "
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


def _register_all() -> None:
    """Register tools, prompts, and resources on the ``mcp`` instance."""
    # Imports kept inside the function to avoid circular references — the
    # per-primitive modules don't reference ``mcp`` at module level.
    from proto_client.mcp.prompts import register_prompts
    from proto_client.mcp.resources import register_resources
    from proto_client.mcp.tools import register_tools

    register_tools(mcp)
    register_prompts(mcp)
    register_resources(mcp)


_register_all()
