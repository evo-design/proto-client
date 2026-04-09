"""FastMCP server exposing Proto Bio APIs to MCP-compatible AI clients.

The server wraps :class:`~proto_client.AsyncProtoClient` and exposes its
methods as MCP tools. Both stdio and HTTP transports are supported via the
CLI in ``__main__.py``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from proto_client._async.client import AsyncProtoClient


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Create an :class:`AsyncProtoClient` on startup and close it on shutdown.

    The client reads ``PROTO_API_KEY``, ``PROTO_TOOLS_BASE_URL``, and
    ``PROTO_RUNS_BASE_URL`` from the environment — no arguments needed.
    """
    client = AsyncProtoClient()
    try:
        yield {"client": client}
    finally:
        await client.aclose()


mcp = FastMCP(
    name="proto-bio",
    instructions=(
        "Proto Bio: a platform for bioinformatics tool execution and "
        "biological sequence optimization. Use list_tools, search_tools, "
        "or list_components to discover capabilities, get_tool_schema to "
        "inspect a tool's input/output contract, then run_tool or "
        "create_run to execute."
    ),
    lifespan=_lifespan,
)


def _register_tools() -> None:
    """Register all MCP tool handlers on the ``mcp`` instance.

    Kept as an explicit call to avoid circular imports — tools.py no longer
    imports ``mcp`` at module level.
    """
    from proto_client.mcp.tools import register_tools

    register_tools(mcp)


_register_tools()
