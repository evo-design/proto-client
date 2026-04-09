"""Tests for MCP server and tool handlers."""

import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

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
    _get_client,
    create_run,
    list_components,
    list_tools,
    run_tool,
    search_tools,
)
from proto_client.models import (
    ConstraintSpec,
    CreateRunResponse,
    GeneratorSpec,
    JobStatusResponse,
    OptimizerSpec,
    RunStatus,
    ToolInfo,
)


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def ctx(mock_client):
    mock_ctx = MagicMock()
    mock_ctx.lifespan_context = {"client": mock_client}
    return mock_ctx


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
)


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


def test_server_metadata():
    from proto_client.mcp.server import mcp

    assert mcp.name == "proto-bio"
    assert "Proto Bio" in mcp.instructions


async def test_lifespan_yields_client_in_context():
    from proto_client.mcp.server import _lifespan, mcp

    mock_client = AsyncMock()
    with patch("proto_client.mcp.server.AsyncProtoClient", return_value=mock_client):
        async with _lifespan(mcp) as context:
            assert context["client"] is mock_client
    mock_client.aclose.assert_awaited_once()


def test_main_stdio(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["proto-client-mcp"])
    with patch("proto_client.mcp.server.mcp") as mock_mcp:
        from proto_client.mcp.__main__ import main

        main()
        mock_mcp.run.assert_called_once_with()


def test_main_http(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["proto-client-mcp", "--transport", "http", "--host", "127.0.0.1", "--port", "8080"]
    )
    with patch("proto_client.mcp.server.mcp") as mock_mcp:
        from proto_client.mcp.__main__ import main

        main()
        mock_mcp.run.assert_called_once_with(transport="http", host="127.0.0.1", port=8080)


def test_get_client_missing_context():
    mock_ctx = MagicMock()
    mock_ctx.lifespan_context = {}
    with pytest.raises(RuntimeError, match="MCP server not initialized"):
        _get_client(mock_ctx)


# ---------------------------------------------------------------------------
# Tool delegation smoke tests
# ---------------------------------------------------------------------------


async def test_list_tools(mock_client, ctx):
    mock_client.tools.list.return_value = [_TOOL_BLAST]
    result = await list_tools(ctx=ctx)
    assert result[0]["key"] == "blast-search"


async def test_create_run(mock_client, ctx):
    mock_client.runs.create.return_value = CreateRunResponse(run_id="r1", status=RunStatus.pending, message="Created")
    result = await create_run({"constructs": []}, ctx=ctx)
    mock_client.runs.create.assert_awaited_once_with({"constructs": []}, execute=True)
    assert result["run_id"] == "r1"


async def test_list_components(mock_client, ctx):
    mock_client.runs.list_constraints.return_value = [
        ConstraintSpec(
            key="gc-content",
            label="GC Content",
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
            label="Random DNA",
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
            key="mcmc", label="MCMC", description="MCMC", uses_gpu=False, config_model={}, targets_single_segment=True
        ),
    ]
    result = await list_components(ctx=ctx)
    assert set(result.keys()) == {"constraints", "generators", "optimizers"}


async def test_run_tool_forwards_config_and_timeout(mock_client, ctx):
    mock_client.tools.run.return_value = JobStatusResponse(
        job_id="j1",
        tool_key="blast-search",
        status="completed",
        result={"hits": []},
        created_at=datetime(2026, 4, 5),
    )
    await run_tool("blast-search", {"query": "MKTL"}, ctx=ctx, config={"db": "nr"}, timeout=1800.0)
    mock_client.tools.run.assert_awaited_once_with("blast-search", {"query": "MKTL"}, {"db": "nr"}, timeout=1800.0)


# ---------------------------------------------------------------------------
# search_tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected_first"),
    [
        ("blast-search", "blast-search"),
        ("blast", "blast-search"),
        ("protein structure", "esmfold-prediction"),
    ],
)
async def test_search_tools_scoring(mock_client, ctx, query, expected_first):
    mock_client.tools.list.return_value = [_TOOL_BLAST, _TOOL_ESMFOLD]
    result = await search_tools(query, ctx=ctx)
    assert result[0]["key"] == expected_first


async def test_search_tools_empty_query(mock_client, ctx):
    mock_client.tools.list.return_value = [_TOOL_BLAST]
    assert await search_tools("", ctx=ctx) == []


async def test_search_tools_max_results(mock_client, ctx):
    mock_client.tools.list.return_value = [_TOOL_BLAST, _TOOL_ESMFOLD]
    result = await search_tools("prediction search", ctx=ctx, max_results=1)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


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
        (TimeoutError("timed out"), "Timed out"),
        (RunFailedError("r1", "OOM killed"), "Run r1 failed"),
        (RunCancelledError("r1"), "cancelled"),
    ],
)
async def test_error_mapping(mock_client, ctx, error, match):
    mock_client.tools.list.side_effect = error
    with pytest.raises(ToolError, match=match):
        await list_tools(ctx=ctx)
