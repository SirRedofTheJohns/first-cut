from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from firstcut.integrations.figma import FigmaClient
from firstcut.integrations.gdocs import GoogleDocsClient
from firstcut.schemas import (
    MAX_PAGES,
    ApprovalDecision,
    PageDraft,
    PageSpec,
    ReviewResult,
    SiteMap,
    StyleGuide,
)


def merge_pages(left: dict[str, PageDraft], right: dict[str, PageDraft]) -> dict[str, PageDraft]:
    """Reducer: parallel writers each return one page; merge them instead of overwriting."""
    return {**(left or {}), **(right or {})}


class SiteState(TypedDict, total=False):
    brief_source: str  # markdown file path or Google Doc URL
    brief: str
    figma_url: str
    style_guide: StyleGuide
    sitemap: SiteMap
    pages: Annotated[dict[str, PageDraft], merge_pages]
    review: ReviewResult
    revision: int
    wp_pages: dict[str, dict[str, Any]]
    approval: ApprovalDecision
    status: Literal["published", "rejected"]


class WriteTask(TypedDict):
    """Private input for one `write_page` run, sent via `Send` (not part of the graph state)."""

    brief: str
    sitemap: SiteMap
    spec: PageSpec
    feedback: str | None


@dataclass
class Deps:
    """Run-scoped dependencies, injected via LangGraph's runtime context so tests can swap them."""

    llm: BaseChatModel
    fallback_llm: BaseChatModel | None = None
    max_revisions: int = 2
    # Fewer pages = fewer LLM calls (the ZeroGPU demo has a few minutes of GPU per visitor).
    max_pages: int = MAX_PAGES
    # None = preview mode: the graph stops after review and never touches WordPress.
    wp_tools: dict[str, BaseTool] | None = None
    figma: FigmaClient | None = None
    gdocs: GoogleDocsClient | None = None
