"""Tests for MCP tool implementations and registration."""

import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import PromptError, ResourceError, ToolError

from proto_client.errors import (
    ProtoAuthError,
    ProtoConflictError,
    ProtoNotFoundError,
    ProtoRateLimitError,
    ProtoServerError,
    ProtoValidationError,
    RunCancelledError,
    RunFailedError,
)
from proto_client.mcp.tools import (
    ComponentsResult,
    _get_client,
    _handle_proto_errors,
    get_tool_citation_impl,
    get_tool_example_impl,
    list_categories_impl,
    list_citations_impl,
    list_components_impl,
    list_cpu_tools_impl,
    list_gpu_tools_impl,
    register_tools,
    search_tools_impl,
)
from proto_client.models import (
    ConstraintSpec,
    GeneratorSpec,
    OptimizerSpec,
    ToolExample,
    ToolInfo,
)


@pytest.fixture
def mock_client():
    return AsyncMock()


_TOOL_BLAST = ToolInfo(
    key="blast-search",
    service="BlastService",
    method="search",
    label="BLAST Search",
    category="sequence_search",
    description="Search sequences against NCBI databases",
    uses_gpu=False,
)

_TOOL_ESMFOLD = ToolInfo(
    key="esmfold-prediction",
    service="EsmFoldService",
    method="predict",
    label="ESMFold Prediction",
    category="structure_prediction",
    description="Predict protein structure from sequence",
    uses_gpu=True,
    citation="@article{esm2,title={Evolutionary-scale prediction}}",
)


# --- Server setup ---


async def test_lifespan_creates_and_closes_client():
    from proto_client.mcp.server import _lifespan, mcp

    fake_client = AsyncMock()
    with patch("proto_client.mcp.server.AsyncProtoClient", return_value=fake_client):
        async with _lifespan(mcp) as context:
            assert context["client"] is fake_client
    fake_client.aclose.assert_awaited_once()


def test_main_stdio_dispatches_to_mcp_run(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["proto-client-mcp"])
    with patch("proto_client.mcp.server.mcp") as mock_mcp:
        from proto_client.mcp.__main__ import main

        main()
        mock_mcp.run.assert_called_once_with()


def test_main_http_serves_app_via_uvicorn(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["proto-client-mcp", "--transport", "http", "--host", "127.0.0.1", "--port", "8080"],
    )
    fake_app = object()
    with (
        patch("proto_client.mcp.app.build_app", return_value=fake_app) as mock_build,
        patch("uvicorn.run") as mock_run,
    ):
        from proto_client.mcp.__main__ import main

        main()
        mock_build.assert_called_once_with()
        mock_run.assert_called_once_with(fake_app, host="127.0.0.1", port=8080)


# --- HTTP wrapper ---


async def test_health_returns_ok():
    from proto_client.mcp.app import build_app

    app = build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


# --- Client lifecycle (_get_client branches on transport) ---


async def test_get_client_falls_back_to_lifespan_outside_http():
    fake_client = AsyncMock()
    ctx = MagicMock()
    ctx.lifespan_context = {"client": fake_client}
    with patch("proto_client.mcp.tools.get_http_request", side_effect=RuntimeError):
        async with _get_client(ctx) as client:
            assert client is fake_client


async def test_get_client_uses_bearer_token_from_http_request():
    fake_request = MagicMock()
    fake_request.headers = {"authorization": "Bearer test-token-xyz"}
    per_request_client = AsyncMock()
    per_request_client.__aenter__ = AsyncMock(return_value=per_request_client)
    per_request_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("proto_client.mcp.tools.get_http_request", return_value=fake_request),
        patch("proto_client.mcp.tools.AsyncProtoClient", return_value=per_request_client) as mock_cls,
    ):
        async with _get_client(MagicMock()) as client:
            assert client is per_request_client
        mock_cls.assert_called_once_with(api_key="test-token-xyz")


@pytest.mark.parametrize(
    "headers",
    [
        {},  # missing Authorization
        {"authorization": "Basic dXNlcjpwYXNz"},  # non-Bearer scheme
        {"authorization": "Bearer "},  # empty token
    ],
)
async def test_get_client_falls_back_when_no_valid_bearer(headers):
    """In HTTP context but no usable Bearer → use lifespan client."""
    fake_request = MagicMock()
    fake_request.headers = headers
    fake_lifespan_client = AsyncMock()
    ctx = MagicMock()
    ctx.lifespan_context = {"client": fake_lifespan_client}

    with patch("proto_client.mcp.tools.get_http_request", return_value=fake_request):
        async with _get_client(ctx) as client:
            assert client is fake_lifespan_client


async def test_get_client_raises_when_no_bearer_and_no_lifespan():
    ctx = MagicMock()
    ctx.lifespan_context = {}
    with patch("proto_client.mcp.tools.get_http_request", side_effect=RuntimeError):
        with pytest.raises(RuntimeError, match="no Bearer token in request and no client in lifespan context"):
            async with _get_client(ctx):
                pass


