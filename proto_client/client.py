"""Main client entrypoint."""

import os
import platform
from typing import Any

import httpx

from proto_client._http import RetryConfig, RetryTransport
from proto_client._version import VERSION
from proto_client.runs import RunsNamespace
from proto_client.tools import ToolsNamespace


class ProtoClient:
    """Unified client for Proto Bio APIs.

    Usage::

        client = ProtoClient(api_key="...")
        result = client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})
    """

    def __init__(
        self,
        api_key: str | None = None,
        tools_base_url: str | None = None,
        runs_base_url: str | None = None,
        timeout: float = 600.0,
        max_retries: int = 2,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            api_key: API key for authentication. Falls back to ``PROTO_API_KEY`` env var.
            tools_base_url: Base URL for the the tools API. Falls back to
                ``PROTO_TOOLS_BASE_URL`` env var, then
                ``https://proto-tools.evodesign.org``.
            runs_base_url: Base URL for the the runs API. Falls back to
                ``PROTO_RUNS_BASE_URL`` env var, then ``https://proto-language.evodesign.org``.
            timeout: Default request timeout in seconds.
            max_retries: Number of retry attempts for failed requests. Ignored if
                *retry_config* is provided.
            retry_config: Advanced retry configuration. Overrides *max_retries*.
        """
        resolved_key = api_key if api_key is not None else os.environ.get("PROTO_API_KEY")
        if resolved_key == "":
            raise ValueError("api_key must not be empty. Pass a valid key or set PROTO_API_KEY.")

        resolved_tools_url = (
            tools_base_url
            if tools_base_url is not None
            else (os.environ.get("PROTO_TOOLS_BASE_URL") or "https://proto-tools.evodesign.org")
        )
        resolved_runs_url = (
            runs_base_url
            if runs_base_url is not None
            else (os.environ.get("PROTO_RUNS_BASE_URL") or "https://proto-language.evodesign.org")
        )

        headers: dict[str, str] = {
            "User-Agent": f"proto-client-python/{VERSION} python/{platform.python_version()}",
        }
        if resolved_key:
            headers["X-API-Key"] = resolved_key

        cfg = retry_config or RetryConfig(max_retries=max_retries)

        tools_http = httpx.Client(
            base_url=resolved_tools_url,
            headers=headers,
            timeout=timeout,
            transport=RetryTransport(httpx.HTTPTransport(), config=cfg),
        )
        runs_http = httpx.Client(
            base_url=resolved_runs_url,
            headers=headers,
            timeout=timeout,
            transport=RetryTransport(httpx.HTTPTransport(), config=cfg),
        )

        self.tools = ToolsNamespace(tools_http)
        self.runs = RunsNamespace(runs_http)
        self._clients: list[httpx.Client] = [tools_http, runs_http]

    def close(self) -> None:
        """Close all underlying HTTP clients."""
        first_error: BaseException | None = None
        for c in self._clients:
            try:
                c.close()
            except Exception as e:  # noqa: PERF203
                if first_error is None:
                    first_error = e
        self._clients.clear()
        if first_error is not None:
            raise first_error

    def __enter__(self) -> "ProtoClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
