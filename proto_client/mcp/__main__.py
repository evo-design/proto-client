"""Entry point for ``python -m proto_client.mcp``."""

import argparse


def main() -> None:
    """Parse CLI args and run the Proto Bio MCP server."""
    from proto_client.mcp.server import mcp

    parser = argparse.ArgumentParser(description="Proto Bio MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9300, help="HTTP port (default: 9300)")
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
