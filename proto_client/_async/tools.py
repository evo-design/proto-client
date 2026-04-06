"""AsyncToolsNamespace — skeleton pending async implementation.

Method signatures mirror sync ``ToolsNamespace`` in ``proto_client/tools.py``.
All methods raise ``NotImplementedError`` until the async implementation lands.
"""

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from proto_client.models import JobStatusResponse, ToolInfo, ToolSchema

T = TypeVar("T", bound=BaseModel)

_PENDING = "AsyncToolsNamespace is pending async implementation. Use the sync ProtoClient.tools for now."

_list = list


class AsyncToolsNamespace:
    """Async tools namespace — skeleton pending async implementation."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        """Initialize with an httpx AsyncClient."""
        self._http = http

    async def list(self) -> _list[ToolInfo]:
        raise NotImplementedError(_PENDING)

    async def get_schema(self, tool_key: str) -> ToolSchema:
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

    async def get(self, tool_key: str, job_id: str) -> JobStatusResponse:
        raise NotImplementedError(_PENDING)

    async def cancel(self, tool_key: str, job_id: str) -> JobStatusResponse:
        raise NotImplementedError(_PENDING)

    async def run(
        self,
        tool_key: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
        *,
        output_model: type[T] | None = None,
    ) -> JobStatusResponse:
        raise NotImplementedError(_PENDING)

    async def run_batch(
        self,
        tool_key: str,
        inputs_list: _list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
        *,
        output_model: type[T] | None = None,
    ) -> JobStatusResponse:
        raise NotImplementedError(_PENDING)
