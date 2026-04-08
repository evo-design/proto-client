"""MCP tool handlers wrapping :class:`~proto_client.AsyncProtoClient`.

Each tool is a thin async wrapper around an ``AsyncProtoClient`` method.
The module-level ``_client`` reference is set by the server lifespan in
``server.py`` — it is ``None`` until the server starts.
"""

import asyncio
from typing import Any

from proto_client._async.client import AsyncProtoClient
from proto_client.mcp.server import mcp

# Set by the server lifespan; ``None`` outside a running server.
_client: AsyncProtoClient | None = None


def _get_client() -> AsyncProtoClient:
    """Return the active client or raise if the server is not running."""
    if _client is None:
        raise RuntimeError("MCP server not initialized — _client is None")
    return _client


# ---------------------------------------------------------------------------
# Tools namespace (wrapping client.tools)
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "List available bioinformatics tools. Returns tool metadata (key, service, method). "
        "Call get_tool_schema(tool_key) to fetch full input/config/output JSON Schemas before calling run_tool."
    ),
    annotations={"readOnlyHint": True},
)
async def list_tools() -> list[dict[str, Any]]:
    """List all registered bioinformatics tools."""
    client = _get_client()
    tools = await client.tools.list()
    return [t.model_dump(mode="json") for t in tools]


@mcp.tool(
    description=(
        "Get the full input, config, and output JSON Schemas for a tool. "
        "Use this to understand what parameters a tool accepts before calling run_tool."
    ),
    annotations={"readOnlyHint": True},
)
async def get_tool_schema(tool_key: str) -> dict[str, Any]:
    """Fetch schemas for a tool.

    Args:
        tool_key: Tool registry key (e.g. 'esmfold-prediction', 'blast-search').
    """
    client = _get_client()
    schema = await client.tools.get_schema(tool_key)
    return schema.model_dump(mode="json")


@mcp.tool(
    description=(
        "Execute a bioinformatics tool and wait for the result. Submits "
        "the job and polls until completion. Call get_tool_schema first "
        "to see the expected input format."
    ),
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def run_tool(
    tool_key: str,
    inputs: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a tool and poll to completion.

    Args:
        tool_key: Tool registry key (e.g. 'esmfold-prediction').
        inputs: Input data matching the tool's Input schema.
        config: Config data matching the tool's Config schema. Omit to use tool defaults.
    """
    client = _get_client()
    result = await client.tools.run(tool_key, inputs, config)
    # mode="json" serializes datetime fields to ISO strings
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Runs namespace (wrapping client.runs)
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Discover all available constraints, generators, and optimizers "
        "for building optimization programs. Returns component metadata "
        "including keys, labels, descriptions, and config schemas."
    ),
    annotations={"readOnlyHint": True},
)
async def list_components() -> dict[str, list[dict[str, Any]]]:
    """List all constraints, generators, and optimizers."""
    client = _get_client()
    constraints, generators, optimizers = await asyncio.gather(
        client.runs.list_constraints(),
        client.runs.list_generators(),
        client.runs.list_optimizers(),
    )
    return {
        "constraints": [c.model_dump(mode="json") for c in constraints],
        "generators": [g.model_dump(mode="json") for g in generators],
        "optimizers": [o.model_dump(mode="json") for o in optimizers],
    }


@mcp.tool(
    description=(
        "Validate an optimization program without executing it. Checks "
        "structure, segment references, generator/constraint/optimizer "
        "keys, and configuration validity."
    ),
    annotations={"readOnlyHint": True},
)
async def validate_program(program_data: dict[str, Any]) -> dict[str, Any]:
    """Validate a program.

    Args:
        program_data: The full program dict.
    """
    client = _get_client()
    result = await client.runs.validate(program_data)
    return result.model_dump(mode="json")


@mcp.tool(
    description=(
        "Submit an optimization run. Returns a run_id for tracking. "
        "Use get_run_status to monitor progress and get_run_results "
        "to retrieve sequences and scores."
    ),
    annotations={"destructiveHint": True},
)
async def create_run(program_data: dict[str, Any]) -> dict[str, Any]:
    """Create and execute an optimization run.

    Args:
        program_data: The full program dict (same format as validate_program).
    """
    client = _get_client()
    result = await client.runs.create(program_data)
    return result.model_dump(mode="json")


@mcp.tool(
    description="Check the status, stage progress, and timing of an optimization run.",
    annotations={"readOnlyHint": True},
)
async def get_run_status(run_id: str) -> dict[str, Any]:
    """Get current run status.

    Args:
        run_id: The UUID of the run.
    """
    client = _get_client()
    result = await client.runs.get(run_id)
    return result.model_dump(mode="json")


@mcp.tool(
    description="Cancel a running optimization.",
    annotations={"destructiveHint": True},
)
async def cancel_run(run_id: str) -> dict[str, Any]:
    """Cancel an in-progress run.

    Args:
        run_id: The UUID of the run.
    """
    client = _get_client()
    result = await client.runs.cancel(run_id)
    return result.model_dump(mode="json")


@mcp.tool(
    description=(
        "Get optimization results — sequences, constraint scores, and "
        "proposal data. Returns timepoint snapshots for the requested "
        "stage or all stages."
    ),
    annotations={"readOnlyHint": True},
)
async def get_run_results(
    run_id: str,
    stage: int | None = None,
    offset: int | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Get optimization timepoints for a run.

    Args:
        run_id: The UUID of the run.
        stage: Filter by optimizer stage index (optional).
        offset: Number of timepoints to skip (default 0).
        limit: Maximum timepoints to return (default 100).
    """
    client = _get_client()
    results = await client.runs.get_timepoints(run_id, stage=stage, offset=offset, limit=limit)
    return [r.model_dump(mode="json") for r in results]
