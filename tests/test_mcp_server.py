import asyncio

import pytest
from langchain_core.tools import ToolException
from mcp.shared.memory import create_connected_server_and_client_session

from firstcut.config import Settings
from firstcut.graph.publish import call_tool
from firstcut.mcp_client import _connection
from mcp_server.server import create_server
from tests.fakes import FakeWordPressClient, mcp_wordpress_tools


def test_server_advertises_tools_with_safety_annotations():
    async def list_tools():
        server = create_server(client_factory=FakeWordPressClient)
        async with create_connected_server_and_client_session(server) as session:
            return {tool.name: tool for tool in (await session.list_tools()).tools}

    tools = asyncio.run(list_tools())
    assert set(tools) == {"list_pages", "get_page", "create_page", "update_page"}
    assert tools["list_pages"].annotations.readOnlyHint
    assert tools["update_page"].annotations.destructiveHint  # can make a page live
    assert "ctx" not in tools["create_page"].inputSchema["properties"]


def test_tools_round_trip_through_mcp():
    wp = FakeWordPressClient()

    async def scenario():
        async with mcp_wordpress_tools(wp) as tools:
            created = await call_tool(
                tools["create_page"], {"title": "Home", "content": "<p>x</p>"}
            )
            await call_tool(tools["update_page"], {"page_id": created["id"], "status": "publish"})
            return await call_tool(tools["list_pages"], {})

    pages = asyncio.run(scenario())
    assert [(p["id"], p["title"], p["status"]) for p in pages] == [(101, "Home", "publish")]
    assert wp.pages[101]["content"] == "<p>x</p>"


def test_wordpress_errors_reach_the_client_as_tool_errors():
    async def scenario():
        async with mcp_wordpress_tools(FakeWordPressClient()) as tools:
            # An LLM gets the error as text, so it can react to it...
            for_llm = await tools["get_page"].ainvoke({"page_id": 999})
            assert "404" in for_llm[0]["text"]
            # ...while code calling a tool gets an exception. (Checked inside the session:
            # leaving it, anyio's task group would wrap the error in an ExceptionGroup.)
            with pytest.raises(ToolException, match="404"):
                await call_tool(tools["get_page"], {"page_id": 999})

    asyncio.run(scenario())


def test_stdio_connection_passes_wordpress_settings_explicitly():
    settings = Settings(_env_file=None, wp_app_password="secret pass")
    connection = _connection(settings)
    assert connection["transport"] == "stdio"
    assert connection["args"] == ["-m", "mcp_server"]
    assert connection["env"]["WP_APP_PASSWORD"] == "secret pass"


def test_http_connection_when_url_is_configured():
    settings = Settings(_env_file=None, mcp_wordpress_url="http://localhost:8765/mcp")
    assert _connection(settings) == {
        "transport": "streamable_http",
        "url": "http://localhost:8765/mcp",
    }
