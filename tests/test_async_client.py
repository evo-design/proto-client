"""Tests for AsyncProtoClient initialization and lifecycle."""

import os
from unittest.mock import patch

import pytest

from proto_client import AsyncProtoClient


async def test_async_client_lifecycle_and_wiring():
    """Context manager closes both clients; base URLs are wired correctly."""
    async with AsyncProtoClient(
        api_key="k",
        tools_base_url="http://tools.test",
        runs_base_url="http://runs.test",
    ) as c:
        tools_http = c.tools._http
        runs_http = c.runs._http
        assert str(runs_http.base_url).rstrip("/") == "http://runs.test"
        assert str(tools_http.base_url).rstrip("/") == "http://tools.test"
        assert not tools_http.is_closed
    assert tools_http.is_closed
    assert runs_http.is_closed


async def test_async_client_api_key_from_env():
    with patch.dict(os.environ, {"PROTO_API_KEY": "env-key"}):
        async with AsyncProtoClient(tools_base_url="http://localhost:9999") as c:
            assert c.runs._http.headers.get("x-api-key") == "env-key"
            assert c.tools._http.headers.get("x-api-key") == "env-key"


async def test_async_client_no_key_no_header():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PROTO_API_KEY", None)
        async with AsyncProtoClient(tools_base_url="http://localhost:9999") as c:
            assert "x-api-key" not in c.runs._http.headers


async def test_async_client_empty_key_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        AsyncProtoClient(api_key="")


async def test_async_tools_namespace_skeleton_raises():
    """AsyncToolsNamespace is a stub pending issue #2 integration."""
    async with AsyncProtoClient(tools_base_url="http://localhost:9999") as c:
        with pytest.raises(NotImplementedError, match="pending async implementation"):
            await c.tools.list()
