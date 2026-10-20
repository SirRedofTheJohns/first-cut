"""Checkpointer setup.

LangGraph deserializes checkpoints with an allowlist: restoring arbitrary classes from a
database is a code-execution risk if that database is ever tampered with. Our state holds
Pydantic models, so they are registered here explicitly.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

STATE_TYPES = [
    ("firstcut.schemas", name)
    for name in (
        "ApprovalDecision",
        "ColorToken",
        "PageDraft",
        "PageIssue",
        "PageSection",
        "PageSpec",
        "ReviewResult",
        "SiteMap",
        "StyleGuide",
        "TypeToken",
    )
]


def serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


@asynccontextmanager
async def sqlite_checkpointer(path: str) -> AsyncIterator[AsyncSqliteSaver]:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        yield AsyncSqliteSaver(conn, serde=serializer())
