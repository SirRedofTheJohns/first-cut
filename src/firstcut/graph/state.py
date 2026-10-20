from dataclasses import dataclass
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel

from firstcut.schemas import PageDraft, PageSpec, ReviewResult, SiteMap


def merge_pages(left: dict[str, PageDraft], right: dict[str, PageDraft]) -> dict[str, PageDraft]:
    """Reducer: parallel writers each return one page; merge them instead of overwriting."""
    return {**(left or {}), **(right or {})}


class SiteState(TypedDict, total=False):
    brief_source: str
    brief: str
    sitemap: SiteMap
    pages: Annotated[dict[str, PageDraft], merge_pages]
    review: ReviewResult
    revision: int


class WriteTask(TypedDict):
    """Private input for one `write_page` run, sent via `Send` (not part of the graph state)."""

    brief: str
    sitemap: SiteMap
    spec: PageSpec
    feedback: str | None
    previous: PageDraft | None


@dataclass
class Deps:
    """Run-scoped dependencies, injected via LangGraph's runtime context so tests can swap them."""

    llm: BaseChatModel
    max_revisions: int = 2
