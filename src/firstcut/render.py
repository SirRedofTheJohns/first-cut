"""Render generated page copy as Gutenberg block markup, so pages stay editable as blocks
in the WordPress editor instead of turning into one "Classic" HTML blob."""

import html
import re
from urllib.parse import quote_plus

from firstcut.schemas import ColorToken, PageDraft, StyleGuide, TypeToken

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_SAFE_FONT = re.compile(r"[A-Za-z0-9 \-]+")
BRAND_CLASS = "firstcut-brand"


def render_blocks(page: PageDraft, style_guide: StyleGuide | None = None) -> str:
    blocks: list[str] = []
    for section in page.sections:
        blocks.append(_heading(section.heading))
        blocks.extend(_paragraph(chunk) for chunk in _paragraphs(section.body))
    blocks.append(_button(page.button_label))
    content = "\n\n".join(blocks)
    if style_guide is None:
        return content
    # Brand styling lives in one Custom HTML block scoped to a Group's class. Inline styles on
    # each block would have to match Gutenberg's own serialization exactly, or the editor
    # flags the block as invalid.
    return (
        f"{_brand_css(style_guide)}\n\n"
        f'<!-- wp:group {{"className":"{BRAND_CLASS}"}} -->\n'
        f'<div class="wp-block-group {BRAND_CLASS}">{content}</div>\n<!-- /wp:group -->'
    )


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


def _brand_css(guide: StyleGuide) -> str:
    """Map style names to roles by convention (primary, text, heading, body), falling back to
    order and size. Values come from a third party, so font names are allow-listed before
    they reach CSS; hex colors are already normalized by the Figma integration."""
    accent = guide.color("primary", "accent", "brand") or (
        guide.colors[0] if guide.colors else None
    )
    text = guide.color("text", "ink", "foreground")
    heading = guide.font("head", "display", "title") or _by_size(guide, largest=True)
    body = guide.font("body", "paragraph") or _by_size(guide, largest=False)
    heading = heading if heading and _SAFE_FONT.fullmatch(heading.family) else None
    body = body if body and _SAFE_FONT.fullmatch(body.family) else None

    scope = f".{BRAND_CLASS}"
    rules = []
    if text:
        rules.append(f"{scope}{{color:{text.hex}}}")
    if body:
        rules.append(f"{scope},{scope} p{{font-family:'{body.family}',sans-serif}}")
    if heading:
        rules.append(
            f"{scope} h2{{font-family:'{heading.family}',serif;font-weight:{heading.weight}}}"
        )
    if accent:
        on_accent = max(guide.colors, key=lambda c: _contrast(c, accent))
        rules.append(
            f"{scope} .wp-block-button__link{{background:{accent.hex};color:{on_accent.hex}}}"
        )

    families = sorted(
        {f"family={quote_plus(f.family)}:wght@{f.weight}" for f in (heading, body) if f}
    )
    link = (
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        f'{"&amp;".join(families)}&amp;display=swap">\n'
        if families
        else ""
    )
    return f"<!-- wp:html -->\n{link}<style>{''.join(rules)}</style>\n<!-- /wp:html -->"


def _by_size(guide: StyleGuide, largest: bool) -> TypeToken | None:
    pick = max if largest else min
    return pick(guide.typography, key=lambda t: t.size_px, default=None)


def _contrast(a: ColorToken, b: ColorToken) -> float:
    """WCAG contrast ratio between two colors (1 to 21)."""
    high, low = sorted((_luminance(a.hex), _luminance(b.hex)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
