"""Tests for AsyncToolsNamespace with mocked HTTP."""

from unittest.mock import MagicMock

import pytest
from helpers import job_payload, mock_response
from pydantic import BaseModel

from proto_client._async.tools import AsyncToolsNamespace
from proto_client.errors import ProtoNotFoundError
from proto_client.models import JobStatus, JobStatusResponse, ToolInfo, ToolSchema


async def test_list_returns_tool_info(mock_async_http):
    mock_async_http.get.return_value = mock_response(
        [
            {
                "key": "esmfold-prediction",
                "service": "ESMFoldService",
                "method": "predict",
            }
        ]
    )
    ns = AsyncToolsNamespace(mock_async_http)
    tools = await ns.list()

    mock_async_http.get.assert_called_once_with("/api/v1/tools")
    assert len(tools) == 1
    assert isinstance(tools[0], ToolInfo)
    assert tools[0].key == "esmfold-prediction"
    assert tools[0].service == "ESMFoldService"
    assert tools[0].method == "predict"


async def test_get_schema(mock_async_http):
    mock_async_http.get.return_value = mock_response(
        {
            "inputs": {
                "type": "object",
                "properties": {"sequences": {"type": "array"}},
            },
            "config": {"type": "object"},
            "output": {"type": "object", "properties": {"pdb": {"type": "string"}}},
        }
    )
    ns = AsyncToolsNamespace(mock_async_http)
    schema = await ns.get_schema("esmfold-prediction")

    mock_async_http.get.assert_called_once_with("/api/v1/tools/esmfold-prediction/schema")
    assert isinstance(schema, ToolSchema)
    assert "sequences" in schema.inputs["properties"]
    assert schema.output["properties"]["pdb"]["type"] == "string"


async def test_submit(mock_async_http: MagicMock) -> None:
    mock_async_http.post.return_value = mock_response({"job_id": "abc123", "status": "pending"}, 202)
    ns = AsyncToolsNamespace(mock_async_http)
    job_id = await ns.submit("esmfold-prediction", {"sequences": ["MKTL"]})

    assert job_id == "abc123"
    mock_async_http.post.assert_called_once_with(
        "/api/v1/tools/esmfold-prediction/run",
        json={"inputs": {"sequences": ["MKTL"]}, "config": {}},
    )


async def test_cancel(mock_async_http):
    mock_async_http.post.return_value = mock_response(job_payload("cancelled", job_id="abc123", completed=True))
    ns = AsyncToolsNamespace(mock_async_http)
    result = await ns.cancel("esmfold-prediction", "abc123")

    assert isinstance(result, JobStatusResponse)
    assert result.status is JobStatus.cancelled


async def test_run_polls_until_complete(mock_async_http: MagicMock) -> None:
    mock_async_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_async_http.get.side_effect = [
        mock_response(job_payload("running")),
        mock_response(job_payload("completed", result={"answer": 42}, completed=True)),
    ]

    ns = AsyncToolsNamespace(mock_async_http)
    result = await ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)

    assert isinstance(result, JobStatusResponse)
    assert result.status is JobStatus.completed
    assert result.result == {"answer": 42}
    assert mock_async_http.get.call_count == 2


async def test_run_with_output_model(mock_async_http):
    class Out(BaseModel):
        answer: int

    mock_async_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_async_http.get.return_value = mock_response(job_payload("completed", result={"answer": 42}, completed=True))

    ns = AsyncToolsNamespace(mock_async_http)
    result = await ns.run(
        "esmfold-prediction",
        {"sequences": ["MKTL"]},
        poll_interval=0.01,
        output_model=Out,
    )

    assert isinstance(result.result, Out)
    assert result.result.answer == 42


async def test_run_raises_on_failure(mock_async_http):
    mock_async_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_async_http.get.return_value = mock_response(job_payload("failed", error="OOM", completed=True))

    ns = AsyncToolsNamespace(mock_async_http)
    with pytest.raises(RuntimeError, match="OOM"):
        await ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


