import asyncio

import pytest
from langchain_core.tools import ToolException
from mcp.shared.memory import create_connected_server_and_client_session

from firstcut.config import Settings
from firstcut.graph.publish import call_tool
from firstcut.integrations.wordpress import WordPressError
from firstcut.mcp_client import _connection
from mcp_server.__main__ import check
from mcp_server.server import create_server
from tests.fakes import FakeWordPressClient, mcp_wordpress_tools


def test_server_advertises_tools_with_safety_annotations():
    async def list_tools():
        server = create_server(client_factory=FakeWordPressClient)
        async with create_connected_server_and_client_session(server) as session:
            return {tool.name: tool for tool in (await session.list_tools()).tools}

    tools = asyncio.run(list_tools())
    assert set(tools) == {"list_pages", "get_page", "save_draft", "create_page", "update_page"}
    assert tools["list_pages"].annotations.readOnlyHint
    assert tools["update_page"].annotations.destructiveHint  # can make a page live
    assert not tools["save_draft"].annotations.destructiveHint  # never touches live pages
    assert "ctx" not in tools["create_page"].inputSchema["properties"]


SECTIONS = [
    {"heading": "Bread worth the wait", "body": "Naturally leavened.\n\nBaked **daily**."},
    {"heading": "Visit us", "body": "Open Tuesday to Sunday on East Cesar Chavez."},
]


def save_draft_args(**overrides) -> dict:
    return {
        "slug": "Home",
        "title": "Home",
        "sections": SECTIONS,
        "button_label": "Pre-order now",
        **overrides,
    }


def test_save_draft_renders_blocks_and_updates_instead_of_duplicating():
    wp = FakeWordPressClient()

    async def scenario():
        async with mcp_wordpress_tools(wp) as tools:
            first = await call_tool(tools["save_draft"], save_draft_args())
            again = await call_tool(tools["save_draft"], save_draft_args(title="Welcome"))
            return first, again

    first, again = asyncio.run(scenario())
    assert (first["action"], first["slug"], first["status"]) == ("created", "home", "draft")
    assert (again["action"], again["id"]) == ("updated", first["id"])
    assert len(wp.pages) == 1
    page = wp.pages[first["id"]]
    assert page["title"] == "Welcome"
    assert '<h2 class="wp-block-heading">Bread worth the wait</h2>' in page["content"]
    assert "<p>Baked <strong>daily</strong>.</p>" in page["content"]
    assert "Pre-order now</a>" in page["content"]


def test_save_draft_never_touches_a_live_page():
    live = {"id": 7, "slug": "home", "status": "publish", "title": "Home", "content": "live"}
    wp = FakeWordPressClient([live])

    async def scenario():
        async with mcp_wordpress_tools(wp) as tools:
            return await call_tool(tools["save_draft"], save_draft_args())

    result = asyncio.run(scenario())
    assert (result["action"], result["id"]) == ("skipped", 7)
    assert "live" in result["reason"]
    assert wp.pages[7]["content"] == "live" and wp.created == []


def test_save_draft_applies_brand_styles():
    wp = FakeWordPressClient()
    brand = {
        "colors": [{"name": "Primary", "hex": "c41"}, {"name": "Text", "hex": "#1F2937"}],
        "fonts": [{"name": "Heading", "family": "Fraunces", "weight": 600}],
    }

    async def scenario():
        async with mcp_wordpress_tools(wp) as tools:
            return await call_tool(tools["save_draft"], save_draft_args(brand=brand))

    content = wp.pages[asyncio.run(scenario())["id"]]["content"]
    assert "background:#cc4411" in content  # short hex expanded
    assert "font-family:'Fraunces',serif;font-weight:600" in content


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"sections": [{"heading": "Hi", "body": "Call [phone] today"}]}, "placeholder"),
        ({"sections": [{"heading": "Hi", "body": "<form>Sign up</form>"}]}, "plain text"),
        ({"button_label": "Click here to book your free tasting session today"}, "2-5 words"),
        (
            {"brand": {"colors": [{"name": "Primary", "hex": "red;}body{display:none"}]}},
            "hex must look like",
        ),
    ],
)
def test_save_draft_rejects_unpublishable_input(overrides, error):
    wp = FakeWordPressClient()

    async def scenario():
        async with mcp_wordpress_tools(wp) as tools:
            with pytest.raises(ToolException, match=error):
                await call_tool(tools["save_draft"], save_draft_args(**overrides))

    asyncio.run(scenario())
    assert wp.pages == {}


def test_missing_credentials_are_explained_by_the_tools():
    """The server still starts, so the agent can tell the user what to configure."""

    def unconfigured():
        raise WordPressError("WP_APP_PASSWORD is not set.")

    async def scenario():
        server = create_server(client_factory=unconfigured)
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool("list_pages", {})

    result = asyncio.run(scenario())
    assert result.isError
    assert "WP_APP_PASSWORD is not set" in result.content[0].text


def test_check_reports_missing_password(capsys):
    assert asyncio.run(check(Settings(_env_file=None))) == 1
    assert "Application Passwords" in capsys.readouterr().err


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
