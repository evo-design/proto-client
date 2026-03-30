"""Main client entrypoint."""

from __future__ import annotations

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
        timeout: float = 600.0,
    ):
        api_key = api_key or os.environ.get("PROTO_API_KEY")
        headers = {}
        if api_key:
            headers["X-API-Key"] = api_key

        tools_http = httpx.Client(
            base_url=tools_base_url,
            headers=headers,
            timeout=timeout,
        )

        self.tools = ToolsNamespace(tools_http)
        self.runs = RunsNamespace()
        self._clients = [tools_http]

    def close(self) -> None:
        for c in self._clients:
            c.close()

    def __enter__(self) -> ProtoClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