async def test_run_raises_on_timeout(mock_async_http):
    mock_async_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_async_http.get.return_value = mock_response(job_payload("running"))

    ns = AsyncToolsNamespace(mock_async_http)
    with pytest.raises(TimeoutError):
        await ns.run(
            "esmfold-prediction",
            {"sequences": ["MKTL"]},
            poll_interval=0.01,
            timeout=0.05,
        )


async def test_submit_batch(mock_async_http):
    mock_async_http.post.return_value = mock_response({"job_id": "batch123", "status": "pending"}, 202)
    ns = AsyncToolsNamespace(mock_async_http)
    job_id = await ns.submit_batch("blast-search", [{"query": "MKTL"}, {"query": "VDAL"}])

    assert job_id == "batch123"
    mock_async_http.post.assert_called_once_with(
        "/api/v1/tools/blast-search/run-batch",
        json={"inputs_list": [{"query": "MKTL"}, {"query": "VDAL"}], "config": {}},
    )


async def test_submit_with_config(mock_async_http):
    config = {"threshold": 0.8, "max_results": 10}
    mock_async_http.post.return_value = mock_response({"job_id": "cfg123", "status": "pending"}, 202)
    ns = AsyncToolsNamespace(mock_async_http)
    job_id = await ns.submit_batch("blast-search", [{"query": "MKTL"}], config=config)

    assert job_id == "cfg123"
    mock_async_http.post.assert_called_once_with(
        "/api/v1/tools/blast-search/run-batch",
        json={"inputs_list": [{"query": "MKTL"}], "config": config},
    )


async def test_run_raises_on_cancelled(mock_async_http):
    mock_async_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_async_http.get.return_value = mock_response(job_payload("cancelled", job_id="j1", completed=True))

    ns = AsyncToolsNamespace(mock_async_http)
    with pytest.raises(RuntimeError, match="cancelled"):
        await ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


async def test_http_error_raises_typed_error(mock_async_http):
    mock_async_http.get.return_value = mock_response({"detail": "Not Found"}, 404)
    ns = AsyncToolsNamespace(mock_async_http)
    with pytest.raises(ProtoNotFoundError):
        await ns.list()


async def test_run_output_model_validation_failure(mock_async_http):
    class Strict(BaseModel):
        count: int

    mock_async_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_async_http.get.return_value = mock_response(
        job_payload("completed", result={"wrong_field": "oops"}, completed=True)
    )
    ns = AsyncToolsNamespace(mock_async_http)
    with pytest.raises(TypeError, match="does not conform to Strict"):
        await ns.run(
            "esmfold-prediction",
            {"sequences": ["MKTL"]},
            poll_interval=0.01,
            output_model=Strict,
        )


async def test_run_output_model_with_none_result_raises(mock_async_http):
    class Out(BaseModel):
        answer: int

    mock_async_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_async_http.get.return_value = mock_response(job_payload("completed", result=None, completed=True))
    ns = AsyncToolsNamespace(mock_async_http)
    with pytest.raises(TypeError, match="completed with no result"):
        await ns.run(
            "esmfold-prediction",
            {"sequences": ["MKTL"]},
            poll_interval=0.01,
            output_model=Out,
        )


async def test_run_batch_polls_until_complete(mock_async_http: MagicMock) -> None:
    mock_async_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_async_http.get.side_effect = [
        mock_response(job_payload("running", job_id="b1")),
        mock_response(job_payload("completed", job_id="b1", result={"items": [1, 2]}, completed=True)),
    ]

    ns = AsyncToolsNamespace(mock_async_http)
    result = await ns.run_batch("blast-search", [{"query": "MKTL"}, {"query": "VDAL"}], poll_interval=0.01)

    assert isinstance(result, JobStatusResponse)
    assert result.status is JobStatus.completed
    assert result.result == {"items": [1, 2]}
    assert mock_async_http.get.call_count == 2
