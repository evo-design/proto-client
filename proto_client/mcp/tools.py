"""MCP tool handlers wrapping :class:`~proto_client.AsyncProtoClient`.

Tools are top-level async functions decorated with :func:`_handle_proto_errors`
and registered on a FastMCP instance via :func:`register_tools`.

:func:`_get_client` yields the right client per call: a per-request client
keyed to a Bearer token in the HTTP headers, otherwise the lifespan-managed
client from ``ctx.lifespan_context``.

``_impl`` functions take an explicit client so tests can exercise them
with a mock without going through FastMCP.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, overload

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import FastMCPError, ToolError
from fastmcp.server.dependencies import get_http_request
from pydantic import BaseModel, Field

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
from proto_client.models import (
    CancelRunResponse,
    ConstraintSpec,
    CreateRunResponse,
    GeneratorSpec,
    JobStatusResponse,
    OptimizerSpec,
    PaginatedTimepoints,
    RunResponse,
    RunTimepointResponse,
    StageMetrics,
    ToolInfo,
    ToolSchema,
    ValidationResponse,
)

# --- Client lifecycle ---


def _bearer_token_from_request() -> str | None:
    """Return the Bearer token from the live HTTP request, or None."""
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token or None


@asynccontextmanager
async def _get_client(ctx: Context) -> AsyncIterator[AsyncProtoClient]:
    """Yield an :class:`AsyncProtoClient` for one tool call.

    Per-request when a Bearer token is in the HTTP headers (closed on exit),
    otherwise the lifespan-managed client (FastMCP owns its lifecycle).
    """
    token = _bearer_token_from_request()
    if token is not None:
        async with AsyncProtoClient(api_key=token) as per_request_client:
            yield per_request_client
        return

    try:
        lifespan_client: AsyncProtoClient = ctx.lifespan_context["client"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            "MCP server not initialized — no Bearer token in request and no client in lifespan context."
        ) from exc
    yield lifespan_client


# --- Error mapping ---

_F = Callable[..., Coroutine[Any, Any, Any]]


@overload
def _handle_proto_errors(fn: _F) -> _F: ...
@overload
def _handle_proto_errors(*, error_cls: type[FastMCPError]) -> Callable[[_F], _F]: ...
def _handle_proto_errors(fn: _F | None = None, *, error_cls: type[FastMCPError] = ToolError) -> Any:
    """Catch Proto API errors and re-raise as the given ``FastMCPError`` subclass.

    Defaults to :class:`ToolError`. Pass ``error_cls=PromptError`` or
    ``error_cls=ResourceError`` so the MCP client receives the
    semantically-correct error type for each primitive kind.
    """

    def _decorate(target: _F) -> _F:
        @wraps(target)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await target(*args, **kwargs)
            except ProtoAuthError as e:
                raise error_cls(f"Authentication failed: {e.message}") from e
            except ProtoRateLimitError as e:
                msg = f"Rate limited. Retry after {e.retry_after}s" if e.retry_after else "Rate limited"
                raise error_cls(msg) from e
            except ProtoValidationError as e:
                lines = []
                for err in e.errors:
                    loc = err.get("loc", "?")
                    loc_str = " → ".join(str(p) for p in loc) if isinstance(loc, (list, tuple)) else str(loc)
                    lines.append(f"  {loc_str}: {err.get('msg', '?')}")
                detail = "\n".join(lines) if lines else e.message
                raise error_cls(f"Validation failed:\n{detail}") from e
            except ProtoNotFoundError as e:
                raise error_cls(f"Not found: {e.message}") from e
            except ProtoConflictError as e:
                raise error_cls(f"Conflict: {e.message}") from e
            except ProtoServerError as e:
                raise error_cls(f"Server error (retriable): {e.message}") from e
            except (RunFailedError, RunCancelledError) as e:
                raise error_cls(str(e)) from e
            except TimeoutError as e:
                raise error_cls(f"Timed out: {e}") from e
            except ProtoAPIError as e:
                raise error_cls(f"API error [{e.status_code}]: {e.message}") from e
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                raise error_cls(f"Connection error: {e}") from e

        return wrapper

    if fn is not None:
        return _decorate(fn)
    return _decorate


# --- Local result models ---


class ComponentsResult(BaseModel):
    """Bundled discovery result combining the three component-spec lists."""

    constraints: list[ConstraintSpec] = Field(description="Available constraints with their config schemas.")
    generators: list[GeneratorSpec] = Field(description="Available sequence/structure generators.")
    optimizers: list[OptimizerSpec] = Field(description="Available optimization strategies.")


# --- Tool implementations (testable directly with a mock client) ---


async def list_tools_impl(
    client: AsyncProtoClient,
    category: str | None = None,
    uses_gpu: bool | None = None,
) -> list[ToolInfo]:
    """List registered bioinformatics tools, optionally filtered by category and/or GPU need."""
    tools = await client.tools.list()
    if category is not None:
        tools = [t for t in tools if t.category == category]
    if uses_gpu is not None:
        tools = [t for t in tools if t.uses_gpu is uses_gpu]
    return tools


async def search_tools_impl(
    client: AsyncProtoClient,
    query: str,
    max_results: int = 10,
) -> list[ToolInfo]:
    """Search bioinformatics tools by keyword with relevance scoring."""
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

        if len(terms) > 1:
            if query_lower in desc_lower:
                score += 5
            if query_lower in label_lower:
                score += 5

        if score > 0:
            scored.append((score, tool.key, tool))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t for _, _, t in scored[:max_results]]


async def get_tool_schema_impl(client: AsyncProtoClient, tool_key: str) -> ToolSchema:
    """Get input/config/output JSON schemas for a bioinformatics tool."""
    return await client.tools.get_schema(tool_key)


async def get_tool_example_impl(client: AsyncProtoClient, tool_key: str) -> dict[str, Any] | None:
    """Minimal valid input dict for a tool, or ``None`` if not declared."""
    return (await client.tools.get_example(tool_key)).example_input


async def run_tool_impl(
    client: AsyncProtoClient,
    tool_key: str,
    inputs: dict[str, Any],
    config: dict[str, Any] | None = None,
    timeout: float = 600.0,
) -> JobStatusResponse:
    """Execute a bioinformatics tool and poll to completion."""
    return await client.tools.run(tool_key, inputs, config, timeout=timeout)


async def list_components_impl(client: AsyncProtoClient) -> ComponentsResult:
    """List all proto-language constraints, generators, and optimizers."""
    constraints, generators, optimizers = await asyncio.gather(
        client.runs.list_constraints(),
        client.runs.list_generators(),
        client.runs.list_optimizers(),
    )
    return ComponentsResult(constraints=constraints, generators=generators, optimizers=optimizers)


async def validate_program_impl(client: AsyncProtoClient, program_data: dict[str, Any]) -> ValidationResponse:
    """Validate a proto-language program without executing it."""
    return await client.runs.validate(program_data)


async def create_run_impl(
    client: AsyncProtoClient,
    program_data: dict[str, Any],
    execute: bool = True,
) -> CreateRunResponse:
    """Submit an optimization run."""
    return await client.runs.create(program_data, execute=execute)


async def get_run_status_impl(client: AsyncProtoClient, run_id: str) -> RunResponse:
    """Get current status of an optimization run."""
    return await client.runs.get(run_id)


async def cancel_run_impl(client: AsyncProtoClient, run_id: str) -> CancelRunResponse:
    """Cancel a running optimization."""
    return await client.runs.cancel(run_id)


async def run_stage_impl(client: AsyncProtoClient, run_id: str, stage_index: int) -> RunResponse:
    """Start a specific stage of a multi-stage optimization run."""
    return await client.runs.run_stage(run_id, stage_index)


async def get_run_metrics_impl(
    client: AsyncProtoClient,
    run_id: str,
    stage: int | None = None,
    resolution: int | None = None,
) -> list[StageMetrics]:
    """Get the decimated energy series for a run."""
    return await client.runs.get_metrics(run_id, stage=stage, resolution=resolution)


async def get_run_timepoints_impl(
    client: AsyncProtoClient,
    run_id: str,
    stage: int | None = None,
    page: int = 0,
    page_size: int = 50,
) -> PaginatedTimepoints:
    """Get one page of full timepoint rows for a run."""
    return await client.runs.get_timepoints(run_id, stage=stage, page=page, page_size=page_size)


async def get_run_timepoint_impl(
    client: AsyncProtoClient,
    run_id: str,
    stage: int,
    timepoint: int,
) -> RunTimepointResponse:
    """Get a single full timepoint row by ``(stage, timepoint)`` coordinate."""
    return await client.runs.get_timepoint(run_id, stage, timepoint)


# --- Tool handlers ---


@_handle_proto_errors
async def list_tools(ctx: Context, category: str | None = None, uses_gpu: bool | None = None) -> list[ToolInfo]:
    """List available bioinformatics tools, optionally filtered by category and/or GPU need."""
    async with _get_client(ctx) as client:
        return await list_tools_impl(client, category, uses_gpu)


@_handle_proto_errors
async def search_tools(query: str, ctx: Context, max_results: int = 10) -> list[ToolInfo]:
    """Search bioinformatics tools by keyword."""
    async with _get_client(ctx) as client:
        return await search_tools_impl(client, query, max_results)


@_handle_proto_errors
async def get_tool_schema(tool_key: str, ctx: Context) -> ToolSchema:
    """Fetch input/config/output JSON Schemas for a tool."""
    async with _get_client(ctx) as client:
        return await get_tool_schema_impl(client, tool_key)


@_handle_proto_errors
async def get_tool_example(tool_key: str, ctx: Context) -> dict[str, Any] | None:
    """Get a tool's minimal valid input dict."""
    async with _get_client(ctx) as client:
        return await get_tool_example_impl(client, tool_key)


