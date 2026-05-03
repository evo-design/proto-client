"""Entry point for ``python -m proto_client.mcp``."""

import argparse
import os


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
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT") or 9300),
        help="HTTP port (default: $PORT or 9300)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        from proto_client.mcp.server import mcp

        mcp.run()
        return

    import uvicorn

    from proto_client.mcp.app import build_app

    uvicorn.run(build_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
