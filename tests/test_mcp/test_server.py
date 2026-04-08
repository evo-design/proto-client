"""Tests for MCP server setup — lifespan, registration, and config."""

from unittest.mock import AsyncMock, patch


def test_server_metadata():
    from proto_client.mcp.server import mcp

    assert mcp.name == "proto-bio"
    assert "Proto Bio" in mcp.instructions


async def test_lifespan_creates_and_closes_client():
    from proto_client.mcp.server import _lifespan, mcp

    mock_client = AsyncMock()
    with patch("proto_client.mcp.server.AsyncProtoClient", return_value=mock_client):
        async with _lifespan(mcp):
            import proto_client.mcp.tools as tools_mod

            assert tools_mod._client is mock_client

    mock_client.aclose.assert_awaited_once()
    assert tools_mod._client is None
