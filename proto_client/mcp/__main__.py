"""Entry point for ``python -m proto_client.mcp``."""

import argparse
import os


def run_server(transport: str, host: str, port: int | None) -> None:
    """Launch the MCP server with the given transport configuration.

    Shared by ``python -m proto_client.mcp`` and the ``proto-client mcp`` CLI
    subcommand. ``port=None`` resolves to ``$PORT`` then 9300 for http.
    """
    from proto_client.mcp.server import mcp

    if transport == "stdio":
        mcp.run()
        return

    resolved_port = port if port is not None else int(os.environ.get("PORT") or 9300)
    mcp.run(transport="http", host=host, port=resolved_port, stateless_http=True)


def main() -> None:
    """Parse CLI args and run the Proto Bio MCP server."""
    parser = argparse.ArgumentParser(description="Proto Bio MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="HTTP port (default: $PORT or 9300)")
    args = parser.parse_args()

    run_server(args.transport, args.host, args.port)


if __name__ == "__main__":
    main()
