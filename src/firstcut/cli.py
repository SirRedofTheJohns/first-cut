import json
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from firstcut.config import get_settings
from firstcut.graph import Deps, build_graph
from firstcut.llm import get_chat_model

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
) -> None:
    """Plan and write a site from a brief."""
    settings = get_settings()
    console.print(f"[dim]LLM: {settings.llm_provider}:{settings.llm_model}[/dim]")
    graph = build_graph()
    deps = Deps(llm=get_chat_model(settings), max_revisions=settings.max_revisions)

    state: dict = {}
    started = time.perf_counter()
    # "updates" drives the progress log; "values" keeps the latest full state.
    for mode, chunk in graph.stream(
        {"brief_source": str(brief)}, context=deps, stream_mode=["updates", "values"]
    ):
        if mode == "values":
            state = chunk
            continue
        for node, update in chunk.items():
            detail = ", ".join(f"/{slug}" for slug in (update or {}).get("pages", {}))
            console.print(f"[green]✓[/green] {node} {detail}")
    elapsed = time.perf_counter() - started
    _print_result(state, elapsed)

    if out:
        payload = {
            "sitemap": state["sitemap"].model_dump(),
            "pages": [page.model_dump() for page in state["pages"].values()],
            "review": state["review"].model_dump(),
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"Saved to {out}")


def _print_result(state: dict, elapsed: float) -> None:
    sitemap = state["sitemap"]
    console.rule(f"[bold]{sitemap.site_name}[/bold] — {sitemap.tagline}")
    console.print(f"Audience: {sitemap.audience}\nTone: {sitemap.tone}\n")

    table = Table("Page", "Slug", "Sections", "CTA")
    for spec in sitemap.pages:
        page = state["pages"][spec.slug]
        table.add_row(spec.title, f"/{spec.slug}", str(len(page.sections)), page.call_to_action)
    console.print(table)

    review = state["review"]
    verdict = "[green]approved[/green]" if review.approved else "[yellow]open issues[/yellow]"
    console.print(f"Review: {verdict} after {state['revision']} round(s)")
    for issue in review.issues:
        console.print(f"  • /{issue.slug}: {issue.problem}")
    console.print(f"[dim]Done in {elapsed:.1f}s[/dim]")
