"""Tests for ProtoClient initialization and configuration."""

import os
from unittest.mock import patch

import pytest

from proto_client import ProtoClient, RetryConfig
from proto_client._http import RetryTransport


def test_client_reads_env_var():
    with patch.dict(os.environ, {"PROTO_API_KEY": "env-key"}):
        c = ProtoClient(tools_base_url="http://localhost:9999")
        assert c.tools._http.headers.get("x-api-key") == "env-key"
        c.close()


def test_client_no_key_no_header():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PROTO_API_KEY", None)
        c = ProtoClient(tools_base_url="http://localhost:9999")
        assert "x-api-key" not in c.tools._http.headers
        c.close()


def test_client_empty_key_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        ProtoClient(api_key="")


def test_runs_namespace_wired():
    with ProtoClient(
        tools_base_url="http://localhost:9999",
        runs_base_url="http://localhost:9998",
    ) as c:
        assert c.runs is not None
        assert str(c.runs._http.base_url).rstrip("/") == "http://localhost:9998"


def test_client_closes_both_http_clients():
    c = ProtoClient(
        tools_base_url="http://localhost:9999",
        runs_base_url="http://localhost:9998",
    )
    tools_http = c.tools._http
    runs_http = c.runs._http
    c.close()
    assert tools_http.is_closed
    assert runs_http.is_closed


def test_close_idempotent():
    c = ProtoClient(
        tools_base_url="http://localhost:9999",
        runs_base_url="http://localhost:9998",
    )
    tools_http = c.tools._http
    runs_http = c.runs._http
    c.close()
    assert tools_http.is_closed
    assert runs_http.is_closed
    assert c._clients == []
    c.close()  # second close on empty list should not raise


def test_default_client_has_retry_transport():
    with ProtoClient(tools_base_url="http://localhost:9999") as c:
        tools_transport = c.tools._http._transport
        runs_transport = c.runs._http._transport
        assert isinstance(tools_transport, RetryTransport)
        assert isinstance(runs_transport, RetryTransport)
        assert tools_transport._config.max_retries == 2


def test_max_retries_zero():
    with ProtoClient(tools_base_url="http://localhost:9999", max_retries=0) as c:
        transport = c.tools._http._transport
        assert isinstance(transport, RetryTransport)
        assert transport._config.max_retries == 0


def test_explicit_retry_config():
    cfg = RetryConfig(max_retries=5, initial_delay=1.0)
    with ProtoClient(tools_base_url="http://localhost:9999", retry_config=cfg) as c:
        transport = c.tools._http._transport
        assert isinstance(transport, RetryTransport)
        assert transport._config.max_retries == 5
        assert transport._config.initial_delay == 1.0


def test_version_exported():
    from proto_client import __version__

    assert isinstance(__version__, str)
    assert __version__


def test_user_agent_header():
    with ProtoClient(tools_base_url="http://localhost:9999") as c:
        ua = c.tools._http.headers.get("user-agent", "")
        assert "proto-client-python/" in ua
        assert "python/" in ua


def test_base_url_from_env_tools():
    with patch.dict(os.environ, {"PROTO_TOOLS_BASE_URL": "http://custom-tools:8000"}):
        with ProtoClient() as c:
            assert str(c.tools._http.base_url).rstrip("/") == "http://custom-tools:8000"


def test_base_url_from_env_runs():
    with patch.dict(os.environ, {"PROTO_RUNS_BASE_URL": "http://custom-runs:8000"}):
        with ProtoClient() as c:
            assert str(c.runs._http.base_url).rstrip("/") == "http://custom-runs:8000"


def test_explicit_base_url_overrides_env():
    with patch.dict(os.environ, {"PROTO_TOOLS_BASE_URL": "http://env:8000"}):
        with ProtoClient(tools_base_url="http://explicit:9000") as c:
            assert str(c.tools._http.base_url).rstrip("/") == "http://explicit:9000"
