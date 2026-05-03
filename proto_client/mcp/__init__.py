"""MCP server exposing Proto Bio capabilities to AI agents.

Install with ``pip install proto-client[mcp]``, then run::

    python -m proto_client.mcp                                # stdio
    python -m proto_client.mcp --transport http --port 9300   # HTTP

The :func:`register_tools`, :func:`register_prompts`, and
:func:`register_resources` functions can also be called on any
``FastMCP`` instance to attach the same surface elsewhere.
"""

from proto_client.mcp.prompts import register_prompts
from proto_client.mcp.resources import register_resources
from proto_client.mcp.tools import register_tools

__all__ = [
    "register_prompts",
    "register_resources",
    "register_tools",
]
