"""Tests for the ``client.me()`` principal-introspection endpoint."""

import httpx
import pytest

from proto_client import AsyncProtoClient, ProtoClient
from proto_client.errors import ProtoAuthError, ProtoServerError


def _swap_runs_transport(client, handler) -> None:
    """Replace the runs httpx client with a MockTransport-backed one."""
    mock = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test")
    client._runs_http = mock
    client._clients = [mock]


def _swap_async_runs_transport(client, handler) -> None:
    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.test")
    client._runs_http = mock
    client._clients = [mock]


def _principal(**overrides):
    base = {"key_id": "pk_demo", "label": "demo", "capabilities": [], "is_master": False}
    base.update(overrides)
    return base


def test_me_returns_principal_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/me"
        assert request.method == "GET"
        return httpx.Response(200, json=_principal(capabilities=["custom_components:execute"]))

    c = ProtoClient(api_key="x")
    _swap_runs_transport(c, handler)
    me = c.me()
    assert me.key_id == "pk_demo"
    assert me.label == "demo"
    assert me.capabilities == ["custom_components:execute"]
    assert me.is_master is False
    c.close()


def test_me_raises_proto_auth_error_on_401():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid or missing API key"})

    c = ProtoClient(api_key="x")
    _swap_runs_transport(c, handler)
    with pytest.raises(ProtoAuthError):
        c.me()
    c.close()


def test_me_raises_proto_server_error_on_500():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    c = ProtoClient(api_key="x")
    _swap_runs_transport(c, handler)
    with pytest.raises(ProtoServerError):
        c.me()
    c.close()


def test_me_master_principal_advertises_flag():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_principal(label="dev-master", is_master=True))

    c = ProtoClient(api_key="x")
    _swap_runs_transport(c, handler)
    me = c.me()
    assert me.is_master is True
    assert me.capabilities == []
    c.close()


async def test_async_me_returns_principal_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/me"
        return httpx.Response(200, json=_principal(capabilities=["custom_components:execute"]))

    c = AsyncProtoClient(api_key="x")
    _swap_async_runs_transport(c, handler)
    me = await c.me()
    assert me.capabilities == ["custom_components:execute"]
    await c.aclose()


async def test_async_me_raises_proto_auth_error_on_403():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "nope"})

    c = AsyncProtoClient(api_key="x")
    _swap_async_runs_transport(c, handler)
    with pytest.raises(ProtoAuthError):
        await c.me()
    await c.aclose()
