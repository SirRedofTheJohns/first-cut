import asyncio
import json
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from firstcut.config import get_settings
from firstcut.graph import Deps, build_graph
from firstcut.llm import get_chat_model
from firstcut.mcp_client import wordpress_tools

app = typer.Typer(help="First Cut: brief in, reviewed site draft out.", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Keeps `run` as an explicit subcommand (more commands arrive in later phases)."""


@app.command()
def run(
    brief: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="Markdown brief file.")
    ],
    out: Annotated[
        Path | None, typer.Option(help="Write the final sitemap and pages as JSON here.")
    ] = None,
    preview: Annotated[
        bool, typer.Option("--preview", help="Generate only; don't save drafts to WordPress.")
    ] = False,
) -> None:
    """Plan and write a site from a brief, then save it to WordPress as drafts."""
    state = asyncio.run(_run(brief, preview))
    if out:
        payload = {
            "sitemap": state["sitemap"].model_dump(),
            "pages": [page.model_dump() for page in state["pages"].values()],
            "review": state["review"].model_dump(),
            "wp_pages": state.get("wp_pages", {}),
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"Saved to {out}")


async def _run(brief: Path, preview: bool) -> dict:
    settings = get_settings()
    console.print(f"[dim]LLM: {settings.llm_provider}:{settings.llm_model}[/dim]")
    async with AsyncExitStack() as stack:
        wp_tools = None
        if not preview:
            wp_tools = await stack.enter_async_context(wordpress_tools(settings))
        deps = Deps(
            llm=get_chat_model(settings), max_revisions=settings.max_revisions, wp_tools=wp_tools
        )

        state: dict = {}
        started = time.perf_counter()
        # "updates" drives the progress log; "values" keeps the latest full state.
        async for mode, chunk in build_graph().astream(
            {"brief_source": str(brief)}, context=deps, stream_mode=["updates", "values"]
        ):
            if mode == "values":
                state = chunk
                continue
            for node, update in chunk.items():
                detail = ", ".join(f"/{slug}" for slug in (update or {}).get("pages", {}))
                console.print(f"[green]✓[/green] {node} {detail}")
        _print_result(state, time.perf_counter() - started)
    return state


def _print_result(state: dict, elapsed: float) -> None:
    sitemap = state["sitemap"]
    wp_pages = state.get("wp_pages", {})
    console.rule(f"[bold]{sitemap.site_name}[/bold] — {sitemap.tagline}")
    console.print(f"Audience: {sitemap.audience}\nTone: {sitemap.tone}\n")

    table = Table("Page", "Sections", "CTA", "WordPress")
    for spec in sitemap.pages:
        page = state["pages"][spec.slug]
        wp = wp_pages.get(spec.slug)
        wp_cell = f"#{wp['id']} {wp['status']} (by {wp['saved_by']})" if wp else "—"
        table.add_row(
            f"{spec.title} /{spec.slug}", str(len(page.sections)), page.button_label, wp_cell
        )
    console.print(table)

    review = state["review"]
    verdict = "[green]approved[/green]" if review.approved else "[yellow]open issues[/yellow]"
    console.print(f"Review: {verdict} after {state['revision']} round(s)")
    for issue in review.issues:
        console.print(f"  • /{issue.slug}: {issue.problem}")
    console.print(f"[dim]Done in {elapsed:.1f}s[/dim]")
