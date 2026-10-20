"""The agent's WordPress tools, loaded from the First Cut MCP server.

The agent never talks to the WordPress REST API itself: every page operation goes through
MCP, the same server Claude Desktop can use.
"""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from firstcut.config import Settings, get_settings


@asynccontextmanager
async def wordpress_tools(settings: Settings | None = None) -> AsyncIterator[dict[str, BaseTool]]:
    settings = settings or get_settings()
    client = MultiServerMCPClient({"wordpress": _connection(settings)})
    # One session for the whole run. `client.get_tools()` would open a new session (and,
    # over stdio, spawn a new server process) for every single tool call.
    async with client.session("wordpress") as session:
        yield {tool.name: tool for tool in await load_mcp_tools(session)}


def _connection(settings: Settings) -> dict:
    if settings.mcp_wordpress_url:
        return {"transport": "streamable_http", "url": settings.mcp_wordpress_url}
    # stdio: spawn the server as a child process. The MCP SDK passes only a minimal,
    # safe set of environment variables to children, so WordPress settings go explicitly.
    env = {"WP_URL": settings.wp_url, "WP_USER": settings.wp_user}
    if settings.wp_app_password:
        env["WP_APP_PASSWORD"] = settings.wp_app_password.get_secret_value()
    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "mcp_server"],
        "env": env,
    }