# --- Tool implementations with non-trivial logic ---


@pytest.mark.parametrize(
    ("query", "expected_first"),
    [
        ("blast-search", "blast-search"),  # exact key match dominates
        ("blast", "blast-search"),  # substring of key
        ("protein structure", "esmfold-prediction"),  # multi-term phrase match
    ],
)
async def test_search_tools_scoring_ranks_relevant_first(mock_client, query, expected_first):
    mock_client.tools.list.return_value = [_TOOL_BLAST, _TOOL_ESMFOLD]
    result = await search_tools_impl(mock_client, query)
    assert result[0].key == expected_first


async def test_search_tools_empty_query_returns_empty(mock_client):
    mock_client.tools.list.return_value = [_TOOL_BLAST]
    assert await search_tools_impl(mock_client, "") == []


async def test_search_tools_respects_max_results(mock_client):
    mock_client.tools.list.return_value = [_TOOL_BLAST, _TOOL_ESMFOLD]
    result = await search_tools_impl(mock_client, "prediction search", max_results=1)
    assert len(result) == 1


async def test_list_components_gathers_all_three_registries(mock_client):
    mock_client.runs.list_constraints.return_value = [
        ConstraintSpec(
            key="gc-content",
            label="GC",
            description="GC",
            uses_gpu=False,
            config_model={},
            tools_called=[],
            supported_sequence_types=["dna"],
        ),
    ]
    mock_client.runs.list_generators.return_value = [
        GeneratorSpec(
            key="random-dna",
            label="Random",
            description="Random",
            uses_gpu=False,
            config_model={},
            category="mutation",
            tools_called=[],
            supported_sequence_types=["dna"],
        ),
    ]
    mock_client.runs.list_optimizers.return_value = [
        OptimizerSpec(
            key="mcmc",
            label="MCMC",
            description="MCMC",
            uses_gpu=False,
            config_model={},
            targets_single_segment=True,
        ),
    ]

    result = await list_components_impl(mock_client)

    assert isinstance(result, ComponentsResult)
    assert [c.key for c in result.constraints] == ["gc-content"]
    assert [g.key for g in result.generators] == ["random-dna"]
    assert [o.key for o in result.optimizers] == ["mcmc"]
    # Verify gather actually parallelized the three calls
    mock_client.runs.list_constraints.assert_awaited_once()
    mock_client.runs.list_generators.assert_awaited_once()
    mock_client.runs.list_optimizers.assert_awaited_once()


# --- Tool discovery (categories, GPU/CPU, citation, example) ---


async def test_list_categories_groups_by_category(mock_client):
    mock_client.tools.list.return_value = [_TOOL_BLAST, _TOOL_ESMFOLD]
    assert await list_categories_impl(mock_client) == {
        "sequence_search": ["blast-search"],
        "structure_prediction": ["esmfold-prediction"],
    }


async def test_list_gpu_and_cpu_tools_partition(mock_client):
    mock_client.tools.list.return_value = [_TOOL_BLAST, _TOOL_ESMFOLD]
    assert [t.key for t in await list_gpu_tools_impl(mock_client)] == ["esmfold-prediction"]
    assert [t.key for t in await list_cpu_tools_impl(mock_client)] == ["blast-search"]


async def test_get_tool_citation_returns_citation_or_none(mock_client):
    mock_client.tools.list.return_value = [_TOOL_BLAST, _TOOL_ESMFOLD]
    assert await get_tool_citation_impl(mock_client, "esmfold-prediction") == _TOOL_ESMFOLD.citation
    # blast has no citation declared
    assert await get_tool_citation_impl(mock_client, "blast-search") is None


async def test_get_tool_citation_unknown_key_raises(mock_client):
    mock_client.tools.list.return_value = [_TOOL_BLAST]
    with pytest.raises(ProtoNotFoundError):
        await get_tool_citation_impl(mock_client, "missing-tool")


async def test_get_tool_example_returns_example_input(mock_client):
    mock_client.tools.get_example.return_value = ToolExample(example_input={"sequences": ["MKTL"]})
    assert await get_tool_example_impl(mock_client, "esmfold-prediction") == {"sequences": ["MKTL"]}
    mock_client.tools.get_example.assert_awaited_once_with("esmfold-prediction")


async def test_list_citations_filters_to_tools_with_citations(mock_client):
    mock_client.tools.list.return_value = [_TOOL_BLAST, _TOOL_ESMFOLD]
    assert await list_citations_impl(mock_client) == {"esmfold-prediction": _TOOL_ESMFOLD.citation}


# --- Registration ---


