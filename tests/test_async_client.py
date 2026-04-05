"""Tests for AsyncProtoClient initialization and lifecycle."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from proto_client import AsyncProtoClient


async def test_async_client_context_manager_closes_both_http_clients():
    async with AsyncProtoClient(
        api_key="k",
        tools_base_url="http://localhost:9999",
        runs_base_url="http://localhost:9998",
    ) as c:
        tools_http = c.tools._http
        runs_http = c.runs._http
        assert not tools_http.is_closed
        assert not runs_http.is_closed
    assert tools_http.is_closed
    assert runs_http.is_closed


async def test_async_client_reads_env_var():
    with patch.dict(os.environ, {"PROTO_API_KEY": "env-key"}):
        c = AsyncProtoClient(tools_base_url="http://localhost:9999")
        try:
            assert c.runs._http.headers.get("x-api-key") == "env-key"
            assert c.tools._http.headers.get("x-api-key") == "env-key"
        finally:
            await c.aclose()


async def test_async_client_empty_key_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        AsyncProtoClient(api_key="")


async def test_async_client_no_key_no_header():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PROTO_API_KEY", None)
        c = AsyncProtoClient(tools_base_url="http://localhost:9999")
        try:
            assert "x-api-key" not in c.runs._http.headers
            assert "x-api-key" not in c.tools._http.headers
        finally:
            await c.aclose()


async def test_async_client_runs_base_url_wired():
    async with AsyncProtoClient(
        tools_base_url="http://tools.test",
        runs_base_url="http://runs.test",
    ) as c:
        assert str(c.runs._http.base_url).rstrip("/") == "http://runs.test"
        assert str(c.tools._http.base_url).rstrip("/") == "http://tools.test"


async def test_async_tools_namespace_skeleton_raises():
    """Per the scope split with issue #2, AsyncToolsNamespace is a stub."""
    async with AsyncProtoClient(
        tools_base_url="http://localhost:9999",
        runs_base_url="http://localhost:9998",
    ) as c:
        with pytest.raises(NotImplementedError, match="issue #2"):
            await c.tools.list()
