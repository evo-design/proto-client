"""Tools namespace — wraps the tools API endpoints."""

from __future__ import annotations

import time
from typing import Any

import httpx


class ToolsNamespace:
    """Access bioinformatics tools via the the tools API.

    Usage::

        client = ProtoClient(api_key="...")
        result = client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})
        tools = client.tools.list()
    """

    def __init__(self, http: httpx.Client):
        self._http = http

    def list(self) -> list[dict[str, str]]:
        """List available tools."""
        resp = self._http.get("/api/v1/tools")
        resp.raise_for_status()
        return resp.json()

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
        resp.raise_for_status()
        return resp.json()["job_id"]

    def submit_batch(
        self,
        tool_key: str,
        inputs_list: list[dict[str, Any]],
        config: dict[str, Any] | None = None,
    ) -> str:
        """Submit a batch job. Returns job_id."""
        resp = self._http.post(
            f"/api/v1/tools/{tool_key}/run-batch",
            json={"inputs_list": inputs_list, "config": config or {}},
        )
        resp.raise_for_status()
        return resp.json()["job_id"]

    def poll(self, tool_key: str, job_id: str) -> dict[str, Any]:
        """Get job status."""
        resp = self._http.get(f"/api/v1/tools/{tool_key}/jobs/{job_id}")
        resp.raise_for_status()
        return resp.json()

    def cancel(self, tool_key: str, job_id: str) -> dict[str, Any]:
        """Cancel a job."""
        resp = self._http.post(f"/api/v1/tools/{tool_key}/jobs/{job_id}/cancel")
        resp.raise_for_status()
        return resp.json()

    def run(
        self,
        tool_key: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Submit and poll until completion. Returns the result dict.

        Raises RuntimeError on failure/cancellation, TimeoutError on timeout.
        """
        job_id = self.submit(tool_key, inputs, config)
        return self._wait(tool_key, job_id, poll_interval, timeout)

    def run_batch(
        self,
        tool_key: str,
        inputs_list: list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Submit batch and poll until completion."""
        job_id = self.submit_batch(tool_key, inputs_list, config)
        return self._wait(tool_key, job_id, poll_interval, timeout)

    def _wait(
        self,
        tool_key: str,
        job_id: str,
        poll_interval: float,
        timeout: float,
    ) -> dict[str, Any]:
        """Poll until terminal status."""
        deadline = time.monotonic() + timeout
        while True:
            status = self.poll(tool_key, job_id)
            if status["status"] == "completed":
                return status.get("result", {})
            if status["status"] == "failed":
                raise RuntimeError(f"Job {job_id} failed: {status.get('error')}")
            if status["status"] == "cancelled":
                raise RuntimeError(f"Job {job_id} was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
            time.sleep(min(poll_interval, remaining))
