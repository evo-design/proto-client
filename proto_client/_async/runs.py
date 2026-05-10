"""Async runs namespace — wraps the runs API endpoints.

This module is the source of truth. The sync counterpart
(``proto_client/runs.py``) is generated from this file via unasync in
``scripts/gen_sync.py``. Do not edit the generated sync file by hand.
"""

import logging
import time
from asyncio import sleep as _sleep
from collections.abc import AsyncIterator
from typing import Any

import httpx

from proto_client._async._ndjson import _acollect_logs_page, _aiter_ndjson_records
from proto_client.errors import RunCancelledError, RunFailedError, from_response
from proto_client.models import (
    CancelRunResponse,
    ConstraintSpec,
    CreateRunResponse,
    GeneratorSpec,
    Level,
    LogRecord,
    LogsEnd,
    LogsPage,
    OptimizerSpec,
    PaginatedTimepoints,
    RunResponse,
    RunStatus,
    RunTimepointResponse,
    StageMetrics,
    StreamChannel,
    ValidationResponse,
)

logger = logging.getLogger("proto_client.runs")

# Terminal run statuses — polling stops when a run reaches any of these.
_TERMINAL_STATUSES = frozenset({RunStatus.completed, RunStatus.failed, RunStatus.cancelled})


class AsyncRunsNamespace:
    """Access the runs API runs, validation, timepoints, and registries.

    Usage::

        async with AsyncProtoClient(...) as client:
            run = await client.runs.create(program_data={...})
            status = await client.runs.get(run.run_id)
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
    ) -> CreateRunResponse:
        """POST /api/v1/runs — create an optimization run.

        With ``execute=True`` (default) the server begins running stages
        immediately. With ``execute=False`` the run is created idle and stages
        must be kicked off with :meth:`run_stage`.
        """
        body: dict[str, Any] = {"program_data": program_data}
        if webhook_url is not None:
            body["webhook_url"] = webhook_url
        if webhook_metadata is not None:
            body["webhook_metadata"] = webhook_metadata
        logger.debug("POST /api/v1/runs")
        resp = await self._http.post("/api/v1/runs", params={"execute": str(execute).lower()}, json=body)
        logger.debug("POST /api/v1/runs -> %d", resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return CreateRunResponse.model_validate(resp.json())

    async def get(self, run_id: str) -> RunResponse:
        """GET /api/v1/runs/{run_id} — fetch run status and stage results."""
        path = f"/api/v1/runs/{run_id}"
        logger.debug("GET %s", path)
        resp = await self._http.get(path)
        logger.debug("GET %s -> %d", path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return RunResponse.model_validate(resp.json())

    async def cancel(self, run_id: str) -> CancelRunResponse:
        """POST /api/v1/runs/{run_id}/cancel — cancel a running job.

        Idempotent: cancelling a finished or already-cancelled run succeeds.
        Inspect ``details.already_cancelled`` / ``details.task_terminated``
        to tell a fresh cancel from a no-op.
        """
        path = f"/api/v1/runs/{run_id}/cancel"
        logger.debug("POST %s", path)
        resp = await self._http.post(path)
        logger.debug("POST %s -> %d", path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return CancelRunResponse.model_validate(resp.json())

    async def run_stage(self, run_id: str, stage_index: int) -> RunResponse:
        """POST /api/v1/runs/{run_id}/stages/{stage_index}/start — run a single stage.

        Used for incremental execution (after ``create(..., execute=False)``)
        and for re-running a failed stage — the latter is a common beta-user
        recovery path.
        """
        path = f"/api/v1/runs/{run_id}/stages/{stage_index}/start"
        logger.debug("POST %s", path)
        resp = await self._http.post(path)
        logger.debug("POST %s -> %d", path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return RunResponse.model_validate(resp.json())

    # ------------------------------------------------------------ validation

    async def validate(
        self,
        program_data: dict[str, Any],
    ) -> ValidationResponse:
        """POST /api/v1/programs/validate — validate a program without creating a run.

        Raises ``ProtoValidationError`` (422) when the program is invalid;
        the response body carries a structured ``{"errors": [...]}`` detail.
        """
        logger.debug("POST /api/v1/programs/validate")
        resp = await self._http.post("/api/v1/programs/validate", json={"program_data": program_data})
        logger.debug("POST /api/v1/programs/validate -> %d", resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return ValidationResponse.model_validate(resp.json())

    # ------------------------------------------------------------- timepoints

    async def get_metrics(
        self,
        run_id: str,
        *,
        stage: int | None = None,
        resolution: int | None = None,
    ) -> list[StageMetrics]:
        """GET /api/v1/runs/{run_id}/metrics — SQL-decimated chart series."""
        params: dict[str, Any] = {}
        if stage is not None:
            params["optimizer_stage_idx"] = stage
        if resolution is not None:
            params["resolution"] = resolution
        url = f"/api/v1/runs/{run_id}/metrics"
        logger.debug("GET %s", url)
        resp = await self._http.get(url, params=params)
        logger.debug("GET %s -> %d", url, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return [StageMetrics.model_validate(item) for item in resp.json()]

    async def get_timepoints(
        self,
        run_id: str,
        *,
        stage: int | None = None,
        page: int = 0,
        page_size: int = 50,
    ) -> PaginatedTimepoints:
        """GET /api/v1/runs/{run_id}/timepoints — one page of full timepoint rows."""
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if stage is not None:
            params["optimizer_stage_idx"] = stage
        url = f"/api/v1/runs/{run_id}/timepoints"
        logger.debug("GET %s", url)
        resp = await self._http.get(url, params=params)
        logger.debug("GET %s -> %d", url, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return PaginatedTimepoints.model_validate(resp.json())

    async def get_timepoint(
        self,
        run_id: str,
        stage: int,
        timepoint: int,
    ) -> RunTimepointResponse:
        """GET /api/v1/runs/{run_id}/timepoints/{stage}/{timepoint} — single row."""
        url = f"/api/v1/runs/{run_id}/timepoints/{stage}/{timepoint}"
        logger.debug("GET %s", url)
        resp = await self._http.get(url)
        logger.debug("GET %s -> %d", url, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return RunTimepointResponse.model_validate(resp.json())

    async def iter_timepoints(
        self,
        run_id: str,
        *,
        stage: int | None = None,
    ) -> AsyncIterator[RunTimepointResponse]:
        """GET /api/v1/runs/{run_id}/timepoints/stream — NDJSON, one row at a time."""
        params: dict[str, Any] = {}
        if stage is not None:
            params["optimizer_stage_idx"] = stage
        url = f"/api/v1/runs/{run_id}/timepoints/stream"
        logger.debug("GET %s (stream)", url)
        async with self._http.stream("GET", url, params=params) as resp:
            logger.debug("GET %s -> %d", url, resp.status_code)
            if resp.is_error:
                await resp.aread()
                raise from_response(resp)
            async for line in resp.aiter_lines():
                if line:
                    yield RunTimepointResponse.model_validate_json(line)

    # ------------------------------------------------------------------- logs

    async def iter_logs(
        self,
        run_id: str,
        *,
        since: int | None = None,
        follow: bool = False,
        limit: int | None = None,
        level: list[Level] | None = None,
        stream: list[StreamChannel] | None = None,
    ) -> AsyncIterator[LogRecord | LogsEnd]:
        """GET /api/v1/runs/{run_id}/logs — stream :class:`LogRecord` rows.

        Yields :class:`LogRecord` for each log line and a final
        :class:`LogsEnd` terminator (when the server emits one) before
        stopping. Discriminate via ``isinstance`` or the ``type`` field.

        Pass ``level`` and/or ``stream`` to filter server-side; both accept a
        list and round-trip as repeated query-string entries (e.g.
        ``level=["warning", "error"]`` becomes ``?level=warning&level=error``).
        Older backends that don't recognise the params silently ignore them.
        """
        params: list[tuple[str, Any]] = [("follow", str(follow).lower())]
        if since is not None:
            params.append(("since", since))
        if limit is not None:
            params.append(("limit", limit))
        params.extend(("level", lv) for lv in level or [])
        params.extend(("stream", st) for st in stream or [])
        path = f"/api/v1/runs/{run_id}/logs"
        async for item in _aiter_ndjson_records(self._http, path, params):
            yield item

    async def get_logs(
        self,
        run_id: str,
        *,
        since: int | None = None,
        limit: int = 1000,
        level: list[Level] | None = None,
        stream: list[StreamChannel] | None = None,
    ) -> LogsPage:
        """Collect log history into a :class:`LogsPage`.

        ``level`` and ``stream`` filter server-side — see :meth:`iter_logs`.
        """
        return await _acollect_logs_page(
            self.iter_logs(run_id, since=since, follow=False, limit=limit, level=level, stream=stream),
            since,
        )

    # ------------------------------------------------------------- discovery

    async def list_constraints(self) -> list[ConstraintSpec]:
        """GET /api/v1/constraints — list registered constraints with their params."""
        logger.debug("GET /api/v1/constraints")
        resp = await self._http.get("/api/v1/constraints")
        logger.debug("GET /api/v1/constraints -> %d", resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return [ConstraintSpec.model_validate(item) for item in resp.json()]

    async def list_generators(self) -> list[GeneratorSpec]:
        """GET /api/v1/generators — list registered generators with their params."""
        logger.debug("GET /api/v1/generators")
        resp = await self._http.get("/api/v1/generators")
        logger.debug("GET /api/v1/generators -> %d", resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return [GeneratorSpec.model_validate(item) for item in resp.json()]

    async def list_optimizers(self) -> list[OptimizerSpec]:
        """GET /api/v1/optimizers — list registered optimizers with their params."""
        logger.debug("GET /api/v1/optimizers")
        resp = await self._http.get("/api/v1/optimizers")
        logger.debug("GET /api/v1/optimizers -> %d", resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return [OptimizerSpec.model_validate(item) for item in resp.json()]

    @staticmethod
    def _check_terminal(run_id: str, response: RunResponse) -> RunResponse:
        """Return the response if completed, raise if failed/cancelled."""
        state = response.status
        logger.info("Run %s reached terminal status: %s", run_id, state.value)
        if state == RunStatus.completed:
            return response
        if state == RunStatus.cancelled:
            raise RunCancelledError(run_id)
        if state != RunStatus.failed:
            raise AssertionError(f"Unexpected terminal status: {state!r}")
        raise RunFailedError(run_id, response.error_message)

    # ------------------------------------------------------------ convenience

    async def run(
        self,
        program_data: dict[str, Any],
        poll_interval: float = 2.0,
        timeout: float = 3600.0,
        webhook_url: str | None = None,
        webhook_metadata: dict[str, Any] | None = None,
    ) -> RunResponse:
        """Submit a run and poll until it reaches a terminal state.

        Returns the final :class:`RunResponse` on success. Raises
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
        run_id = created.run_id
        # Short-circuit if the server already resolved (e.g. instant validation
        # failure) — avoids a redundant GET.
        if created.status in _TERMINAL_STATUSES:
            full = await self.get(run_id)
            if full.status in _TERMINAL_STATUSES:
                return self._check_terminal(run_id, full)
            # create() said terminal but get() disagrees (eventual consistency)
            # — fall through to poll loop.
        deadline = time.monotonic() + timeout
        while True:
            status = await self.get(run_id)
            if status.status in _TERMINAL_STATUSES:
                return self._check_terminal(run_id, status)
            logger.debug("Polling run %s (status=%s)", run_id, status.status.value)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Run {run_id} did not complete within {timeout}s")
            await _sleep(min(poll_interval, remaining))
