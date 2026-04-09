"""MCP tool handlers wrapping :class:`~proto_client.AsyncProtoClient`.

Each tool is a thin async wrapper around an ``AsyncProtoClient`` method.
The ``AsyncProtoClient`` is injected via FastMCP's lifespan context —
tool functions access it through ``ctx.lifespan_context["client"]``.
"""

import asyncio
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from proto_client._async.client import AsyncProtoClient
from proto_client.errors import (
    ProtoAPIError,
    ProtoAuthError,
    ProtoConflictError,
    ProtoNotFoundError,
    ProtoRateLimitError,
    ProtoServerError,
    ProtoValidationError,
    RunCancelledError,
    RunFailedError,
)
from proto_client.models import ToolInfo


def _get_client(ctx: Context) -> AsyncProtoClient:
    """Extract the ``AsyncProtoClient`` from the lifespan context."""
    try:
        client: AsyncProtoClient = ctx.lifespan_context["client"]
        return client
    except KeyError:
        raise RuntimeError("MCP server not initialized — client not found in lifespan context") from None


# ---------------------------------------------------------------------------
# Error mapping — ProtoAPIError subclasses → ToolError
# ---------------------------------------------------------------------------

_F = Callable[..., Coroutine[Any, Any, Any]]


def _handle_proto_errors(fn: _F) -> _F:
    """Catch Proto API errors and re-raise as MCP ToolError with agent-friendly messages.

    Transport-level errors (httpx.ConnectError, httpx.ReadTimeout, etc.)
    intentionally propagate uncaught as internal server errors.
    """

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except ProtoAuthError as e:
            raise ToolError(f"Authentication failed: {e.message}") from e
        except ProtoRateLimitError as e:
            msg = f"Rate limited. Retry after {e.retry_after}s" if e.retry_after else "Rate limited"
            raise ToolError(msg) from e
        except ProtoValidationError as e:
            lines = [f"  {err.get('loc', '?')}: {err.get('msg', '?')}" for err in e.errors]
            detail = "\n".join(lines) if lines else e.message
            raise ToolError(f"Validation failed:\n{detail}") from e
        except ProtoNotFoundError as e:
            raise ToolError(f"Not found: {e.message}") from e
        except ProtoConflictError as e:
            raise ToolError(f"Conflict: {e.message}") from e
        except ProtoServerError as e:
            raise ToolError(f"Server error (retriable): {e.message}") from e
        except (RunFailedError, RunCancelledError) as e:
            raise ToolError(str(e)) from e
        except TimeoutError as e:
            raise ToolError(f"Timed out: {e}") from e
        except ProtoAPIError as e:
            raise ToolError(f"API error [{e.status_code}]: {e.message}") from e

    return wrapper


# ---------------------------------------------------------------------------
# Tool handler functions (registered via register_tools below)
# ---------------------------------------------------------------------------


@_handle_proto_errors
async def list_tools(ctx: Context) -> list[dict[str, Any]]:
    """List all registered bioinformatics tools."""
    client = _get_client(ctx)
    tools = await client.tools.list()
    return [t.model_dump(mode="json") for t in tools]


@_handle_proto_errors
async def search_tools(query: str, ctx: Context, max_results: int = 10) -> list[dict[str, Any]]:
    """Search tools by keyword with relevance scoring.

    Args:
        query: Search query (e.g. 'protein structure', 'blast', 'esmfold').
        max_results: Maximum results to return (default 10).
    """
    client = _get_client(ctx)
    all_tools = await client.tools.list()

    query_lower = query.strip().lower()
    terms = query_lower.split()
    if not terms:
        return []

    scored: list[tuple[int, str, ToolInfo]] = []
    for tool in all_tools:
        score = 0
        key_lower = tool.key.lower()
        label_lower = tool.label.lower()
        category_lower = tool.category.lower()
        desc_lower = tool.description.lower()

        if key_lower == query_lower:
            score += 100

        for term in terms:
            if term == key_lower:
                score += 20
            elif term in key_lower:
                score += 5
            if term in label_lower:
                score += 3
            if term in category_lower:
                score += 3
            if term in desc_lower:
                score += 1

        # Bonus for matching the full multi-word query as a phrase
        if len(terms) > 1:
            if query_lower in desc_lower:
                score += 5
            if query_lower in label_lower:
                score += 5

        if score > 0:
            scored.append((score, tool.key, tool))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t.model_dump(mode="json") for _, _, t in scored[:max_results]]


@_handle_proto_errors
async def get_tool_schema(tool_key: str, ctx: Context) -> dict[str, Any]:
    """Fetch schemas for a tool.

    Args:
        tool_key: Tool registry key (e.g. 'esmfold-prediction', 'blast-search').
    """
    client = _get_client(ctx)
    schema = await client.tools.get_schema(tool_key)
    return schema.model_dump(mode="json")


