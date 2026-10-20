"""Render generated page copy as Gutenberg block markup, so pages stay editable as blocks
in the WordPress editor instead of turning into one "Classic" HTML blob."""

import html
import re

from firstcut.schemas import PageDraft

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def render_blocks(page: PageDraft) -> str:
    blocks: list[str] = []
    for section in page.sections:
        blocks.append(_heading(section.heading))
        blocks.extend(_paragraph(chunk) for chunk in _paragraphs(section.body))
    blocks.append(_button(page.button_label))
    return "\n\n".join(blocks)


def _paragraphs(text: str) -> list[str]:
    return [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]


def _inline(text: str) -> str:
    # Escape first so model output can never inject markup; then allow **bold** and line breaks.
    escaped = _BOLD.sub(r"<strong>\1</strong>", html.escape(text))
    return escaped.replace("\n", "<br>")


def _heading(text: str) -> str:
    return (
        f'<!-- wp:heading -->\n<h2 class="wp-block-heading">{html.escape(text)}</h2>\n'
        "<!-- /wp:heading -->"
    )


def _paragraph(text: str) -> str:
    return f"<!-- wp:paragraph -->\n<p>{_inline(text)}</p>\n<!-- /wp:paragraph -->"


def _button(label: str) -> str:
    return (
        '<!-- wp:buttons -->\n<div class="wp-block-buttons"><!-- wp:button -->\n'
        '<div class="wp-block-button"><a class="wp-block-button__link wp-element-button">'
        f"{html.escape(label)}</a></div>\n<!-- /wp:button --></div>\n<!-- /wp:buttons -->"
    )
