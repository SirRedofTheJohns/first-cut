import pytest
from pydantic import ValidationError

from firstcut.schemas import PageSpec, SiteMap, slugify
from tests.fakes import SITEMAP


def test_slugs_are_normalized():
    assert slugify("About Us!") == "about-us"
    assert PageSpec(slug="Our Team", title="t", purpose="p", sections=["a", "b"]).slug == "our-team"


def test_sitemap_rejects_duplicate_slugs():
    data = {**SITEMAP, "pages": [SITEMAP["pages"][0], SITEMAP["pages"][0], SITEMAP["pages"][2]]}
    with pytest.raises(ValidationError, match="unique"):
        SiteMap.model_validate(data)


def test_sitemap_caps_page_count():
    page = SITEMAP["pages"][0]
    pages = [{**page, "slug": f"p{i}"} for i in range(7)]
    with pytest.raises(ValidationError):
        SiteMap.model_validate({**SITEMAP, "pages": pages})
