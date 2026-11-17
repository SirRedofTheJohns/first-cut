"""MCP server exposing WordPress page tools.

Any MCP client can use it: the First Cut agent (through langchain-mcp-adapters), Claude
Code, Claude Desktop, Cursor, or MCP Inspector.

    uvx --from git+https://github.com/SirRedofTheJohns/first-cut first-cut-mcp   # stdio
    uv run python -m mcp_server                                  # stdio, from a clone
    uv run python -m mcp_server --transport streamable-http      # http://127.0.0.1:8765/mcp
    uv run python -m mcp_server --check                          # test the WordPress login
"""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from firstcut.integrations.wordpress import PageStatus, WordPressClient, WordPressError
from firstcut.render import render_blocks
from firstcut.schemas import ColorToken, PageDraft, PageSection, StyleGuide, TypeToken, slugify

INSTRUCTIONS = """\
Manage pages on a WordPress site. To save site copy, use save_draft: it renders valid,
editable blocks, updates the draft with the same slug instead of duplicating it, and never
touches live pages. New pages are drafts by default. Setting status='publish' makes a page
live, so only do that when the user explicitly asks."""


class Brand(BaseModel):
    """Brand styling for save_draft, from the client's style guide or Figma file."""

    colors: list[ColorToken] = Field(
        default_factory=list,
        description="Named colors, e.g. {'name': 'Primary', 'hex': '#C2410C'}. A name with "
        "primary/accent/brand colors the button; a name with text/ink colors the body text.",
    )
    fonts: list[TypeToken] = Field(
        default_factory=list,
        description="Google Fonts, e.g. {'name': 'Heading', 'family': 'Fraunces', 'weight': "
        "600}. A name with head/display/title styles headings; body/paragraph styles text.",
    )

    def style_guide(self) -> StyleGuide | None:
        if not self.colors and not self.fonts:
            return None
        return StyleGuide(source="save_draft", colors=self.colors, typography=self.fonts)


def create_server(
    client_factory: Callable[[], WordPressClient] = WordPressClient.from_settings,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> FastMCP:
    """Build the server. Tests pass a factory that returns an in-memory fake."""

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[WordPressClient | WordPressError]:
        try:
            client = client_factory()
        except WordPressError as exc:
            # Missing settings: start anyway, so the agent can tell the user what to fix
            # instead of the MCP client only reporting "server failed to start".
            yield exc
            return
        # One HTTP connection pool for the server's lifetime, closed on shutdown.
        async with client:
            yield client

    mcp = FastMCP(
        "first-cut-wordpress", instructions=INSTRUCTIONS, lifespan=lifespan, host=host, port=port
    )

    def wp(ctx: Context) -> WordPressClient:
        client = ctx.request_context.lifespan_context
        if isinstance(client, WordPressError):
            raise client
        return client

    # Results are JSON text, so every MCP client (and LLM) gets one predictable payload.
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True), structured_output=False)
    async def list_pages(ctx: Context, search: str | None = None) -> str:
        """List WordPress pages of any status (id, slug, status, link, title)."""
        return json.dumps(await wp(ctx).list_pages(search))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True), structured_output=False)
    async def get_page(ctx: Context, page_id: int) -> str:
        """Get one WordPress page, including its raw block content."""
        return json.dumps(await wp(ctx).get_page(page_id))

    @mcp.tool(
        annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True),
        structured_output=False,
    )
    async def save_draft(
        ctx: Context,
        slug: str,
        title: str,
        sections: list[PageSection],
        button_label: str,
        brand: Brand | None = None,
    ) -> str:
        """Save one page of site copy to WordPress as a draft, rendered as editable blocks.

        Each section is a heading plus plain-text body (no HTML or [placeholders]; **bold**
        and blank lines between paragraphs are kept). `button_label` is the main button,
        2-5 words. If a draft with this slug exists it is updated, not duplicated. A live page
        with this slug is never changed: the result says it was skipped.
        """
        client = wp(ctx)
        draft = PageDraft(
            slug=slugify(slug),
            title=title,
            sections=sections,
            button_label=button_label,
            meta_description="",
        )
        content = render_blocks(draft, brand.style_guide() if brand else None)
        same_slug = await client.list_pages(slug=draft.slug)
        live = next((page for page in same_slug if page["status"] == "publish"), None)
        if live:
            return _result("skipped", live, "it is live; publish changes only when the user asks")
        if same_slug:
            page = await client.update_page(same_slug[0]["id"], draft.title, content)
            return _result("updated", page)
        page = await client.create_page(draft.title, content, draft.slug, "draft")
        return _result("created", page)

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


def _result(action: str, page: dict[str, Any], reason: str | None = None) -> str:
    result = {"action": action, **page}
    if reason:
        result["reason"] = reason
    return json.dumps(result)
