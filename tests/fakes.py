"""Deterministic stand-ins for LLMs.

Writers run in parallel, so a fake that replays a fixed list of responses would hand them
out in a nondeterministic order. These fakes decide what to answer from the prompt instead.
"""

import json
import threading
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from firstcut.graph.prompts import PLANNER_SYSTEM, REVIEWER_SYSTEM, WRITER_SYSTEM


class ScriptedChatModel(BaseChatModel):
    """Answers each call with `respond(messages)`. Has no native structured output."""

    respond: Callable[[list[BaseMessage]], str]
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        with self._lock:
            self._calls.append(list(messages))
        reply = AIMessage(content=self.respond(list(messages)))
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
        "call_to_action": "Pre-order now",
    }


def site_responder(reviews: list[dict] | None = None) -> Callable[[list[BaseMessage]], str]:
    """Routes by system prompt. `reviews` are returned in order, then 'approved' forever."""
    pending_reviews = list(reviews or [])

    def respond(messages: list[BaseMessage]) -> str:
        system = messages[0].content
        if system == PLANNER_SYSTEM.format(max_pages=6):
            return json.dumps(SITEMAP)
        if system == WRITER_SYSTEM:
            revision = "This is a revision" in messages[1].content
            return json.dumps(page_copy("Revised" if revision else "Hello"))
        if system == REVIEWER_SYSTEM:
            review = pending_reviews.pop(0) if pending_reviews else {"approved": True, "issues": []}
            return json.dumps(review)
        raise AssertionError(f"unexpected prompt: {system[:60]}")

    return respond


def calls_with(llm: ScriptedChatModel, system_prompt: str) -> list[list[BaseMessage]]:
    return [call for call in llm.calls if call[0].content == system_prompt]
