"""Read a client's brand (color and text styles) from a Figma file via the REST API.

Figma's free plan allows very few file reads per month (~20 for `GET /v1/files/:key`),
so responses are cached on disk and reused for `max_age`. If Figma rate-limits us, a stale
cached copy is better than failing the run.
"""

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from firstcut.schemas import ColorToken, StyleGuide, TypeToken

_FILE_KEY = re.compile(r"figma\.com/(?:file|design|proto)/([A-Za-z0-9]+)")


class FigmaError(RuntimeError):
    pass


def file_key(url_or_key: str) -> str:
    if match := _FILE_KEY.search(url_or_key):
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{10,}", url_or_key):
        return url_or_key
    raise FigmaError(f"Not a Figma file URL: {url_or_key!r}")


class FigmaClient:
    def __init__(self, token: str, cache_dir: Path, max_age_hours: float = 24) -> None:
        self._token = token
        self._cache_dir = cache_dir
        self._max_age = max_age_hours * 3600

    def get_file(self, key: str, refresh: bool = False) -> dict[str, Any]:
        cached = self._cache_dir / f"{key}.json"
        if cached.exists() and not refresh and time.time() - cached.stat().st_mtime < self._max_age:
            return json.loads(cached.read_text(encoding="utf-8"))

        response = httpx.get(
            f"https://api.figma.com/v1/files/{key}",
            headers={"X-Figma-Token": self._token},
            timeout=60,
        )
        if response.status_code == 429 and cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))  # stale beats nothing
        if response.status_code == 429:
            raise FigmaError("Figma rate limit reached (free plan: ~20 file reads per month)")
        if response.status_code in (403, 404):
            raise FigmaError(
                f"Figma returned {response.status_code}: check that FIGMA_TOKEN has the "
                "file_content:read scope and that its owner can open this file"
            )
        response.raise_for_status()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(response.text, encoding="utf-8")
        return response.json()


def extract_style_guide(figma_file: dict[str, Any]) -> StyleGuide:
    """Resolve each local style to its values.

    The file's `styles` map only has names and types; the actual values live on the layers
    that use each style, so the document tree is walked to find one layer per style.
    """
    styles = figma_file.get("styles", {})
    colors: dict[str, ColorToken] = {}
    fonts: dict[str, TypeToken] = {}

    def walk(node: dict[str, Any]) -> None:
        refs = node.get("styles", {})
        fill_id = refs.get("fill")
        if fill_id in styles and fill_id not in colors:
            solid = next((f for f in node.get("fills", []) if f.get("type") == "SOLID"), None)
            if solid:
                colors[fill_id] = ColorToken(name=styles[fill_id]["name"], hex=_hex(solid["color"]))
        text_id = refs.get("text")
        if text_id in styles and text_id not in fonts and node.get("type") == "TEXT":
            style = node["style"]
            fonts[text_id] = TypeToken(
                name=styles[text_id]["name"],
                family=style["fontFamily"],
                weight=int(style.get("fontWeight", 400)),
                size_px=style["fontSize"],
            )
        for child in node.get("children", []):
            walk(child)

    walk(figma_file["document"])
    if not colors and not fonts:
        raise FigmaError(
            "No color or text styles found. Create local styles and apply them to layers."
        )
    return StyleGuide(
        source=figma_file.get("name", "Figma"),
        colors=list(colors.values()),
        typography=list(fonts.values()),
    )


def _hex(color: dict[str, float]) -> str:
    return "#" + "".join(f"{round(color[c] * 255):02X}" for c in ("r", "g", "b"))
