import json
import os
import time
from pathlib import Path

import httpx
import pytest

from firstcut.integrations import figma
from firstcut.integrations.figma import FigmaClient, FigmaError, extract_style_guide, file_key
from firstcut.render import render_blocks
from firstcut.schemas import ColorToken, PageDraft, PageSection, StyleGuide, TypeToken

FIXTURE = Path(__file__).parent / "fixtures" / "figma_masa_brand.json"
KEY = "9z5IYb5tdxSrHHd3XJGWoz"


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_file_key_from_any_figma_url():
    url = f"https://www.figma.com/design/{KEY}/First-Cut-%E2%80%93-Brand?node-id=0-1&p=f"
    assert file_key(url) == KEY
    assert file_key(f"https://www.figma.com/file/{KEY}/x") == KEY
    with pytest.raises(FigmaError):
        file_key("https://example.com/not-figma")


def test_style_values_are_resolved_through_the_layers_that_use_them():
    guide = extract_style_guide(fixture())
    assert [(c.name, c.hex) for c in guide.colors] == [
        ("Brand/Primary", "#C2410C"),
        ("Brand/Secondary", "#FDE68A"),
        ("Neutral/Text", "#1C1917"),
        ("Neutral/Background", "#FFFBF5"),
    ]
    assert [(t.name, t.family, t.weight, t.size_px) for t in guide.typography] == [
        ("Heading", "Playfair Display", 700, 40.0),
        ("Body", "Inter", 400, 16.0),
    ]


def test_file_without_styles_is_a_clear_error():
    with pytest.raises(FigmaError, match="No color or text styles"):
        extract_style_guide({"styles": {}, "document": {"type": "DOCUMENT", "children": []}})


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status_code = status
        self.text = json.dumps(payload or {})
        self.is_success = status < 400

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if not self.is_success:
            raise httpx.HTTPStatusError("error", request=None, response=None)


def test_cache_avoids_spending_the_monthly_quota(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        figma.httpx, "get", lambda *a, **k: calls.append(1) or FakeResponse(200, fixture())
    )
    client = FigmaClient("token", tmp_path)

    client.get_file(KEY)
    client.get_file(KEY)
    assert len(calls) == 1
    client.get_file(KEY, refresh=True)
    assert len(calls) == 2


def test_rate_limit_falls_back_to_a_stale_cache(tmp_path, monkeypatch):
    cached = tmp_path / f"{KEY}.json"
    cached.write_text(json.dumps(fixture()), encoding="utf-8")
    two_days_ago = time.time() - 48 * 3600
    os.utime(cached, (two_days_ago, two_days_ago))
    monkeypatch.setattr(figma.httpx, "get", lambda *a, **k: FakeResponse(429))

    assert FigmaClient("token", tmp_path).get_file(KEY)["name"].startswith("First Cut")


def test_rate_limit_without_cache_explains_the_free_plan_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(figma.httpx, "get", lambda *a, **k: FakeResponse(429))
    with pytest.raises(FigmaError, match="rate limit"):
        FigmaClient("token", tmp_path).get_file(KEY)


def page() -> PageDraft:
    return PageDraft(
        slug="home",
        title="Home",
        meta_description="m",
        sections=[PageSection(heading="Hi", body="Bread.")],
        button_label="Pre-order",
    )


def test_brand_is_applied_with_scoped_css_and_web_fonts():
    markup = render_blocks(page(), extract_style_guide(fixture()))
    assert markup.startswith("<!-- wp:html -->")
    assert "family=Playfair+Display:wght@700" in markup
    assert ".firstcut-brand h2{font-family:'Playfair Display',serif;font-weight:700}" in markup
    # Button: primary color, with the palette color that contrasts most for the label.
    assert ".firstcut-brand .wp-block-button__link{background:#C2410C;color:#FFFBF5}" in markup
    assert '<div class="wp-block-group firstcut-brand">' in markup


def test_untrusted_font_names_never_reach_the_css():
    guide = StyleGuide(
        source="evil",
        colors=[ColorToken(name="Primary", hex="#000000"), ColorToken(name="Bg", hex="#FFFFFF")],
        typography=[TypeToken(name="Heading", family="X}</style><script>", weight=700, size_px=40)],
    )
    markup = render_blocks(page(), guide)
    assert "<script>" not in markup
    assert "font-family" not in markup
    assert "fonts.googleapis.com" not in markup
