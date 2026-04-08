"""Tests for AsyncToolsNamespace with mocked HTTP."""

from unittest.mock import AsyncMock

import httpx
import pytest
from helpers import job_payload, mock_response
from pydantic import BaseModel

from proto_client._async.tools import AsyncToolsNamespace
from proto_client.errors import ProtoAPIError, ProtoConflictError, ProtoNotFoundError
from proto_client.models import JobStatus, JobStatusResponse, ToolInfo, ToolSchema


@pytest.fixture
def mock_http() -> AsyncMock:
    """Override conftest fixture with an async mock for AsyncToolsNamespace tests."""
    return AsyncMock(spec=httpx.AsyncClient)


async def test_list_returns_tool_info(mock_http: AsyncMock) -> None:
    mock_http.get.return_value = mock_response(
        [
            {
                "key": "esmfold-prediction",
                "service": "ESMFoldService",
                "method": "predict",
            }
        ]
    )
    ns = AsyncToolsNamespace(mock_http)
    tools = await ns.list()

    mock_http.get.assert_called_once_with("/api/v1/tools")
    assert len(tools) == 1
    assert isinstance(tools[0], ToolInfo)
    assert tools[0].key == "esmfold-prediction"
    assert tools[0].service == "ESMFoldService"
    assert tools[0].method == "predict"


async def test_get_schema(mock_http: AsyncMock) -> None:
    mock_http.get.return_value = mock_response(
        {
            "inputs": {
                "type": "object",
                "properties": {"sequences": {"type": "array"}},
            },
            "config": {"type": "object"},
            "output": {"type": "object", "properties": {"pdb": {"type": "string"}}},
        }
    )
    ns = AsyncToolsNamespace(mock_http)
    schema = await ns.get_schema("esmfold-prediction")

    mock_http.get.assert_called_once_with("/api/v1/tools/esmfold-prediction/schema")
    assert isinstance(schema, ToolSchema)
    assert "sequences" in schema.inputs["properties"]
    assert schema.output["properties"]["pdb"]["type"] == "string"


async def test_submit(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "abc123", "status": "pending"}, 202)
    ns = AsyncToolsNamespace(mock_http)
    job_id = await ns.submit("esmfold-prediction", {"sequences": ["MKTL"]})

    assert job_id == "abc123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/esmfold-prediction/run",
        json={"inputs": {"sequences": ["MKTL"]}, "config": {}},
        headers={},
    )


async def test_cancel(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response(job_payload("cancelled", job_id="abc123", completed=True))
    ns = AsyncToolsNamespace(mock_http)
    result = await ns.cancel("esmfold-prediction", "abc123")

    assert isinstance(result, JobStatusResponse)
    assert result.status is JobStatus.cancelled


async def test_run_polls_until_complete(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.side_effect = [
        mock_response(job_payload("running")),
        mock_response(job_payload("completed", result={"answer": 42}, completed=True)),
    ]

    ns = AsyncToolsNamespace(mock_http)
    result = await ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)

    assert isinstance(result, JobStatusResponse)
    assert result.status is JobStatus.completed
    assert result.result == {"answer": 42}
    assert mock_http.get.call_count == 2


async def test_run_with_output_model(mock_http: AsyncMock) -> None:
    class Out(BaseModel):
        answer: int

    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", result={"answer": 42}, completed=True))

    ns = AsyncToolsNamespace(mock_http)
    result = await ns.run(
        "esmfold-prediction",
        {"sequences": ["MKTL"]},
        poll_interval=0.01,
        output_model=Out,
    )

    assert isinstance(result.result, Out)
    assert result.result.answer == 42


async def test_run_raises_on_failure(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("failed", error="OOM", completed=True))

    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="OOM"):
        await ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


async def test_run_raises_on_timeout(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("running"))

    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(TimeoutError):
        await ns.run(
            "esmfold-prediction",
            {"sequences": ["MKTL"]},
            poll_interval=0.01,
            timeout=0.05,
        )


async def test_submit_batch(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "batch123", "status": "pending"}, 202)
    ns = AsyncToolsNamespace(mock_http)
    job_id = await ns.submit_batch("blast-search", [{"query": "MKTL"}, {"query": "VDAL"}])

    assert job_id == "batch123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast-search/run-batch",
        json={"inputs_list": [{"query": "MKTL"}, {"query": "VDAL"}], "config": {}},
        headers={},
    )


