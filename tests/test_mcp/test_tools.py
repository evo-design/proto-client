"""Tests for MCP tool handlers — verify delegation to AsyncProtoClient."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from proto_client.models import (
    ConstraintSpec,
    CreateRunResponse,
    GeneratorSpec,
    JobStatusResponse,
    OptimizerSpec,
    RunResponse,
    RunStatus,
    StageTimepointHistory,
    ToolInfo,
    ToolSchema,
    ValidationResponse,
)


@pytest.fixture
def mock_client():
    client = AsyncMock()
    with patch("proto_client.mcp.tools._client", client):
        yield client


EXPECTED_TOOLS = {
    "list_tools",
    "get_tool_schema",
    "run_tool",
    "list_components",
    "validate_program",
    "create_run",
    "get_run_status",
    "cancel_run",
    "get_run_results",
}


async def test_registered_tools():
    from proto_client.mcp.server import mcp

    tools = await mcp.list_tools()
    registered = {t.name for t in tools}
    assert registered == EXPECTED_TOOLS


# ---------------------------------------------------------------------------
# Tools namespace delegation
# ---------------------------------------------------------------------------


async def test_list_tools(mock_client: AsyncMock):
    from proto_client.mcp.tools import list_tools

    mock_client.tools.list.return_value = [
        ToolInfo(
            key="blast-search",
            service="BlastService",
            method="search",
            label="BLAST Search",
            category="sequence_search",
            description="Search sequences",
            uses_gpu=False,
        ),
    ]
    result = await list_tools()
    mock_client.tools.list.assert_awaited_once()
    assert result[0]["key"] == "blast-search"


async def test_get_tool_schema(mock_client: AsyncMock):
    from proto_client.mcp.tools import get_tool_schema

    mock_client.tools.get_schema.return_value = ToolSchema(
        inputs={"type": "object"},
        config={"type": "object"},
        output={"type": "object"},
    )
    result = await get_tool_schema("esmfold-prediction")
    mock_client.tools.get_schema.assert_awaited_once_with("esmfold-prediction")
    assert "inputs" in result


@pytest.mark.parametrize("config", [{"db": "nr"}, None])
async def test_run_tool(mock_client: AsyncMock, config: dict | None):
    from proto_client.mcp.tools import run_tool

    mock_client.tools.run.return_value = JobStatusResponse(
        job_id="j1",
        tool_key="blast-search",
        status="completed",
        result={"hits": []},
        created_at=datetime(2026, 4, 5),
    )
    result = await run_tool("blast-search", {"query": "MKTL"}, config)
    mock_client.tools.run.assert_awaited_once_with("blast-search", {"query": "MKTL"}, config)
    assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# Runs namespace delegation
# ---------------------------------------------------------------------------


async def test_list_components(mock_client: AsyncMock):
    from proto_client.mcp.tools import list_components

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
            key="mcmc",
            label="MCMC",
            description="MCMC",
            uses_gpu=False,
            config_model={},
            targets_single_segment=True,
        ),
    ]
    result = await list_components()
    assert len(result["constraints"]) == 1
    assert len(result["generators"]) == 1
    assert len(result["optimizers"]) == 1


async def test_validate_program(mock_client: AsyncMock):
    from proto_client.mcp.tools import validate_program

    mock_client.runs.validate.return_value = ValidationResponse(valid=True, message="OK")
    result = await validate_program({"constructs": []})
    mock_client.runs.validate.assert_awaited_once_with({"constructs": []})
    assert result["valid"] is True


async def test_create_run(mock_client: AsyncMock):
    from proto_client.mcp.tools import create_run

    mock_client.runs.create.return_value = CreateRunResponse(
        run_id="r1",
        status=RunStatus.pending,
        message="Created",
    )
    result = await create_run({"constructs": []})
    mock_client.runs.create.assert_awaited_once_with({"constructs": []})
    assert result["run_id"] == "r1"


async def test_get_run_status(mock_client: AsyncMock):
    from proto_client.mcp.tools import get_run_status

    mock_client.runs.get.return_value = RunResponse(
        id="r1",
        status=RunStatus.running,
        created_at=datetime(2026, 4, 5),
        updated_at=datetime(2026, 4, 5),
        current_stage=0,
        total_stages=1,
        stage_results=[],
    )
    result = await get_run_status("r1")
    mock_client.runs.get.assert_awaited_once_with("r1")
    assert result["status"] == "running"


async def test_cancel_run(mock_client: AsyncMock):
    from proto_client.mcp.tools import cancel_run

    mock_client.runs.cancel.return_value = RunResponse(
        id="r1",
        status=RunStatus.cancelled,
        created_at=datetime(2026, 4, 5),
        updated_at=datetime(2026, 4, 5),
        current_stage=0,
        total_stages=1,
        stage_results=[],
    )
    result = await cancel_run("r1")
    assert result["status"] == "cancelled"


@pytest.mark.parametrize(
    ("kwargs", "expected_call"),
    [
        ({}, {"stage": None, "offset": None, "limit": 10000}),
        ({"stage": 0, "limit": 50}, {"stage": 0, "offset": None, "limit": 50}),
    ],
)
async def test_get_run_results(mock_client: AsyncMock, kwargs: dict, expected_call: dict):
    from proto_client.mcp.tools import get_run_results

    mock_client.runs.get_timepoints.return_value = [
        StageTimepointHistory(optimizer_stage_idx=0, timepoints=[]),
    ]
    result = await get_run_results("r1", **kwargs)
    mock_client.runs.get_timepoints.assert_awaited_once_with("r1", **expected_call)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_client_not_initialized():
    from proto_client.mcp.tools import list_tools

    with patch("proto_client.mcp.tools._client", None):
        with pytest.raises(RuntimeError, match="not initialized"):
            await list_tools()


async def test_api_error_propagates(mock_client: AsyncMock):
    from proto_client.errors import ProtoNotFoundError
    from proto_client.mcp.tools import get_tool_schema

    mock_client.tools.get_schema.side_effect = ProtoNotFoundError("Not found", status_code=404)
    with pytest.raises(ProtoNotFoundError):
        await get_tool_schema("bogus")
