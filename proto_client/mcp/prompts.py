"""MCP prompts — reusable templates for tool discovery and education.

- ``find_tool`` and ``tool_walkthrough`` guide an LLM through tool discovery.
"""

from fastmcp import FastMCP
from fastmcp.prompts import Message

# --- Prompt implementations ---


def find_tool_impl(task: str) -> list[Message]:
    """Workflow prompt: pick the right bioinformatics tool for a task."""
    template = f"""\
Find the right bioinformatics tool for this task and explain how to call it.

**Task:** {task}

## Workflow

1. **Search** — call `search_tools(query="{task}")` for relevance-ranked candidates.
2. **Narrow (optional)** — call `list_tools(category=...)` or `list_tools(uses_gpu=...)` to
   browse a category or filter by compute.
3. **Inspect** — for the top 1-3 results, call `get_tool_schema(tool_key)` to see the
   input/config/output contract.
4. **Try** — call `get_tool_example(tool_key)` for a runnable input dict.
5. **Recommend** — pick the best tool and show the user a Python snippet using
   `client.tools.run(tool_key, inputs)` or the `run_tool` MCP tool.

If no tool matches, say so explicitly rather than recommending a poor fit.
"""
    return [Message(template, role="user")]


def tool_walkthrough_impl(tool_key: str) -> list[Message]:
    """Workflow prompt: walk a user through a single bioinformatics tool."""
    template = f"""\
Give a complete walkthrough of `{tool_key}`.

## Workflow

1. Call `get_tool_schema("{tool_key}")` to fetch the input, config, and output
   JSON Schemas.
2. Call `get_tool_example("{tool_key}")` for a minimal runnable input.
3. Read `proto-tools://citations/{tool_key}` for the BibTeX entry (may be a placeholder).
4. Read `proto-tools://tools/{tool_key}` for an assembled metadata view (label,
   schemas, example, citation, and links).

Then present the walkthrough:

- One-sentence purpose.
- Required vs optional input fields, with types.
- Config fields with their defaults.
- A runnable Python example calling `client.tools.run("{tool_key}", inputs, config)`.
- Citation, if available.
"""
    return [Message(template, role="user")]


# --- Prompt handlers ---


def find_tool(task: str) -> list[Message]:
    """Workflow prompt: pick the right bioinformatics tool for a task."""
    return find_tool_impl(task)


def tool_walkthrough(tool_key: str) -> list[Message]:
    """Workflow prompt: walk a user through a single bioinformatics tool."""
    return tool_walkthrough_impl(tool_key)


# --- Registration ---


def register_prompts(mcp: FastMCP) -> None:
    """Register MCP prompts on the given FastMCP instance."""
    mcp.prompt(
        description=(
            "Workflow for finding the right bioinformatics tool for a user's task. "
            "Guides through search_tools, list_tools, get_tool_schema, get_tool_example."
        ),
    )(find_tool)

    mcp.prompt(
        description=(
            "Workflow for walking a user through a single bioinformatics tool — "
            "schema, example input, citation, and a runnable Python snippet."
        ),
    )(tool_walkthrough)