@_handle_proto_errors
async def run_tool(
    tool_key: str,
    inputs: dict[str, Any],
    ctx: Context,
    config: dict[str, Any] | None = None,
    timeout: float = 600.0,
) -> JobStatusResponse:
    """Execute a bioinformatics tool and poll to completion."""
    async with _get_client(ctx) as client:
        return await run_tool_impl(client, tool_key, inputs, config, timeout)


@_handle_proto_errors
async def list_components(ctx: Context) -> ComponentsResult:
    """List all constraints, generators, and optimizers."""
    async with _get_client(ctx) as client:
        return await list_components_impl(client)


@_handle_proto_errors
async def validate_program(program_data: dict[str, Any], ctx: Context) -> ValidationResponse:
    """Validate a program without executing it."""
    async with _get_client(ctx) as client:
        return await validate_program_impl(client, program_data)


@_handle_proto_errors
async def create_run(program_data: dict[str, Any], ctx: Context, execute: bool = True) -> CreateRunResponse:
    """Submit an optimization run."""
    async with _get_client(ctx) as client:
        return await create_run_impl(client, program_data, execute)


@_handle_proto_errors
async def get_run_status(run_id: str, ctx: Context) -> RunResponse:
    """Get current run status."""
    async with _get_client(ctx) as client:
        return await get_run_status_impl(client, run_id)