async def test_register_tools_attaches_full_surface():
    """Catches if a tool is forgotten in the registration list."""
    fresh_mcp = FastMCP("test-server")
    register_tools(fresh_mcp)
    registered = {t.name for t in await fresh_mcp.list_tools()}
    assert registered == {
        "list_tools",
        "search_tools",
        "get_tool_schema",
        "list_categories",
        "list_gpu_tools",
        "list_cpu_tools",
        "get_tool_citation",
        "get_tool_example",
        "list_citations",
        "run_tool",
        "list_components",
        "validate_program",
        "create_run",
        "get_run_status",
        "cancel_run",
        "run_stage",
        "get_run_results",
    }


@pytest.mark.parametrize(
    ("tool_name", "kwargs"),
    [
        ("list_tools", {}),
        ("list_categories", {}),
        ("list_gpu_tools", {}),
        ("list_cpu_tools", {}),
        ("get_tool_citation", {"tool_key": "blast-search"}),
        ("list_citations", {}),
    ],
)
async def test_registered_wrapper_routes_through_get_client(tool_name, kwargs):
    """Each registered wrapper goes through _get_client and reaches its impl."""
    fake_client = AsyncMock()
    fake_client.tools.list.return_value = [_TOOL_BLAST]

    @asynccontextmanager
    async def fake_get_client(_ctx):
        yield fake_client

    fresh_mcp = FastMCP("test-server")
    register_tools(fresh_mcp)
    handler = next(t for t in await fresh_mcp.list_tools() if t.name == tool_name)

    with patch("proto_client.mcp.tools._get_client", fake_get_client):
        await handler.fn(ctx=MagicMock(), **kwargs)

    fake_client.tools.list.assert_awaited()


async def test_registered_get_tool_example_calls_get_example():
    """get_tool_example wrapper routes through client.tools.get_example, not list."""
    fake_client = AsyncMock()
    fake_client.tools.get_example.return_value = ToolExample(example_input={"x": 1})

    @asynccontextmanager
    async def fake_get_client(_ctx):
        yield fake_client

    fresh_mcp = FastMCP("test-server")
    register_tools(fresh_mcp)
    handler = next(t for t in await fresh_mcp.list_tools() if t.name == "get_tool_example")

    with patch("proto_client.mcp.tools._get_client", fake_get_client):
        result = await handler.fn(ctx=MagicMock(), tool_key="esmfold-prediction")

    assert result == {"x": 1}
    fake_client.tools.get_example.assert_awaited_once_with("esmfold-prediction")


# --- New prompt impls ---


def test_find_tool_impl_embeds_task_in_template():
    from proto_client.mcp.prompts import find_tool_impl

    [msg] = find_tool_impl("predict protein structure")
    assert "predict protein structure" in msg.content.text
    assert "search_tools" in msg.content.text


def test_tool_walkthrough_impl_embeds_tool_key():
    from proto_client.mcp.prompts import tool_walkthrough_impl

    [msg] = tool_walkthrough_impl("esmfold-prediction")
    assert "esmfold-prediction" in msg.content.text
    assert "get_tool_schema" in msg.content.text


# --- Error mapping ---


@pytest.mark.parametrize(
    ("error", "match"),
    [
        (ProtoAuthError("Unauthorized", status_code=401), "Authentication failed"),
        (ProtoNotFoundError("Not found", status_code=404), "Not found"),
        (ProtoConflictError("Already completed", status_code=409), "Conflict"),
        (ProtoServerError("Internal error", status_code=500), "Server error"),
        (ProtoRateLimitError("Too many", status_code=429, retry_after=30.0), r"Retry after 30\.0s"),
        (ProtoRateLimitError("Too many", status_code=429, retry_after=None), "Rate limited"),
        (ProtoValidationError("Bad", status_code=422, errors=[{"loc": "x", "msg": "required"}]), "Validation failed"),
        (
            ProtoValidationError("Bad", status_code=422, errors=[{"loc": ["body", "name"], "msg": "required"}]),
            r"body → name",
        ),
        (TimeoutError("timed out"), "Timed out"),
        (RunFailedError("r1", "OOM killed"), "Run r1 failed"),
        (RunCancelledError("r1"), "cancelled"),
        (httpx.ConnectError("connection refused"), "Connection error"),
        (httpx.ReadTimeout("read timed out"), "Connection error"),
    ],
)
async def test_handle_proto_errors_maps_each_class_to_tool_error(error, match):
    @_handle_proto_errors
    async def boom():
        raise error

    with pytest.raises(ToolError, match=match):
        await boom()


@pytest.mark.parametrize("error_cls", [PromptError, ResourceError])
async def test_handle_proto_errors_honors_custom_error_cls(error_cls):
    """Prompt and resource handlers raise the semantically-correct FastMCP error subclass."""

    @_handle_proto_errors(error_cls=error_cls)
    async def boom():
        raise ProtoNotFoundError("nope", status_code=404)

    with pytest.raises(error_cls, match="Not found"):
        await boom()
