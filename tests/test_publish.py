import asyncio

from firstcut.graph import Deps, build_graph
from firstcut.tools import wordpress_tools
from tests.fakes import FakeWordPressClient, ScriptedChatModel, lazy_publisher, site_responder

SLUGS = {"home", "workshops", "contact"}


def run(wp: FakeWordPressClient, **responder_kwargs) -> dict:
    llm = ScriptedChatModel(respond=site_responder(**responder_kwargs))
    deps = Deps(llm=llm, wp_tools=wordpress_tools(wp))
    return asyncio.run(build_graph().ainvoke({"brief": "Masa Bakery"}, context=deps))


def test_agent_saves_every_page_as_a_draft():
    wp = FakeWordPressClient()
    state = run(wp)

    assert set(state["wp_pages"]) == SLUGS
    assert {page["saved_by"] for page in state["wp_pages"].values()} == {"agent"}
    assert all(page["status"] == "draft" for page in wp.pages.values())
    # Content is rendered as Gutenberg blocks by code, not copied by the LLM.
    assert "<!-- wp:heading -->" in wp.pages[state["wp_pages"]["home"]["id"]]["content"]


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
