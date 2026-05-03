"""ASGI wrapper that exposes the MCP server over HTTP with a /health endpoint."""

from fastapi import FastAPI

from proto_client.mcp.server import mcp


def build_app() -> FastAPI:
    """Build the ASGI app: FastMCP HTTP transport at ``/mcp`` plus ``/health``."""
    mcp_app = mcp.http_app(path="/", stateless_http=True)

    app = FastAPI(title="Proto Bio MCP", version="0.1.0", lifespan=mcp_app.lifespan)
    app.mount("/mcp", mcp_app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy"}

    return app