@_handle_proto_errors
async def run_tool(
    tool_key: str,
    inputs: dict[str, Any],
    ctx: Context,
    config: dict[str, Any] | None = None,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Execute a tool and poll to completion.

    Args:
        tool_key: Tool registry key (e.g. 'esmfold-prediction').
        inputs: Input data matching the tool's Input schema.
        config: Config data matching the tool's Config schema. Omit to use tool defaults.
        timeout: Maximum seconds to wait for completion (default 600).
    """
    client = _get_client(ctx)
    result = await client.tools.run(tool_key, inputs, config, timeout=timeout)
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Runs namespace
# ---------------------------------------------------------------------------


@_handle_proto_errors
async def list_components(ctx: Context) -> dict[str, list[dict[str, Any]]]:
    """List all constraints, generators, and optimizers."""
    client = _get_client(ctx)
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


@_handle_proto_errors
async def validate_program(program_data: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Validate a program.

    Args:
        program_data: The full program dict.
    """
    client = _get_client(ctx)
    result = await client.runs.validate(program_data)
    return result.model_dump(mode="json")


@_handle_proto_errors
async def create_run(
    program_data: dict[str, Any],
    ctx: Context,
    execute: bool = True,
) -> dict[str, Any]:
    """Create an optimization run.

    Args:
        program_data: The full program dict (same format as validate_program).
        execute: Whether to start execution immediately (default True). Set to False to create idle.
    """
    client = _get_client(ctx)
    result = await client.runs.create(program_data, execute=execute)
    return result.model_dump(mode="json")


@_handle_proto_errors
async def get_run_status(run_id: str, ctx: Context) -> dict[str, Any]:
    """Get current run status.

    Args:
        run_id: The UUID of the run.
    """
    client = _get_client(ctx)
    result = await client.runs.get(run_id)
    return result.model_dump(mode="json")


@_handle_proto_errors
async def cancel_run(run_id: str, ctx: Context) -> dict[str, Any]:
    """Cancel an in-progress run.

    Args:
        run_id: The UUID of the run.
    """
    client = _get_client(ctx)
    result = await client.runs.cancel(run_id)
    return result.model_dump(mode="json")


@_handle_proto_errors
async def get_run_results(
    run_id: str,
    ctx: Context,
    stage: int | None = None,
    timepoint: int | None = None,
    offset: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get optimization timepoints for a run.

    Args:
        run_id: The UUID of the run.
        stage: Filter by optimizer stage index (optional).
        timepoint: Filter by timepoint index within a stage (requires stage).
        offset: Number of timepoints to skip (optional, omitted by default).
        limit: Maximum timepoints to return (default 100). Increase for large runs.
    """
    client = _get_client(ctx)
    results = await client.runs.get_timepoints(run_id, stage=stage, timepoint=timepoint, offset=offset, limit=limit)
    return [r.model_dump(mode="json") for r in results]


# ---------------------------------------------------------------------------
# Registration — called by server.py after FastMCP is created
# ---------------------------------------------------------------------------


def register_tools(mcp: FastMCP) -> None:
    """Register all tool handlers on the given FastMCP instance."""
    mcp.tool(
        description=(
            "List available bioinformatics tools. Returns tool metadata "
            "(key, label, category, description, uses_gpu). "
            "Call get_tool_schema(tool_key) for full input/config/output JSON Schemas before calling run_tool."
        ),
        annotations={"readOnlyHint": True},
    )(list_tools)

    mcp.tool(
        description=(
            "Search for bioinformatics tools by keyword. Scores matches against "
            "tool key, label, category, and description. Returns top results ranked by relevance."
        ),
        annotations={"readOnlyHint": True},
    )(search_tools)

    mcp.tool(
        description=(
            "Get the full input, config, and output JSON Schemas for a tool. "
            "Use this to understand what parameters a tool accepts before calling run_tool."
        ),
        annotations={"readOnlyHint": True},
    )(get_tool_schema)

    mcp.tool(
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
    )(run_tool)

    mcp.tool(
        description=(
            "Discover all available constraints, generators, and optimizers "
            "for building optimization programs. Returns component metadata "
            "including keys, labels, descriptions, and config schemas."
        ),
        annotations={"readOnlyHint": True},
    )(list_components)

    mcp.tool(
        description=(
            "Validate an optimization program without executing it. Checks "
            "structure, segment references, generator/constraint/optimizer "
            "keys, and configuration validity."
        ),
        annotations={"readOnlyHint": True},
    )(validate_program)

    mcp.tool(
        description=(
            "Submit an optimization run. Returns a run_id for tracking. "
            "Use get_run_status to monitor progress and get_run_results "
            "to retrieve sequences and scores."
        ),
        annotations={"destructiveHint": True},
    )(create_run)

    mcp.tool(
        description="Check the status, stage progress, and timing of an optimization run.",
        annotations={"readOnlyHint": True},
    )(get_run_status)

    mcp.tool(
        description="Cancel a running optimization.",
        annotations={"destructiveHint": True},
    )(cancel_run)

    mcp.tool(
        description=(
            "Get optimization results — sequences, constraint scores, and "
            "proposal data. Returns timepoint snapshots for the requested "
            "stage or all stages."
        ),
        annotations={"readOnlyHint": True},
    )(get_run_results)
