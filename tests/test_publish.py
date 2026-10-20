import asyncio
import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from firstcut.graph import Deps, build_graph
from tests.fakes import (
    FakeWordPressClient,
    ScriptedChatModel,
    lazy_publisher,
    mcp_wordpress_tools,
    site_responder,
)

SLUGS = {"home", "workshops", "contact"}


def run(wp: FakeWordPressClient, **responder_kwargs) -> dict:
    """Runs the graph up to the approval pause; WordPress tools go through a real (in-memory)
    MCP session."""
    llm = ScriptedChatModel(respond=site_responder(**responder_kwargs))

    async def go():
        async with mcp_wordpress_tools(wp) as tools:
            graph = build_graph(checkpointer=InMemorySaver())
            return await graph.ainvoke(
                {"brief": "Masa Bakery"},
                {"configurable": {"thread_id": "t"}},
                context=Deps(llm=llm, wp_tools=tools),
            )

    return asyncio.run(go())


def test_agent_saves_every_page_as_a_draft():
    wp = FakeWordPressClient()
    state = run(wp)

    assert set(state["wp_pages"]) == SLUGS
    assert {page["saved_by"] for page in state["wp_pages"].values()} == {"agent"}
    assert all(page["status"] == "draft" for page in wp.pages.values())
    # Content is rendered as Gutenberg blocks by code, not copied by the LLM.
    assert "<!-- wp:heading -->" in wp.pages[state["wp_pages"]["home"]["id"]]["content"]
    # The run then pauses for a human.
    assert "__interrupt__" in state


def test_verification_saves_what_a_lazy_agent_skipped():
    wp = FakeWordPressClient()
    state = run(wp, publisher=lazy_publisher)

    assert set(state["wp_pages"]) == SLUGS
    assert {page["saved_by"] for page in state["wp_pages"].values()} == {"verification"}


def test_existing_draft_is_updated_not_duplicated():
    wp = FakeWordPressClient([{"id": 7, "slug": "home", "status": "draft", "title": "Old"}])
    state = run(wp, publisher=lazy_publisher)  # even without the agent passing page_id

    assert state["wp_pages"]["home"]["id"] == 7
    assert wp.pages[7]["title"] == "Home"
    assert len(wp.created) == 2


def test_live_page_is_never_overwritten():
    live = {"id": 9, "slug": "contact", "status": "publish", "title": "Live", "content": "live"}
    wp = FakeWordPressClient([live])
    state = run(wp)

    assert wp.pages[9]["content"] == "live"
    assert state["wp_pages"]["contact"]["status"] == "publish"


def test_preview_mode_never_touches_wordpress():
    llm = ScriptedChatModel(respond=site_responder())
    state = build_graph().invoke({"brief": "Masa Bakery"}, context=Deps(llm=llm))
    assert "wp_pages" not in state


class FixtureFigma:
    def get_file(self, key, refresh=False):
        assert key == "9z5IYb5tdxSrHHd3XJGWoz"
        path = Path(__file__).parent / "fixtures" / "figma_masa_brand.json"
        return json.loads(path.read_text(encoding="utf-8"))


def test_figma_brand_is_applied_to_every_draft():
    wp = FakeWordPressClient()
    llm = ScriptedChatModel(respond=site_responder())

    async def go():
        async with mcp_wordpress_tools(wp) as tools:
            graph = build_graph(checkpointer=InMemorySaver())
            return await graph.ainvoke(
                {
                    "brief": "Masa Bakery",
                    "figma_url": "https://www.figma.com/design/9z5IYb5tdxSrHHd3XJGWoz/Brand",
                },
                {"configurable": {"thread_id": "t"}},
                context=Deps(llm=llm, wp_tools=tools, figma=FixtureFigma()),
            )

    state = asyncio.run(go())
    assert state["style_guide"].colors[0].hex == "#C2410C"
    assert all("background:#C2410C" in page["content"] for page in wp.pages.values())
