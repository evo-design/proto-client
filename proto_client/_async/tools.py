"""Async tools namespace — wraps the tools API endpoints."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from proto_client._async._ndjson import _acollect_logs_page, _aiter_ndjson_records
from proto_client.errors import from_response
from proto_client.models import (
    BatchItemFailure,
    BatchItemSuccess,
    BatchResult,
    JobResponse,
    JobStatus,
    JobStatusResponse,
    LogRecord,
    LogsPage,
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

    async def list(self) -> _list[ToolInfo]:
        """List available tools."""
        logger.debug("GET /api/v1/tools")
        resp = await self._http.get("/api/v1/tools")
        logger.debug("GET /api/v1/tools -> %d", resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return [ToolInfo.model_validate(item) for item in resp.json()]

    async def get_schema(self, tool_key: str) -> ToolSchema:
        """Get JSON schemas for a tool's input, config, and output models."""
        path = f"/api/v1/tools/{tool_key}/schema"
        logger.debug("GET %s", path)
        resp = await self._http.get(path)
        logger.debug("GET %s -> %d", path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return ToolSchema.model_validate(resp.json())

    async def get_example(self, tool_key: str) -> ToolExample:
        """Get a tool's minimal valid input dict for documentation and quickstarts."""
        path = f"/api/v1/tools/{tool_key}/example"
        logger.debug("GET %s", path)
        resp = await self._http.get(path)
        logger.debug("GET %s -> %d", path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return ToolExample.model_validate(resp.json())

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
        logger.debug("POST %s", path)
        resp = await self._http.post(path, json={"inputs": inputs, "config": config or {}}, headers=headers)
        logger.debug("POST %s -> %d", path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return JobResponse.model_validate(resp.json()).job_id

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
        logger.debug("POST %s", path)
        resp = await self._http.post(path, json={"inputs_list": inputs_list, "config": config or {}}, headers=headers)
        logger.debug("POST %s -> %d", path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return JobResponse.model_validate(resp.json()).job_id

    async def get(self, tool_key: str, job_id: str) -> JobStatusResponse:
        """Get job status."""
        path = f"/api/v1/tools/{tool_key}/jobs/{job_id}"
        logger.debug("GET %s", path)
        resp = await self._http.get(path)
        logger.debug("GET %s -> %d", path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return JobStatusResponse.model_validate(resp.json())

    async def cancel(self, tool_key: str, job_id: str) -> JobStatusResponse:
        """Cancel a job."""
        path = f"/api/v1/tools/{tool_key}/jobs/{job_id}/cancel"
        logger.debug("POST %s", path)
        resp = await self._http.post(path)
        logger.debug("POST %s -> %d", path, resp.status_code)
        if resp.is_error:
            raise from_response(resp)
        return JobStatusResponse.model_validate(resp.json())

    # ------------------------------------------------------------------- logs

    async def iter_job_logs(
        self,
        tool_key: str,
        job_id: str,
        *,
        since: int | None = None,
        follow: bool = False,
        limit: int | None = None,
    ) -> AsyncIterator[LogRecord]:
        """GET /api/v1/tools/{tool_key}/jobs/{job_id}/logs — stream :class:`LogRecord` rows."""
        params: dict[str, Any] = {"follow": str(follow).lower()}
        if since is not None:
            params["since"] = since
        if limit is not None:
            params["limit"] = limit
        path = f"/api/v1/tools/{tool_key}/jobs/{job_id}/logs"
        async for record in _aiter_ndjson_records(self._http, path, params):
            yield record

    async def get_job_logs(
        self,
        tool_key: str,
        job_id: str,
        *,
        since: int | None = None,
        limit: int = 1000,
    ) -> LogsPage:
        """Collect job log history into a :class:`LogsPage`."""
        return await _acollect_logs_page(
            self.iter_job_logs(tool_key, job_id, since=since, follow=False, limit=limit),
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

        Raises RuntimeError on failure/cancellation, TimeoutError on timeout.
        """
        job_id = await self.submit(tool_key, inputs, config, idempotency_key=idempotency_key)
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
        """
        job_id = await self.submit_batch(tool_key, inputs_list, config, idempotency_key=idempotency_key)
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
                raise RuntimeError(f"Job {job_id} failed: {status.error}")
            if status.status is JobStatus.cancelled:
                logger.info("Job %s reached terminal status: %s", job_id, status.status.value)
                raise RuntimeError(f"Job {job_id} was cancelled")
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
                raise RuntimeError(f"Batch job {job_id} failed: {status.error}")
            if status.status is JobStatus.cancelled:
                logger.info("Batch job %s reached terminal status: %s", job_id, status.status.value)
                raise RuntimeError(f"Batch job {job_id} was cancelled")
            logger.debug("Polling batch job %s (status=%s)", job_id, status.status.value)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Batch job {job_id} did not complete within {timeout}s")
            await asyncio.sleep(min(poll_interval, remaining))
