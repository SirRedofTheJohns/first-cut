import pytest

from firstcut.integrations.gdocs import GoogleDocsError, document_id, is_google_doc, to_markdown

URL = "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit?tab=t.0"


def paragraph(text: str, style: str = "NORMAL_TEXT", bullet: bool = False) -> dict:
    p = {
        "elements": [{"textRun": {"content": text + "\n"}}],
        "paragraphStyle": {"namedStyleType": style},
    }
    if bullet:
        p["bullet"] = {"listId": "x"}
    return {"paragraph": p}


def test_document_id_from_url():
    assert is_google_doc(URL)
    assert document_id(URL) == "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    assert not is_google_doc("briefs/masa-bakery.md")
    with pytest.raises(GoogleDocsError):
        document_id("https://example.com/doc")


def test_docs_api_structure_becomes_markdown():
    doc = {
        "title": "Brief — Northline PT",
        "body": {
            "content": [
                {"sectionBreak": {}},
                paragraph("Brief — Northline PT", "HEADING_1"),  # repeated title is dropped
                paragraph("Goals", "HEADING_1"),
                paragraph("More online bookings", bullet=True),
                paragraph("Physician referrals", bullet=True),
                paragraph(""),
                paragraph("We are in-network with Aetna and Cigna."),
                {
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {"content": [paragraph("Phone")]},
                                    {"content": [paragraph("(303) 555-0187")]},
                                ]
                            }
                        ]
                    }
                },
            ]
        },
    }
    assert to_markdown(doc) == (
        "# Brief — Northline PT\n\n"
        "## Goals\n"
        "- More online bookings\n"
        "- Physician referrals\n"
        "We are in-network with Aetna and Cigna.\n"
        "Phone | (303) 555-0187\n"
    )
