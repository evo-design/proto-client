"""Tests for ToolsNamespace with mocked HTTP."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from helpers import job_payload, mock_response
from pydantic import BaseModel

from proto_client.errors import ProtoAPIError, ProtoConflictError, ProtoNotFoundError
from proto_client.models import (
    BatchItemFailure,
    BatchItemSuccess,
    BatchResult,
    JobStatus,
    JobStatusResponse,
    ToolInfo,
    ToolSchema,
)
from proto_client.tools import ToolsNamespace


def test_list_returns_tool_info(mock_http):
    mock_http.get.return_value = mock_response(
        [
            {
                "key": "esmfold-prediction",
                "service": "ESMFoldService",
                "method": "predict",
                "label": "ESMFold Prediction",
                "category": "structure_prediction",
                "description": "Predict protein structure",
                "uses_gpu": True,
                "hosted": True,
                "source_url": "https://github.com/facebookresearch/esm",
                "iterable_input_fields": ["sequences"],
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
    assert tools[0].iterable_input_fields == ["sequences"]


def test_list_accepts_inline_and_unhosted_tools_with_null_service(mock_http):
    """Inline + unhosted tools serve ``service``/``method`` as ``null`` — list() must not raise."""
    mock_http.get.return_value = mock_response(
        [
            {
                "key": "pdb-fetch-entry",  # inline tool: null service/method
                "service": None,
                "method": None,
                "label": "PDB Fetch Entry",
                "category": "data_retrieval",
                "description": "Fetch a structure from RCSB PDB",
                "uses_gpu": False,
                "hosted": True,
                "source_url": "https://www.rcsb.org",
            },
            {
                "key": "alphafold3-prediction",  # unhosted: no service/method, carries a reason
                "service": None,
                "method": None,
                "label": "AlphaFold3",
                "category": "structure_prediction",
                "description": "Not hosted; bring your own weights",
                "uses_gpu": True,
                "hosted": False,
                "unhosted_reason": "License prohibits hosted inference",
                "source_url": "https://github.com/google-deepmind/alphafold3",
            },
        ]
    )
    ns = ToolsNamespace(mock_http)
    tools = ns.list()

    assert [t.key for t in tools] == ["pdb-fetch-entry", "alphafold3-prediction"]
    assert tools[0].service is None and tools[0].method is None
    assert tools[0].hosted is True
    assert tools[1].hosted is False
    assert tools[1].unhosted_reason == "License prohibits hosted inference"


def test_get_schema(mock_http):
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
    ns = ToolsNamespace(mock_http)
    schema = ns.get_schema("esmfold-prediction")

    mock_http.get.assert_called_once_with("/api/v1/tools/esmfold-prediction/schema")
    assert isinstance(schema, ToolSchema)
    assert "sequences" in schema.inputs["properties"]
    assert schema.output["properties"]["pdb"]["type"] == "string"


def test_get_example(mock_http):
    mock_http.get.return_value = mock_response({"example_input": {"sequences": ["MKTL"]}})
    example = ToolsNamespace(mock_http).get_example("esmfold-prediction")

    mock_http.get.assert_called_once_with("/api/v1/tools/esmfold-prediction/example")
    assert example.example_input == {"sequences": ["MKTL"]}


def test_submit(mock_http: MagicMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "abc123", "status": "pending"}, 202)
    ns = ToolsNamespace(mock_http)
    job_id = ns.submit("esmfold-prediction", {"sequences": ["MKTL"]})

    assert job_id == "abc123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/esmfold-prediction/run",
        json={"inputs": {"sequences": ["MKTL"]}, "config": {}},
        headers={},
    )


def test_cancel(mock_http):
    mock_http.post.return_value = mock_response(job_payload("cancelled", job_id="abc123", completed=True))
    ns = ToolsNamespace(mock_http)
    result = ns.cancel("esmfold-prediction", "abc123")

    assert isinstance(result, JobStatusResponse)
    assert result.status is JobStatus.cancelled


def test_run_polls_until_complete(mock_http: MagicMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.side_effect = [
        mock_response(job_payload("running")),
        mock_response(job_payload("completed", result={"answer": 42}, completed=True)),
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

    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", result={"answer": 42}, completed=True))

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
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("failed", error="OOM", completed=True))

    ns = ToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="OOM"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


def test_run_raises_on_timeout(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("running"))

    ns = ToolsNamespace(mock_http)
    with pytest.raises(TimeoutError):
        ns.run(
            "esmfold-prediction",
            {"sequences": ["MKTL"]},
            poll_interval=0.01,
            timeout=0.05,
        )


def test_submit_batch(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "batch123", "status": "pending"}, 202)
    ns = ToolsNamespace(mock_http)
    job_id = ns.submit_batch("blast-search", [{"query": "MKTL"}, {"query": "VDAL"}])

    assert job_id == "batch123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast-search/run-batch",
        json={"inputs_list": [{"query": "MKTL"}, {"query": "VDAL"}], "config": {}},
        headers={},
    )


def test_submit_with_config(mock_http):
    config = {"threshold": 0.8, "max_results": 10}
    mock_http.post.return_value = mock_response({"job_id": "cfg123", "status": "pending"}, 202)
    ns = ToolsNamespace(mock_http)
    job_id = ns.submit_batch("blast-search", [{"query": "MKTL"}], config=config)

    assert job_id == "cfg123"
    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast-search/run-batch",
        json={"inputs_list": [{"query": "MKTL"}], "config": config},
        headers={},
    )


def test_run_raises_on_cancelled(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("cancelled", job_id="j1", completed=True))

    ns = ToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="cancelled"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01)


def test_http_error_raises_typed_error(mock_http):
    mock_http.get.return_value = mock_response({"detail": "Not Found"}, 404)
    ns = ToolsNamespace(mock_http)
    with pytest.raises(ProtoNotFoundError):
        ns.list()


def test_run_output_model_validation_failure(mock_http):
    class Strict(BaseModel):
        count: int

    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", result={"wrong_field": "oops"}, completed=True))
    ns = ToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="does not conform to Strict"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01, output_model=Strict)


def test_run_output_model_with_none_result_raises(mock_http):
    class Out(BaseModel):
        answer: int

    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", result=None, completed=True))
    ns = ToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="completed with no result"):
        ns.run("esmfold-prediction", {"sequences": ["MKTL"]}, poll_interval=0.01, output_model=Out)


def test_run_auto_generates_idempotency_key(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", completed=True))
    ToolsNamespace(mock_http).run("blast", {"x": 1}, poll_interval=0.01)
    key = mock_http.post.call_args.kwargs["headers"]["Idempotency-Key"]
    assert len(key) == 32


def test_run_preserves_explicit_idempotency_key(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", completed=True))
    ToolsNamespace(mock_http).run("blast", {"x": 1}, poll_interval=0.01, idempotency_key="mine")
    assert mock_http.post.call_args.kwargs["headers"]["Idempotency-Key"] == "mine"


def test_run_batch_auto_generates_idempotency_key(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", completed=True, result={"items": []}))
    ToolsNamespace(mock_http).run_batch("blast", [{"x": 1}], poll_interval=0.01)
    key = mock_http.post.call_args.kwargs["headers"]["Idempotency-Key"]
    assert len(key) == 32


def test_run_batch_polls_until_complete(mock_http: MagicMock) -> None:
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.side_effect = [
        mock_response(job_payload("running", job_id="b1")),
        mock_response(
            job_payload(
                "completed",
                job_id="b1",
                result={"items": [{"index": 0, "status": "succeeded", "output": {"x": 1}}]},
                completed=True,
            )
        ),
    ]

    ns = ToolsNamespace(mock_http)
    result = ns.run_batch("blast-search", [{"query": "MKTL"}], poll_interval=0.01)

    assert isinstance(result, BatchResult)
    assert len(result.succeeded) == 1
    assert mock_http.get.call_count == 2


# ── Idempotency key ──


def test_submit_sends_idempotency_header(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    ns = ToolsNamespace(mock_http)
    ns.submit("blast", {"query": "MKTL"}, idempotency_key="abc-123")

    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast/run",
        json={"inputs": {"query": "MKTL"}, "config": {}},
        headers={"Idempotency-Key": "abc-123"},
    )


def test_submit_batch_sends_idempotency_header(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "j1", "status": "pending"}, 202)
    ns = ToolsNamespace(mock_http)
    ns.submit_batch("blast", [{"query": "MKTL"}], idempotency_key="batch-key")

    mock_http.post.assert_called_once_with(
        "/api/v1/tools/blast/run-batch",
        json={"inputs_list": [{"query": "MKTL"}], "config": {}},
        headers={"Idempotency-Key": "batch-key"},
    )


def test_submit_idempotency_409_raises_conflict(mock_http):
    mock_http.post.return_value = mock_response(
        {"detail": "Idempotency key 'k1' was previously used with different inputs"},
        409,
    )
    ns = ToolsNamespace(mock_http)
    with pytest.raises(ProtoConflictError) as exc_info:
        ns.submit("blast", {"query": "MKTL"}, idempotency_key="k1")
    assert exc_info.value.status_code == 409
    assert "different inputs" in exc_info.value.message


# ── Batch result ──


def _batch_result_payload(items: list[dict[str, Any]]) -> dict:
    return job_payload("completed", result={"items": items}, completed=True)


def test_run_batch_returns_batch_result(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(
        _batch_result_payload(
            [
                {"index": 0, "status": "succeeded", "output": {"pdb": "abc"}},
                {"index": 1, "status": "succeeded", "output": {"pdb": "def"}},
            ]
        )
    )
    ns = ToolsNamespace(mock_http)
    result = ns.run_batch("esmfold-prediction", [{"seq": "A"}, {"seq": "B"}], poll_interval=0.01)

    assert isinstance(result, BatchResult)
    assert len(result.items) == 2
    assert len(result.succeeded) == 2
    assert len(result.failed) == 0
    assert result.get_output(0) == {"pdb": "abc"}
    assert result.get_output(1) == {"pdb": "def"}


def test_run_batch_partial_failure(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(
        _batch_result_payload(
            [
                {"index": 0, "status": "succeeded", "output": {"ok": True}},
                {"index": 1, "status": "failed", "error": "OOM on item"},
                {"index": 2, "status": "succeeded", "output": {"ok": True}},
            ]
        )
    )
    ns = ToolsNamespace(mock_http)
    result = ns.run_batch("blast", [{}, {}, {}], poll_interval=0.01)

    assert len(result.succeeded) == 2
    assert len(result.failed) == 1
    assert result.errors == {1: "OOM on item"}
    assert result.get_output(0) == {"ok": True}
    assert result.get_error(1) == "OOM on item"
    assert result.get_output(1) is None
    assert result.get_error(0) is None
    assert isinstance(result.succeeded[0], BatchItemSuccess)
    assert isinstance(result.failed[0], BatchItemFailure)


def test_run_batch_with_output_model(mock_http):
    class Out(BaseModel):
        pdb: str

    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(
        _batch_result_payload(
            [
                {"index": 0, "status": "succeeded", "output": {"pdb": "structure1"}},
                {"index": 1, "status": "succeeded", "output": {"pdb": "structure2"}},
            ]
        )
    )
    ns = ToolsNamespace(mock_http)
    result = ns.run_batch(
        "esmfold-prediction",
        [{"seq": "A"}, {"seq": "B"}],
        poll_interval=0.01,
        output_model=Out,
    )

    assert len(result.succeeded) == 2
    assert isinstance(result.succeeded[0].output, Out)
    assert result.succeeded[0].output.pdb == "structure1"


def test_run_batch_output_model_validation_failure(mock_http):
    class Strict(BaseModel):
        pdb: str

    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(
        _batch_result_payload([{"index": 0, "status": "succeeded", "output": {"wrong_field": "oops"}}])
    )
    ns = ToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="does not conform to Strict"):
        ns.run_batch("blast", [{}], poll_interval=0.01, output_model=Strict)


def test_run_batch_raises_on_failure(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("failed", error="Backend crashed", completed=True))
    ns = ToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="Backend crashed"):
        ns.run_batch("blast", [{}], poll_interval=0.01)


# ── Error paths for get_schema, submit_batch, get, cancel ──


def test_get_schema_error(mock_http):
    mock_http.get.return_value = mock_response({"detail": "Not Found"}, 404)
    ns = ToolsNamespace(mock_http)
    with pytest.raises(ProtoNotFoundError):
        ns.get_schema("nonexistent-tool")


def test_submit_batch_error(mock_http):
    mock_http.post.return_value = mock_response({"detail": "Server Error"}, 500)
    ns = ToolsNamespace(mock_http)
    with pytest.raises(ProtoAPIError):
        ns.submit_batch("blast", [{"query": "MKTL"}])


def test_get_error(mock_http):
    mock_http.get.return_value = mock_response({"detail": "Not Found"}, 404)
    ns = ToolsNamespace(mock_http)
    with pytest.raises(ProtoNotFoundError):
        ns.get("blast", "missing-job")


def test_cancel_error(mock_http):
    mock_http.post.return_value = mock_response({"detail": "Job already completed"}, 409)
    ns = ToolsNamespace(mock_http)
    with pytest.raises(ProtoConflictError):
        ns.cancel("blast", "done-job")


# ── _wait_batch edge cases ──


def test_run_batch_missing_items_in_result(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", result={"no_items_key": []}, completed=True))
    ns = ToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="missing 'items'"):
        ns.run_batch("blast", [{}], poll_interval=0.01)


def test_run_batch_unparseable_items(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    # Items with invalid shape — missing required fields.
    mock_http.get.return_value = mock_response(
        job_payload("completed", result={"items": [{"bad": "shape"}]}, completed=True)
    )
    ns = ToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="unparseable items"):
        ns.run_batch("blast", [{}], poll_interval=0.01)


def test_run_batch_passes_failed_items_through_with_output_model(mock_http):
    class Out(BaseModel):
        pdb: str

    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(
        _batch_result_payload(
            [
                {"index": 0, "status": "succeeded", "output": {"pdb": "ok"}},
                {"index": 1, "status": "failed", "error": "OOM"},
            ]
        )
    )
    ns = ToolsNamespace(mock_http)
    result = ns.run_batch("blast", [{}, {}], poll_interval=0.01, output_model=Out)
    assert len(result.succeeded) == 1
    assert isinstance(result.succeeded[0].output, Out)
    assert len(result.failed) == 1


def test_run_batch_cancelled(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("cancelled", job_id="b1", completed=True))
    ns = ToolsNamespace(mock_http)
    with pytest.raises(RuntimeError, match="cancelled"):
        ns.run_batch("blast", [{}], poll_interval=0.01)


def test_run_batch_timeout(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("running", job_id="b1"))
    ns = ToolsNamespace(mock_http)
    with pytest.raises(TimeoutError):
        ns.run_batch("blast", [{}], poll_interval=0.01, timeout=0.05)


def test_run_batch_result_none(mock_http):
    mock_http.post.return_value = mock_response({"job_id": "b1", "status": "pending"}, 202)
    mock_http.get.return_value = mock_response(job_payload("completed", result=None, completed=True))
    ns = ToolsNamespace(mock_http)
    with pytest.raises(TypeError, match="missing 'items'"):
        ns.run_batch("blast", [{}], poll_interval=0.01)
