"""WordPressClient against a mocked HTTP transport: the errors a first-time setup hits."""

import asyncio

import httpx
import pytest

from firstcut.integrations.wordpress import WordPressClient, WordPressError


def client_with(handler) -> WordPressClient:
    client = WordPressClient("https://example.com/", "admin", "app pass")
    client._http = httpx.AsyncClient(
        base_url="https://example.com/wp-json/wp/v2/", transport=httpx.MockTransport(handler)
    )
    return client


def list_pages(handler, **kwargs):
    async def scenario():
        async with client_with(handler) as client:
            return await client.list_pages(**kwargs)

    return asyncio.run(scenario())


def test_slug_lookup_is_an_exact_server_side_filter():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json=[{"id": 3, "slug": "home", "status": "draft"}])

    assert list_pages(handler, slug="home")[0]["id"] == 3
    assert seen["slug"] == "home" and seen["status"] == "any"


def test_wrong_password_names_application_passwords():
    def handler(request):
        return httpx.Response(401, json={"code": "incorrect_password", "message": "Bad login."})

    with pytest.raises(WordPressError, match="401: Bad login.*Application Password"):
        list_pages(handler)


def test_a_login_wordpress_ignored_is_still_reported_as_a_login_problem():
    # What WordPress 7.1 actually answers to a wrong Application Password on GET pages.
    payload = {
        "code": "rest_invalid_param",
        "message": "Invalid parameter(s): status",
        "data": {
            "status": 400,
            "params": {"status": "Status is forbidden."},
            "details": {"status": {"code": "rest_forbidden_status"}},
        },
    }

    def handler(request):
        return httpx.Response(400, json=payload)

    with pytest.raises(WordPressError, match="400: Invalid parameter.*Application Password"):
        list_pages(handler)


def test_wrong_url_points_at_wp_url_without_dumping_html():
    def handler(request):
        return httpx.Response(404, text="<!DOCTYPE html><html>Not Found</html>")

    with pytest.raises(WordPressError, match=r"wp-json/\. WP_URL should be") as error:
        list_pages(handler)
    assert "<html" not in str(error.value)


def test_a_site_that_is_not_wordpress_is_explained():
    def handler(request):
        return httpx.Response(200, text="<html>Hello</html>")

    with pytest.raises(WordPressError, match="did not answer like WordPress"):
        list_pages(handler)


def test_unreachable_site_points_at_wp_url():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(WordPressError, match="unreachable at https://example.com.*WP_URL"):
        list_pages(handler)
