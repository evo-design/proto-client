"""Tests for AsyncProtoClient initialization and lifecycle."""

import os
from unittest.mock import patch

import pytest

from proto_client import AsyncProtoClient, RetryConfig
from proto_client._http import AsyncRetryTransport


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


async def test_async_tools_namespace_is_functional():
    """AsyncToolsNamespace methods do not raise NotImplementedError."""
    import asyncio

    async with AsyncProtoClient(tools_base_url="http://localhost:9999") as c:
        assert asyncio.iscoroutinefunction(c.tools.list)
        assert asyncio.iscoroutinefunction(c.tools.get_schema)
        assert asyncio.iscoroutinefunction(c.tools.submit)
        assert asyncio.iscoroutinefunction(c.tools.run)


async def test_async_default_client_has_retry_transport():
    async with AsyncProtoClient(tools_base_url="http://localhost:9999") as c:
        tools_transport = c.tools._http._transport
        runs_transport = c.runs._http._transport
        assert isinstance(tools_transport, AsyncRetryTransport)
        assert isinstance(runs_transport, AsyncRetryTransport)
        assert tools_transport._config.max_retries == 2


async def test_async_max_retries_zero():
    async with AsyncProtoClient(tools_base_url="http://localhost:9999", max_retries=0) as c:
        transport = c.tools._http._transport
        assert isinstance(transport, AsyncRetryTransport)
        assert transport._config.max_retries == 0


async def test_async_explicit_retry_config():
    cfg = RetryConfig(max_retries=5, initial_delay=1.0)
    async with AsyncProtoClient(tools_base_url="http://localhost:9999", retry_config=cfg) as c:
        transport = c.tools._http._transport
        assert isinstance(transport, AsyncRetryTransport)
        assert transport._config.max_retries == 5
        assert transport._config.initial_delay == 1.0


async def test_async_user_agent_header():
    async with AsyncProtoClient(tools_base_url="http://localhost:9999") as c:
        ua = c.tools._http.headers.get("user-agent", "")
        assert "proto-client-python/" in ua
        assert "python/" in ua


async def test_async_base_url_from_env_tools():
    with patch.dict(os.environ, {"PROTO_TOOLS_BASE_URL": "http://custom-tools:8000"}):
        async with AsyncProtoClient() as c:
            assert str(c.tools._http.base_url).rstrip("/") == "http://custom-tools:8000"


async def test_async_base_url_from_env_runs():
    with patch.dict(os.environ, {"PROTO_RUNS_BASE_URL": "http://custom-runs:8000"}):
        async with AsyncProtoClient() as c:
            assert str(c.runs._http.base_url).rstrip("/") == "http://custom-runs:8000"


async def test_async_explicit_base_url_overrides_env():
    with patch.dict(os.environ, {"PROTO_TOOLS_BASE_URL": "http://env:8000"}):
        async with AsyncProtoClient(tools_base_url="http://explicit:9000") as c:
            assert str(c.tools._http.base_url).rstrip("/") == "http://explicit:9000"
