from firstcut.graph import Deps, build_graph
from firstcut.graph.prompts import WRITER_SYSTEM
from tests.fakes import ScriptedChatModel, calls_with, site_responder

BRIEF = "Masa Bakery, sourdough in Austin."


def run(llm, max_revisions=2, **state):
    return build_graph().invoke(
        state or {"brief": BRIEF}, context=Deps(llm=llm, max_revisions=max_revisions)
    )


def test_happy_path_writes_every_planned_page():
    llm = ScriptedChatModel(respond=site_responder())
    state = run(llm)

    assert [p.slug for p in state["sitemap"].pages] == ["home", "workshops", "contact"]
    assert set(state["pages"]) == {"home", "workshops", "contact"}
    assert state["pages"]["workshops"].title == "Workshops"
    assert state["review"].approved
    assert state["revision"] == 1


def test_brief_is_loaded_from_file(tmp_path):
    brief_file = tmp_path / "brief.md"
    brief_file.write_text(BRIEF, encoding="utf-8")
    state = run(ScriptedChatModel(respond=site_responder()), brief_source=str(brief_file))
    assert state["brief"] == BRIEF


def test_review_rewrites_only_flagged_pages():
    rejection = {"approved": False, "issues": [{"slug": "contact", "problem": "Missing hours"}]}
    llm = ScriptedChatModel(respond=site_responder(reviews=[rejection]))
    state = run(llm)

    writer_calls = calls_with(llm, WRITER_SYSTEM)
    assert len(writer_calls) == 4  # 3 initial pages + 1 rewrite
    assert "Missing hours" in writer_calls[-1][1].content
    assert state["pages"]["contact"].sections[0].heading == "Revised"
    assert state["pages"]["home"].sections[0].heading == "Hello"
    assert state["revision"] == 2


def test_revision_loop_is_bounded():
    rejection = {"approved": False, "issues": [{"slug": "home", "problem": "Too generic"}]}
    llm = ScriptedChatModel(respond=site_responder(reviews=[rejection] * 10))
    state = run(llm, max_revisions=2)

    assert state["revision"] == 3  # initial review + 2 re-reviews, then stop
    assert len(calls_with(llm, WRITER_SYSTEM)) == 3 + 2
    assert not state["review"].approved


def test_issues_for_unknown_pages_are_ignored():
    hallucinated = {"approved": False, "issues": [{"slug": "blog", "problem": "Add posts"}]}
    llm = ScriptedChatModel(respond=site_responder(reviews=[hallucinated]))
    state = run(llm)

    assert state["review"].issues == []
    assert len(calls_with(llm, WRITER_SYSTEM)) == 3
