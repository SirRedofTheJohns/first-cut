from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command, Send, interrupt

from firstcut.graph.prompts import PLANNER_SYSTEM, REVIEWER_SYSTEM, WRITER_SYSTEM, site_context
from firstcut.graph.state import Deps, SiteState, WriteTask
from firstcut.integrations.figma import extract_style_guide, file_key
from firstcut.integrations.gdocs import is_google_doc
from firstcut.schemas import (
    MAX_PAGES,
    ApprovalDecision,
    PageCopy,
    PageDraft,
    ReviewResult,
    SiteMap,
)
from firstcut.structured import structured_call


def _structured[T](runtime: Runtime[Deps], schema: type[T], messages) -> T:
    return structured_call(
        runtime.context.llm, schema, messages, fallback=runtime.context.fallback_llm
    )


def load_brief(state: SiteState, runtime: Runtime[Deps]) -> SiteState:
    if state.get("brief"):
        return {}
    source = state["brief_source"]
    if is_google_doc(source):
        if runtime.context.gdocs is None:
            raise ValueError("A Google Doc brief needs GOOGLE_APPLICATION_CREDENTIALS")
        return {"brief": runtime.context.gdocs.read_markdown(source)}
    return {"brief": Path(source).read_text(encoding="utf-8")}


def load_style_guide(state: SiteState, runtime: Runtime[Deps]) -> SiteState:
    """Optional: read brand colors and typography from the client's Figma file."""
    if state.get("style_guide") or not state.get("figma_url"):
        return {}
    if runtime.context.figma is None:
        raise ValueError("A Figma URL needs FIGMA_TOKEN")
    figma_file = runtime.context.figma.get_file(file_key(state["figma_url"]))
    return {"style_guide": extract_style_guide(figma_file)}


def plan_sitemap(state: SiteState, runtime: Runtime[Deps]) -> SiteState:
    sitemap = _structured(
        runtime,
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
    if task["feedback"]:
        # Revisions are rewritten from the brief, without the previous draft: shown its own
        # JSON, an 8B model copied it back unchanged (0/4 requests applied, 4/4 without it).
        # The request goes first, overrides the plan, and is repeated last for emphasis.
        request = (
            f"REVISION REQUEST (overrides the planned sections): {task['feedback']}\n\n"
            f"{request}\n\nMake every point of the revision request clearly visible in the "
            f"copy; add or rename a section if needed. Revision request: {task['feedback']}"
        )
    copy = _structured(runtime, PageCopy, [SystemMessage(WRITER_SYSTEM), HumanMessage(request)])
    draft = PageDraft(slug=spec.slug, title=spec.title, **copy.model_dump())
    return {"pages": {spec.slug: draft}}


def review(state: SiteState, runtime: Runtime[Deps]) -> SiteState:
    pages = "\n\n".join(page.model_dump_json() for page in state["pages"].values())
    result = _structured(
        runtime,
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
        return "publish_drafts" if runtime.context.wp_tools else END

    feedback: dict[str, list[str]] = {}
    for issue in result.issues:
        feedback.setdefault(issue.slug, []).append(issue.problem)
    return _rewrites(state, {slug: "; ".join(problems) for slug, problems in feedback.items()})


def human_approval(
    state: SiteState,
) -> Command[Literal["finalize", "write_page", "__end__"]]:
    """Pause until a human approves, asks for changes, or rejects.

    `interrupt` saves the run in the checkpointer and returns the payload to the caller.
    Resuming with `Command(resume=decision)` re-runs this node from the top, so nothing
    before `interrupt` may have side effects.
    """
    decision = ApprovalDecision.model_validate(
        interrupt(
            {
                "question": "Publish these drafts? Approve, or reject with feedback per page.",
                "pages": [
                    {key: page.get(key) for key in ("id", "title", "status", "link")}
                    | {"slug": slug}
                    for slug, page in state["wp_pages"].items()
                ],
                "open_issues": [issue.model_dump() for issue in state["review"].issues],
            }
        )
    )
    if decision.approved:
        return Command(goto="finalize", update={"approval": decision})
    feedback = {slug: text for slug, text in decision.feedback.items() if slug in state["pages"]}
    if not feedback:
        return Command(goto=END, update={"approval": decision, "status": "rejected"})
    # Human feedback joins the brief: it may add facts (e.g. "pre-orders close Thursday"),
    # and the writer and reviewer only trust facts in the brief.
    notes = "\n".join(f"- /{slug}: {text}" for slug, text in feedback.items())
    brief = f"{state['brief']}\n\n## Editor feedback (authoritative)\n{notes}"
    return Command(
        goto=_rewrites(state, feedback, brief=brief),
        # Fresh review budget: the reviewer now also checks the editor's requests.
        update={"approval": decision, "brief": brief, "revision": 0},
    )


def _rewrites(state: SiteState, feedback: dict[str, str], brief: str | None = None) -> list[Send]:
    specs = {spec.slug: spec for spec in state["sitemap"].pages}
    return [
        Send(
            "write_page",
            WriteTask(
                brief=brief or state["brief"],
                sitemap=state["sitemap"],
                spec=specs[slug],
                feedback=text,
            ),
        )
        for slug, text in feedback.items()
    ]
