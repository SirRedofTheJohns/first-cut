"""MCP server exposing WordPress page tools.

Any MCP client can use it: the First Cut agent (through langchain-mcp-adapters), Claude
Desktop, or MCP Inspector.

    uv run python -m mcp_server                                  # stdio (Claude Desktop, Inspector)
    uv run python -m mcp_server --transport streamable-http      # http://127.0.0.1:8765/mcp
"""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from firstcut.integrations.wordpress import PageStatus, WordPressClient

INSTRUCTIONS = """\
Manage pages on a WordPress site. New pages are created as drafts by default. Setting
status='publish' makes a page live, so only do that when the user explicitly asks."""


def create_server(
    client_factory: Callable[[], WordPressClient] = WordPressClient.from_settings,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> FastMCP:
    """Build the server. Tests pass a factory that returns an in-memory fake."""

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[WordPressClient]:
        # One HTTP connection pool for the server's lifetime, closed on shutdown.
        async with client_factory() as client:
            yield client

    mcp = FastMCP(
        "first-cut-wordpress", instructions=INSTRUCTIONS, lifespan=lifespan, host=host, port=port
    )

    def wp(ctx: Context) -> WordPressClient:
        return ctx.request_context.lifespan_context

    # Results are JSON text, so every MCP client (and LLM) gets one predictable payload.
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True), structured_output=False)
    async def list_pages(ctx: Context, search: str | None = None) -> str:
        """List WordPress pages of any status (id, slug, status, link, title)."""
        return json.dumps(await wp(ctx).list_pages(search))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True), structured_output=False)
    async def get_page(ctx: Context, page_id: int) -> str:
        """Get one WordPress page, including its raw block content."""
        return json.dumps(await wp(ctx).get_page(page_id))

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=False), structured_output=False)
    async def create_page(
        ctx: Context,
        title: str,
        content: str,
        slug: str | None = None,
        status: PageStatus = "draft",
    ) -> str:
        """Create a WordPress page. `content` is block markup or HTML. Defaults to a draft."""
        return json.dumps(await wp(ctx).create_page(title, content, slug, status))

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True), structured_output=False)
    async def update_page(
        ctx: Context,
        page_id: int,
        title: str | None = None,
        content: str | None = None,
        status: PageStatus | None = None,
    ) -> str:
        """Update a page's title, content and/or status ('publish' makes it live)."""
        return json.dumps(await wp(ctx).update_page(page_id, title, content, status))

    return mcp
