"""Domain models shared by the agent, the API and the MCP server.

Field descriptions double as instructions for the LLM: they are sent as part of the
JSON schema when a model is asked for structured output.
"""

import re

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_PAGES = 6


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "page"


class PageSpec(BaseModel):
    slug: str = Field(
        description="URL slug in kebab-case, e.g. 'about-us'. Use 'home' for the homepage."
    )
    title: str = Field(description="Page title shown in navigation.")
    purpose: str = Field(description="One sentence: what this page must achieve for the visitor.")
    sections: list[str] = Field(
        min_length=2,
        max_length=6,
        description="Ordered topics this page covers, e.g. 'Founders story', 'Weekend "
        "pre-orders'. Content topics, not layout names like 'Hero section'.",
    )

    @field_validator("slug")
    @classmethod
    def _normalize_slug(cls, value: str) -> str:
        return slugify(value)


class SiteMap(BaseModel):
    site_name: str = Field(description="The client's business or brand name.")
    tagline: str = Field(description="Short brand tagline, max ~10 words.")
    audience: str = Field(description="Primary target audience, one sentence.")
    tone: str = Field(description="Voice and tone for all copy, e.g. 'warm, artisanal, playful'.")
    pages: list[PageSpec] = Field(
        min_length=3,
        max_length=MAX_PAGES,
        description=f"3 to {MAX_PAGES} pages. The first page must be the homepage.",
    )

    @model_validator(mode="after")
    def _unique_slugs(self) -> "SiteMap":
        slugs = [page.slug for page in self.pages]
        if len(slugs) != len(set(slugs)):
            raise ValueError(f"page slugs must be unique, got {slugs}")
        return self


_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_PLACEHOLDER = re.compile(r"\[[^\]]{2,}\]|lorem ipsum", re.IGNORECASE)


class PageSection(BaseModel):
    heading: str = Field(description="A compelling heading written for visitors.")
    body: str = Field(
        description="Final, publishable plain-text copy for this section, 40-120 words. "
        "No HTML, no forms, no [placeholders] or image notes."
    )

    # Rules live in validators, not in JSON-schema constraints: Ollama compiles schema
    # constraints into its decoding grammar, which cuts text mid-word instead of making the
    # model rewrite it. A validator error is fed back to the model, which then fixes the text.
    @field_validator("body")
    @classmethod
    def _publishable(cls, value: str) -> str:
        if _HTML_TAG.search(value):
            raise ValueError("section body must be plain text; remove all HTML tags and forms")
        if match := _PLACEHOLDER.search(value):
            raise ValueError(f"section body contains a placeholder: {match.group(0)!r}")
        return value


class PageCopy(BaseModel):
    """What the writer LLM produces for one page. Slug and title come from the sitemap."""

    meta_description: str = Field(description="SEO meta description, max 160 characters.")
    sections: list[PageSection] = Field(min_length=1, max_length=6)
    # Named `button_label`, not `call_to_action`: small models follow field names more than
    # descriptions, and "call_to_action" invited full sentences.
    button_label: str = Field(
        description="Text on the page's main button, 2-5 words. E.g. 'Book a free tasting'."
    )

    @field_validator("button_label")
    @classmethod
    def _short_label(cls, value: str) -> str:
        if len(value) > 40:
            raise ValueError(f"button_label must be 2-5 words, got {value!r}")
        return value

    @field_validator("meta_description")
    @classmethod
    def _short_meta(cls, value: str) -> str:
        # Repaired in code rather than sent back to the model: a retry rewrites the whole
        # page (~15 s locally) and models often repeat the same length. Cut at a word.
        if len(value) <= 160:
            return value
        return value[:157].rsplit(" ", 1)[0].rstrip(",;:") + "..."


class PageDraft(PageCopy):
    slug: str
    title: str


class PageIssue(BaseModel):
    slug: str = Field(description="Slug of the page that has the problem.")
    problem: str = Field(
        description="A specific instruction for the writer: name the exact fact from the brief "
        "that is missing or wrong, or quote the passage to change, and say what to write instead."
    )


class ReviewResult(BaseModel):
    approved: bool = Field(description="True if the site copy is ready for a human to review.")
    issues: list[PageIssue] = Field(
        default_factory=list,
        description="Only significant problems. Empty when approved.",
    )


class ApprovalDecision(BaseModel):
    """A human's answer at the approval step."""

    approved: bool
    feedback: dict[str, str] = Field(
        default_factory=dict,
        description="When not approved: requested change per page slug. Empty = reject outright.",
    )


class ColorToken(BaseModel):
    name: str
    hex: str


class TypeToken(BaseModel):
    name: str
    family: str
    weight: int
    size_px: float


class StyleGuide(BaseModel):
    """Brand colors and typography, read from the client's Figma styles."""

    source: str
    colors: list[ColorToken]
    typography: list[TypeToken]

    def color(self, *hints: str) -> ColorToken | None:
        """First color whose name contains any hint (e.g. 'primary'), case-insensitive."""
        return next((c for c in self.colors if any(h in c.name.lower() for h in hints)), None)

    def font(self, *hints: str) -> TypeToken | None:
        return next((t for t in self.typography if any(h in t.name.lower() for h in hints)), None)
