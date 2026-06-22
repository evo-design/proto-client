"""MCP server exposing Proto Bio capabilities to AI agents.

:func:`register_tools`, :func:`register_prompts`, and :func:`register_resources`
attach the tool, prompt, and resource surface to a ``FastMCP`` instance.
"""

from proto_client.mcp.prompts import register_prompts
from proto_client.mcp.resources import register_resources
from proto_client.mcp.tools import register_tools

__all__ = [
    "register_prompts",
    "register_resources",
    "register_tools",
]
