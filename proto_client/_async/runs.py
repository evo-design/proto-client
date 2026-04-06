"""Async runs namespace — wraps the runs API endpoints.

This module is the source of truth. The sync counterpart
(``proto_client/runs.py``) is generated from this file via unasync in
``scripts/gen_sync.py``. Do not edit the generated sync file by hand.
"""

from __future__ import annotations

import time
from asyncio import sleep as _sleep
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
from httpx_sse import aconnect_sse

from proto_client.errors import RunCancelledError, RunFailedError, from_response
from proto_client.events import CancelledEvent, CompletedEvent, FailedEvent, RunEvent, parse_sse_event

# Terminal run statuses — polling stops when a run reaches any of these.
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class AsyncRunsNamespace:
    """Access the runs API runs, validation, timepoints, and registries.

    Usage::

        async with AsyncProtoClient(...) as client:
            run = await client.runs.create(program_data={...})
            status = await client.runs.get(run["run_id"])

    Return types are currently ``dict[str, Any]``. Issue #2 (typed Pydantic
    models) will replace them wholesale once its ``models.py`` lands — this
    is a mechanical find-and-replace tracked in the integration PR.
    """

    def __init__(self, http: httpx.AsyncClient) -> None:
        """Initialize with an httpx AsyncClient."""
        self._http = http

    # ------------------------------------------------------------------ runs

    async def create(
        self,
        program_data: dict[str, Any],
        execute: bool = True,
        webhook_url: str | None = None,
        webhook_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /runs — create an optimization run.

        With ``execute=True`` (default) the server begins running stages
        immediately. With ``execute=False`` the run is created idle and stages
        must be kicked off with :meth:`run_stage`.
        """
        body: dict[str, Any] = {"program_data": program_data}
        if webhook_url is not None:
            body["webhook_url"] = webhook_url
        if webhook_metadata is not None:
            body["webhook_metadata"] = webhook_metadata
        resp = await self._http.post("/runs", params={"execute": str(execute).lower()}, json=body)
        if resp.is_error:
            raise from_response(resp)
        return cast(dict[str, Any], resp.json())

    async def get(self, run_id: str) -> dict[str, Any]:
        """GET /runs/{run_id} — fetch run status and stage results."""
        resp = await self._http.get(f"/runs/{run_id}")
        if resp.is_error:
            raise from_response(resp)
        return cast(dict[str, Any], resp.json())

    async def cancel(self, run_id: str) -> dict[str, Any]:
        """DELETE /runs/{run_id} — cancel a running job.

        Propagates the server's 400 if the run is already in a completed or
        failed terminal state; callers need to know that cancelling a finished
        run is a no-op, not silently swallowed.
        """
        resp = await self._http.delete(f"/runs/{run_id}")
        if resp.is_error:
            raise from_response(resp)
        return cast(dict[str, Any], resp.json())

    async def run_stage(self, run_id: str, stage_index: int) -> dict[str, Any]:
        """POST /runs/{run_id}/stages/{stage_index}/start — run a single stage.

        Used for incremental execution (after ``create(..., execute=False)``)
        and for re-running a failed stage — the latter is a common beta-user
        recovery path.
        """
        resp = await self._http.post(f"/runs/{run_id}/stages/{stage_index}/start")
        if resp.is_error:
            raise from_response(resp)
        return cast(dict[str, Any], resp.json())

    # ------------------------------------------------------------ validation

    async def validate(
        self,
        program_data: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /validate — validate a program without creating a run.

        Raises ``ProtoValidationError`` (422) when the program is invalid;
        the response body carries a structured ``{"errors": [...]}`` detail.
        """
        resp = await self._http.post("/validate", json={"program_data": program_data})
        if resp.is_error:
            raise from_response(resp)
        return cast(dict[str, Any], resp.json())

    # ------------------------------------------------------------- timepoints

    async def get_timepoints(
        self,
        run_id: str,
        stage: int | None = None,
        offset: int | None = None,
        limit: int = 10000,
        timepoint: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get optimization timepoints for a run.

        When ``stage`` is ``None`` hits ``GET /runs/{run_id}/timepoints`` and
        returns timepoints from every stage. When ``stage`` is set hits
        ``GET /runs/{run_id}/stages/{stage}/timepoints`` which additionally
        supports the ``timepoint`` query filter.

        Pass ``limit=0`` to request no cap (the server treats 0 as unlimited).
        """
        params: dict[str, Any] = {"limit": limit}
        if offset is not None:
            params["offset"] = offset
        if stage is None:
            if timepoint is not None:
                raise ValueError("timepoint filter is only supported when stage is specified")
            url = f"/runs/{run_id}/timepoints"
        else:
            if timepoint is not None:
                params["timepoint"] = timepoint
            url = f"/runs/{run_id}/stages/{stage}/timepoints"
        resp = await self._http.get(url, params=params)
        if resp.is_error:
            raise from_response(resp)
        return cast(list[dict[str, Any]], resp.json())

    # ------------------------------------------------------------- discovery

    async def list_constraints(self) -> list[dict[str, Any]]:
        """GET /constraints — list registered constraints with their params."""
        resp = await self._http.get("/constraints")
        if resp.is_error:
            raise from_response(resp)
        return cast(list[dict[str, Any]], resp.json())

    async def list_generators(self) -> list[dict[str, Any]]:
        """GET /generators — list registered generators with their params."""
        resp = await self._http.get("/generators")
        if resp.is_error:
            raise from_response(resp)
        return cast(list[dict[str, Any]], resp.json())

    async def list_optimizers(self) -> list[dict[str, Any]]:
        """GET /optimizers — list registered optimizers with their params."""
        resp = await self._http.get("/optimizers")
        if resp.is_error:
            raise from_response(resp)
        return cast(list[dict[str, Any]], resp.json())

    @staticmethod
    def _check_terminal(run_id: str, response: dict[str, Any]) -> dict[str, Any]:
        """Return the response if completed, raise if failed/cancelled."""
        state = response["status"]
        if state == "completed":
            return response
        if state == "cancelled":
            raise RunCancelledError(run_id)
        if state != "failed":
            raise AssertionError(f"Unexpected terminal status: {state!r}")
        raise RunFailedError(run_id, response.get("error_message"))

    # ------------------------------------------------------------ convenience

    async def run(
        self,
        program_data: dict[str, Any],
        poll_interval: float = 2.0,
        timeout: float = 3600.0,
        webhook_url: str | None = None,
        webhook_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit a run and poll until it reaches a terminal state.

        Returns the final ``RunResponse`` dict on success. Raises
        ``RunFailedError`` if the run fails, ``RunCancelledError`` if
        cancelled, and ``TimeoutError`` if it does not complete within
        ``timeout`` seconds.

        On timeout the server-side run is **not** cancelled — callers can
        poll later with the ``run_id`` or cancel explicitly.
        """
        created = await self.create(
            program_data,
            execute=True,
            webhook_url=webhook_url,
            webhook_metadata=webhook_metadata,
        )
        run_id = created["run_id"]
        # Short-circuit if the server already resolved (e.g. instant validation
        # failure) — avoids a redundant GET.
        if created.get("status") in _TERMINAL_STATUSES:
            full = await self.get(run_id)
            if full["status"] in _TERMINAL_STATUSES:
                return self._check_terminal(run_id, full)
            # create() said terminal but get() disagrees (eventual consistency)
            # — fall through to poll loop.
        deadline = time.monotonic() + timeout
        while True:
            status = await self.get(run_id)
            if status["status"] in _TERMINAL_STATUSES:
                return self._check_terminal(run_id, status)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Run {run_id} did not complete within {timeout}s")
            await _sleep(min(poll_interval, remaining))

    # -------------------------------------------------------------- streaming

    async def stream(self, run_id: str) -> AsyncIterator[RunEvent]:
        """Stream SSE events for a run.

        Connects to ``GET /events?run_id={run_id}`` and yields typed
        :class:`~proto_client.events.RunEvent` subclasses. The SSE
        connection closes when the generator is exhausted or explicitly
        closed. Skips the server's ``connected`` keep-alive event.

        Usage::

            async for event in client.runs.stream(run_id):
                match event.type:
                    case "progress":
                        print(event.progress_percent)
                    case "completed":
                        print(event.stage_results)
        """
        async with aconnect_sse(self._http, "GET", "/events", params={"run_id": run_id}) as es:
            if es.response.is_error:
                raise from_response(es.response)
            async for sse in es.aiter_sse():
                event = parse_sse_event(sse.event, sse.json())
                if event is not None:
                    yield event

    async def run_stream(
        self,
        program_data: dict[str, Any],
        execute: bool = True,
        webhook_url: str | None = None,
        webhook_metadata: dict[str, Any] | None = None,
    ) -> AsyncRunStream:
        """Create a run and stream its events.

        Returns an :class:`AsyncRunStream` that is both async-iterable and
        an async context manager. After iteration completes, access the
        final result via ``.result``.

        Usage::

            async with await client.runs.run_stream(program_data={...}) as stream:
                async for event in stream:
                    print(event.type)
                print(stream.result)
        """
        created = await self.create(
            program_data,
            execute=execute,
            webhook_url=webhook_url,
            webhook_metadata=webhook_metadata,
        )
        run_id: str = created["run_id"]
        return AsyncRunStream(run_id=run_id, stream=self.stream(run_id))


class AsyncRunStream:
    """Wrapper that iterates run events and captures the final result.

    Use as an async context manager and async iterator::

        async with stream:
            async for event in stream:
                ...
        final = stream.result

    ``.result`` holds the ``CompletedEvent`` data (or ``None`` if the run
    did not complete). For failed/cancelled runs, inspect ``.final_event``
    or match on the terminal event during iteration — the polling
    ``run()`` method raises on these, but streaming yields them for the
    caller to handle.
    """

    def __init__(self, run_id: str, stream: AsyncIterator[RunEvent]) -> None:
        """Wrap *stream* to capture the completed result for *run_id*."""
        self.run_id = run_id
        self._stream = stream
        self._result: dict[str, Any] | None = None
        self._final_event: RunEvent | None = None

    async def __aenter__(self) -> AsyncRunStream:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def __aiter__(self) -> AsyncRunStream:
        return self

    async def __anext__(self) -> RunEvent:
        event = await anext(self._stream)
        if isinstance(event, (CompletedEvent, FailedEvent, CancelledEvent)):
            self._final_event = event
        if isinstance(event, CompletedEvent):
            self._result = event.data
        return event

    @property
    def result(self) -> dict[str, Any] | None:
        """The ``CompletedEvent`` data, or ``None`` if not yet finished."""
        return self._result

    @property
    def final_event(self) -> RunEvent | None:
        """The last terminal event (completed/failed/cancelled), if any."""
        return self._final_event

    async def close(self) -> None:
        """Close the underlying SSE connection."""
        await self._stream.aclose()
