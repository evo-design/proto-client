"""Tests for ProtoClient initialization and configuration."""

import os
from unittest.mock import patch

import pytest

from proto_client import ProtoClient, RetryConfig
from proto_client.utils.http import RetryTransport


def test_client_reads_env_var():
    with patch.dict(os.environ, {"PROTO_API_KEY": "env-key"}):
        c = ProtoClient()
        assert c.tools._http.headers.get("x-api-key") == "env-key"
        c.close()


def test_client_no_key_no_header():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PROTO_API_KEY", None)
        c = ProtoClient()
        assert "x-api-key" not in c.tools._http.headers
        c.close()


def test_client_empty_key_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        ProtoClient(api_key="")


def test_client_sets_app_user_id_header_on_both_namespaces():
    with ProtoClient(api_key="x", app_user_id="user-abc") as c:
        assert c.tools._http.headers.get("x-app-user-id") == "user-abc"
        assert c.runs._http.headers.get("x-app-user-id") == "user-abc"


def test_client_no_app_user_id_no_header():
    with ProtoClient(api_key="x") as c:
        assert "x-app-user-id" not in c.tools._http.headers


def test_client_empty_app_user_id_raises():
    with pytest.raises(ValueError, match="app_user_id must not be empty"):
        ProtoClient(api_key="x", app_user_id="")


def test_client_closes_both_http_clients():
    c = ProtoClient()
    tools_http = c.tools._http
    runs_http = c.runs._http
    c.close()
    assert tools_http.is_closed
    assert runs_http.is_closed


@pytest.mark.parametrize("max_retries,expected", [(2, 2), (0, 0)])
def test_retry_config_propagation(max_retries, expected):
    kwargs = {}
    if max_retries != 2:
        kwargs["max_retries"] = max_retries
    with ProtoClient(**kwargs) as c:
        transport = c.tools._http._transport
        assert isinstance(transport, RetryTransport)
        assert transport._config.max_retries == expected


def test_explicit_retry_config():
    cfg = RetryConfig(max_retries=5, initial_delay=1.0)
    with ProtoClient(retry_config=cfg) as c:
        transport = c.tools._http._transport
        assert isinstance(transport, RetryTransport)
        assert transport._config.max_retries == 5
        assert transport._config.initial_delay == 1.0


def test_user_agent_header():
    with ProtoClient() as c:
        ua = c.tools._http.headers.get("user-agent", "")
        assert "proto-client-python/" in ua
        assert "python/" in ua


def test_base_urls_are_fixed():
    """Both base URLs are hardcoded — env-var hijack attempts are ignored."""
    from proto_client.utils.defaults import RUNS_BASE_URL, TOOLS_BASE_URL

    with patch.dict(
        os.environ,
        {"PROTO_TOOLS_BASE_URL": "http://hijack-tools:8000", "PROTO_RUNS_BASE_URL": "http://hijack-runs:8000"},
    ):
        with ProtoClient() as c:
            assert str(c.tools._http.base_url).rstrip("/") == TOOLS_BASE_URL.rstrip("/")
            assert str(c.runs._http.base_url).rstrip("/") == RUNS_BASE_URL.rstrip("/")


def test_close_reraises_first_error():
    """When a client raises during close(), the first error is re-raised after all clients are closed."""
    c = ProtoClient()

    original_close = c._clients[0].close

    def exploding_close():
        original_close()
        raise RuntimeError("close boom")

    c._clients[0].close = exploding_close

    with pytest.raises(RuntimeError, match="close boom"):
        c.close()
    assert c._clients == []


def test_close_captures_first_error_only():
    """When multiple clients raise during close(), only the first error propagates."""
    c = ProtoClient()

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

    assert close_calls == [1, 1]
