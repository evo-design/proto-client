"""Tools namespace — wraps the tools API endpoints."""

import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from proto_client.errors import from_response
from proto_client.models import (
    JobResponse,
    JobStatus,
    JobStatusResponse,
    ToolInfo,
    ToolSchema,
)

T = TypeVar("T", bound=BaseModel)

# Alias to avoid shadowing by the `list` method defined below.
_list = list


class ToolsNamespace:
    """Access bioinformatics tools via the the tools API.

    Usage::

        client = ProtoClient(api_key="...")
        result = client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})
        tools = client.tools.list()
    """

    def __init__(self, http: httpx.Client) -> None:
        """Initialize with an httpx Client."""
        self._http = http

    def list(self) -> list[ToolInfo]:
        """List available tools."""
        resp = self._http.get("/api/v1/tools")
        if resp.is_error:
            raise from_response(resp)
        return [ToolInfo.model_validate(item) for item in resp.json()]

    def get_schema(self, tool_key: str) -> ToolSchema:
        """Get JSON schemas for a tool's input, config, and output models."""
        resp = self._http.get(f"/api/v1/tools/{tool_key}/schema")
        if resp.is_error:
            raise from_response(resp)
        return ToolSchema.model_validate(resp.json())

    def submit(
        self,
        tool_key: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str:
        """Submit a job. Returns job_id."""
        resp = self._http.post(
            f"/api/v1/tools/{tool_key}/run",
            json={"inputs": inputs, "config": config or {}},
        )
        if resp.is_error:
            raise from_response(resp)
        return JobResponse.model_validate(resp.json()).job_id

    def submit_batch(
        self,
        tool_key: str,
        inputs_list: _list[dict[str, Any]],
        config: dict[str, Any] | None = None,
    ) -> str:
        """Submit a batch job. Returns job_id."""
        resp = self._http.post(
            f"/api/v1/tools/{tool_key}/run-batch",
            json={"inputs_list": inputs_list, "config": config or {}},
        )
        if resp.is_error:
            raise from_response(resp)
        return JobResponse.model_validate(resp.json()).job_id

    def get(self, tool_key: str, job_id: str) -> JobStatusResponse:
        """Get job status."""
        resp = self._http.get(f"/api/v1/tools/{tool_key}/jobs/{job_id}")
        if resp.is_error:
            raise from_response(resp)
        return JobStatusResponse.model_validate(resp.json())

    def cancel(self, tool_key: str, job_id: str) -> JobStatusResponse:
        """Cancel a job."""
        resp = self._http.post(f"/api/v1/tools/{tool_key}/jobs/{job_id}/cancel")
        if resp.is_error:
            raise from_response(resp)
        return JobStatusResponse.model_validate(resp.json())

    def run(
        self,
        tool_key: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
        *,
        output_model: type[T] | None = None,
    ) -> JobStatusResponse:
        """Submit and poll until completion. Returns the full job envelope.

        Pass ``output_model=MyModel`` to validate the ``result`` dict into a
        typed Pydantic instance, swapped into ``response.result`` at runtime.

        Raises RuntimeError on failure/cancellation, TimeoutError on timeout.
        """
        job_id = self.submit(tool_key, inputs, config)
        return self._wait(tool_key, job_id, poll_interval, timeout, output_model)

    def run_batch(
        self,
        tool_key: str,
        inputs_list: _list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
        *,
        output_model: type[T] | None = None,
    ) -> JobStatusResponse:
        """Submit batch and poll until completion.

        Currently returns a single ``JobStatusResponse`` envelope. If the API
        evolves to return per-input results, the return type will change to
        ``list[JobStatusResponse]``.
        """
        job_id = self.submit_batch(tool_key, inputs_list, config)
        return self._wait(tool_key, job_id, poll_interval, timeout, output_model)

    def _wait(
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
            status = self.get(tool_key, job_id)
            if status.status is JobStatus.completed:
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
                raise RuntimeError(f"Job {job_id} failed: {status.error}")
            if status.status is JobStatus.cancelled:
                raise RuntimeError(f"Job {job_id} was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
            time.sleep(min(poll_interval, remaining))
