"""AsyncProtoClient -- async entrypoint mirroring the sync ``ProtoClient``."""

import asyncio
import os
import platform
from typing import Any

import httpx

from proto_client._async.assets import AsyncAssetsNamespace
from proto_client._async.runs import AsyncRunsNamespace
from proto_client._async.tools import AsyncToolsNamespace
from proto_client._defaults import RUNS_BASE_URL, TOOLS_BASE_URL
from proto_client._http import AsyncRetryTransport, RetryConfig
from proto_client._version import VERSION
from proto_client.errors import from_response
from proto_client.models import MeResponse


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
        timeout: float = 600.0,
        max_retries: int = 2,
        retry_config: RetryConfig | None = None,
        app_user_id: str | None = None,
    ) -> None:
        resolved_key = api_key if api_key is not None else os.environ.get("PROTO_API_KEY")
        if resolved_key == "":
            raise ValueError("api_key must not be empty. Pass a valid key or set PROTO_API_KEY.")
        if app_user_id == "":
            raise ValueError("app_user_id must not be empty. Pass a non-empty value or omit the argument.")

        headers: dict[str, str] = {
            "User-Agent": f"proto-client-python/{VERSION} python/{platform.python_version()}",
        }
        if resolved_key:
            headers["X-API-Key"] = resolved_key
        if app_user_id:
            headers["x-app-user-id"] = app_user_id

        cfg = retry_config or RetryConfig(max_retries=max_retries)

        tools_http = httpx.AsyncClient(
            base_url=TOOLS_BASE_URL,
            headers=headers,
            timeout=timeout,
            transport=AsyncRetryTransport(httpx.AsyncHTTPTransport(), config=cfg),
        )
        runs_http = httpx.AsyncClient(
            base_url=RUNS_BASE_URL,
            headers=headers,
            timeout=timeout,
            transport=AsyncRetryTransport(httpx.AsyncHTTPTransport(), config=cfg),
        )

        self.tools = AsyncToolsNamespace(tools_http)
        self.runs = AsyncRunsNamespace(runs_http)
        self.assets = AsyncAssetsNamespace([tools_http, runs_http])
        self._runs_http = runs_http
        self._clients: list[httpx.AsyncClient] = [tools_http, runs_http]

    async def me(self) -> MeResponse:
        """Return the calling key's principal info from ``GET /api/v1/me``.

        Source of truth for capability strings; intended to be called once
        at agent / client boot. Raises the same typed errors as every other
        endpoint (``ProtoAuthError`` on 401/403, etc.).
        """
        resp = await self._runs_http.get("/api/v1/me")
        if resp.is_error:
            raise from_response(resp)
        return MeResponse.model_validate(resp.json())

    async def aclose(self) -> None:
        # Close in parallel; return_exceptions ensures one failure doesn't
        # leak the other client.
        results = await asyncio.gather(*(c.aclose() for c in self._clients), return_exceptions=True)
        self._clients.clear()
        for r in results:
            if isinstance(r, BaseException):
                raise r

    async def __aenter__(self) -> "AsyncProtoClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
