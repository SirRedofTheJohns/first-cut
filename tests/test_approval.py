"""Human-in-the-loop: pause at approval, persist, resume (possibly in another process)."""

import asyncio

import pytest
from langgraph.types import Command

from firstcut.checkpoints import sqlite_checkpointer
from firstcut.graph import Deps, build_graph
from firstcut.graph.prompts import WRITER_SYSTEM
from tests.fakes import (
    FakeWordPressClient,
    ScriptedChatModel,
    calls_with,
    mcp_wordpress_tools,
    site_responder,
)

CONFIG = {"configurable": {"thread_id": "masa-1"}}


@pytest.fixture(autouse=True)
def strict_checkpoint_types(monkeypatch):
    """Fail if the state holds a type that isn't on the deserialization allowlist (future
    LangGraph default) instead of just logging a warning."""
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")


async def step(db: str, wp, llm, graph_input) -> tuple[dict, list]:
    """One request's worth of work with a fresh checkpointer, as an API server would do."""
    async with (
        sqlite_checkpointer(db) as saver,
        mcp_wordpress_tools(wp) as tools,
    ):
        graph = build_graph(checkpointer=saver)
        await graph.ainvoke(graph_input, CONFIG, context=Deps(llm=llm, wp_tools=tools))
        snapshot = await graph.aget_state(CONFIG)
        return snapshot.values, snapshot.interrupts


def test_run_pauses_survives_a_restart_and_publishes_on_approval(tmp_path):
    db, wp = str(tmp_path / "checkpoints.sqlite"), FakeWordPressClient()
    llm = ScriptedChatModel(respond=site_responder())

    values, interrupts = asyncio.run(step(db, wp, llm, {"brief": "Masa Bakery"}))
    assert len(interrupts) == 1
    payload = interrupts[0].value
    assert {page["slug"] for page in payload["pages"]} == {"home", "workshops", "contact"}
    assert all(page["status"] == "draft" for page in wp.pages.values())

    # New saver + new graph instance on the same file: state (with Pydantic models) is restored.
    values, interrupts = asyncio.run(step(db, wp, llm, Command(resume={"approved": True})))
    assert not interrupts
    assert values["status"] == "published"
    assert values["sitemap"].site_name == "Masa Bakery"
    assert all(page["status"] == "publish" for page in wp.pages.values())


def test_feedback_rewrites_only_those_pages_and_asks_again(tmp_path):
    db, wp = str(tmp_path / "checkpoints.sqlite"), FakeWordPressClient()
    llm = ScriptedChatModel(respond=site_responder())

    asyncio.run(step(db, wp, llm, {"brief": "Masa Bakery"}))
    decision = {"approved": False, "feedback": {"contact": "Add the opening hours"}}
    values, interrupts = asyncio.run(step(db, wp, llm, Command(resume=decision)))

    rewrites = [
        c for c in calls_with(llm, WRITER_SYSTEM) if "Add the opening hours" in c[1].content
    ]
    assert len(rewrites) == 1
    # The feedback became part of the brief, so the writer may use the new facts.
    assert "## Editor feedback" in rewrites[0][1].content
    assert "- /contact: Add the opening hours" in values["brief"]
    assert values["pages"]["contact"].sections[0].heading == "Revised"
    assert len(interrupts) == 1  # back at the approval step, with the updated drafts
    assert len(wp.pages) == 3  # updated in place, no duplicates
    assert all(page["status"] == "draft" for page in wp.pages.values())


def test_reject_without_feedback_ends_and_keeps_drafts(tmp_path):
    db, wp = str(tmp_path / "checkpoints.sqlite"), FakeWordPressClient()
    llm = ScriptedChatModel(respond=site_responder())

    asyncio.run(step(db, wp, llm, {"brief": "Masa Bakery"}))
    values, interrupts = asyncio.run(step(db, wp, llm, Command(resume={"approved": False})))

    assert not interrupts
    assert values["status"] == "rejected"
    assert all(page["status"] == "draft" for page in wp.pages.values())
