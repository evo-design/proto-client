"""Tests for AsyncRunsNamespace against a mocked the runs API.

All transport is stubbed via ``httpx.MockTransport``; no network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from proto_client._async.runs import AsyncRunsNamespace
from proto_client.errors import ProtoAPIError, ProtoValidationError


def make_ns(handler) -> AsyncRunsNamespace:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    return AsyncRunsNamespace(http)


async def test_create_run_default_execute_true():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "run_id": "abc-123",
                "status": "running",
                "message": "Run abc-123 created and execution started",
            },
        )

    ns = make_ns(handler)
    result = await ns.create(
        {"constructs": [{}], "optimization_stages": [{}]},
        webhook_url="https://hook.example/x",
        webhook_metadata={"user": "lucas"},
    )
    assert result["run_id"] == "abc-123"
    assert captured["method"] == "POST"
    assert captured["path"] == "/runs"
    assert captured["query"] == {"execute": "true"}
    assert "webhook_url" in captured["body"]
    assert "webhook_metadata" in captured["body"]


async def test_create_run_execute_false():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["query"] = dict(request.url.params)
        # No webhook fields should be present when not set.
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"run_id": "r", "status": "pending", "message": ""})

    ns = make_ns(handler)
    await ns.create({"constructs": [{}], "optimization_stages": [{}]}, execute=False)
    assert captured["query"] == {"execute": "false"}
    assert "webhook_url" not in captured["body"]
    assert "webhook_metadata" not in captured["body"]


async def test_get_cancel_run_stage():
    """GET, DELETE (cancel), and POST (run_stage) hit the right paths."""

    def handler(request):
        if request.method == "GET" and request.url.path == "/runs/abc":
            return httpx.Response(200, json={"id": "abc", "status": "running"})
        if request.method == "DELETE" and request.url.path == "/runs/xyz":
            return httpx.Response(200, json={"message": "cancelled", "status": "cancelled"})
        if request.method == "POST" and request.url.path == "/runs/abc/stages/2/start":
            return httpx.Response(200, json={"stage_index": 2, "run_id": "abc"})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    ns = make_ns(handler)
    assert (await ns.get("abc"))["status"] == "running"
    assert (await ns.cancel("xyz"))["status"] == "cancelled"
    assert (await ns.run_stage("abc", 2))["stage_index"] == 2


async def test_cancel_completed_run_propagates_400():
    """Server 400 on cancelling a completed/failed run must reach the caller."""

    def handler(request):
        return httpx.Response(400, json={"detail": "Cannot cancel run with status: completed"})

    ns = make_ns(handler)
    with pytest.raises(ProtoAPIError) as exc_info:
        await ns.cancel("done")
    assert exc_info.value.status_code == 400


async def test_validate_ok():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/validate"
        return httpx.Response(200, json={"valid": True, "message": "ok"})

    ns = make_ns(handler)
    assert (await ns.validate({"constructs": [], "optimization_stages": []}))["valid"] is True


async def test_validate_errors_propagate_422():
    def handler(request):
        return httpx.Response(
            422,
            json={"detail": {"errors": ["Missing field: constructs"]}},
        )

    ns = make_ns(handler)
    with pytest.raises(ProtoValidationError) as exc_info:
        await ns.validate({})
    assert exc_info.value.status_code == 422


async def test_get_timepoints_all_stages():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json=[{"optimizer_stage_idx": 0, "timepoints": []}])

    ns = make_ns(handler)
    result = await ns.get_timepoints("abc", offset=5, limit=100)
    assert captured["path"] == "/runs/abc/timepoints"
    assert captured["query"] == {"limit": "100", "offset": "5"}
    assert isinstance(result, list)


async def test_get_timepoints_single_stage_with_filter():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json=[{"optimizer_stage_idx": 1, "timepoints": []}])

    ns = make_ns(handler)
    await ns.get_timepoints("abc", stage=1, timepoint=5, limit=10)
    assert captured["path"] == "/runs/abc/stages/1/timepoints"
    assert captured["query"] == {"limit": "10", "timepoint": "5"}


async def test_get_timepoints_rejects_filter_without_stage():
    ns = make_ns(lambda r: httpx.Response(200, json=[]))
    with pytest.raises(ValueError, match="timepoint filter"):
        await ns.get_timepoints("abc", timepoint=5)


async def test_list_constraints_generators_optimizers():
    paths: list[str] = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=[{"name": "dummy"}])

    ns = make_ns(handler)
    await ns.list_constraints()
    await ns.list_generators()
    await ns.list_optimizers()
    assert paths == ["/constraints", "/generators", "/optimizers"]


async def test_run_polls_until_completed(monkeypatch):
    # Make the sleep a no-op so the test runs instantly.
    import proto_client._async.runs as runs_mod

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(runs_mod, "_sleep", fake_sleep)

    call_count = {"get": 0}

    def handler(request):
        if request.method == "POST" and request.url.path == "/runs":
            return httpx.Response(200, json={"run_id": "r1", "status": "pending", "message": ""})
        if request.method == "GET" and request.url.path == "/runs/r1":
            call_count["get"] += 1
            if call_count["get"] < 3:
                return httpx.Response(200, json={"id": "r1", "status": "running"})
            return httpx.Response(
                200,
                json={"id": "r1", "status": "completed", "stage_results": []},
            )
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    ns = make_ns(handler)
    final = await ns.run(
        {"constructs": [{}], "optimization_stages": [{}]},
        poll_interval=0.01,
        timeout=5.0,
    )
    assert final["status"] == "completed"
    assert call_count["get"] == 3


@pytest.mark.parametrize(
    "terminal_status,expect_error",
    [("completed", False), ("failed", True)],
)
async def test_run_short_circuits_on_instant_terminal(terminal_status, expect_error):
    """When create() returns a terminal status the poll loop is skipped."""
    get_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/runs":
            return httpx.Response(200, json={"run_id": "r1", "status": terminal_status, "message": ""})
        if request.method == "GET":
            get_calls["n"] += 1
            return httpx.Response(
                200,
                json={"id": "r1", "status": terminal_status, "error_message": "bad program", "stage_results": []},
            )
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    ns = make_ns(handler)
    if expect_error:
        with pytest.raises(RuntimeError, match="bad program"):
            await ns.run({"constructs": [{}], "optimization_stages": [{}]})
    else:
        result = await ns.run({"constructs": [{}], "optimization_stages": [{}]})
        assert result["status"] == "completed"
    assert get_calls["n"] == 1


async def test_run_times_out(monkeypatch):
    # Pin monotonic so deadline is exceeded immediately on the second read.
    import proto_client._async.runs as runs_mod

    async def fake_sleep(_seconds):
        return None

    values = [0.0, 0.0, 100.0]
    calls = {"i": 0}

    def fake_monotonic():
        i = calls["i"]
        calls["i"] = min(i + 1, len(values) - 1)
        return values[i]

    monkeypatch.setattr(runs_mod, "_sleep", fake_sleep)
    monkeypatch.setattr(runs_mod.time, "monotonic", fake_monotonic)

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"run_id": "r1", "status": "running", "message": ""})
        return httpx.Response(200, json={"id": "r1", "status": "running"})

    ns = make_ns(handler)
    with pytest.raises(TimeoutError):
        await ns.run(
            {"constructs": [{}], "optimization_stages": [{}]},
            timeout=1.0,
            poll_interval=0.01,
        )
