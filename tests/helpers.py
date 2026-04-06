"""Shared test helpers for building mock responses and namespaces."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx

from proto_client._async.runs import AsyncRunsNamespace
from proto_client.runs import RunsNamespace


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
