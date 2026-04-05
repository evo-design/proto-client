"""Round-trip tests for response models.

These parse representative JSON payloads that mirror the tools API wire
shapes, so model drift from the server is caught independently of mocked
HTTP in test_tools.py.
"""

from __future__ import annotations

from datetime import datetime

from proto_client.models import (
    JobResponse,
    JobStatus,
    JobStatusResponse,
    ToolInfo,
    ToolSchema,
)


def test_tool_info_parse():
    info = ToolInfo.model_validate(
        {"key": "esmfold-prediction", "service": "ESMFoldService", "method": "predict"}
    )
    assert info.key == "esmfold-prediction"
    assert info.service == "ESMFoldService"
    assert info.method == "predict"


def test_tool_schema_parse():
    schema = ToolSchema.model_validate(
        {
            "inputs": {
                "type": "object",
                "properties": {"sequences": {"type": "array"}},
            },
            "config": {"type": "object"},
            "output": {"type": "object", "properties": {"pdb": {"type": "string"}}},
        }
    )
    assert schema.inputs["properties"]["sequences"]["type"] == "array"
    assert schema.config == {"type": "object"}
    assert schema.output["properties"]["pdb"]["type"] == "string"


def test_job_response_parse():
    resp = JobResponse.model_validate({"job_id": "abc", "status": "pending"})
    assert resp.job_id == "abc"
    assert resp.status is JobStatus.pending


def test_job_response_default_status():
    resp = JobResponse.model_validate({"job_id": "abc"})
    assert resp.status is JobStatus.pending


def test_job_status_response_full_parse():
    resp = JobStatusResponse.model_validate(
        {
            "job_id": "j1",
            "tool_key": "esmfold-prediction",
            "status": "completed",
            "result": {"pdb": "ATOM..."},
            "error": None,
            "created_at": "2026-04-05T12:00:00",
            "completed_at": "2026-04-05T12:00:05",
        }
    )
    assert resp.status is JobStatus.completed
    assert resp.result == {"pdb": "ATOM..."}
    assert isinstance(resp.created_at, datetime)
    assert isinstance(resp.completed_at, datetime)


def test_job_status_response_pending():
    resp = JobStatusResponse.model_validate(
        {
            "job_id": "j1",
            "tool_key": "esmfold-prediction",
            "status": "running",
            "result": None,
            "error": None,
            "created_at": "2026-04-05T12:00:00",
            "completed_at": None,
        }
    )
    assert resp.status is JobStatus.running
    assert resp.result is None
    assert resp.completed_at is None


def test_job_status_enum_values():
    # Mirror the server-side enum exactly
    assert {s.value for s in JobStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
    }
