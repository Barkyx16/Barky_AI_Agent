import asyncio
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


def test_share_links_are_public_and_private_details_hidden(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    evs = events(client.post("/api/meetings", json={"question": "Should I sell my car?", "context": "My salary is 52k"}))
    meeting_id = evs[0]["id"]
    step_id = client.get(f"/api/meetings/{meeting_id}").json()["steps"][0]["id"]
    client.patch(f"/api/steps/{step_id}", json={"done": True})

    token = client.post(f"/api/meetings/{meeting_id}/share").json()["token"]
    assert client.post(f"/api/meetings/{meeting_id}/share").json()["token"] == token  # stable
    client.post("/api/logout")

    public = client.get(f"/api/shared/{token}")
    assert public.status_code == 200
    data = public.json()
    assert data["question"] == "Should I sell my car?"
    assert data["verdict"]["headline"]
    assert len(data["takes"]) == 4
    assert "52k" not in public.text
    assert "context" not in data and "id" not in data
    assert not any(s["done"] for s in data["steps"])

    client.post("/api/login", json={"email": "ada@example.com", "password": "correct horse"})
    assert client.delete(f"/api/meetings/{meeting_id}/share").status_code == 200
    assert client.get(f"/api/shared/{token}").status_code == 404


def test_cannot_share_someone_elses_or_unfinished_meeting(tmp_path):
    client = make_client(tmp_path, engine=BrokenEngine(delay=0))
    signup(client)
    failed = events(client.post("/api/meetings", json={"question": "Will this work?"}))[0]["id"]
    assert client.post(f"/api/meetings/{failed}/share").status_code == 409
    client.post("/api/logout")
    signup(client, email="eve@example.com")
    assert client.post(f"/api/meetings/{failed}/share").status_code == 404
    assert client.get("/api/shared/not-a-real-token").status_code == 404


def test_login_is_throttled(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    client.post("/api/logout")
    codes = [client.post("/api/login", json={"email": "ada@example.com", "password": "wrong pass"}).status_code for _ in range(9)]
    assert codes[:8] == [401] * 8
    assert codes[8] == 429


def test_guest_advisor_joins_the_board(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    guest = {"name": "Your future self", "perspective": "You, ten years from now, looking back."}
    evs = events(client.post("/api/meetings", json={"question": "Should I move abroad?", "mode": "deep", "guest": guest}))
    assert evs[0]["guest"] == {"key": "guest", "name": "Your future self", "role": "Guest advisor", "initials": "YF", "color": "#ec4899"}
    done = [e["advisor"] for e in evs if e["type"] == "advisor_done"]
    assert done.count("guest") == 2 and len(done) == 10
    verdict = next(e["verdict"] for e in evs if e["type"] == "verdict")
    assert "guest" in {v["advisor"] for v in verdict["votes"]}

    meeting_id = evs[0]["id"]
    m = client.get(f"/api/meetings/{meeting_id}").json()
    assert m["guest"]["name"] == "Your future self"
    assert any(t["member"] == "guest" and "Your future self" in t["text"] for t in m["takes"])

    # Follow-ups keep the same guest seat.
    follow = events(client.post("/api/meetings", json={"question": "And if I wait?", "parent_id": meeting_id}))
    assert follow[0]["guest"]["name"] == "Your future self"


def test_votes_only_from_advisors_present(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    evs = events(client.post("/api/meetings", json={"question": "No guest today"}))
    assert evs[0]["guest"] is None
    verdict = next(e["verdict"] for e in evs if e["type"] == "verdict")
    assert {v["advisor"] for v in verdict["votes"]} == {"analyst", "skeptic", "strategist", "operator"}


def test_guest_validation(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    assert client.post("/api/meetings", json={"question": "Valid?", "guest": {"name": "X"}}).status_code == 422


# ---- billing --------------------------------------------------------------

import hashlib
import hmac
import time as _time

from boardroom.billing import Billing, verify_signature


def _signed(payload: dict, secret: str, ts: int | None = None):
    body = json.dumps(payload).encode()
    ts = ts or int(_time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def billing_client(tmp_path):
    calls = []

    def fake_post(key, path, params):
        calls.append((path, params))
        return {"url": f"https://stripe.test{path}"}

    billing = Billing("sk_test", "price_123", "whsec_test", post=fake_post)
    app = create_app(
        settings(tmp_path, demo_mode=False, public_url="https://boardroom.app"),
        engine=PaidEngine(delay=0),
        billing=billing,
    )
    return TestClient(app), calls


def test_signature_verification():
    body, header = _signed({"a": 1}, "whsec_x")
    assert verify_signature(body, header, "whsec_x")
    assert not verify_signature(body, header, "whsec_other")
    assert not verify_signature(body + b" ", header, "whsec_x")
    old_body, old_header = _signed({"a": 1}, "whsec_x", ts=int(_time.time()) - 3600)
    assert not verify_signature(old_body, old_header, "whsec_x")
    assert not verify_signature(body, "garbage", "whsec_x")


def test_checkout_and_subscription_lifecycle(tmp_path):
    client, calls = billing_client(tmp_path)
    assert client.get("/api/config").json()["billing"] is True
    signup(client)
    me = client.get("/api/me").json()
    assert me["usage"]["plan"] == "free" and me["can_manage_billing"] is False

    r = client.post("/api/billing/checkout")
    assert r.json()["url"] == "https://stripe.test/checkout/sessions"
    path, params = calls[-1]
    assert params["line_items[0][price]"] == "price_123"
    assert params["customer_email"] == "ada@example.com"
    assert params["success_url"] == "https://boardroom.app/#/billing/success"
    user_id = params["client_reference_id"]

    # Forged webhook is rejected.
    body, _ = _signed({"type": "checkout.session.completed"}, "wrong")
    bad = client.post("/api/billing/webhook", content=body, headers={"stripe-signature": "t=1,v1=00"})
    assert bad.status_code == 400

    body, header = _signed(
        {"type": "checkout.session.completed", "data": {"object": {"client_reference_id": user_id, "customer": "cus_1"}}},
        "whsec_test",
    )
    assert client.post("/api/billing/webhook", content=body, headers={"stripe-signature": header}).status_code == 200
    me = client.get("/api/me").json()
    assert me["usage"]["plan"] == "pro" and me["can_manage_billing"] is True
    assert client.post("/api/billing/checkout").status_code == 409
    assert client.post("/api/billing/portal").json()["url"] == "https://stripe.test/billing_portal/sessions"

    body, header = _signed(
        {"type": "customer.subscription.deleted", "data": {"object": {"customer": "cus_1", "status": "canceled"}}},
        "whsec_test",
    )
    client.post("/api/billing/webhook", content=body, headers={"stripe-signature": header})
    assert client.get("/api/me").json()["usage"]["plan"] == "free"


def test_billing_disabled_without_keys(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    assert client.get("/api/config").json()["billing"] is False
    assert client.post("/api/billing/checkout").status_code == 404


# ---- resilient meetings ---------------------------------------------------


def test_reattach_replays_the_meeting(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    first = events(client.post("/api/meetings", json={"question": "Replay me"}))
    meeting_id = first[0]["id"]
    replay = events(client.get(f"/api/meetings/{meeting_id}/events"))
    assert replay == first
    client.post("/api/logout")
    signup(client, email="eve@example.com")
    assert client.get(f"/api/meetings/{meeting_id}/events").status_code == 404


@pytest.mark.anyio
async def test_meeting_keeps_running_when_viewer_leaves():
    from boardroom.hub import MeetingHub

    async def slow():
        for i in range(5):
            await asyncio.sleep(0.01)
            yield {"type": "tick", "i": i}

    hub = MeetingHub()
    run = hub.start(1, user_id=7, events=slow())
    async for event in run.follow():
        break  # viewer disconnects after the first event
    await run.task
    assert [e["i"] for e in run.events] == [0, 1, 2, 3, 4]
    assert run.finished
    assert hub.get(1, user_id=8) is None
    late = [e async for e in hub.get(1, user_id=7).follow()]
    assert len(late) == 5


def test_failed_meetings_do_not_use_quota(tmp_path):
    class PaidBroken(BrokenEngine):
        name = "claude"

    client = make_client(tmp_path, engine=PaidBroken(delay=0), demo_mode=False)
    signup(client)
    for _ in range(3):
        events(client.post("/api/meetings", json={"question": "Will this fail?"}))
    assert client.get("/api/me").json()["usage"]["used_today"] == 0


def test_stale_running_meetings_are_marked_interrupted(tmp_path):
    from boardroom.db import Database

    db = Database(str(tmp_path / "test.db"))
    uid = db.create_user("x@example.com", "X", "h")
    mid = db.create_meeting(uid, "Q?", "", "quick", None)
    make_client(tmp_path)  # a fresh server process starts
    assert db.get_meeting(uid, mid)["status"] == "interrupted"
