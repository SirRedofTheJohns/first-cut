import argparse
import logging

from mcp_server.server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="First Cut WordPress MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    # httpx logs every request URL at INFO; keep MCP client logs readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    create_server(host=args.host, port=args.port).run(transport=args.transport)


if __name__ == "__main__":
    main()
