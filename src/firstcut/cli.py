import asyncio
import json
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Annotated

import typer
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from rich.console import Console
from rich.table import Table

from firstcut.checkpoints import serializer
from firstcut.config import get_settings
from firstcut.graph import Deps, build_graph
from firstcut.integrations.factory import figma_client, gdocs_client
from firstcut.integrations.gdocs import is_google_doc
from firstcut.llm import get_chat_model
from firstcut.mcp_client import wordpress_tools

app = typer.Typer(help="First Cut: brief in, reviewed site draft out.", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Keeps `run` as an explicit subcommand (more commands arrive in later phases)."""


@app.command()
def run(
    brief: Annotated[str, typer.Argument(help="Markdown brief file or Google Doc URL.")],
    figma: Annotated[
        str | None, typer.Option(help="Figma file URL with the brand's color and text styles.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="Write the final sitemap and pages as JSON here.")
    ] = None,
    preview: Annotated[
        bool, typer.Option("--preview", help="Generate only; don't save drafts to WordPress.")
    ] = False,
) -> None:
    """Plan and write a site from a brief, then save it to WordPress as drafts."""
    if not is_google_doc(brief) and not Path(brief).is_file():
        raise typer.BadParameter(f"{brief!r} is neither a file nor a Google Doc URL")
    state = asyncio.run(_run(brief, figma, preview))
    if out:
        payload = {
            "sitemap": state["sitemap"].model_dump(),
            "pages": [page.model_dump() for page in state["pages"].values()],
            "review": state["review"].model_dump(),
            "style_guide": state["style_guide"].model_dump() if "style_guide" in state else None,
            "wp_pages": state.get("wp_pages", {}),
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"Saved to {out}")


async def _run(brief: str, figma: str | None, preview: bool) -> dict:
    settings = get_settings()
    console.print(f"[dim]LLM: {settings.llm_provider}:{settings.llm_model}[/dim]")
    async with AsyncExitStack() as stack:
        wp_tools = None
        if not preview:
            wp_tools = await stack.enter_async_context(wordpress_tools(settings))
        deps = Deps(
            llm=get_chat_model(settings),
            max_revisions=settings.max_revisions,
            wp_tools=wp_tools,
            figma=figma_client(settings),
            gdocs=gdocs_client(settings),
        )

        graph = build_graph(checkpointer=InMemorySaver(serde=serializer()))
        config = {"configurable": {"thread_id": "cli"}}
        graph_input: dict | Command = {"brief_source": brief}
        if figma:
            graph_input["figma_url"] = figma
        state: dict = {}
        started = time.perf_counter()
        while True:
            # "updates" drives the progress log; "values" keeps the latest full state.
            async for mode, chunk in graph.astream(
                graph_input, config, context=deps, stream_mode=["updates", "values"]
            ):
                if mode == "values":
                    state = chunk
                    continue
                for node, update in chunk.items():
                    if isinstance(update, dict):
                        detail = ", ".join(f"/{slug}" for slug in update.get("pages", {}))
                        console.print(f"[green]✓[/green] {node} {detail}")
            interrupts = (await graph.aget_state(config)).interrupts
            if not interrupts:
                break
            _print_result(state, time.perf_counter() - started)
            graph_input = Command(resume=_ask_approval(interrupts[0].value))
        _print_result(state, time.perf_counter() - started)
    return state


def _ask_approval(request: dict) -> dict:
    console.rule("[bold]Human approval[/bold]")
    for page in request["pages"]:
        console.print(f"  /{page['slug']}: {page['link']}")
    if typer.confirm("Publish these pages?", default=False):
        return {"approved": True}
    console.print("Feedback as 'slug: change', one per line. Empty line to finish.")
    feedback = {}
    while line := typer.prompt("", default="", show_default=False).strip():
        slug, _, text = line.partition(":")
        feedback[slug.strip().lstrip("/")] = text.strip()
    return {"approved": False, "feedback": feedback}


def _print_result(state: dict, elapsed: float) -> None:
    sitemap = state["sitemap"]
    wp_pages = state.get("wp_pages", {})
    console.rule(f"[bold]{sitemap.site_name}[/bold] — {sitemap.tagline}")
    console.print(f"Audience: {sitemap.audience}\nTone: {sitemap.tone}")
    if guide := state.get("style_guide"):
        colors = ", ".join(f"{c.name} {c.hex}" for c in guide.colors)
        fonts = ", ".join(f"{t.name} {t.family} {t.weight}" for t in guide.typography)
        console.print(f"Brand ({guide.source}): {colors} | {fonts}")
    console.print()

    table = Table("Page", "Sections", "CTA", "WordPress")
    for spec in sitemap.pages:
        page = state["pages"][spec.slug]
        wp = wp_pages.get(spec.slug)
        wp_cell = f"#{wp['id']} {wp['status']} (by {wp['saved_by']})" if wp else "—"
        table.add_row(
            f"{spec.title} /{spec.slug}", str(len(page.sections)), page.button_label, wp_cell
        )
    console.print(table)

    if status := state.get("status"):
        console.print(f"Status: [bold]{status}[/bold]")
    review = state["review"]
    verdict = "[green]approved[/green]" if review.approved else "[yellow]open issues[/yellow]"
    console.print(f"Review: {verdict} after {state['revision']} round(s)")
    for issue in review.issues:
        console.print(f"  • /{issue.slug}: {issue.problem}")
    console.print(f"[dim]Done in {elapsed:.1f}s[/dim]")
