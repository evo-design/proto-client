"""Shared test helpers for building mock responses and namespaces."""

import json
from typing import Any
from unittest.mock import MagicMock

import httpx

from proto_client._async.runs import AsyncRunsNamespace
from proto_client._async.tools import AsyncToolsNamespace
from proto_client.runs import RunsNamespace
from proto_client.tools import ToolsNamespace


def mock_response(data: Any, status_code: int = 200) -> MagicMock:
    """Minimal httpx.Response mock for namespace tests."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_error = status_code >= 400
    resp.json.return_value = data
    resp.headers = {}
    resp.read = MagicMock()
    return resp


def job_payload(
    status: str,
    *,
    job_id: str = "j1",
    tool_key: str = "esmfold-prediction",
    result: dict | None = None,
    error: str | None = None,
    completed: bool = False,
) -> dict:
    """Build a job status response payload."""
    return {
        "job_id": job_id,
        "tool_key": tool_key,
        "status": status,
        "result": result,
        "error": error,
        "created_at": "2026-04-05T12:00:00",
        "completed_at": "2026-04-05T12:00:05" if completed else None,
    }


def run_response_json(
    run_id: str,
    status: str,
    *,
    current_stage: int = 0,
    total_stages: int = 1,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Build a minimal ``RunResponse``-shaped dict for mock transports."""
    return {
        "id": run_id,
        "status": status,
        "created_at": "2026-04-05T12:00:00",
        "updated_at": "2026-04-05T12:00:01",
        "started_at": None,
        "completed_at": None,
        "current_stage": current_stage,
        "total_stages": total_stages,
        "stage_results": [],
        "error_message": error_message,
    }


def make_async_ns(handler) -> AsyncRunsNamespace:
    """Create an AsyncRunsNamespace backed by a mock transport."""
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    return AsyncRunsNamespace(http)


def make_sync_ns(handler) -> RunsNamespace:
    """Create a RunsNamespace backed by a mock transport."""
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.test")
    return RunsNamespace(http)


def make_async_tools_ns(handler) -> AsyncToolsNamespace:
    """Create an AsyncToolsNamespace backed by a mock transport."""
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    return AsyncToolsNamespace(http)


def make_sync_tools_ns(handler) -> ToolsNamespace:
    """Create a ToolsNamespace backed by a mock transport."""
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.test")
    return ToolsNamespace(http)


def log_line(
    seq: int,
    stream: str = "stdout",
    msg: str = "hello",
    *,
    level: str = "info",
) -> bytes:
    """NDJSON line for a :class:`LogRecord`."""
    return json.dumps(
        {
            "type": "record",
            "seq": seq,
            "ts": "2026-05-09T12:34:56.789Z",
            "stream": stream,
            "level": level,
            "msg": msg,
        }
    ).encode()


def end_line(reason: str = "completed", final_seq: int = 0) -> bytes:
    """NDJSON terminator line for a :class:`LogsEnd`."""
    return json.dumps({"type": "end", "reason": reason, "final_seq": final_seq}).encode()


def logs_payload(*lines: bytes) -> bytes:
    return b"\n".join(lines) + b"\n"


def ndjson_response(payload: bytes = b"", status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=payload, headers={"content-type": "application/x-ndjson"})