@_handle_proto_errors
async def cancel_run(run_id: str, ctx: Context) -> CancelRunResponse:
    """Cancel an in-progress run."""
    async with _get_client(ctx) as client:
        return await cancel_run_impl(client, run_id)


@_handle_proto_errors
async def run_stage(run_id: str, stage_index: int, ctx: Context) -> RunResponse:
    """Start a specific stage of a multi-stage run."""
    async with _get_client(ctx) as client:
        return await run_stage_impl(client, run_id, stage_index)


@_handle_proto_errors
async def get_run_metrics(
    run_id: str,
    ctx: Context,
    stage: int | None = None,
    resolution: int | None = None,
) -> list[StageMetrics]:
    """Get the decimated energy series for a run (cheap, chart-friendly)."""
    async with _get_client(ctx) as client:
        return await get_run_metrics_impl(client, run_id, stage, resolution)


@_handle_proto_errors
async def get_run_timepoints(
    run_id: str,
    ctx: Context,
    stage: int | None = None,
    page: int = 0,
    page_size: int = 50,
) -> PaginatedTimepoints:
    """Get one page of full timepoint rows for a run."""
    async with _get_client(ctx) as client:
        return await get_run_timepoints_impl(client, run_id, stage, page, page_size)


@_handle_proto_errors
async def get_run_timepoint(
    run_id: str,
    ctx: Context,
    stage: int,
    timepoint: int,
) -> RunTimepointResponse:
    """Get a single full timepoint row by ``(stage, timepoint)`` coordinate."""
    async with _get_client(ctx) as client:
        return await get_run_timepoint_impl(client, run_id, stage, timepoint)


