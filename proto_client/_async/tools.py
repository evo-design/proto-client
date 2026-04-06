"""AsyncToolsNamespace — skeleton pending integration with typed models.

The sync ``ToolsNamespace`` in ``proto_client/tools.py`` is the real
implementation. This async skeleton mirrors its method signatures so the
integration PR is a body-fill, not a rename. Methods raise
``NotImplementedError`` until then.
"""

from __future__ import annotations

from typing import Any

import httpx

_PENDING = (
    "AsyncToolsNamespace is pending integration with issue #2 (typed models). Use the sync ProtoClient.tools for now."
)

_list = list


class AsyncToolsNamespace:
    """Async tools namespace — skeleton pending integration with typed models."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        """Initialize with an httpx AsyncClient."""
        self._http = http

    async def list(self) -> _list[dict[str, str]]:
        raise NotImplementedError(_PENDING)

    async def get_schema(self, tool_key: str) -> dict[str, Any]:
        raise NotImplementedError(_PENDING)

    async def submit(
        self,
        tool_key: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError(_PENDING)

    async def submit_batch(
        self,
        tool_key: str,
        inputs_list: _list[dict[str, Any]],
        config: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError(_PENDING)

    async def get(self, tool_key: str, job_id: str) -> dict[str, Any]:
        raise NotImplementedError(_PENDING)

    async def cancel(self, tool_key: str, job_id: str) -> dict[str, Any]:
        raise NotImplementedError(_PENDING)

    async def run(
        self,
        tool_key: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        raise NotImplementedError(_PENDING)

    async def run_batch(
        self,
        tool_key: str,
        inputs_list: _list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        raise NotImplementedError(_PENDING)
