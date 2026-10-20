"""Background graph runs and their event streams.

The checkpointer is the source of truth for a run's state, so status and approval work
after a restart. The in-memory event log only feeds live SSE streams; it is per process and
lost on restart, which is acceptable for progress updates.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.messages import AIMessageChunk
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic_core import to_jsonable_python

from firstcut.graph import Deps

log = structlog.get_logger()

DepsFactory = Callable[[], AbstractAsyncContextManager[Deps]]
FINAL_STATUSES = {"published", "rejected", "failed", "completed"}


@dataclass
class Run:
    id: str
    status: str = "running"
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None


class RunService:
    def __init__(self, graph: CompiledStateGraph, deps_factory: DepsFactory) -> None:
        self.graph = graph
        self.deps_factory = deps_factory
        self.runs: dict[str, Run] = {}

    def config(self, run_id: str) -> dict:
        return {"configurable": {"thread_id": run_id}}

    async def start(self, run_id: str, graph_input: dict[str, Any]) -> Run:
        run = self.runs[run_id] = Run(run_id)
        run.task = asyncio.create_task(self._execute(run, graph_input))
        return run

    async def resume(self, run_id: str, decision: dict[str, Any]) -> Run:
        run = self.runs.setdefault(run_id, Run(run_id))  # may be a run from before a restart
        run.status = "running"
        run.task = asyncio.create_task(self._execute(run, Command(resume=decision)))
        return run

    async def snapshot(self, run_id: str):
        return await self.graph.aget_state(self.config(run_id))

    async def status(self, run_id: str) -> str | None:
        run = self.runs.get(run_id)
        if run and run.status == "running":
            return "running"
        snapshot = await self.snapshot(run_id)
        if not snapshot.values:
            return run.status if run else None
        if snapshot.interrupts:
            return "awaiting_approval"
        if snapshot.next:
            return run.status if run else "interrupted"  # crashed mid-run
        return snapshot.values.get("status", "completed")

    async def events(self, run_id: str, start: int = 0) -> AsyncIterator[tuple[int, dict]]:
        """Replay events from `start`, then follow live ones until the run stops."""
        run = self.runs[run_id]
        index = start
        while True:
            async with run.changed:
                await run.changed.wait_for(
                    lambda seen=index: seen < len(run.events) or run.status != "running"
                )
                pending = run.events[index:]
            for event in pending:
                yield index, event
                index += 1
            if not pending and run.status != "running":
                return

    async def _execute(self, run: Run, graph_input: dict | Command) -> None:
        with structlog.contextvars.bound_contextvars(run_id=run.id):
            log.info("run_segment_started", resume=isinstance(graph_input, Command))
            try:
                async with self.deps_factory() as deps:
                    async for mode, chunk in self.graph.astream(
                        graph_input,
                        self.config(run.id),
                        context=deps,
                        stream_mode=["updates", "messages"],
                    ):
                        for event in _to_events(mode, chunk):
                            await self._emit(run, event)
                status = await self._final_status(run.id)
            except Exception as exc:  # report any failure to the client, then log it
                log.exception("run_failed")
                await self._emit(run, {"type": "error", "message": str(exc)})
                status = "failed"
            await self._set_status(run, status)
            log.info("run_segment_finished", status=status)

    async def _final_status(self, run_id: str) -> str:
        snapshot = await self.snapshot(run_id)
        if snapshot.interrupts:
            return "awaiting_approval"
        return snapshot.values.get("status", "completed")

    async def _emit(self, run: Run, event: dict) -> None:
        async with run.changed:
            run.events.append(event)
            run.changed.notify_all()

    async def _set_status(self, run: Run, status: str) -> None:
        async with run.changed:
            run.status = status
            run.events.append({"type": "status", "status": status})
            run.changed.notify_all()


def _to_events(mode: str, chunk: Any) -> list[dict]:
    if mode == "messages":
        message, metadata = chunk
        # LLM tokens as they are generated (structured outputs stream as JSON text).
        if isinstance(message, AIMessageChunk) and message.text:
            return [{"type": "token", "node": metadata.get("langgraph_node"), "text": message.text}]
        return []

    events = []
    for node, update in chunk.items():
        if node == "__interrupt__":
            events.append({"type": "awaiting_approval", "payload": update[0].value})
        else:
            events.append({"type": "node", "node": node, "summary": _summarize(node, update)})
    return events


def _summarize(node: str, update: dict | None) -> Any:
    update = update or {}
    if node == "load_brief" and "brief" in update:
        return {"characters": len(update["brief"])}
    if node == "load_style_guide" and "style_guide" in update:
        guide = update["style_guide"]
        return {
            "colors": [c.hex for c in guide.colors],
            "fonts": [t.family for t in guide.typography],
        }
    if node == "plan_sitemap":
        return {"pages": [f"{p.title} (/{p.slug})" for p in update["sitemap"].pages]}
    if node == "write_page":
        return {"pages": list(update.get("pages", {}))}
    if node == "review":
        return {"approved": update["review"].approved, "issues": len(update["review"].issues)}
    if "wp_pages" in update:
        return {
            slug: {key: page.get(key) for key in ("id", "status", "link")}
            for slug, page in update["wp_pages"].items()
        }
    return to_jsonable_python(update, fallback=str)
