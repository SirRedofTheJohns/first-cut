import json
import time
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from firstcut.api.app import create_app
from firstcut.api.security import (
    DELIVERY_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    InvalidSignature,
    sign,
    verify,
)
from firstcut.config import Settings
from firstcut.graph import Deps
from tests.fakes import FakeWordPressClient, ScriptedChatModel, mcp_wordpress_tools, site_responder

SECRET = "test-secret"
BRIEF = {"brief": "Masa Bakery: family sourdough bakery in Austin, TX."}


def signed_headers(body: bytes, secret: str = SECRET, timestamp: int | None = None) -> dict:
    ts = str(timestamp or int(time.time()))
    return {TIMESTAMP_HEADER: ts, SIGNATURE_HEADER: sign(secret, ts, body)}


@pytest.fixture
def wp():
    return FakeWordPressClient()


@pytest.fixture
def client(wp):
    @asynccontextmanager
    async def deps():
        async with mcp_wordpress_tools(wp) as tools:
            yield Deps(llm=ScriptedChatModel(respond=site_responder()), wp_tools=tools)

    @asynccontextmanager
    async def checkpointer():
        yield InMemorySaver()

    settings = Settings(_env_file=None, webhook_secret=SECRET)
    with TestClient(create_app(settings, deps, checkpointer)) as test_client:
        yield test_client


def post_brief(client, payload=BRIEF, **header_overrides):
    body = json.dumps(payload).encode()
    headers = signed_headers(body) | header_overrides
    return client.post("/webhooks/brief", content=body, headers=headers)


def read_events(client, run_id: str, **headers) -> list[dict]:
    with client.stream("GET", f"/runs/{run_id}/events", headers=headers) as response:
        return [json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")]


def test_signature_verification():
    body = b'{"brief": "x"}'
    now = 1_700_000_000
    verify(SECRET, str(now), sign(SECRET, str(now), body), body, now=now)
    with pytest.raises(InvalidSignature, match="mismatch"):
        verify(SECRET, str(now), sign("wrong", str(now), body), body, now=now)
    with pytest.raises(InvalidSignature, match="mismatch"):  # body tampered after signing
        verify(SECRET, str(now), sign(SECRET, str(now), body), body + b" ", now=now)
    with pytest.raises(InvalidSignature, match="window"):  # replayed 10 minutes later
        verify(SECRET, str(now), sign(SECRET, str(now), body), body, now=now + 600)


def test_webhook_rejects_unsigned_and_forged_requests(client):
    assert client.post("/webhooks/brief", json=BRIEF).status_code == 401
    body = json.dumps(BRIEF).encode()
    forged = signed_headers(body, secret="attacker")
    assert client.post("/webhooks/brief", content=body, headers=forged).status_code == 401


def test_webhook_fails_closed_without_a_secret(wp):
    app = create_app(Settings(_env_file=None, webhook_secret=None))
    with TestClient(app) as test_client:
        assert post_brief(test_client).status_code == 503


def test_full_flow_webhook_stream_approve_publish(client, wp):
    response = post_brief(client)
    assert response.status_code == 202
    run_id = response.json()["run_id"]

    events = read_events(client, run_id)
    nodes = [e["node"] for e in events if e["type"] == "node"]
    assert nodes[:2] == ["load_brief", "plan_sitemap"]
    assert "publish_drafts" in nodes
    assert events[-2]["type"] == "awaiting_approval"
    assert events[-1] == {"type": "status", "status": "awaiting_approval"}

    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "awaiting_approval"
    assert {p["slug"] for p in run["approval_request"]["pages"]} == {"home", "workshops", "contact"}
    assert all(page["status"] == "draft" for page in wp.pages.values())

    assert client.post(f"/runs/{run_id}/approval", json={"approved": True}).status_code == 202
    # Reconnect like an EventSource would: only events after the last one we saw.
    later = read_events(client, run_id, **{"Last-Event-ID": str(len(events) - 1)})
    assert later[-1] == {"type": "status", "status": "published"}
    assert client.get(f"/runs/{run_id}").json()["status"] == "published"
    assert all(page["status"] == "publish" for page in wp.pages.values())


def test_approval_is_rejected_when_not_waiting(client):
    run_id = post_brief(client).json()["run_id"]
    read_events(client, run_id)  # wait until it pauses
    assert client.post(f"/runs/{run_id}/approval", json={"approved": False}).status_code == 202
    read_events(client, run_id)
    assert client.get(f"/runs/{run_id}").json()["status"] == "rejected"
    assert client.post(f"/runs/{run_id}/approval", json={"approved": True}).status_code == 409


def test_redelivered_webhook_does_not_start_a_second_run(client, wp):
    first = post_brief(client, **{DELIVERY_HEADER: "delivery-42"})
    read_events(client, "delivery-42")
    again = post_brief(client, **{DELIVERY_HEADER: "delivery-42"})
    assert first.status_code == 202
    assert again.status_code == 200 and again.json()["duplicate"]
    assert len(wp.pages) == 3


def test_unknown_run_is_404(client):
    assert client.get("/runs/nope").status_code == 404
