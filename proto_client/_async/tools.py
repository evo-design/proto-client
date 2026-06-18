"""Async tools namespace — wraps the tools API endpoints."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

from proto_client._async._ndjson import _acollect_logs_page, _aiter_ndjson_records
from proto_client.errors import JobCancelledError, JobFailedError, from_response
from proto_client.models import (
    BatchItemFailure,
    BatchItemSuccess,
    BatchResult,
    JobResponse,
    JobStatus,
    JobStatusResponse,
    Level,
    LogRecord,
    LogsEnd,
    LogsPage,
    StreamChannel,
    ToolExample,
    ToolInfo,
    ToolSchema,
)

logger = logging.getLogger("proto_client.tools")

T = TypeVar("T", bound=BaseModel)

# Alias to avoid shadowing by the `list` method defined below.
_list = list


class AsyncToolsNamespace:
    """Access bioinformatics tools via the the tools API.

    Usage::

        async with AsyncProtoClient(api_key="...") as client:
            result = await client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})
            tools = await client.tools.list()
    """

    def __init__(self, http: httpx.AsyncClient) -> None:
        """Initialize with an httpx AsyncClient."""
        self._http = http

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Issue a GET/POST, log it, and raise a typed error on any non-2xx response."""
        logger.debug("%s %s", method, path)
        # Dispatch by verb (only GET/POST are used) to keep the method-specific
        # httpx call surface the namespace tests assert on.
        verb: Callable[..., Awaitable[httpx.Response]] = self._http.get if method == "GET" else self._http.post
        resp = await verb(path, **kwargs)
        logger.debug("%s %s -> %d", method, path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return resp

    async def _request(self, method: str, path: str, *, model: type[T], **kwargs: Any) -> T:
        """Send a request and validate the JSON body into *model*."""
        resp = await self._send(method, path, **kwargs)
        return model.model_validate(resp.json())

    async def list(self) -> _list[ToolInfo]:
        """List available tools."""
        resp = await self._send("GET", "/api/v1/tools")
        return [ToolInfo.model_validate(item) for item in resp.json()]

    async def get_schema(self, tool_key: str) -> ToolSchema:
        """Get JSON schemas for a tool's input, config, and output models."""
        return await self._request("GET", f"/api/v1/tools/{tool_key}/schema", model=ToolSchema)

    async def get_example(self, tool_key: str) -> ToolExample:
        """Get a tool's minimal valid input dict for documentation and quickstarts."""
        return await self._request("GET", f"/api/v1/tools/{tool_key}/example", model=ToolExample)

    async def submit(
        self,
        tool_key: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> str:
        """Submit a job. Returns job_id.

        Pass ``idempotency_key`` to safely retry without creating duplicate
        jobs. Reusing a key with different inputs raises
        :class:`~proto_client.errors.ProtoConflictError` (409).
        """
        path = f"/api/v1/tools/{tool_key}/run"
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        job = await self._request(
            "POST", path, model=JobResponse, json={"inputs": inputs, "config": config or {}}, headers=headers
        )
        return job.job_id

    async def submit_batch(
        self,
        tool_key: str,
        inputs_list: _list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> str:
        """Submit a batch job. Returns job_id.

        Pass ``idempotency_key`` to safely retry without creating duplicate
        jobs. Reusing a key with different inputs raises
        :class:`~proto_client.errors.ProtoConflictError` (409).
        """
        path = f"/api/v1/tools/{tool_key}/run-batch"
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        job = await self._request(
            "POST", path, model=JobResponse, json={"inputs_list": inputs_list, "config": config or {}}, headers=headers
        )
        return job.job_id

    async def get(self, tool_key: str, job_id: str) -> JobStatusResponse:
        """Get job status."""
        return await self._request("GET", f"/api/v1/tools/{tool_key}/jobs/{job_id}", model=JobStatusResponse)

    async def cancel(self, tool_key: str, job_id: str) -> JobStatusResponse:
        """Cancel a job."""
        return await self._request("POST", f"/api/v1/tools/{tool_key}/jobs/{job_id}/cancel", model=JobStatusResponse)

    # ------------------------------------------------------------------- logs

    async def iter_job_logs(
        self,
        tool_key: str,
        job_id: str,
        *,
        since: int | None = None,
        follow: bool = False,
        limit: int | None = None,
        level: _list[Level] | None = None,
        stream: _list[StreamChannel] | None = None,
    ) -> AsyncIterator[LogRecord | LogsEnd]:
        """GET /api/v1/tools/{tool_key}/jobs/{job_id}/logs — stream :class:`LogRecord` rows + final :class:`LogsEnd`.

        ``level`` / ``stream`` round-trip as repeated query-string entries (server-side filter).
        """
        params: _list[tuple[str, Any]] = [("follow", str(follow).lower())]
        if since is not None:
            params.append(("since", since))
        if limit is not None:
            params.append(("limit", limit))
        params.extend(("level", lv) for lv in level or [])
        params.extend(("stream", st) for st in stream or [])
        path = f"/api/v1/tools/{tool_key}/jobs/{job_id}/logs"
        async for item in _aiter_ndjson_records(self._http, path, params):
            yield item

    async def get_job_logs(
        self,
        tool_key: str,
        job_id: str,
        *,
        since: int | None = None,
        limit: int = 1000,
        level: _list[Level] | None = None,
        stream: _list[StreamChannel] | None = None,
    ) -> LogsPage:
        """Collect job log history into a :class:`LogsPage`. ``level`` / ``stream`` filter server-side per :meth:`iter_job_logs`."""
        return await _acollect_logs_page(
            self.iter_job_logs(tool_key, job_id, since=since, follow=False, limit=limit, level=level, stream=stream),
            since,
        )

    async def run(
        self,
        tool_key: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
        *,
        output_model: type[T] | None = None,
        idempotency_key: str | None = None,
    ) -> JobStatusResponse:
        """Submit and poll until completion. Returns the full job envelope.

        Pass ``output_model=MyModel`` to validate the ``result`` dict into a
        typed Pydantic instance, swapped into ``response.result`` at runtime.

        An ``Idempotency-Key`` is auto-generated when ``idempotency_key`` is not
        supplied, so the submit is safe to retry without creating a duplicate job.

        Raises ``JobFailedError`` / ``JobCancelledError`` on failure/cancellation,
        ``TimeoutError`` on timeout.
        """
        job_id = await self.submit(tool_key, inputs, config, idempotency_key=idempotency_key or uuid4().hex)
        return await self._wait(tool_key, job_id, poll_interval, timeout, output_model)

    async def run_batch(
        self,
        tool_key: str,
        inputs_list: _list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
        *,
        output_model: type[T] | None = None,
        idempotency_key: str | None = None,
    ) -> BatchResult:
        """Submit batch and poll until completion.

        Returns a :class:`~proto_client.models.BatchResult` with per-item
        results. Each item is either a :class:`BatchItemSuccess` or
        :class:`BatchItemFailure`.

        Pass ``output_model`` to validate each succeeded item's output.
        An ``Idempotency-Key`` is auto-generated when ``idempotency_key`` is not
        supplied, so the submit is safe to retry without duplicating the batch.
        """
        job_id = await self.submit_batch(tool_key, inputs_list, config, idempotency_key=idempotency_key or uuid4().hex)
        return await self._wait_batch(tool_key, job_id, poll_interval, timeout, output_model)

    async def _wait(
        self,
        tool_key: str,
        job_id: str,
        poll_interval: float,
        timeout: float,
        output_model: type[T] | None,
    ) -> JobStatusResponse:
        """Poll until terminal status."""
        deadline = time.monotonic() + timeout
        while True:
            status = await self.get(tool_key, job_id)
            if status.status is JobStatus.completed:
                logger.info("Job %s reached terminal status: %s", job_id, status.status.value)
                if output_model is not None:
                    if not isinstance(status.result, dict):
                        raise TypeError(
                            f"Job {job_id} completed with no result, "
                            f"but output_model={output_model.__name__} was requested"
                        )
                    try:
                        parsed = output_model.model_validate(status.result)
                    except ValidationError as exc:
                        raise TypeError(
                            f"Job {job_id} result does not conform to {output_model.__name__}: {exc}"
                        ) from exc
                    status = status.model_copy(update={"result": parsed})
                return status
            if status.status is JobStatus.failed:
                logger.info("Job %s reached terminal status: %s", job_id, status.status.value)
                raise JobFailedError(job_id, status.error)
            if status.status is JobStatus.cancelled:
                logger.info("Job %s reached terminal status: %s", job_id, status.status.value)
                raise JobCancelledError(job_id)
            logger.debug("Polling job %s (status=%s)", job_id, status.status.value)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
            await asyncio.sleep(min(poll_interval, remaining))

    async def _wait_batch(
        self,
        tool_key: str,
        job_id: str,
        poll_interval: float,
        timeout: float,
        output_model: type[T] | None,
    ) -> BatchResult:
        """Poll until terminal status, then parse the flat items list into a BatchResult."""
        deadline = time.monotonic() + timeout
        while True:
            status = await self.get(tool_key, job_id)
            if status.status is JobStatus.completed:
                if not isinstance(status.result, dict) or "items" not in status.result:
                    raise TypeError(f"Batch job {job_id} missing 'items' in result")
                try:
                    batch = BatchResult.model_validate({"items": status.result["items"]})
                except ValidationError as exc:
                    raise TypeError(f"Batch job {job_id} returned unparseable items: {exc}") from exc
                if output_model is not None:
                    validated: _list[BatchItemSuccess | BatchItemFailure] = []
                    for item in batch.items:
                        if isinstance(item, BatchItemSuccess):
                            try:
                                parsed = output_model.model_validate(item.output)
                            except ValidationError as exc:
                                raise TypeError(
                                    f"Batch item {item.index} does not conform to {output_model.__name__}: {exc}"
                                ) from exc
                            validated.append(item.model_copy(update={"output": parsed}))
                        else:
                            validated.append(item)
                    batch = BatchResult(items=validated)
                logger.info("Batch job %s completed with %d items", job_id, len(batch.items))
                return batch
            if status.status is JobStatus.failed:
                logger.info("Batch job %s reached terminal status: %s", job_id, status.status.value)
                raise JobFailedError(job_id, status.error)
            if status.status is JobStatus.cancelled:
                logger.info("Batch job %s reached terminal status: %s", job_id, status.status.value)
                raise JobCancelledError(job_id)
            logger.debug("Polling batch job %s (status=%s)", job_id, status.status.value)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Batch job {job_id} did not complete within {timeout}s")
            await asyncio.sleep(min(poll_interval, remaining))
