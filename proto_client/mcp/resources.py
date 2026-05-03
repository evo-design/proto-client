"""MCP resources — markdown documentation for proto-language components.

Three URI templates:

- ``bio://constraints/{key}``
- ``bio://generators/{key}``
- ``bio://optimizers/{key}``

Each handler fetches the component list via ``AsyncProtoClient`` and renders
the requested spec as markdown with the JSON Schema inlined.
"""

import json
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ResourceError

from proto_client._async.client import AsyncProtoClient
from proto_client.errors import ProtoNotFoundError
from proto_client.mcp.tools import _get_client, _handle_proto_errors


def _format_metadata(spec: Any) -> str:
    """Render every spec field except those displayed elsewhere; skip empty/None/False."""
    displayed_elsewhere = {"key", "label", "description", "config_model"}
    parts: list[str] = []
    for name, field_info in type(spec).model_fields.items():
        if name in displayed_elsewhere or field_info.exclude:
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


# --- Resource handlers ---


@_handle_proto_errors(error_cls=ResourceError)
async def constraint_doc(key: str, ctx: Context) -> str:
    """Render markdown documentation for one constraint by key."""
    async with _get_client(ctx) as client:
        return await constraint_doc_impl(client, key)


@_handle_proto_errors(error_cls=ResourceError)
async def generator_doc(key: str, ctx: Context) -> str:
    """Render markdown documentation for one generator by key."""
    async with _get_client(ctx) as client:
        return await generator_doc_impl(client, key)


@_handle_proto_errors(error_cls=ResourceError)
async def optimizer_doc(key: str, ctx: Context) -> str:
    """Render markdown documentation for one optimizer by key."""
    async with _get_client(ctx) as client:
        return await optimizer_doc_impl(client, key)


# --- Registration ---


def register_resources(mcp: FastMCP) -> None:
    """Register MCP resources on the given FastMCP instance."""
    mcp.resource(
        "bio://constraints/{key}",
        description="Markdown documentation for a registered constraint.",
        mime_type="text/markdown",
    )(constraint_doc)

    mcp.resource(
        "bio://generators/{key}",
        description="Markdown documentation for a registered generator.",
        mime_type="text/markdown",
    )(generator_doc)

    mcp.resource(
        "bio://optimizers/{key}",
        description="Markdown documentation for a registered optimizer.",
        mime_type="text/markdown",
    )(optimizer_doc)
