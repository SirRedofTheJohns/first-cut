"""Read a client brief from a Google Doc with the Google Docs API and a service account.

The service account is a robot identity: it can only read documents explicitly shared with
its email address, and the JSON key never leaves this machine (git-ignored `secrets/`).
"""

import re
from pathlib import Path
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/documents.readonly"]
_DOC_ID = re.compile(r"docs\.google\.com/document/d/([A-Za-z0-9_-]+)")


class GoogleDocsError(RuntimeError):
    pass


def is_google_doc(source: str) -> bool:
    return bool(_DOC_ID.search(source))


def document_id(url_or_id: str) -> str:
    if match := _DOC_ID.search(url_or_id):
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", url_or_id):
        return url_or_id
    raise GoogleDocsError(f"Not a Google Docs URL: {url_or_id!r}")


class GoogleDocsClient:
    def __init__(self, credentials_file: Path) -> None:
        if not credentials_file.exists():
            raise GoogleDocsError(f"Service account key not found at {credentials_file}")
        self._credentials = service_account.Credentials.from_service_account_file(
            str(credentials_file), scopes=SCOPES
        )

    @property
    def robot_email(self) -> str:
        return self._credentials.service_account_email

    def read_markdown(self, url_or_id: str) -> str:
        if not self._credentials.valid:
            self._credentials.refresh(Request())  # short-lived OAuth token from the key
        response = httpx.get(
            f"https://docs.googleapis.com/v1/documents/{document_id(url_or_id)}",
            headers={"Authorization": f"Bearer {self._credentials.token}"},
            timeout=30,
        )
        if response.status_code in (403, 404):
            raise GoogleDocsError(
                f"Google Docs returned {response.status_code}. Share the document with "
                f"{self.robot_email} (Viewer) and check that the Docs API is enabled."
            )
        response.raise_for_status()
        return to_markdown(response.json())


def to_markdown(document: dict[str, Any]) -> str:
    """Convert a Docs API document to markdown: headings, bullets, paragraphs, tables."""
    lines = [f"# {document.get('title', 'Brief')}"]
    for element in document.get("body", {}).get("content", []):
        if "paragraph" in element:
            lines.append(_paragraph(element["paragraph"]))
        elif "table" in element:
            for row in element["table"].get("tableRows", []):
                cells = [_cell_text(cell) for cell in row.get("tableCells", [])]
                lines.append(" | ".join(cells))
    return "\n".join(line for line in lines if line.strip()).strip() + "\n"


def _paragraph(paragraph: dict[str, Any]) -> str:
    text = "".join(
        run.get("textRun", {}).get("content", "") for run in paragraph.get("elements", [])
    ).strip()
    if not text:
        return ""
    style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "")
    if style.startswith("HEADING_"):
        return f"\n{'#' * (int(style[-1]) + 1)} {text}"  # the doc title is already level 1
    if style == "TITLE":
        return f"\n# {text}"
    if "bullet" in paragraph:
        indent = "  " * paragraph["bullet"].get("nestingLevel", 0)
        return f"{indent}- {text}"
    return text


def _cell_text(cell: dict[str, Any]) -> str:
    return " ".join(
        _paragraph(content["paragraph"]).strip()
        for content in cell.get("content", [])
        if "paragraph" in content
    )
