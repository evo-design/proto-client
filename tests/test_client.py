"""Tests for ProtoClient initialization and configuration."""

import logging
import os
from unittest.mock import patch

import pytest

from proto_client import AsyncProtoClient, ProtoClient, RetryConfig
from proto_client.utils.defaults import RUNS_BASE_URL, TOOLS_BASE_URL, resolve_base_url
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


def _clear_base_url_env() -> None:
    os.environ.pop("PROTO_TOOLS_BASE_URL", None)
    os.environ.pop("PROTO_RUNS_BASE_URL", None)


def test_default_base_urls_when_unset():
    """With nothing overridden, both namespaces use the packaged defaults."""
    with patch.dict(os.environ, {}, clear=False):
        _clear_base_url_env()
        with ProtoClient() as c:
            assert str(c.tools._http.base_url).rstrip("/") == TOOLS_BASE_URL.rstrip("/")
            assert str(c.runs._http.base_url).rstrip("/") == RUNS_BASE_URL.rstrip("/")


def test_base_url_constructor_args_override():
    with ProtoClient(tools_base_url="https://tools.example.com", runs_base_url="https://runs.example.com") as c:
        assert str(c.tools._http.base_url).rstrip("/") == "https://tools.example.com"
        assert str(c.runs._http.base_url).rstrip("/") == "https://runs.example.com"


def test_base_url_env_vars_override():
    with patch.dict(
        os.environ,
        {"PROTO_TOOLS_BASE_URL": "https://tools.env.com", "PROTO_RUNS_BASE_URL": "https://runs.env.com"},
    ):
        with ProtoClient() as c:
            assert str(c.tools._http.base_url).rstrip("/") == "https://tools.env.com"
            assert str(c.runs._http.base_url).rstrip("/") == "https://runs.env.com"


def test_base_url_arg_beats_env():
    with patch.dict(os.environ, {"PROTO_TOOLS_BASE_URL": "https://from-env.com"}):
        with ProtoClient(tools_base_url="https://from-arg.com") as c:
            assert str(c.tools._http.base_url).rstrip("/") == "https://from-arg.com"


def test_base_url_plaintext_override_rejected():
    with pytest.raises(ValueError, match="must use https"):
        ProtoClient(tools_base_url="http://insecure.example.com:8000")


async def test_async_base_url_overrides():
    async with AsyncProtoClient(
        tools_base_url="https://tools.example.com", runs_base_url="https://runs.example.com"
    ) as c:
        assert str(c.tools._http.base_url).rstrip("/") == "https://tools.example.com"
        assert str(c.runs._http.base_url).rstrip("/") == "https://runs.example.com"


class TestResolveBaseUrl:
    """Unit tests for the base-URL resolution chain and its https guard."""

    def test_precedence_arg_over_env_over_default(self):
        with patch.dict(os.environ, {"PROTO_X": "https://env.com"}):
            assert resolve_base_url("https://arg.com", env_var="PROTO_X", default="https://d.com") == "https://arg.com"
            assert resolve_base_url(None, env_var="PROTO_X", default="https://d.com") == "https://env.com"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROTO_X", None)
            assert resolve_base_url(None, env_var="PROTO_X", default="https://d.com") == "https://d.com"

    def test_default_returned_verbatim_without_scheme_check(self):
        """A non-https default is trusted and never validated."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROTO_X", None)
            assert resolve_base_url(None, env_var="PROTO_X", default="http://trusted") == "http://trusted"

    def test_non_default_plaintext_rejected(self):
        with pytest.raises(ValueError, match="must use https"):
            resolve_base_url("http://evil.example.com:8000", env_var="PROTO_X", default="https://d.com")

    @pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"])
    def test_loopback_http_allowed(self, url):
        assert resolve_base_url(url, env_var="PROTO_X", default="https://d.com") == url

    def test_https_non_default_allowed(self):
        assert resolve_base_url("https://staging.example.com", env_var="PROTO_X", default="https://d.com") == (
            "https://staging.example.com"
        )

    def test_logs_on_override(self, caplog):
        with caplog.at_level(logging.INFO, logger="proto_client.utils.defaults"):
            resolve_base_url("https://staging.example.com", env_var="PROTO_X", default="https://d.com")
        assert any("non-default base URL" in r.message for r in caplog.records)


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
