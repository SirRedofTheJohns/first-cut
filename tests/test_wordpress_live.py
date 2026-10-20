"""Runs against the local Docker WordPress: `docker compose up -d && uv run pytest -m integration`."""

import asyncio

import pytest

from firstcut.integrations.wordpress import WordPressClient, WordPressError

pytestmark = pytest.mark.integration


def test_page_lifecycle_against_real_wordpress():
    async def lifecycle():
        async with WordPressClient.from_settings() as wp:
            page = await wp.create_page("Integration probe", "<p>hi</p>", slug="it-probe")
            try:
                assert page["status"] == "draft"
                assert page["slug"] == "it-probe"  # WordPress keeps explicit slugs on drafts
                assert any(p["id"] == page["id"] for p in await wp.list_pages())

                updated = await wp.update_page(page["id"], status="publish")
                assert updated["status"] == "publish"
                assert "<p>hi</p>" in (await wp.get_page(page["id"]))["content"]
            finally:
                await wp.delete_page(page["id"])
            with pytest.raises(WordPressError, match="404"):
                await wp.get_page(page["id"])

    asyncio.run(lifecycle())