async def test_submit_batch_with_config(mock_http: AsyncMock) -> None:
    config = {"threshold": 0.8, "max_results": 10}
    mock_http.post.return_value = mock_response({"job_id": "cfg123", "status": "pending"}, 202)
    ns = AsyncToolsNamespace(mock_http)
    job_id = await ns.submit_batch("blast-search", [{"query": "MKTL"}], config=config)

    assert job_id == "cfg123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast-search/run-batch",
        json={"inputs_list": [{"query": "MKTL"}], "config": config},
        headers={},
    )


async def test_run_raises_on_cancelled(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("cancelled", job_id="j1", completed=True))

    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="cancelled"):
        await ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


async def test_http_error_raises_typed_error(mock_http: AsyncMock) -> None:
    mock_http.get.return_value = mock_response({"detail": "Not Found"}, 404)
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(ProtoNotFoundError):
        await ns.list()


async def test_run_output_model_validation_failure(mock_http: AsyncMock) -> None:
    class Strict(BaseModel):
        count: int

    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", result={"wrong_field": "oops"}, completed=True))
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="does not conform to Strict"):
        await ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01, output_model=Strict)


async def test_run_output_model_with_none_result_raises(mock_http: AsyncMock) -> None:
    class Out(BaseModel):
        answer: int

    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", result=None, completed=True))
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="completed with no result"):
        await ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01, output_model=Out)


# -- run_batch --


async def test_run_batch_polls_until_complete(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.side_effect = [
        mock_response(job_payload("running", job_id="b1")),
        mock_response(job_payload("completed", job_id="b1", result={"answer": 42}, completed=True)),
    ]

    ns = AsyncToolsNamespace(mock_http)
    result = await ns.run_batch("blast-search", [{"query": "MKTL"}], poll_interval=0.01)

    assert isinstance(result, JobStatusResponse)
    assert result.status is JobStatus.completed
    assert mock_http.get.call_count == 2


async def test_run_batch_raises_on_failure(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("failed", error="Backend crashed", completed=True))
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="Backend crashed"):
        await ns.run_batch("blast", [{}], poll_interval=0.01)


async def test_run_batch_cancelled(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("cancelled", job_id="b1", completed=True))
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="cancelled"):
        await ns.run_batch("blast", [{}], poll_interval=0.01)


async def test_run_batch_timeout(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("running", job_id="b1"))
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(TimeoutError):
        await ns.run_batch("blast", [{}], poll_interval=0.01, timeout=0.05)


# -- Idempotency key --


async def test_submit_sends_idempotency_header(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    ns = AsyncToolsNamespace(mock_http)
    await ns.submit("blast", {"query": "MKTL"}, idempotency_key="abc-123")

    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast/run",
        json={"inputs": {"query": "MKTL"}, "config": {}},
        headers={"Idempotency-Key": "abc-123"},
    )


async def test_submit_batch_sends_idempotency_header(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    ns = AsyncToolsNamespace(mock_http)
    await ns.submit_batch("blast", [{"query": "MKTL"}], idempotency_key="batch-key")

    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast/run-batch",
        json={"inputs_list": [{"query": "MKTL"}], "config": {}},
        headers={"Idempotency-Key": "batch-key"},
    )


async def test_submit_idempotency_409_raises_conflict(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response(
        {"detail": "Idempotency key 'k1' was previously used with different inputs"},
        409,
    )
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(ProtoConflictError, match="different inputs"):
        await ns.submit("blast", {"query": "MKTL"}, idempotency_key="k1")


# -- Error paths for individual methods --


async def test_get_schema_error(mock_http: AsyncMock) -> None:
    mock_http.get.return_value = mock_response({"detail": "Not Found"}, 404)
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(ProtoNotFoundError):
        await ns.get_schema("nonexistent-tool")


async def test_submit_batch_error(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"detail": "Server Error"}, 500)
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(ProtoAPIError):
        await ns.submit_batch("blast", [{"query": "MKTL"}])


async def test_get_error(mock_http: AsyncMock) -> None:
    mock_http.get.return_value = mock_response({"detail": "Not Found"}, 404)
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(ProtoNotFoundError):
        await ns.get("blast", "missing-job")


async def test_cancel_error(mock_http: AsyncMock) -> None:
    mock_http.post.return_value = mock_response({"detail": "Job already completed"}, 409)
    ns = AsyncToolsNamespace(mock_http)
    with pytest.raises(ProtoConflictError):
        await ns.cancel("blast", "done-job")
