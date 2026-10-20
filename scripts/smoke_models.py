"""Compare local Ollama models on the three capabilities this agent depends on.

    uv run python scripts/smoke_models.py [model ...] [--reps 3]

1. Structured output: a valid SiteMap on the first try (no repair loop).
2. Single tool call: exactly one well-formed `create_page` call.
3. Parallel tool calls: one `create_page` call per requested page, in a single turn.
"""

import argparse
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from rich.console import Console
from rich.table import Table

from firstcut.graph.prompts import PLANNER_SYSTEM
from firstcut.schemas import MAX_PAGES, SiteMap

DEFAULT_MODELS = ["qwen3.5:9b", "hf.co/Qwen/Qwen3-8B-GGUF:Q8_0", "gemma4:12b"]
BRIEF = Path(__file__).parents[1].joinpath("briefs", "masa-bakery.md").read_text(encoding="utf-8")


@tool
def create_page(title: str, content: str, status: str = "draft") -> str:
    """Create a WordPress page. `content` is HTML. `status` is 'draft' or 'publish'."""
    return "ok"


def check_structured(llm: ChatOllama) -> bool:
    result = llm.with_structured_output(SiteMap, include_raw=True).invoke(
        [
            SystemMessage(PLANNER_SYSTEM.format(max_pages=MAX_PAGES)),
            HumanMessage(f"Client brief:\n\n{BRIEF}"),
        ]
    )
    return result["parsed"] is not None


def check_single_tool(llm: ChatOllama) -> bool:
    reply = llm.bind_tools([create_page]).invoke(
        "Create a draft page titled 'About Us' with one short HTML paragraph about Masa Bakery."
    )
    calls = reply.tool_calls
    return (
        len(calls) == 1
        and calls[0]["name"] == "create_page"
        and "about" in calls[0]["args"].get("title", "").lower()
    )


def check_parallel_tools(llm: ChatOllama) -> bool:
    reply = llm.bind_tools([create_page]).invoke(
        "Create three draft pages for Masa Bakery: 'Home', 'Menu' and 'Contact'. "
        "Each needs one short HTML paragraph. Call the tool once per page."
    )
    titles = {call["args"].get("title", "").lower() for call in reply.tool_calls}
    return titles == {"home", "menu", "contact"}


CHECKS = {
    "structured": check_structured,
    "1 tool": check_single_tool,
    "3 tools": check_parallel_tools,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*", default=DEFAULT_MODELS)
    parser.add_argument("--reps", type=int, default=3)
    args = parser.parse_args()

    console = Console()
    table = Table("Model", *(f"{name} (ok / avg s)" for name in CHECKS))
    for model in args.models:
        llm = ChatOllama(model=model, temperature=0.3, reasoning=False)
        llm.invoke("hi")  # load weights into VRAM so it doesn't skew the first timing
        row = [model]
        for name, check in CHECKS.items():
            passed, elapsed = 0, 0.0
            for _ in range(args.reps):
                started = time.perf_counter()
                try:
                    passed += check(llm)
                except Exception as exc:  # a crash counts as a failure, but keep going
                    console.print(f"[red]{model} {name}: {exc}[/red]")
                elapsed += time.perf_counter() - started
            row.append(f"{passed}/{args.reps}, {elapsed / args.reps:.1f}s")
            console.print(f"{model} {name}: {row[-1]}")
        table.add_row(*row)
    console.print(table)


if __name__ == "__main__":
    main()
