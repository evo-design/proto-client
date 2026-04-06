"""SSE streaming tests for runs namespace (sync + async)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from proto_client.events import (
    CancelledEvent,
    CompletedEvent,
    FailedEvent,
    ProgressEvent,
    StageCompleteEvent,
    parse_sse_event,
)


def _sse_body(*events: tuple[str, dict[str, Any]]) -> bytes:
    """Build a raw ``text/event-stream`` byte payload."""
    lines: list[str] = []
    for event_type, data in events:
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


_PROGRESS_DATA: dict[str, Any] = {
    "run_id": "r1",
    "timepoint": 5,
    "optimizer_stage_idx": 0,
    "total_stages": 2,
    "best_result_idx": 0,
    "results": [{"score": 0.9}],
    "proposal_results": [],
    "timestamp": "2026-04-05T00:00:00Z",
    "progress_percent": 50.0,
}
_COMPLETED_DATA: dict[str, Any] = {
    "run_id": "r1",
    "status": "completed",
    "timestamp": "2026-04-05T00:01:00Z",
    "stage_results": [{"best": "MKTL"}],
}
_FAILED_DATA: dict[str, Any] = {
    "run_id": "r1",
    "status": "failed",
    "timestamp": "2026-04-05T00:01:00Z",
    "error_message": "GPU OOM",
}
_CONNECTED_DATA: dict[str, Any] = {
    "run_id": "r1",
    "message": "Connected to run stream",
}
_CREATE_RESP: dict[str, Any] = {"run_id": "r1", "status": "running"}


def _sse_transport(
    sse_events: list[tuple[str, dict[str, Any]]],
    create_resp: dict[str, Any] | None = None,
) -> httpx.MockTransport:
    """Build a MockTransport that serves SSE for /events and JSON for /runs."""
    body = _sse_body(*sse_events)

    def handler(request: httpx.Request) -> httpx.Response:
        if "/events" in str(request.url):
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "text/event-stream"},
                request=request,
            )
        if str(request.url.path) == "/runs" and request.method == "POST":
            return httpx.Response(
                200,
                json=create_resp or _CREATE_RESP,
                request=request,
            )
        return httpx.Response(404, request=request)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------- parse_sse_event


def test_parse_progress_event() -> None:
    event = parse_sse_event("progress", _PROGRESS_DATA)
    assert isinstance(event, ProgressEvent)
    assert event.type == "progress"
    assert event.run_id == "r1"
    assert event.progress_percent == 50.0
    assert event.optimizer_stage_idx == 0


def test_parse_stage_complete_event() -> None:
    data = {"run_id": "r1", "optimizer_stage_idx": 1, "best_result_idx": 3, "results": [], "timestamp": "t"}
    event = parse_sse_event("stage_complete", data)
    assert isinstance(event, StageCompleteEvent)
    assert event.optimizer_stage_idx == 1


def test_parse_completed_event() -> None:
    event = parse_sse_event("completed", _COMPLETED_DATA)
    assert isinstance(event, CompletedEvent)
    assert event.stage_results == [{"best": "MKTL"}]


def test_parse_failed_event() -> None:
    event = parse_sse_event("failed", _FAILED_DATA)
    assert isinstance(event, FailedEvent)
    assert event.error_message == "GPU OOM"


def test_parse_cancelled_event() -> None:
    data = {"run_id": "r1", "status": "cancelled", "timestamp": "t", "message": "User cancelled"}
    event = parse_sse_event("cancelled", data)
    assert isinstance(event, CancelledEvent)


def test_parse_connected_returns_none() -> None:
    assert parse_sse_event("connected", _CONNECTED_DATA) is None


def test_parse_unknown_type_returns_none() -> None:
    assert parse_sse_event("some_future_event", {"run_id": "r1"}) is None


def test_parse_none_type_returns_none() -> None:
    assert parse_sse_event(None, {"run_id": "r1"}) is None


# ------------------------------------------------------------------- sync stream


def test_sync_stream_yields_progress_and_completed() -> None:
    transport = _sse_transport([("progress", _PROGRESS_DATA), ("completed", _COMPLETED_DATA)])
    with httpx.Client(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client.runs import RunsNamespace

        ns = RunsNamespace(http)
        events = list(ns.stream("r1"))

    assert len(events) == 2
    assert isinstance(events[0], ProgressEvent)
    assert isinstance(events[1], CompletedEvent)


def test_sync_stream_skips_connected() -> None:
    transport = _sse_transport(
        [
            ("connected", _CONNECTED_DATA),
            ("progress", _PROGRESS_DATA),
        ]
    )
    with httpx.Client(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client.runs import RunsNamespace

        ns = RunsNamespace(http)
        events = list(ns.stream("r1"))

    assert len(events) == 1
    assert isinstance(events[0], ProgressEvent)


def test_sync_stream_skips_unknown_events() -> None:
    transport = _sse_transport(
        [
            ("new_fancy_event", {"run_id": "r1"}),
            ("completed", _COMPLETED_DATA),
        ]
    )
    with httpx.Client(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client.runs import RunsNamespace

        ns = RunsNamespace(http)
        events = list(ns.stream("r1"))

    assert len(events) == 1
    assert isinstance(events[0], CompletedEvent)


def test_sync_stream_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Unauthorized"}, request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client.errors import ProtoAuthError
        from proto_client.runs import RunsNamespace

        ns = RunsNamespace(http)
        with pytest.raises(ProtoAuthError):
            list(ns.stream("r1"))


def test_sync_run_stream_creates_and_captures_result() -> None:
    transport = _sse_transport(
        [
            ("connected", _CONNECTED_DATA),
            ("progress", _PROGRESS_DATA),
            ("completed", _COMPLETED_DATA),
        ]
    )
    with httpx.Client(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client.runs import RunsNamespace

        ns = RunsNamespace(http)
        with ns.run_stream(program_data={"constructs": []}) as stream:
            events = list(stream)

    assert len(events) == 2  # connected skipped
    assert isinstance(events[0], ProgressEvent)
    assert isinstance(events[1], CompletedEvent)
    assert stream.result is not None
    assert stream.result["status"] == "completed"
    assert stream.run_id == "r1"


def test_sync_run_stream_result_none_before_completion() -> None:
    transport = _sse_transport([("progress", _PROGRESS_DATA)])
    with httpx.Client(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client.runs import RunsNamespace

        ns = RunsNamespace(http)
        with ns.run_stream(program_data={"constructs": []}) as stream:
            events = list(stream)

    assert len(events) == 1
    assert stream.result is None


# ------------------------------------------------------------------ async stream


@pytest.mark.asyncio
async def test_async_stream_yields_progress_and_completed() -> None:
    transport = _sse_transport([("progress", _PROGRESS_DATA), ("completed", _COMPLETED_DATA)])
    async with httpx.AsyncClient(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client._async.runs import AsyncRunsNamespace

        ns = AsyncRunsNamespace(http)
        events = [e async for e in ns.stream("r1")]

    assert len(events) == 2
    assert isinstance(events[0], ProgressEvent)
    assert isinstance(events[1], CompletedEvent)


@pytest.mark.asyncio
async def test_async_stream_skips_connected() -> None:
    transport = _sse_transport([("connected", _CONNECTED_DATA), ("progress", _PROGRESS_DATA)])
    async with httpx.AsyncClient(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client._async.runs import AsyncRunsNamespace

        ns = AsyncRunsNamespace(http)
        events = [e async for e in ns.stream("r1")]

    assert len(events) == 1


@pytest.mark.asyncio
async def test_async_run_stream_creates_and_captures_result() -> None:
    transport = _sse_transport(
        [
            ("connected", _CONNECTED_DATA),
            ("progress", _PROGRESS_DATA),
            ("completed", _COMPLETED_DATA),
        ]
    )
    async with httpx.AsyncClient(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client._async.runs import AsyncRunsNamespace

        ns = AsyncRunsNamespace(http)
        stream = await ns.run_stream(program_data={"constructs": []})
        async with stream:
            events = [e async for e in stream]

    assert len(events) == 2
    assert stream.result is not None
    assert stream.result["status"] == "completed"
    assert stream.run_id == "r1"


@pytest.mark.asyncio
async def test_async_stream_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Unauthorized"}, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://proto-language.evodesign.org") as http:
        from proto_client._async.runs import AsyncRunsNamespace
        from proto_client.errors import ProtoAuthError

        ns = AsyncRunsNamespace(http)
        with pytest.raises(ProtoAuthError):
            async for _ in ns.stream("r1"):
                pass
