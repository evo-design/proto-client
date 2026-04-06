"""Tests for ToolsNamespace with mocked HTTP."""

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from proto_client.tools import ToolsNamespace


@pytest.fixture
def mock_http() -> MagicMock:
    return MagicMock(spec=httpx.Client)


def _mock_response(data: Any, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


def test_list_tools(mock_http: MagicMock) -> None:
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
    assert tools[0]["key"] == "esmfold-prediction"


def test_submit(mock_http: MagicMock) -> None:
    mock_http.post.return_value = _mock_response({"job_id": "abc123", "status": "pending"}, 202)
    ns = ToolsNamespace(mock_http)
    job_id = ns.submit("esmfold-prediction", {"sequences": ["MKTL"]})

    assert job_id == "abc123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/esmfold-prediction/run",
        json={"inputs": {"sequences": ["MKTL"]}, "config": {}},
    )


def test_poll(mock_http: MagicMock) -> None:
    mock_http.get.return_value = _mock_response({"job_id": "abc123", "status": "completed", "result": {"score": 0.9}})
    ns = ToolsNamespace(mock_http)
    status = ns.poll("esmfold-prediction", "abc123")

    assert status["status"] == "completed"


def test_cancel(mock_http: MagicMock) -> None:
    mock_http.post.return_value = _mock_response({"job_id": "abc123", "status": "cancelled"})
    ns = ToolsNamespace(mock_http)
    result = ns.cancel("esmfold-prediction", "abc123")

    assert result["status"] == "cancelled"


def test_run_polls_until_complete(mock_http: MagicMock) -> None:
    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.side_effect = [
        _mock_response({"job_id": "j1", "status": "running"}),
        _mock_response({"job_id": "j1", "status": "completed", "result": {"answer": 42}}),
    ]

    ns = ToolsNamespace(mock_http)
    result = ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)

    assert result == {"answer": 42}
    assert mock_http.get.call_count == 2


def test_run_raises_on_failure(mock_http: MagicMock) -> None:
    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = _mock_response({"job_id": "j1", "status": "failed", "error": "OOM"})

    ns = ToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="OOM"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


def test_run_raises_on_timeout(mock_http: MagicMock) -> None:
    mock_http.post.return_value = _mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = _mock_response({"job_id": "j1", "status": "running"})

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


def test_run_batch_polls_until_complete(mock_http):
    mock_http.post.return_value = _mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.side_effect = [
        _mock_response({"job_id": "b1", "status": "running"}),
        _mock_response(
            {
                "job_id": "b1",
                "status": "completed",
                "result": {"hits": [{"id": "prot1"}, {"id": "prot2"}]},
            }
        ),
    ]

    ns = ToolsNamespace(mock_http)
    result = ns.run_batch(
        "blast-search",
        [{"query": "MKTL"}, {"query": "VDAL"}],
        poll_interval=0.01,
    )

    assert result == {"hits": [{"id": "prot1"}, {"id": "prot2"}]}
    assert mock_http.get.call_count == 2


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
    mock_http.get.return_value = _mock_response({"job_id": "j1", "status": "cancelled"})

    ns = ToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="cancelled"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


def test_http_error_propagation(mock_http):
    error_resp = _mock_response({}, 404)
    error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found", request=MagicMock(), response=MagicMock()
    )
    mock_http.get.return_value = error_resp
    ns = ToolsNamespace(mock_http)
    with pytest.raises(httpx.HTTPStatusError):
        ns.list()
