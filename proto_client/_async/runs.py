"""Async runs namespace — wraps the runs API endpoints.

This module is the source of truth. The sync counterpart
(``proto_client/runs.py``) is generated from this file via unasync in
``scripts/gen_sync.py``. Do not edit the generated sync file by hand.
"""

from __future__ import annotations

import time
from asyncio import sleep as _sleep
from typing import Any

import httpx

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

    def __init__(self, http: httpx.AsyncClient):
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
        resp = await self._http.post(
            "/runs", params={"execute": str(execute).lower()}, json=body
        )
        resp.raise_for_status()
        return resp.json()

    async def get(self, run_id: str) -> dict[str, Any]:
        """GET /runs/{run_id} — fetch run status and stage results."""
        resp = await self._http.get(f"/runs/{run_id}")
        resp.raise_for_status()
        return resp.json()

    async def cancel(self, run_id: str) -> dict[str, Any]:
        """DELETE /runs/{run_id} — cancel a running job.

        Propagates the server's 400 if the run is already in a completed or
        failed terminal state; callers need to know that cancelling a finished
        run is a no-op, not silently swallowed.
        """
        resp = await self._http.delete(f"/runs/{run_id}")
        resp.raise_for_status()
        return resp.json()

    async def run_stage(self, run_id: str, stage_index: int) -> dict[str, Any]:
        """POST /runs/{run_id}/stages/{stage_index}/start — run a single stage.

        Used for incremental execution (after ``create(..., execute=False)``)
        and for re-running a failed stage — the latter is a common beta-user
        recovery path.
        """
        resp = await self._http.post(f"/runs/{run_id}/stages/{stage_index}/start")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------ validation

    async def validate(
        self,
        program_data: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /validate — validate a program without creating a run.

        Raises ``httpx.HTTPStatusError`` (422) when the program is invalid;
        the response body carries a structured ``{"errors": [...]}`` detail.
        """
        resp = await self._http.post("/validate", json={"program_data": program_data})
        resp.raise_for_status()
        return resp.json()

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
                raise ValueError(
                    "timepoint filter is only supported when stage is specified"
                )
            url = f"/runs/{run_id}/timepoints"
        else:
            if timepoint is not None:
                params["timepoint"] = timepoint
            url = f"/runs/{run_id}/stages/{stage}/timepoints"
        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------- discovery

    async def list_constraints(
        self,
    ) -> list[dict[str, Any]]:
        """GET /constraints — list registered constraints with their params."""
        resp = await self._http.get("/constraints")
        resp.raise_for_status()
        return resp.json()

    async def list_generators(
        self,
    ) -> list[dict[str, Any]]:
        """GET /generators — list registered generators with their params."""
        resp = await self._http.get("/generators")
        resp.raise_for_status()
        return resp.json()

    async def list_optimizers(
        self,
    ) -> list[dict[str, Any]]:
        """GET /optimizers — list registered optimizers with their params."""
        resp = await self._http.get("/optimizers")
        resp.raise_for_status()
        return resp.json()

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
        ``RuntimeError`` if the run ends in ``failed`` or ``cancelled`` and
        ``TimeoutError`` if it does not reach a terminal state within
        ``timeout`` seconds. The polling cadence is naive sleep — v0 streaming
        via SSE is the job of issue #6.
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
            state = full["status"]
            if state == "completed":
                return full
            raise RuntimeError(
                f"Run {run_id} ended with status={state!r}: {full.get('error_message')}"
            )
        deadline = time.monotonic() + timeout
        while True:
            status = await self.get(run_id)
            state = status["status"]
            if state == "completed":
                return status
            if state in _TERMINAL_STATUSES:
                raise RuntimeError(
                    f"Run {run_id} ended with status={state!r}: "
                    f"{status.get('error_message')}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Run {run_id} did not complete within {timeout}s")
            await _sleep(min(poll_interval, remaining))
