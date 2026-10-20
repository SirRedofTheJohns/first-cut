"""Publishing step: a small tool-calling agent saves the drafts to WordPress, then plain code
checks the result.

The LLM never copies page HTML into tool arguments (slow and error-prone for small models).
It works with slugs and page ids, and `save_draft` injects the rendered content itself.
"""

import contextlib
import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, ToolException, tool
from langgraph.errors import GraphRecursionError
from langgraph.runtime import Runtime

from firstcut.graph.prompts import PUBLISHER_SYSTEM
from firstcut.graph.state import Deps, SiteState
from firstcut.render import render_blocks
from firstcut.schemas import PageDraft


async def publish_drafts(state: SiteState, runtime: Runtime[Deps]) -> SiteState:
    wp = runtime.context.wp_tools
    drafts = state["pages"]
    existing = {page["slug"]: page for page in await call_tool(wp["list_pages"], {})}
    saved: dict[str, dict[str, Any]] = {}
    save_draft = _save_draft_tool(wp, drafts, existing, saved)

    agent = create_agent(
        runtime.context.llm, [wp["list_pages"], save_draft], system_prompt=PUBLISHER_SYSTEM
    )
    request = f"Save these drafts to WordPress: {', '.join(drafts)}"
    # If the agent loops, the verification below completes whatever it left unfinished.
    with contextlib.suppress(GraphRecursionError):
        await agent.ainvoke(
            {"messages": [HumanMessage(request)]}, {"recursion_limit": 4 * len(drafts) + 10}
        )

    # Verification: every draft must exist in WordPress, whatever the agent did.
    by_agent = set(saved)
    for slug in drafts.keys() - saved.keys():
        await call_tool(save_draft, {"slug": slug})
    for slug, page in saved.items():
        page["saved_by"] = "agent" if slug in by_agent else "verification"
    return {"wp_pages": saved}


def _save_draft_tool(
    wp: dict[str, BaseTool],
    drafts: dict[str, PageDraft],
    existing: dict[str, dict[str, Any]],
    saved: dict[str, dict[str, Any]],
):
    @tool
    async def save_draft(slug: str, page_id: int | None = None) -> str:
        """Save the generated draft for `slug` to WordPress as a draft page.

        Pass `page_id` when a page with this slug already exists, so it is updated instead of
        duplicated. Omit it to create a new page.
        """
        if slug not in drafts:
            return f"Error: unknown slug {slug!r}. Valid slugs: {', '.join(drafts)}"
        # The model decides what to call; these checks keep its mistakes harmless.
        known = saved.get(slug) or existing.get(slug)
        if page_id is not None and (known is None or known["id"] != page_id):
            hint = "Omit page_id to create it." if known is None else f"Use page_id {known['id']}."
            return f"Error: page {page_id} is not the page for /{slug}. {hint}"
        if known and known["status"] == "publish":
            saved[slug] = known
            return f"Skipped /{slug}: it is live; live pages only change through approval."

        draft = drafts[slug]
        content = render_blocks(draft)
        if known:  # also covers a forgotten page_id or a slug saved twice: no duplicates
            args = {"page_id": known["id"], "title": draft.title, "content": content}
            saved[slug] = await call_tool(wp["update_page"], args)
        else:
            args = {"title": draft.title, "content": content, "slug": slug, "status": "draft"}
            saved[slug] = await call_tool(wp["create_page"], args)
        return json.dumps(saved[slug])

    # A WordPress failure goes back to the model as an error message instead of crashing.
    save_draft.handle_tool_error = True
    return save_draft


async def call_tool(tool: BaseTool, args: dict[str, Any]) -> Any:
    """Call a tool from code (not from the LLM) and return its JSON result as data.

    Errors are returned as messages so an LLM can react to them (MCP adapters do this by
    default); here, code is the caller, so an error becomes an exception again.
    """
    message = await tool.ainvoke(
        {"name": tool.name, "args": args, "id": "direct", "type": "tool_call"}
    )
    if message.status == "error":
        raise ToolException(f"{tool.name} failed: {message.text}")
    return json.loads(message.text)
