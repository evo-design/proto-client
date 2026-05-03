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
        "create_run to execute. Prebuilt prompts (design_program, "
        "implement_constraint, implement_generator) and component-doc "
        "resources (bio://constraints/{key}, bio://generators/{key}, "
        "bio://optimizers/{key}) are also available."
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
