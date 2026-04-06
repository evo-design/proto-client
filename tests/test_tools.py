"""Tests for ToolsNamespace with mocked HTTP."""

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import BaseModel

from proto_client.errors import ProtoNotFoundError
from proto_client.models import JobStatus, JobStatusResponse, ToolInfo, ToolSchema
from proto_client.tools import ToolsNamespace

_CREATED_AT = "2026-04-05T12:00:00"
_COMPLETED_AT = "2026-04-05T12:00:05"


def _job_payload(
    status: str,
    *,
    job_id: str = "j1",
    tool_key: str = "esmfold-prediction",
    result: dict | None = None,
    error: str | None = None,
    completed: bool = False,
) -> dict:
    return {
        "job_id": job_id,
        "tool_key": tool_key,
        "status": status,
        "result": result,
        "error": error,
        "created_at": _CREATED_AT,
        "completed_at": _COMPLETED_AT if completed else None,
    }


@pytest.fixture
def mock_http() -> MagicMock:
    return MagicMock(spec=httpx.Client)


def _mock_response(data: Any, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_error = status_code >= 400
    resp.json.return_value = data
    resp.headers = {}
    resp.read = MagicMock()
    return resp


def test_list_returns_tool_info(mock_http):
    mock_http.get.return_value = _mock_response(
        [
            {
                "key": "esmfold-prediction",
                "service": "ESMFoldService",
                "method": "predict",
            }
        ]
    )
    ns = ToolsNamespace(mock_http)
    tools = ns.list()

    mock_http.get.assert_called_once_with("/api/v1/tools")
    assert len(tools) == 1
    assert isinstance(tools[0], ToolInfo)
    assert tools[0].key == "esmfold-prediction"
    assert tools[0].service == "ESMFoldService"
    assert tools[0].method == "predict"


def test_get_schema(mock_http):
    mock_http.get.return_value = _mock_response(
        {
            "inputs": {
                "type": "object",
                "properties": {"sequences": {"type": "array"}},
            },
            "config": {"type": "object"},
            "output": {"type": "object", "properties": {"pdb": {"type": "string"}}},
        }
    )
    ns = ToolsNamespace(mock_http)
    schema = ns.get_schema("esmfold-prediction")

    mock_http.get.assert_called_once_with("/api/v1/tools/esmfold-prediction/schema")
    assert isinstance(schema, ToolSchema)
    assert "sequences" in schema.inputs["properties"]
    assert schema.output["properties"]["pdb"]["type"] == "string"


def test_submit(mock_http: MagicMock) -> None:
    mock_http.post.return_value = _mock_response({"job_id": "abc123", "status": "pending"}, 202)
    ns = ToolsNamespace(mock_http)
    job_id = ns.submit("esmfold-prediction", {"sequences": ["MKTL"]})

    assert job_id == "abc123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/esmfold-prediction/run",
        json={"inputs": {"sequences": ["MKTL"]}, "config": {}},
    )


def test_cancel(mock_http):
    mock_http.post.return_value = _mock_response(_job_payload("cancelled", job_id="abc123", completed=True))
    ns = ToolsNamespace(mock_http)
    result = ns.cancel("esmfold-prediction", "abc123")

    assert isinstance(result, JobStatusResponse)
    assert result.status is JobStatus.cancelled


def test_run_polls_until_complete(mock_http: MagicMock) -> None:
    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.side_effect = [
        _mock_response(_job_payload("running")),
        _mock_response(_job_payload("completed", result={"answer": 42}, completed=True)),
    ]

    ns = ToolsNamespace(mock_http)
    result = ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)

    assert isinstance(result, JobStatusResponse)
    assert result.status is JobStatus.completed
    assert result.result == {"answer": 42}
    assert mock_http.get.call_count == 2


def test_run_with_output_model(mock_http):
    class Out(BaseModel):
        answer: int

    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = _mock_response(_job_payload("completed", result={"answer": 42}, completed=True))

    ns = ToolsNamespace(mock_http)
    result = ns.run(
        "esmfold-prediction",
        {"sequences": ["MKTL"]},
        poll_interval=0.01,
        output_model=Out,
    )

    assert isinstance(result.result, Out)
    assert result.result.answer == 42


def test_run_raises_on_failure(mock_http):
    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = _mock_response(_job_payload("failed", error="OOM", completed=True))

    ns = ToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="OOM"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


def test_run_raises_on_timeout(mock_http):
    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = _mock_response(_job_payload("running"))

    ns = ToolsNamespace(mock_http)
    with pytest.raises(TimeoutError):
        ns.run(
            "esmfold-prediction",
            {"sequences": ["MKTL"]},
            poll_interval=0.01,
            timeout=0.05,
        )


def test_submit_batch(mock_http):
    mock_http.post.return_value = _mock_response({"job_id": "batch123", "status": "pending"}, 202)
    ns = ToolsNamespace(mock_http)
    job_id = ns.submit_batch("blast-search", [{"query": "MKTL"}, {"query": "VDAL"}])

    assert job_id == "batch123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast-search/run-batch",
        json={"inputs_list": [{"query": "MKTL"}, {"query": "VDAL"}], "config": {}},
    )


def test_submit_with_config(mock_http):
    config = {"threshold": 0.8, "max_results": 10}
    mock_http.post.return_value = _mock_response({"job_id": "cfg123", "status": "pending"}, 202)
    ns = ToolsNamespace(mock_http)
    job_id = ns.submit_batch("blast-search", [{"query": "MKTL"}], config=config)

    assert job_id == "cfg123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast-search/run-batch",
        json={"inputs_list": [{"query": "MKTL"}], "config": config},
    )


def test_run_raises_on_cancelled(mock_http):
    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = _mock_response(_job_payload("cancelled", job_id="j1", completed=True))

    ns = ToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="cancelled"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


def test_http_error_raises_typed_error(mock_http):
    mock_http.get.return_value = _mock_response({"detail": "Not Found"}, 404)
    ns = ToolsNamespace(mock_http)
    with pytest.raises(ProtoNotFoundError):
        ns.list()


def test_run_output_model_validation_failure(mock_http):
    class Strict(BaseModel):
        count: int

    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = _mock_response(
        _job_payload("completed", result={"wrong_field": "oops"}, completed=True)
    )
    ns = ToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="does not conform to Strict"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01, output_model=Strict)


def test_run_output_model_with_none_result_raises(mock_http):
    class Out(BaseModel):
        answer: int

    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = _mock_response(_job_payload("completed", result=None, completed=True))
    ns = ToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="completed with no result"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01, output_model=Out)
