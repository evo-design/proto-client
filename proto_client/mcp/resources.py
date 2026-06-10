"""MCP resources — rendered views over registry/API metadata.

These are not the human-authored docs site. Each
handler fetches data via ``AsyncProtoClient`` and formats the live registry
response so an MCP client can read it inline.

Six URI templates:

- ``bio://constraints/{key}`` — constraint spec + JSON Schema (markdown)
- ``bio://generators/{key}`` — generator spec + JSON Schema (markdown)
- ``bio://optimizers/{key}`` — optimizer spec + JSON Schema (markdown)
- ``proto-tools://tools/{key}`` — tool metadata + schemas + example + citation (markdown)
- ``proto-tools://schemas/{key}`` — input/config/output JSON Schemas (JSON)
- ``proto-tools://citations/{key}`` — BibTeX citation (plain text)
"""

import json
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ResourceError

from proto_client._async.client import AsyncProtoClient
from proto_client.errors import ProtoNotFoundError
from proto_client.mcp.tools import _get_client, _handle_proto_errors
from proto_client.models import ToolInfo


def _format_metadata(spec: Any) -> str:
    """Render every spec field except those displayed elsewhere; skip empty/None/False."""
    displayed_elsewhere = {"key", "label", "description", "config_model"}
    parts: list[str] = []
    for name in type(spec).model_fields:
        if name in displayed_elsewhere:
            continue
        value = getattr(spec, name)
        if value is None or value is False or value == [] or value == "":
            continue
        if hasattr(value, "value"):
            value = value.value
        parts.append(f"{name.replace('_', ' ').title()}: {value}")
    return " | ".join(parts)


def _format_component_doc(spec: Any, component_type: str) -> str:
    """Render a constraint/generator/optimizer spec as markdown."""
    lines = [
        f"# {spec.label} ({spec.key})",
        f"Type: {component_type} | {spec.description}",
    ]

    metadata = _format_metadata(spec)
    if metadata:
        lines.extend([metadata, ""])

    config_model = getattr(spec, "config_model", None)
    if config_model:
        lines.append(f"Config (JSON Schema):\n```json\n{json.dumps(config_model, indent=2)}\n```\n")

    return "\n".join(lines)


# --- Resource implementations ---


async def constraint_doc_impl(client: AsyncProtoClient, key: str) -> str:
    """Render the doc for one constraint."""
    constraints = await client.runs.list_constraints()
    spec = next((c for c in constraints if c.key == key), None)
    if spec is None:
        available = ", ".join(sorted(c.key for c in constraints))
        raise ProtoNotFoundError(f"Unknown constraint '{key}'. Available: {available}", status_code=404)
    return _format_component_doc(spec, "constraint")


async def generator_doc_impl(client: AsyncProtoClient, key: str) -> str:
    """Render the doc for one generator."""
    generators = await client.runs.list_generators()
    spec = next((g for g in generators if g.key == key), None)
    if spec is None:
        available = ", ".join(sorted(g.key for g in generators))
        raise ProtoNotFoundError(f"Unknown generator '{key}'. Available: {available}", status_code=404)
    return _format_component_doc(spec, "generator")


async def optimizer_doc_impl(client: AsyncProtoClient, key: str) -> str:
    """Render the doc for one optimizer."""
    optimizers = await client.runs.list_optimizers()
    spec = next((o for o in optimizers if o.key == key), None)
    if spec is None:
        available = ", ".join(sorted(o.key for o in optimizers))
        raise ProtoNotFoundError(f"Unknown optimizer '{key}'. Available: {available}", status_code=404)
    return _format_component_doc(spec, "optimizer")


async def _find_tool(client: AsyncProtoClient, key: str) -> ToolInfo:
    """Fetch the tool metadata for ``key`` or raise ProtoNotFoundError."""
    for tool in await client.tools.list():
        if tool.key == key:
            return tool
    raise ProtoNotFoundError(f"Unknown tool '{key}'", status_code=404)


