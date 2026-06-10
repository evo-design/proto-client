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
    base = {
        "workspace_id": "11111111-1111-1111-1111-111111111111",
        "workspace_name": "Demo Workspace",
        "key_id": "pk_demo",
        "scopes": ["full"],
        "member_user_id": None,
        "tier": "expanded",
        "credit_cap": None,
        "remaining_credits": None,
    }
    base.update(overrides)
    return base


def test_me_returns_principal_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/me"
        assert request.method == "GET"
        return httpx.Response(
            200, json=_principal(scopes=["read_only"], tier="preview", credit_cap=10.0, remaining_credits=7.0)
        )

    c = ProtoClient(api_key="x")
    _swap_runs_transport(c, handler)
    me = c.me()
    assert me.workspace_id == "11111111-1111-1111-1111-111111111111"
    assert me.workspace_name == "Demo Workspace"
    assert me.key_id == "pk_demo"
    assert me.scopes == ["read_only"]
    assert me.tier == "preview"
    assert me.credit_cap == 10.0
    assert me.remaining_credits == 7.0
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


def test_me_uncapped_workspace_reports_null_credits():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_principal(credit_cap=None, remaining_credits=None))

    c = ProtoClient(api_key="x")
    _swap_runs_transport(c, handler)
    me = c.me()
    assert me.credit_cap is None
    assert me.remaining_credits is None
    assert me.member_user_id is None
    c.close()


async def test_async_me_returns_principal_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/me"
        return httpx.Response(
            200, json=_principal(scopes=["full"], member_user_id="22222222-2222-2222-2222-222222222222")
        )

    c = AsyncProtoClient(api_key="x")
    _swap_async_runs_transport(c, handler)
    me = await c.me()
    assert me.scopes == ["full"]
    assert me.member_user_id == "22222222-2222-2222-2222-222222222222"
    await c.aclose()


async def test_async_me_raises_proto_auth_error_on_403():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "nope"})

    c = AsyncProtoClient(api_key="x")
    _swap_async_runs_transport(c, handler)
    with pytest.raises(ProtoAuthError):
        await c.me()
    await c.aclose()
