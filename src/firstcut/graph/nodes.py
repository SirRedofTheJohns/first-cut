from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Send

from firstcut.graph.prompts import PLANNER_SYSTEM, REVIEWER_SYSTEM, WRITER_SYSTEM, site_context
from firstcut.graph.state import Deps, SiteState, WriteTask
from firstcut.schemas import MAX_PAGES, PageCopy, PageDraft, ReviewResult, SiteMap
from firstcut.structured import structured_call


def load_brief(state: SiteState) -> SiteState:
    if state.get("brief"):
        return {}
    return {"brief": Path(state["brief_source"]).read_text(encoding="utf-8")}


def plan_sitemap(state: SiteState, runtime: Runtime[Deps]) -> SiteState:
    sitemap = structured_call(
        runtime.context.llm,
        SiteMap,
        [
            SystemMessage(PLANNER_SYSTEM.format(max_pages=MAX_PAGES)),
            HumanMessage(f"Client brief:\n\n{state['brief']}"),
        ],
    )
    return {"sitemap": sitemap}


def fan_out_writers(state: SiteState) -> list[Send]:
    return [
        Send(
            "write_page",
            WriteTask(
                brief=state["brief"],
                sitemap=state["sitemap"],
                spec=spec,
                feedback=None,
                previous=None,
            ),
        )
        for spec in state["sitemap"].pages
    ]


def write_page(task: WriteTask, runtime: Runtime[Deps]) -> SiteState:
    spec = task["spec"]
    request = (
        f"Client brief:\n\n{task['brief']}\n\n{site_context(task['sitemap'])}\n\n"
        f"Write the page '{spec.title}' (/{spec.slug}).\nPurpose: {spec.purpose}\n"
        f"Sections, in order: {', '.join(spec.sections)}"
    )
    if task["previous"] and task["feedback"]:
        request += (
            f"\n\nThis is a revision. Previous version:\n{task['previous'].model_dump_json()}\n"
            f"Fix this problem raised by the reviewer: {task['feedback']}"
        )
    copy = structured_call(
        runtime.context.llm, PageCopy, [SystemMessage(WRITER_SYSTEM), HumanMessage(request)]
    )
    draft = PageDraft(slug=spec.slug, title=spec.title, **copy.model_dump())
    return {"pages": {spec.slug: draft}}


def review(state: SiteState, runtime: Runtime[Deps]) -> SiteState:
    pages = "\n\n".join(page.model_dump_json() for page in state["pages"].values())
    result = structured_call(
        runtime.context.llm,
        ReviewResult,
        [
            SystemMessage(REVIEWER_SYSTEM),
            HumanMessage(
                f"Client brief:\n\n{state['brief']}\n\n{site_context(state['sitemap'])}\n\n"
                f"Page copy (JSON, one page per block):\n\n{pages}"
            ),
        ],
    )
    # Small models sometimes flag pages that don't exist; ignore those.
    result.issues = [issue for issue in result.issues if issue.slug in state["pages"]]
    return {"review": result, "revision": state.get("revision", 0) + 1}


def route_after_review(state: SiteState, runtime: Runtime[Deps]) -> list[Send] | str:
    result = state["review"]
    if result.approved or not result.issues or state["revision"] > runtime.context.max_revisions:
        return END

    feedback: dict[str, list[str]] = {}
    for issue in result.issues:
        feedback.setdefault(issue.slug, []).append(issue.problem)
    specs = {spec.slug: spec for spec in state["sitemap"].pages}
    return [
        Send(
            "write_page",
            WriteTask(
                brief=state["brief"],
                sitemap=state["sitemap"],
                spec=specs[slug],
                feedback="; ".join(problems),
                previous=state["pages"][slug],
            ),
        )
        for slug, problems in feedback.items()
    ]
