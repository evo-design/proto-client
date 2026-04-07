"""Tests for ProtoClient initialization and configuration."""

import importlib
import logging
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


@pytest.mark.parametrize("max_retries,expected", [(2, 2), (0, 0)])
def test_retry_config_propagation(max_retries, expected):
    kwargs = {"tools_base_url": "http://localhost:9999"}
    if max_retries != 2:
        kwargs["max_retries"] = max_retries
    with ProtoClient(**kwargs) as c:
        transport = c.tools._http._transport
        assert isinstance(transport, RetryTransport)
        assert transport._config.max_retries == expected


def test_explicit_retry_config():
    cfg = RetryConfig(max_retries=5, initial_delay=1.0)
    with ProtoClient(tools_base_url="http://localhost:9999", retry_config=cfg) as c:
        transport = c.tools._http._transport
        assert isinstance(transport, RetryTransport)
        assert transport._config.max_retries == 5
        assert transport._config.initial_delay == 1.0


def test_user_agent_header():
    with ProtoClient(tools_base_url="http://localhost:9999") as c:
        ua = c.tools._http.headers.get("user-agent", "")
        assert "proto-client-python/" in ua
        assert "python/" in ua


@pytest.mark.parametrize(
    "env_var,namespace",
    [
        ("PROTO_TOOLS_BASE_URL", "tools"),
        ("PROTO_RUNS_BASE_URL", "runs"),
    ],
)
def test_base_url_from_env(monkeypatch, env_var, namespace):
    url = f"http://custom-{namespace}:8000"
    monkeypatch.setenv(env_var, url)
    with ProtoClient() as c:
        assert str(getattr(c, namespace)._http.base_url).rstrip("/") == url


def test_explicit_base_url_overrides_env():
    with patch.dict(os.environ, {"PROTO_TOOLS_BASE_URL": "http://env:8000"}):
        with ProtoClient(tools_base_url="http://explicit:9000") as c:
            assert str(c.tools._http.base_url).rstrip("/") == "http://explicit:9000"


def test_close_reraises_first_error():
    """When a client raises during close(), the first error is re-raised after all clients are closed."""
    c = ProtoClient(
        tools_base_url="http://localhost:9999",
        runs_base_url="http://localhost:9998",
    )

    original_close = c._clients[0].close

    def exploding_close():
        original_close()
        raise RuntimeError("close boom")

    c._clients[0].close = exploding_close

    with pytest.raises(RuntimeError, match="close boom"):
        c.close()
    # Second client should still be closed even though the first one raised.
    assert c._clients == []


def test_close_captures_first_error_only():
    """When multiple clients raise during close(), only the first error propagates."""
    c = ProtoClient(
        tools_base_url="http://localhost:9999",
        runs_base_url="http://localhost:9998",
    )

    original_close_0 = c._clients[0].close
    original_close_1 = c._clients[1].close
    close_calls = [0, 0]

    def exploding_close_0():
        close_calls[0] += 1
        original_close_0()
        raise RuntimeError("first boom")

    def exploding_close_1():
        close_calls[1] += 1
        original_close_1()
        raise RuntimeError("second boom")

    c._clients[0].close = exploding_close_0
    c._clients[1].close = exploding_close_1

    with pytest.raises(RuntimeError, match="first boom"):
        c.close()

    # Both clients' close() must be called even when the first one raises.
    assert close_calls == [1, 1]


# ── PROTO_LOG env var ──

# These tests use importlib.reload to exercise module-level logging setup,
# which mutates global logger state.  Do NOT run them in parallel with
# pytest-xdist (they are not xdist-safe).


@pytest.mark.parametrize("level", ["debug", "info"])
def test_proto_log_env_var(monkeypatch, level):
    import proto_client

    logger = logging.getLogger("proto_client")
    original_level = logger.level
    original_handlers = logger.handlers[:]

    try:
        monkeypatch.setenv("PROTO_LOG", level)
        importlib.reload(proto_client)
        assert logger.level == getattr(logging, level.upper())
        if level == "debug":
            stream_handlers = [
                h
                for h in logger.handlers
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler)
            ]
            assert len(stream_handlers) >= 1
    finally:
        logger.setLevel(original_level)
        logger.handlers = original_handlers
        importlib.reload(proto_client)