async def tool_doc_impl(client: AsyncProtoClient, key: str) -> str:
    """Render full markdown docs for a tool: metadata + schemas + example + citation."""
    tool = await _find_tool(client, key)
    schema = await client.tools.get_schema(key)
    example = (await client.tools.get_example(key)).example_input

    lines = [
        f"# {tool.label} (`{tool.key}`)",
        f"Category: {tool.category} | {'GPU' if tool.uses_gpu else 'CPU'}",
        "",
        tool.description,
        "",
    ]
    links: list[str] = []
    if tool.docs_url:
        links.append(f"[Docs]({tool.docs_url})")
    if tool.github_url:
        links.append(f"[GitHub]({tool.github_url})")
    if tool.paper_url:
        links.append(f"[Paper]({tool.paper_url})")
    if tool.example_notebook_url:
        links.append(f"[Example notebook]({tool.example_notebook_url})")
    if links:
        lines.extend([" · ".join(links), ""])

    lines.append(f"## Input schema\n```json\n{json.dumps(schema.inputs, indent=2)}\n```\n")
    lines.append(f"## Config schema\n```json\n{json.dumps(schema.config, indent=2)}\n```\n")
    lines.append(f"## Output schema\n```json\n{json.dumps(schema.output, indent=2)}\n```\n")

    if example is not None:
        lines.append(f"## Example input\n```json\n{json.dumps(example, indent=2)}\n```\n")

    if tool.citation:
        lines.append(f"## Citation\n```bibtex\n{tool.citation}\n```")

    return "\n".join(lines)


async def tool_schema_resource_impl(client: AsyncProtoClient, key: str) -> str:
    """Return a tool's JSON schemas as a single JSON document."""
    schema = await client.tools.get_schema(key)
    return json.dumps(schema.model_dump(mode="json"), indent=2)


async def tool_citation_resource_impl(client: AsyncProtoClient, key: str) -> str:
    """Return a tool's BibTeX citation, or a marker if not declared."""
    tool = await _find_tool(client, key)
    return tool.citation or f"% No citation declared for {tool.key}."


# --- Resource handlers ---


@_handle_proto_errors(error_cls=ResourceError)
async def constraint_doc(key: str, ctx: Context) -> str:
    """Render the constraint spec + JSON Schema as markdown."""
    async with _get_client(ctx) as client:
        return await constraint_doc_impl(client, key)


@_handle_proto_errors(error_cls=ResourceError)
async def generator_doc(key: str, ctx: Context) -> str:
    """Render the generator spec + JSON Schema as markdown."""
    async with _get_client(ctx) as client:
        return await generator_doc_impl(client, key)


@_handle_proto_errors(error_cls=ResourceError)
async def optimizer_doc(key: str, ctx: Context) -> str:
    """Render the optimizer spec + JSON Schema as markdown."""
    async with _get_client(ctx) as client:
        return await optimizer_doc_impl(client, key)


@_handle_proto_errors(error_cls=ResourceError)
async def tool_doc(key: str, ctx: Context) -> str:
    """Render tool metadata + schemas + example + citation as markdown."""
    async with _get_client(ctx) as client:
        return await tool_doc_impl(client, key)


@_handle_proto_errors(error_cls=ResourceError)
async def tool_schema_resource(key: str, ctx: Context) -> str:
    """Return the tool's input/config/output JSON Schemas."""
    async with _get_client(ctx) as client:
        return await tool_schema_resource_impl(client, key)


@_handle_proto_errors(error_cls=ResourceError)
async def tool_citation_resource(key: str, ctx: Context) -> str:
    """Return the tool's BibTeX citation (or a placeholder marker if none)."""
    async with _get_client(ctx) as client:
        return await tool_citation_resource_impl(client, key)


# --- Registration ---


def register_resources(mcp: FastMCP) -> None:
    """Register MCP resources on the given FastMCP instance."""
    mcp.resource(
        "bio://constraints/{key}",
        description="Constraint spec + JSON Schema for one key, rendered as markdown.",
        mime_type="text/markdown",
    )(constraint_doc)

    mcp.resource(
        "bio://generators/{key}",
        description="Generator spec + JSON Schema for one key, rendered as markdown.",
        mime_type="text/markdown",
    )(generator_doc)

    mcp.resource(
        "bio://optimizers/{key}",
        description="Optimizer spec + JSON Schema for one key, rendered as markdown.",
        mime_type="text/markdown",
    )(optimizer_doc)

    mcp.resource(
        "proto-tools://tools/{key}",
        description="Tool metadata + schemas + example + citation for one key, rendered as markdown.",
        mime_type="text/markdown",
    )(tool_doc)

    mcp.resource(
        "proto-tools://schemas/{key}",
        description="Input/config/output JSON Schemas for one tool key.",
        mime_type="application/json",
    )(tool_schema_resource)

    mcp.resource(
        "proto-tools://citations/{key}",
        description="BibTeX citation for one tool key.",
        mime_type="text/plain",
    )(tool_citation_resource)
