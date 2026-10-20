"""Deterministic stand-ins for LLMs.

Writers run in parallel, so a fake that replays a fixed list of responses would hand them
out in a nondeterministic order. These fakes decide what to answer from the prompt instead.
"""

import json
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import PrivateAttr

from firstcut.graph.prompts import (
    PLANNER_SYSTEM,
    PUBLISHER_SYSTEM,
    REVIEWER_SYSTEM,
    WRITER_SYSTEM,
)
from firstcut.integrations.wordpress import WordPressError
from mcp_server.server import create_server


class ScriptedChatModel(BaseChatModel):
    """Answers each call with `respond(messages)` (text or a full AIMessage with tool calls).

    Accepts tools, but has no native structured output, so `structured_call` uses its
    JSON-prompt fallback with it.
    """

    respond: Callable[[list[BaseMessage]], str | AIMessage]
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        raise NotImplementedError

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        with self._lock:
            self._calls.append(list(messages))
        reply = self.respond(list(messages))
        if isinstance(reply, str):
            reply = AIMessage(content=reply)
        return ChatResult(generations=[ChatGeneration(message=reply)])


SITEMAP = {
    "site_name": "Masa Bakery",
    "tagline": "Sourdough with Monterrey roots",
    "audience": "Austin locals who care about real ingredients",
    "tone": "warm, artisanal, playful",
    "pages": [
        {"slug": "home", "title": "Home", "purpose": "Welcome", "sections": ["Hero", "Menu"]},
        {
            "slug": "Workshops",
            "title": "Workshops",
            "purpose": "Sell seats",
            "sections": ["What", "Book"],
        },
        {
            "slug": "contact",
            "title": "Contact",
            "purpose": "Visit us",
            "sections": ["Hours", "Map"],
        },
    ],
}


def page_copy(heading: str = "Hello") -> dict:
    return {
        "meta_description": "Fresh sourdough in Austin.",
        "sections": [{"heading": heading, "body": "Naturally leavened bread baked daily."}],
        "button_label": "Pre-order now",
    }


def site_responder(
    reviews: list[dict] | None = None, publisher: Callable | None = None
) -> Callable[[list[BaseMessage]], str | AIMessage]:
    """Routes by system prompt. `reviews` are returned in order, then 'approved' forever."""
    pending_reviews = list(reviews or [])
    publisher = publisher or diligent_publisher

    def respond(messages: list[BaseMessage]) -> str | AIMessage:
        system = messages[0].content
        if system == PLANNER_SYSTEM.format(max_pages=6):
            return json.dumps(SITEMAP)
        if system == WRITER_SYSTEM:
            revision = "REVISION REQUEST" in messages[1].content
            return json.dumps(page_copy("Revised" if revision else "Hello"))
        if system == REVIEWER_SYSTEM:
            review = pending_reviews.pop(0) if pending_reviews else {"approved": True, "issues": []}
            return json.dumps(review)
        if system == PUBLISHER_SYSTEM:
            return publisher(messages)
        raise AssertionError(f"unexpected prompt: {system[:60]}")

    return respond


def calls_with(llm: ScriptedChatModel, system_prompt: str) -> list[list[BaseMessage]]:
    return [call for call in llm.calls if call[0].content == system_prompt]


def _call(name: str, args: dict, idx: int) -> dict:
    return {"name": name, "args": args, "id": f"call_{name}_{idx}", "type": "tool_call"}


def diligent_publisher(messages: list[BaseMessage]) -> AIMessage:
    """Lists pages, then saves every requested slug in parallel (reusing ids it saw)."""
    last = messages[-1]
    if isinstance(last, HumanMessage):
        return AIMessage(content="", tool_calls=[_call("list_pages", {}, 0)])
    if isinstance(last, ToolMessage) and last.name == "list_pages":
        existing = {page["slug"]: page["id"] for page in json.loads(last.text)}
        slugs = messages[1].content.split(": ", 1)[1].split(", ")
        calls = [
            _call("save_draft", {"slug": slug, "page_id": existing.get(slug)}, i)
            for i, slug in enumerate(slugs)
        ]
        return AIMessage(content="", tool_calls=calls)
    return AIMessage(content="All drafts saved.")


def lazy_publisher(messages: list[BaseMessage]) -> AIMessage:
    """Claims success without calling any tool."""
    return AIMessage(content="Done!")


class FakeWordPressClient:
    """In-memory stand-in with the same async interface as WordPressClient."""

    def __init__(self, pages: list[dict] | None = None) -> None:
        self.pages = {page["id"]: dict(page) for page in pages or []}
        self.created: list[int] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        pass

    async def list_pages(self, search=None):
        return [_without_content(page) for page in self.pages.values()]

    async def get_page(self, page_id):
        if page_id not in self.pages:
            raise WordPressError(f"GET pages/{page_id} -> 404: Invalid post ID.")
        return dict(self.pages[page_id])

    async def create_page(self, title, content, slug=None, status="draft"):
        page_id = max(self.pages, default=100) + 1
        self.pages[page_id] = {
            "id": page_id,
            "slug": slug,
            "status": status,
            "title": title,
            "link": f"http://wp.test/?page_id={page_id}",
            "content": content,
        }
        self.created.append(page_id)
        return _without_content(self.pages[page_id])

    async def update_page(self, page_id, title=None, content=None, status=None):
        page = self.pages[page_id]
        page.update(
            {k: v for k, v in [("title", title), ("content", content), ("status", status)] if v}
        )
        return _without_content(page)


def _without_content(page: dict) -> dict:
    return {key: value for key, value in page.items() if key != "content"}


@asynccontextmanager
async def mcp_wordpress_tools(wp: FakeWordPressClient):
    """The agent's tools exactly as in production (MCP server -> MCP protocol ->
    langchain-mcp-adapters), but over in-memory streams instead of stdio or HTTP."""
    server = create_server(client_factory=lambda: wp)
    async with create_connected_server_and_client_session(server) as session:
        yield {tool.name: tool for tool in await load_mcp_tools(session)}
