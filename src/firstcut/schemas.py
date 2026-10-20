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
        description="Ordered section headings planned for this page.",
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


class PageSection(BaseModel):
    heading: str
    body: str = Field(
        description="Final, publishable copy for this section. 40-120 words. No placeholders."
    )


class PageCopy(BaseModel):
    """What the writer LLM produces for one page. Slug and title come from the sitemap."""

    meta_description: str = Field(description="SEO meta description, max 160 characters.")
    sections: list[PageSection] = Field(min_length=1, max_length=6)
    call_to_action: str = Field(
        description="Button label for the primary call to action, 2-5 words, no brackets. "
        "E.g. 'Book a free tasting'."
    )

    # Length limits live in validators, not in Field(max_length=...): schema constraints are
    # compiled into Ollama's decoding grammar, which truncates text mid-word instead of making
    # the model write something shorter. A validator error is fed back so the model rewrites.
    @field_validator("call_to_action")
    @classmethod
    def _short_cta(cls, value: str) -> str:
        if len(value) > 40:
            raise ValueError(f"call_to_action must be a 2-5 word button label, got {value!r}")
        return value

    @field_validator("meta_description")
    @classmethod
    def _short_meta(cls, value: str) -> str:
        if len(value) > 200:
            raise ValueError(f"meta_description must be under 160 characters, got {len(value)}")
        return value


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
