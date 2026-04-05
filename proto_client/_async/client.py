"""AsyncProtoClient — async entrypoint mirroring the sync ``ProtoClient``."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from proto_client._async.runs import AsyncRunsNamespace
from proto_client._async.tools import AsyncToolsNamespace


class AsyncProtoClient:
    """Async client for Proto Bio APIs.

    Usage::

        async with AsyncProtoClient(api_key="...") as client:
            run = await client.runs.create(program_data={...})
            status = await client.runs.get(run["run_id"])
    """

    def __init__(
        self,
        api_key: str | None = None,
        tools_base_url: str = "https://proto-tools.evodesign.org",
        runs_base_url: str = "https://proto-language.evodesign.org",
        timeout: float = 600.0,
    ):
        resolved_key = (
            api_key if api_key is not None else os.environ.get("PROTO_API_KEY")
        )
        if resolved_key == "":
            raise ValueError(
                "api_key must not be empty. Pass a valid key or set PROTO_API_KEY."
            )
        headers: dict[str, str] = {}
        if resolved_key:
            headers["X-API-Key"] = resolved_key

        
        tools_http = httpx.AsyncClient(
            base_url=tools_base_url,
            headers=headers,
            timeout=timeout,
        )
        runs_http = httpx.AsyncClient(
            base_url=runs_base_url,
            headers=headers,
            timeout=timeout,
        )

        self.tools = AsyncToolsNamespace(tools_http)
        self.runs = AsyncRunsNamespace(runs_http)
        self._clients: list[httpx.AsyncClient] = [tools_http, runs_http]

    async def aclose(self) -> None:
        # Close in parallel — one slow shutdown shouldn't block the other.
        await asyncio.gather(*(c.aclose() for c in self._clients))
        self._clients.clear()

    async def __aenter__(self) -> AsyncProtoClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
