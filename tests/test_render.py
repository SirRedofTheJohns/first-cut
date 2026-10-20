import pytest
from pydantic import ValidationError

from firstcut.render import render_blocks
from firstcut.schemas import PageDraft, PageSection


def draft(body: str) -> PageDraft:
    return PageDraft(
        slug="home",
        title="Home",
        meta_description="m",
        sections=[PageSection(heading="Fresh & warm", body=body)],
        button_label="Pre-order now",
    )


def test_renders_editable_gutenberg_blocks():
    markup = render_blocks(draft("First paragraph.\n\nSecond with **bold**."))
    assert markup.count("<!-- wp:paragraph -->") == 2
    assert '<h2 class="wp-block-heading">Fresh &amp; warm</h2>' in markup
    assert "<strong>bold</strong>" in markup
    assert 'wp-block-button__link wp-element-button">Pre-order now</a>' in markup


def test_model_text_cannot_inject_markup():
    # The schema already rejects tags; rendering escapes anyway (defense in depth).
    page = draft("safe").model_copy(update={"button_label": "<script>x</script>"})
    assert "<script>" not in render_blocks(page)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("Fill in <form><input></form> below.", "plain text"),
        ("Workshops start on [insert date].", "placeholder"),
        ("Lorem ipsum dolor sit amet.", "placeholder"),
    ],
)
def test_unpublishable_copy_is_rejected(body, error):
    with pytest.raises(ValidationError, match=error):
        PageSection(heading="h", body=body)


def test_long_button_label_is_rejected():
    with pytest.raises(ValidationError, match="2-5 words"):
        draft("ok").model_validate({**draft("ok").model_dump(), "button_label": "x" * 41})


def test_long_meta_description_is_trimmed_not_rejected():
    page = draft("ok").model_validate(
        {**draft("ok").model_dump(), "meta_description": "word " * 60}
    )
    assert len(page.meta_description) <= 160
    assert page.meta_description.endswith("...")
