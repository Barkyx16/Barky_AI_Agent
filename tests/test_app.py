import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from boardroom.app import create_app
from boardroom.auth import hash_password, verify_password
from boardroom.config import Settings
from boardroom.engine import DemoEngine, EngineError


def settings(tmp_path, **overrides):
    base = dict(
        model="test-model",
        db_path=str(tmp_path / "test.db"),
        web_search=False,
        free_daily_limit=2,
        secure_cookies=False,
        demo_mode=True,
        demo_delay=0,
    )
    base.update(overrides)
    return Settings(**base)


class PaidEngine(DemoEngine):
    """Demo output, but reported as a real engine so plan limits apply."""

    name = "claude"


class BrokenEngine(DemoEngine):
    name = "claude"

    async def verdict(self, prompt):
        raise EngineError("The board is at capacity right now.")


def make_client(tmp_path, engine=None, **overrides):
    app = create_app(settings(tmp_path, **overrides), engine=engine or DemoEngine(delay=0))
    return TestClient(app)


def signup(client, email="ada@example.com"):
    r = client.post("/api/signup", json={"email": email, "name": "Ada", "password": "correct horse"})
    assert r.status_code == 200, r.text
    return r.json()


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_password_hashing():
    stored = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")


def test_config_and_index(tmp_path):
    client = make_client(tmp_path)
    cfg = client.get("/api/config").json()
    assert cfg["demo"] is True
    assert [a["key"] for a in cfg["board"]] == ["analyst", "skeptic", "strategist", "operator", "chair"]
    page = client.get("/")
    assert page.status_code == 200
    assert "Boardroom" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]


def test_auth_flow(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/me").status_code == 401
    me = signup(client)
    assert me["name"] == "Ada"
    assert client.post("/api/signup", json={"email": "ADA@example.com", "name": "A", "password": "another pass"}).status_code == 409
    assert client.post("/api/signup", json={"email": "not-an-email", "name": "A", "password": "12345678"}).status_code == 422
    assert client.post("/api/signup", json={"email": "b@example.com", "name": "B", "password": "short"}).status_code == 422
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login", json={"email": "ada@example.com", "password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"email": "Ada@Example.com", "password": "correct horse"}).status_code == 200
    assert client.get("/api/me").status_code == 200


