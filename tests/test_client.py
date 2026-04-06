"""Tests for ProtoClient initialization and configuration."""

import os
from unittest.mock import patch

import pytest

from proto_client import ProtoClient


def test_client_init_with_api_key():
    with ProtoClient(api_key="test-key", tools_base_url="http://localhost:9999") as c:
        assert c.tools is not None


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


def test_client_context_manager():
    with ProtoClient(tools_base_url="http://localhost:9999") as c:
        assert c is not None


def test_runs_not_implemented():
    with ProtoClient(tools_base_url="http://localhost:9999") as c:
        with pytest.raises(NotImplementedError, match="not yet available"):
            c.runs.create({})


def test_close_cleans_up():
    c = ProtoClient(tools_base_url="http://localhost:9999")
    assert len(c._clients) > 0
    c.close()
    assert len(c._clients) == 0
