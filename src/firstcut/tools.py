"""WordPress tools for the agent.

The graph only depends on four tool *names* (list_pages, get_page, create_page, update_page).
Here they are backed directly by the REST client; the MCP server exposes the same names, so
the backend can be swapped without touching the graph. Results are JSON text, like MCP tool
results, so the LLM sees the same thing with either backend.
"""

import json
from typing import Any

from langchain_core.tools import BaseTool, tool

from firstcut.integrations.wordpress import PageStatus, WordPressClient

WordPressTools = dict[str, BaseTool]


def wordpress_tools(client: WordPressClient) -> WordPressTools:
    @tool
    async def list_pages(search: str | None = None) -> str:
        """List WordPress pages of any status (id, slug, status, link, title)."""
        return json.dumps(await client.list_pages(search))

    @tool
    async def get_page(page_id: int) -> str:
        """Get one WordPress page, including its raw block content."""
        return json.dumps(await client.get_page(page_id))

    @tool
    async def create_page(
        title: str, content: str, slug: str | None = None, status: PageStatus = "draft"
    ) -> str:
        """Create a WordPress page. `content` is block markup or HTML. Defaults to a draft."""
        return json.dumps(await client.create_page(title, content, slug, status))

    @tool
    async def update_page(
        page_id: int,
        title: str | None = None,
        content: str | None = None,
        status: PageStatus | None = None,
    ) -> str:
        """Update a page's title, content and/or status ('publish' makes it live)."""
        return json.dumps(await client.update_page(page_id, title, content, status))

    return {t.name: t for t in (list_pages, get_page, create_page, update_page)}


def tool_data(result: Any) -> Any:
    """Normalize a tool result to plain data.

    Tools return JSON text; MCP results may also arrive wrapped in a
    list of content blocks.
    """
    if isinstance(result, list) and result and isinstance(result[0], dict) and "type" in result[0]:
        result = "".join(block.get("text", "") for block in result if block["type"] == "text")
    if isinstance(result, str):
        return json.loads(result)
    return result
