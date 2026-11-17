"""Minimal async client for the WordPress REST API (pages only), authenticated with an
Application Password. Shared by the agent's tools and the MCP server."""

from typing import Any, Literal

import httpx

from firstcut.config import Settings, get_settings

PageStatus = Literal["draft", "publish", "pending", "private"]
_PAGE_FIELDS = "id,slug,status,link,title"
_AUTH_HINT = (
    " WordPress didn't accept the login: check WP_USER and WP_APP_PASSWORD. It must be an"
    " Application Password (Users > Profile > Application Passwords), not the login password."
)


class WordPressError(RuntimeError):
    pass


class WordPressClient:
    def __init__(self, base_url: str, user: str, app_password: str, timeout: float = 30) -> None:
        self._site = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/wp-json/wp/v2/",
            auth=(user, app_password),
            timeout=timeout,
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "WordPressClient":
        settings = settings or get_settings()
        if settings.wp_app_password is None:
            raise WordPressError(
                "WP_APP_PASSWORD is not set. Create one in WordPress (Users > Profile > "
                "Application Passwords) and pass it to the MCP server as WP_APP_PASSWORD. "
                "Local Docker setup: `docker compose logs wpcli`."
            )
        return cls(settings.wp_url, settings.wp_user, settings.wp_app_password.get_secret_value())

    async def __aenter__(self) -> "WordPressClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._http.aclose()

    async def list_pages(
        self, search: str | None = None, slug: str | None = None
    ) -> list[dict[str, Any]]:
        params = {"status": "any", "per_page": 100, "_fields": _PAGE_FIELDS, "context": "edit"}
        if search:
            params["search"] = search
        if slug:  # exact match, so sites with more than 100 pages still find it
            params["slug"] = slug
        return [_summary(page) for page in await self._request("GET", "pages", params=params)]

    async def get_page(self, page_id: int) -> dict[str, Any]:
        page = await self._request("GET", f"pages/{page_id}", params={"context": "edit"})
        return {**_summary(page), "content": page["content"]["raw"]}

    async def create_page(
        self, title: str, content: str, slug: str | None = None, status: PageStatus = "draft"
    ) -> dict[str, Any]:
        payload = {"title": title, "content": content, "status": status}
        if slug:
            payload["slug"] = slug
        return _summary(await self._request("POST", "pages", json=payload))

    async def update_page(
        self,
        page_id: int,
        title: str | None = None,
        content: str | None = None,
        status: PageStatus | None = None,
    ) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in {"title": title, "content": content, "status": status}.items()
            if value is not None
        }
        return _summary(await self._request("POST", f"pages/{page_id}", json=payload))

    async def delete_page(self, page_id: int) -> None:
        await self._request("DELETE", f"pages/{page_id}", params={"force": "true"})

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise WordPressError(
                f"WordPress unreachable at {self._site}: {exc}. Check WP_URL."
            ) from exc
        try:
            body = response.json() if response.content else None
        except ValueError:  # an HTML page: not a WordPress REST API
            body = None
        if response.is_error:
            # WordPress returns {"code": ..., "message": ...} on errors.
            error = body if isinstance(body, dict) else {}
            detail = error.get("message") or "an HTML page, not the WordPress REST API"
            message = f"{method} {path} -> {response.status_code}: {detail.rstrip('.')}."
            if response.status_code in (401, 403) or _anonymous(error):
                message += _AUTH_HINT
            elif response.status_code == 404 and error.get("code") in (None, "rest_no_route"):
                message += (
                    f" Nothing answered at {self._site}/wp-json/. WP_URL should be the site's "
                    "home address, e.g. https://example.com, without /wp-admin."
                )
            raise WordPressError(message)
        if body is None:
            raise WordPressError(
                f"{self._site} did not answer like WordPress. WP_URL should be the site's "
                "address, e.g. https://example.com"
            )
        return body


def _anonymous(error: dict[str, Any]) -> bool:
    """A rejected login doesn't always give a 401: WordPress may treat the request as
    anonymous, and listing drafts (status=any) then fails with 400 'Status is forbidden'."""
    data = error.get("data")
    details = data.get("details", {}) if isinstance(data, dict) else {}
    return details.get("status", {}).get("code") == "rest_forbidden_status"


def _summary(page: dict[str, Any]) -> dict[str, Any]:
    title = page.get("title", {})
    if isinstance(title, dict):  # {"raw": ..., "rendered": ...} with context=edit
        title = title.get("raw") or title.get("rendered", "")
    return {
        "id": page["id"],
        "slug": page.get("slug", ""),
        "status": page.get("status"),
        "link": page.get("link"),
        "title": title,
    }