def test_quick_meeting_streams_and_persists(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    r = client.post("/api/meetings", json={"question": "Should I learn to fly planes?", "mode": "quick"})
    assert r.status_code == 200
    evs = events(r)
    assert evs[0]["type"] == "meeting"
    meeting_id = evs[0]["id"]
    kinds = [e["type"] for e in evs]
    assert kinds.count("advisor_done") == 4
    assert "round_start" in kinds and "chair_start" in kinds
    assert kinds[-2:] == ["verdict", "done"]
    assert 0 <= evs[-2]["verdict"]["confidence"] <= 100
    statuses = [e for e in evs if e["type"] == "status"]
    assert statuses and statuses[0]["advisor"] == "analyst"

    m = client.get(f"/api/meetings/{meeting_id}").json()
    assert m["status"] == "done"
    assert {t["member"] for t in m["takes"]} == {"analyst", "skeptic", "strategist", "operator"}
    assert all("fly planes" in t["text"] for t in m["takes"])
    assert len(m["steps"]) == 5

    step = m["steps"][0]
    assert client.patch(f"/api/steps/{step['id']}", json={"done": True}).status_code == 200
    listing = client.get("/api/meetings").json()
    assert listing[0]["done_steps"] == 1 and listing[0]["total_steps"] == 5
    assert listing[0]["headline"]


def test_deep_meeting_has_rebuttals(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    evs = events(client.post("/api/meetings", json={"question": "Buy or rent?", "mode": "deep"}))
    rounds = [e["round"] for e in evs if e["type"] == "round_start"]
    assert rounds == [1, 2]
    meeting_id = evs[0]["id"]
    takes = client.get(f"/api/meetings/{meeting_id}").json()["takes"]
    assert len(takes) == 8


def test_followup_includes_parent_context(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    first = events(client.post("/api/meetings", json={"question": "Should I start a bakery?"}))[0]["id"]
    second = events(client.post("/api/meetings", json={"question": "What if I wait a year?", "parent_id": first}))[0]["id"]
    m = client.get(f"/api/meetings/{second}").json()
    assert m["parent_id"] == first
    assert "start a bakery" in m["context"]


def test_users_are_isolated(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "Private question"}))[0]["id"]
    step_id = client.get(f"/api/meetings/{meeting_id}").json()["steps"][0]["id"]
    client.post("/api/logout")
    signup(client, email="eve@example.com")
    assert client.get(f"/api/meetings/{meeting_id}").status_code == 404
    assert client.patch(f"/api/steps/{step_id}", json={"done": True}).status_code == 404
    assert client.delete(f"/api/meetings/{meeting_id}").status_code == 404
    assert client.get("/api/meetings").json() == []
    assert client.post("/api/meetings", json={"question": "Sneaky follow-up", "parent_id": meeting_id}).status_code == 404


def test_free_plan_limits(tmp_path):
    client = make_client(tmp_path, engine=PaidEngine(delay=0), demo_mode=False)
    signup(client)
    me = client.get("/api/me").json()
    assert me["usage"] == {"plan": "free", "used_today": 0, "daily_limit": 2, "deep_mode": False}
    assert client.post("/api/meetings", json={"question": "Deep one", "mode": "deep"}).status_code == 403
    for _ in range(2):
        assert client.post("/api/meetings", json={"question": "Question here"}).status_code == 200
    r = client.post("/api/meetings", json={"question": "One too many"})
    assert r.status_code == 429
    assert "Upgrade" in r.json()["detail"]


def test_pro_plan_is_unlimited(tmp_path):
    client = make_client(tmp_path, engine=PaidEngine(delay=0), demo_mode=False)
    signup(client)
    client.app.state.db.set_plan("ada@example.com", "pro")
    for _ in range(3):
        assert client.post("/api/meetings", json={"question": "Question here", "mode": "deep"}).status_code == 200


def test_engine_error_is_reported_and_meeting_marked_failed(tmp_path):
    client = make_client(tmp_path, engine=BrokenEngine(delay=0))
    signup(client)
    evs = events(client.post("/api/meetings", json={"question": "Will this work?"}))
    assert evs[-1] == {"type": "error", "message": "The board is at capacity right now."}
    m = client.get(f"/api/meetings/{evs[0]['id']}").json()
    assert m["status"] == "failed"
    assert m["verdict"] is None


def test_delete_meeting(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "Delete me"}))[0]["id"]
    assert client.delete(f"/api/meetings/{meeting_id}").status_code == 200
    assert client.get(f"/api/meetings/{meeting_id}").status_code == 404


def test_validation(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    assert client.post("/api/meetings", json={"question": "x"}).status_code == 422
    assert client.post("/api/meetings", json={"question": "Valid?", "mode": "turbo"}).status_code == 422


# ---- Claude engine wiring, with a fake SDK client ---------------------------


class FakeStream:
    def __init__(self, message, texts):
        self.message, self.texts = message, texts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            yield SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="server_tool_use"))
            for t in self.texts:
                yield SimpleNamespace(type="text", text=t)
        return gen()

    async def get_final_message(self):
        return self.message


class FakeMessages:
    def __init__(self):
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        result = SimpleNamespace(
            type="web_search_tool_result",
            content=[SimpleNamespace(url="https://example.com/a", title="Example A")],
        )
        if len(self.calls) == 1:
            msg = SimpleNamespace(stop_reason="pause_turn", content=[result])
            return FakeStream(msg, ["Looking. "])
        msg = SimpleNamespace(stop_reason="end_turn", content=[result])
        return FakeStream(msg, ["Found it."])


@pytest.mark.anyio
async def test_claude_engine_resumes_pause_turn_and_collects_sources():
    from boardroom.board import BOARD_BY_KEY
    from boardroom.engine import ClaudeEngine

    messages = FakeMessages()
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    engine = ClaudeEngine(model="claude-opus-5-5", web_search=True, client=client)
    out = [e async for e in engine.take(BOARD_BY_KEY["analyst"], "prompt")]

    assert ("text", "Looking. ") in out and ("text", "Found it.") in out
    assert out[-1] == ("sources", [{"url": "https://example.com/a", "title": "Example A"}])
    assert len(messages.calls) == 2
    first = messages.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default"
    assert first["thinking"] == {"type": "adaptive"}
    assert first["tools"][0]["type"] == "web_search_20260209"
    # The paused assistant turn is re-sent unchanged to resume.
    assert messages.calls[1]["messages"][-1]["role"] == "assistant"


@pytest.fixture
def anyio_backend():
    return "asyncio"