# --- Registration ---


def register_tools(mcp: FastMCP) -> None:
    """Register all MCP tool handlers on the given FastMCP instance."""
    mcp.tool(
        description=(
            "List available bioinformatics tools (metadata: key, label, category, "
            "description, uses_gpu). Optionally filter by `category` and/or `uses_gpu`. "
            "Call get_tool_schema before run_tool."
        ),
        annotations={"readOnlyHint": True},
    )(list_tools)

    mcp.tool(
        description=(
            "Search bioinformatics tools by keyword, ranked by relevance against "
            "key/label/category/description. Returns the same metadata as list_tools."
        ),
        annotations={"readOnlyHint": True},
    )(search_tools)

    mcp.tool(
        description="Get the input, config, and output JSON Schemas for a tool.",
        annotations={"readOnlyHint": True},
    )(get_tool_schema)

    mcp.tool(
        description=(
            "Get a tool's minimal valid input as a dict — useful for quickstarts and "
            "as a template before building a real input from the schema."
        ),
        annotations={"readOnlyHint": True},
    )(get_tool_example)

    mcp.tool(
        description=(
            "Execute a bioinformatics tool and wait for the result. Submits and polls until "
            "completion. Call get_tool_schema first for the inputs/config formats. "
            "Raises ToolError on timeout, cancellation, or tool failure."
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
            "Discover available constraints, generators, and optimizers. "
            "Returns component metadata (key, label, description, config_model)."
        ),
        annotations={"readOnlyHint": True},
    )(list_components)

    mcp.tool(
        description=(
            "Validate an optimization program without executing it. "
            "Returns ``{valid, message}``; ``valid`` is false on structural issues."
        ),
        annotations={"readOnlyHint": True},
    )(validate_program)

    mcp.tool(
        description=(
            "Submit an optimization run. Returns ``{run_id, status, message}``. "
            "Use get_run_status to poll and get_run_timepoints / get_run_metrics "
            "to retrieve results."
        ),
        annotations={"destructiveHint": False, "openWorldHint": True},
    )(create_run)

    mcp.tool(
        description=(
            "Check status, stage progress, and timing of a run. "
            "``status`` is one of pending|running|completed|failed|cancelled. "
            "Once completed, fetch outputs with get_run_timepoints (full rows) "
            "or get_run_metrics (decimated chart series)."
        ),
        annotations={"readOnlyHint": True},
    )(get_run_status)

    mcp.tool(
        description=(
            "Cancel a running optimization. ``details.already_cancelled`` is true if the run had already finished."
        ),
        annotations={"destructiveHint": True, "idempotentHint": True},
    )(cancel_run)

    mcp.tool(
        description=(
            "Start a specific stage of a multi-stage run. Use after creating with "
            "execute=False, or to re-run a failed stage."
        ),
        annotations={"destructiveHint": True},
    )(run_stage)

    mcp.tool(
        description=(
            "Get the decimated energy series for a run — cheap to fetch, ideal for "
            "charts. Use get_run_timepoints for full per-step detail."
        ),
        annotations={"readOnlyHint": True},
    )(get_run_metrics)

    mcp.tool(
        description=(
            "Get one page of full timepoint rows (sequences, constraint scores, "
            "proposal data). Server-paginated; walk pages with the ``page`` arg."
        ),
        annotations={"readOnlyHint": True},
    )(get_run_timepoints)

    mcp.tool(
        description=(
            "Get a single full timepoint row by ``(stage, timepoint)`` coordinate. "
            "Cheap direct lookup when you already know the step you want."
        ),
        annotations={"readOnlyHint": True},
    )(get_run_timepoint)
