"""End-to-end HTTP integration test for the hosted MCP server.

Exercises the full ASGI + MCP JSON-RPC stack — not just isolated helpers — to
prove the hosted per-request-auth contract: a Bearer token in the HTTP
``Authorization`` header reaches a tool handler and becomes the per-request
``AsyncProtoClient``'s ``api_key``. The per-request vs lifespan branching of
``_get_client`` itself is unit-tested in ``test_tools.py``.

The FastMCP client is pointed at the in-process app via ``httpx.ASGITransport``
(no socket bound) through ``StreamableHttpTransport``'s ``httpx_client_factory``
hook. The app is built exactly as production builds it: ``stateless_http=True``.
"""

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from proto_client.models import MeResponse

_ME = MeResponse(
    workspace_id="ws_test",
    workspace_name="Acme Bio",
    key_id="key_test",
    scopes=["tools:run"],
    tier="pro",
)


class _RecordingClient:
    """Stand-in for ``AsyncProtoClient`` recording the api_key it is built with."""

    last_api_key: str | None = None

    def __init__(self, api_key: str | None = None, **_kwargs: object) -> None:
        type(self).last_api_key = api_key

    async def __aenter__(self) -> "_RecordingClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def me(self) -> MeResponse:
        return _ME


def _asgi_client_factory(app: object):
    """Return an MCP-compatible httpx client factory backed by the in-process app."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        **_kwargs: object,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=True,
        )

    return factory


async def test_bearer_header_becomes_per_request_api_key(monkeypatch):
    """A Bearer token on the HTTP request authenticates that one tool call."""
    from proto_client.mcp.server import mcp

    monkeypatch.setattr("proto_client.mcp.tools.AsyncProtoClient", _RecordingClient)
    _RecordingClient.last_api_key = None

    app = mcp.http_app(stateless_http=True)
    transport = StreamableHttpTransport(
        url="http://test/mcp",
        headers={"Authorization": "Bearer sk-test-123"},
        httpx_client_factory=_asgi_client_factory(app),
    )

    # ASGITransport doesn't drive ASGI lifespan, but the streamable-HTTP session
    # manager initializes its task group there — run the lifespan explicitly.
    async with app.router.lifespan_context(app):
        async with Client(transport) as client:
            result = await client.call_tool("whoami", {})

    # The HTTP Bearer token reached _get_client and built the per-request client.
    assert _RecordingClient.last_api_key == "sk-test-123"
    # And the handler's MeResponse round-tripped back through the JSON-RPC layer.
    assert result.data.workspace_id == "ws_test"
