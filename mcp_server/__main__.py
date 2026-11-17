import argparse
import asyncio
import logging
import sys

from firstcut.config import Settings, get_settings
from firstcut.integrations.wordpress import WordPressClient, WordPressError
from mcp_server.server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="First Cut WordPress MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--check", action="store_true", help="test the WordPress login, print the result, exit"
    )
    args = parser.parse_args()
    # httpx logs every request URL at INFO; keep MCP client logs readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.check:
        sys.exit(asyncio.run(check()))
    create_server(host=args.host, port=args.port).run(transport=args.transport)


async def check(settings: Settings | None = None) -> int:
    """Log in with WP_URL / WP_USER / WP_APP_PASSWORD and list pages: 0 if it works."""
    settings = settings or get_settings()
    try:
        async with WordPressClient.from_settings(settings) as client:
            pages = await client.list_pages()
    except WordPressError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"OK: logged in to {settings.wp_url} as {settings.wp_user} ({len(pages)} pages found).")
    return 0


if __name__ == "__main__":
    main()
