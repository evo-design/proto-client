"""Main client entrypoint."""

import os
from typing import Any

import httpx

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
        tools_base_url: str = "https://proto-tools.evodesign.org",
        runs_base_url: str = "https://proto-language.evodesign.org",
        timeout: float = 600.0,
    ) -> None:
        """Initialize the client.

        Args:
            api_key: API key for authentication. Falls back to PROTO_API_KEY env var.
            tools_base_url: Base URL for the the tools API.
            timeout: Default request timeout in seconds.
        """
        resolved_key = api_key if api_key is not None else os.environ.get("PROTO_API_KEY")
        if resolved_key == "":
            raise ValueError("api_key must not be empty. Pass a valid key or set PROTO_API_KEY.")
        headers: dict[str, str] = {}
        if resolved_key:
            headers["X-API-Key"] = resolved_key

        tools_http = httpx.Client(
            base_url=tools_base_url,
            headers=headers,
            timeout=timeout,
        )
        runs_http = httpx.Client(
            base_url=runs_base_url,
            headers=headers,
            timeout=timeout,
        )

        self.tools = ToolsNamespace(tools_http)
        self.runs = RunsNamespace(runs_http)
        self._clients: list[httpx.Client] = [tools_http, runs_http]

    def close(self) -> None:
        """Close all underlying HTTP clients."""
        errors: list[BaseException] = []
        for c in self._clients:
            try:
                c.close()
            except Exception as e:
                errors.append(e)
        self._clients.clear()
        if errors:
            raise errors[0]

    def __enter__(self) -> "ProtoClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
