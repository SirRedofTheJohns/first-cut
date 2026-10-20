"""HTTP API: a signed webhook starts a run, SSE streams its progress, a human approves it.

uv run uvicorn --factory firstcut.api.app:create_app --port 8000
"""

import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

import structlog
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_core import to_jsonable_python
from sse_starlette import EventSourceResponse, ServerSentEvent

from firstcut.api.runs import DepsFactory, RunService
from firstcut.api.security import (
    DELIVERY_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    InvalidSignature,
    verify,
)
from firstcut.checkpoints import sqlite_checkpointer
from firstcut.config import Settings, get_settings
from firstcut.graph import Deps, build_graph
from firstcut.integrations.factory import figma_client, gdocs_client
from firstcut.llm import get_chat_model, get_fallback_model
from firstcut.logs import configure_logging
from firstcut.mcp_client import wordpress_tools
from firstcut.schemas import ApprovalDecision

log = structlog.get_logger()
CheckpointerFactory = Callable[[], AbstractAsyncContextManager[BaseCheckpointSaver]]


class BriefWebhook(BaseModel):
    brief: str | None = Field(None, min_length=20, description="The brief as markdown/text.")
    gdoc_url: str | None = Field(None, description="Or: a Google Doc with the brief.")
    figma_url: str | None = Field(None, description="Optional Figma file with brand styles.")

    @model_validator(mode="after")
    def _one_brief_source(self) -> "BriefWebhook":
        if bool(self.brief) == bool(self.gdoc_url):
            raise ValueError("send exactly one of `brief` or `gdoc_url`")
        return self

    def graph_input(self) -> dict:
        graph_input = {"brief": self.brief} if self.brief else {"brief_source": self.gdoc_url}
        return graph_input | ({"figma_url": self.figma_url} if self.figma_url else {})


def create_app(
    settings: Settings | None = None,
    deps_factory: DepsFactory | None = None,
    checkpointer_factory: CheckpointerFactory | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    deps_factory = deps_factory or (lambda: _production_deps(settings))
    checkpointer_factory = checkpointer_factory or (
        lambda: sqlite_checkpointer(settings.checkpoint_db)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        async with checkpointer_factory() as checkpointer:
            app.state.runs = RunService(build_graph(checkpointer), deps_factory)
            log.info("api_started", llm=f"{settings.llm_provider}:{settings.llm_model}")
            yield

    app = FastAPI(title="First Cut", lifespan=lifespan)

    def runs(request: Request) -> RunService:
        return request.app.state.runs

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.post("/webhooks/brief", status_code=202)
    async def brief_webhook(
        request: Request,
        signature: Annotated[str | None, Header(alias=SIGNATURE_HEADER)] = None,
        timestamp: Annotated[str | None, Header(alias=TIMESTAMP_HEADER)] = None,
        delivery: Annotated[str | None, Header(alias=DELIVERY_HEADER)] = None,
    ):
        if settings.webhook_secret is None:
            raise HTTPException(503, "Webhook secret not configured")  # fail closed
        # Verify the raw bytes before parsing: the signature covers exactly what was sent.
        body = await request.body()
        try:
            verify(
                settings.webhook_secret.get_secret_value(),
                timestamp,
                signature,
                body,
                tolerance_seconds=settings.webhook_tolerance_seconds,
            )
        except InvalidSignature as exc:
            log.warning("webhook_rejected", reason=str(exc))
            raise HTTPException(401, "Invalid signature") from exc
        try:
            payload = BriefWebhook.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False)) from exc

        # Senders retry webhooks; the same delivery id must not start a second run.
        run_id = delivery or uuid.uuid4().hex
        service = runs(request)
        if run_id in service.runs or (await service.snapshot(run_id)).values:
            return JSONResponse(_links(run_id) | {"duplicate": True}, status_code=200)
        await service.start(run_id, payload.graph_input())
        log.info("run_started", run_id=run_id)
        return _links(run_id)

    @app.get("/runs/{run_id}")
    async def get_run(request: Request, run_id: str) -> dict:
        service = runs(request)
        status = await service.status(run_id)
        if status is None:
            raise HTTPException(404, "Unknown run")
        snapshot = await service.snapshot(run_id)
        values = snapshot.values
        return {
            "run_id": run_id,
            "status": status,
            "approval_request": snapshot.interrupts[0].value if snapshot.interrupts else None,
            "sitemap": to_jsonable_python(values.get("sitemap")),
            "pages": to_jsonable_python(values.get("pages", {})),
            "review": to_jsonable_python(values.get("review")),
            "wordpress": values.get("wp_pages", {}),
        }

    @app.get("/runs/{run_id}/events")
    async def run_events(
        request: Request,
        run_id: str,
        tokens: bool = False,
        last_event_id: Annotated[str | None, Header()] = None,
    ):
        service = runs(request)
        if run_id not in service.runs:
            raise HTTPException(404, "No live events for this run (try GET /runs/{id})")
        # EventSource clients send Last-Event-ID when reconnecting: resume, don't replay.
        start = int(last_event_id) + 1 if last_event_id and last_event_id.isdigit() else 0

        async def stream():
            async for index, event in service.events(run_id, start):
                if event["type"] == "token" and not tokens:
                    continue
                # sse-starlette sends str(data): a dict would arrive as a Python repr, not JSON.
                yield ServerSentEvent(data=json.dumps(event), event=event["type"], id=str(index))

        return EventSourceResponse(stream())

    @app.post("/runs/{run_id}/approval", status_code=202)
    async def approve(request: Request, run_id: str, decision: ApprovalDecision) -> dict:
        service = runs(request)
        if await service.status(run_id) != "awaiting_approval":
            raise HTTPException(409, "Run is not waiting for approval")
        log.info("approval_received", run_id=run_id, approved=decision.approved)
        await service.resume(run_id, decision.model_dump())
        return _links(run_id)

    return app


def _links(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "status_url": f"/runs/{run_id}",
        "events_url": f"/runs/{run_id}/events",
        "approval_url": f"/runs/{run_id}/approval",
    }


@asynccontextmanager
async def _production_deps(settings: Settings) -> AsyncIterator[Deps]:
    async with wordpress_tools(settings) as tools:
        yield Deps(
            llm=get_chat_model(settings),
            fallback_llm=get_fallback_model(settings),
            max_revisions=settings.max_revisions,
            wp_tools=tools,
            figma=figma_client(settings),
            gdocs=gdocs_client(settings),
        )
