"""FastMCP server exposing Proto Bio APIs to MCP-compatible AI clients.

The server wraps :class:`~proto_client.AsyncProtoClient` and exposes its
methods as MCP tools. Both stdio and HTTP transports are supported via the
CLI in ``__main__.py``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from proto_client._async.client import AsyncProtoClient


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncIterator[None]:
    """Create an :class:`AsyncProtoClient` on startup and close it on shutdown.

    The client reads ``PROTO_API_KEY``, ``PROTO_TOOLS_BASE_URL``, and
    ``PROTO_RUNS_BASE_URL`` from the environment — no arguments needed.
    """
    import proto_client.mcp.tools as tools_mod

    client = AsyncProtoClient()
    tools_mod._client = client
    try:
        yield
    finally:
        tools_mod._client = None
        await client.aclose()


mcp = FastMCP(
    name="proto-bio",
    instructions=(
        "Proto Bio: a platform for bioinformatics tool execution and "
        "biological sequence optimization. Use list_tools or list_components "
        "to discover capabilities, get_tool_schema to inspect a tool's "
        "input/output contract, then run_tool or create_run to execute."
    ),
    lifespan=_lifespan,
)

# Register tools by importing the module (decorators fire at import time).
import proto_client.mcp.tools  # noqa: F401, E402
