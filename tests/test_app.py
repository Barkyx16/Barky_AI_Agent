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

    async def verdict(self, prompt, **kwargs):
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
    assert me["usage"] == {"plan": "free", "used_today": 0, "daily_limit": 2, "deep_mode": False, "bonus_meetings": 0}
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
        {"type": "checkout.session.completed", "data": {"object": {"client_reference_id": user_id, "customer": "cus_1", "payment_status": "paid"}}},
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


class FlakySkepticEngine(DemoEngine):
    async def take(self, advisor, prompt):
        if advisor.key == "skeptic":
            raise EngineError("The AI service had a hiccup. Please try again.")
            yield  # pragma: no cover - makes this an async generator
        async for event in super().take(advisor, prompt):
            yield event


class AllDownEngine(DemoEngine):
    async def take(self, advisor, prompt):
        raise EngineError("Couldn't reach the AI service.")
        yield  # pragma: no cover


def test_one_advisor_failing_does_not_end_the_meeting(tmp_path):
    client = make_client(tmp_path, engine=FlakySkepticEngine(delay=0))
    signup(client)
    evs = events(client.post("/api/meetings", json={"question": "Should I renovate?"}))
    errors = [e for e in evs if e["type"] == "advisor_error"]
    assert [e["advisor"] for e in errors] == ["skeptic"]
    assert evs[-1]["type"] == "done"
    m = client.get(f"/api/meetings/{evs[0]['id']}").json()
    assert m["status"] == "done"
    assert {t["member"] for t in m["takes"]} == {"analyst", "strategist", "operator"}


def test_whole_board_failing_reports_an_error(tmp_path):
    client = make_client(tmp_path, engine=AllDownEngine(delay=0))
    signup(client)
    evs = events(client.post("/api/meetings", json={"question": "Anyone there?"}))
    assert evs[-1] == {"type": "error", "message": "Couldn't reach the AI service."}
    assert client.get(f"/api/meetings/{evs[0]['id']}").json()["status"] == "failed"


def test_signup_is_throttled(tmp_path):
    client = make_client(tmp_path)
    codes = [
        client.post("/api/signup", json={"email": f"u{i}@example.com", "name": "U", "password": "password1"}).status_code
        for i in range(11)
    ]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_change_password_signs_out_other_devices(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    other = TestClient(client.app)
    other.post("/api/login", json={"email": "ada@example.com", "password": "correct horse"})
    assert other.get("/api/me").status_code == 200
    assert client.post("/api/account/password", json={"current_password": "wrong", "new_password": "new password"}).status_code == 401
    assert client.post("/api/account/password", json={"current_password": "correct horse", "new_password": "new password"}).status_code == 200
    assert client.get("/api/me").status_code == 200
    assert other.get("/api/me").status_code == 401
    client.post("/api/logout")
    assert client.post("/api/login", json={"email": "ada@example.com", "password": "new password"}).status_code == 200


def test_delete_account_removes_everything(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "Delete my data?"}))[0]["id"]
    token = client.post(f"/api/meetings/{meeting_id}/share").json()["token"]
    assert client.request("DELETE", "/api/account", json={"password": "nope"}).status_code == 401
    assert client.request("DELETE", "/api/account", json={"password": "correct horse"}).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.get(f"/api/shared/{token}").status_code == 404
    with client.app.state.db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM meetings").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 0
    signup(client)  # the email is free again


# ---- password reset -------------------------------------------------------


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))


def reset_client(tmp_path):
    mailer = FakeMailer()
    app = create_app(settings(tmp_path, public_url="https://boardroom.app"), engine=DemoEngine(delay=0), mailer=mailer)
    return TestClient(app), mailer


def test_password_reset_flow(tmp_path):
    client, mailer = reset_client(tmp_path)
    assert client.get("/api/config").json()["password_reset"] is True
    signup(client)
    other = TestClient(client.app)
    other.post("/api/login", json={"email": "ada@example.com", "password": "correct horse"})
    client.post("/api/logout")

    # Unknown emails get the same answer and no email.
    assert client.post("/api/password/forgot", json={"email": "nobody@example.com"}).json() == {"ok": True}
    assert mailer.sent == []

    assert client.post("/api/password/forgot", json={"email": "ADA@example.com"}).status_code == 200
    to, subject, body = mailer.sent[-1]
    assert to == "ada@example.com" and "Reset" in subject
    token = body.split("/#/reset/")[1].split()[0]

    assert client.post("/api/password/reset", json={"token": "x" * 20, "password": "brand new pw"}).status_code == 400
    r = client.post("/api/password/reset", json={"token": token, "password": "brand new pw"})
    assert r.status_code == 200 and r.json()["name"] == "Ada"
    assert client.get("/api/me").status_code == 200          # signed in on this device
    assert other.get("/api/me").status_code == 401            # everywhere else signed out
    assert client.post("/api/password/reset", json={"token": token, "password": "again again"}).status_code == 400  # single use
    client.post("/api/logout")
    assert client.post("/api/login", json={"email": "ada@example.com", "password": "brand new pw"}).status_code == 200


def test_reset_tokens_expire(tmp_path):
    client, mailer = reset_client(tmp_path)
    signup(client)
    client.post("/api/password/forgot", json={"email": "ada@example.com"})
    token = mailer.sent[-1][2].split("/#/reset/")[1].split()[0]
    with client.app.state.db.conn() as c:
        c.execute("UPDATE password_resets SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert client.post("/api/password/reset", json={"token": token, "password": "brand new pw"}).status_code == 400


def test_reset_disabled_without_smtp(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/config").json()["password_reset"] is False
    assert client.post("/api/password/forgot", json={"email": "a@example.com"}).status_code == 404


# ---- usage & cost tracking -------------------------------------------------


class MeteredEngine(DemoEngine):
    async def take(self, advisor, prompt):
        async for event in super().take(advisor, prompt):
            yield event
        searches = 1 if advisor.key == "analyst" else 0
        yield ("usage", {"input_tokens": 1000, "output_tokens": 500, "web_searches": searches})

    async def verdict(self, prompt, on_usage=None, on_draft=None):
        if on_usage:
            on_usage({"input_tokens": 3000, "output_tokens": 1000, "cache_read_tokens": 10000})
        return await super().verdict(prompt)


def test_usage_and_cost_are_recorded(tmp_path):
    from boardroom.costs import Prices

    client = make_client(tmp_path, engine=MeteredEngine(delay=0))
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "What does this cost?"}))[0]["id"]
    with client.app.state.db.conn() as c:
        row = dict(c.execute("SELECT input_tokens, output_tokens, cache_read_tokens, web_searches, cost_usd FROM meetings WHERE id = ?", (meeting_id,)).fetchone())
    assert row["input_tokens"] == 4 * 1000 + 3000
    assert row["output_tokens"] == 4 * 500 + 1000
    assert row["cache_read_tokens"] == 10000 and row["web_searches"] == 1
    expected = Prices().cost({"input_tokens": 7000, "output_tokens": 3000, "cache_read_tokens": 10000, "web_searches": 1})
    assert row["cost_usd"] == pytest.approx(expected)
    assert expected == pytest.approx(7000 * 4e-6 + 3000 * 20e-6 + 10000 * 0.2e-6 + 0.01)


def test_admin_stats_are_admin_only(tmp_path):
    client = make_client(tmp_path, engine=MeteredEngine(delay=0), admin_emails=("boss@example.com",), pro_price_usd=15.0)
    signup(client)  # ada, not an admin
    events(client.post("/api/meetings", json={"question": "First question"}))
    assert client.get("/api/me").json()["is_admin"] is False
    assert client.get("/api/admin/stats").status_code == 403
    client.app.state.db.set_plan("ada@example.com", "pro")
    client.post("/api/logout")
    signup(client, email="boss@example.com")
    assert client.get("/api/me").json()["is_admin"] is True
    stats = client.get("/api/admin/stats").json()
    assert stats["users"] == {"total": 2, "pro": 1, "new_7d": 2, "active_7d": 1}
    assert stats["meetings"]["total"] == 1 and stats["meetings"]["today"] == 1
    assert stats["revenue"]["mrr_estimate_usd"] == 15.0
    assert stats["cost"]["avg_per_meeting_usd"] > 0
    assert len(stats["daily"]) == 14
    assert stats["daily"][-1]["meetings"] == 1 and stats["daily"][-1]["signups"] == 2


def test_export_contains_all_my_data(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    events(client.post("/api/meetings", json={"question": "Export me", "context": "secret notes"}))
    r = client.get("/api/account/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["account"]["email"] == "ada@example.com"
    assert data["meetings"][0]["question"] == "Export me"
    assert data["meetings"][0]["context"] == "secret notes"
    assert len(data["meetings"][0]["steps"]) == 5
    client.post("/api/logout")
    assert client.get("/api/account/export").status_code == 401


def test_sample_meeting_is_public_and_well_formed(tmp_path):
    from boardroom.board import Verdict

    client = make_client(tmp_path)
    data = client.get("/api/sample").json()
    Verdict.model_validate({**data["verdict"], "steps": data["steps"]})
    assert {t["member"] for t in data["takes"]} == {"analyst", "skeptic", "strategist", "operator"}


# ---- review dates & reminders ----------------------------------------------


def test_verdict_sets_a_review_date_and_reminders_send_once(tmp_path):
    from datetime import date, timedelta

    client, mailer = reset_client(tmp_path)
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "Should I learn Spanish?"}))[0]["id"]
    m = client.get(f"/api/meetings/{meeting_id}").json()
    assert m["verdict"]["review_in_days"] == 30
    assert m["review_at"] == (date.today() + timedelta(days=30)).isoformat()
    assert client.get("/api/meetings").json()[0]["review_at"] == m["review_at"]

    send = client.app.state.send_review_reminders
    assert send() == 0  # not due yet
    with client.app.state.db.conn() as c:
        c.execute("UPDATE meetings SET review_at = ?", ((date.today() - timedelta(days=1)).isoformat(),))
    assert send() == 1
    to, subject, body = mailer.sent[-1]
    assert to == "ada@example.com" and "Spanish" in subject and f"/#/m/{meeting_id}" in body
    assert send() == 0  # only once


def test_reminders_respect_opt_out(tmp_path):
    from datetime import date

    client, mailer = reset_client(tmp_path)
    signup(client)
    assert client.get("/api/me").json()["remind_emails"] is True
    events(client.post("/api/meetings", json={"question": "Opt out test"}))
    assert client.patch("/api/account/preferences", json={"remind_emails": False}).status_code == 200
    assert client.get("/api/me").json()["remind_emails"] is False
    with client.app.state.db.conn() as c:
        c.execute("UPDATE meetings SET review_at = ?", (date.today().isoformat(),))
    assert client.app.state.send_review_reminders() == 0
    assert mailer.sent == []


def test_shared_page_has_link_preview_tags(tmp_path):
    client = make_client(tmp_path, public_url="https://boardroom.app")
    signup(client)
    evs = events(client.post("/api/meetings", json={"question": 'Should I quit? <script>alert("x")</script>'}))
    token = client.post(f"/api/meetings/{evs[0]['id']}/share").json()["token"]
    client.post("/api/logout")
    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    assert '<meta property="og:title" content="“Should I quit? &lt;script&gt;' in page.text
    assert "<script>alert" not in page.text
    assert "72% confidence" in page.text
    assert 'content="https://boardroom.app/static/og.png"' in page.text
    assert f'content="https://boardroom.app/s/{token}"' in page.text
    # Unknown tokens fall back to the normal page (the app shows "no longer shared").
    fallback = client.get("/s/unknown-token")
    assert fallback.status_code == 200 and "your private board of advisors" in fallback.text
    assert client.get("/static/og.png").headers["content-type"] == "image/png"


# ---- regressions from code review -----------------------------------------


def test_reminder_subject_has_no_newlines(tmp_path):
    from datetime import date

    client, mailer = reset_client(tmp_path)
    signup(client)
    events(client.post("/api/meetings", json={"question": "Should I move?\nWe have two kids"}))
    with client.app.state.db.conn() as c:
        c.execute("UPDATE meetings SET review_at = ?", (date.today().isoformat(),))
    assert client.app.state.send_review_reminders() == 1
    subject = mailer.sent[-1][1]
    assert "\n" not in subject and "Should I move? We have two kids" in subject


def test_reminders_without_any_known_url_are_skipped(tmp_path):
    mailer = FakeMailer()
    app = create_app(settings(tmp_path), engine=DemoEngine(delay=0), mailer=mailer)
    assert app.state.send_review_reminders() == 0  # no public URL, no request seen yet


def test_unpaid_checkout_does_not_grant_pro(tmp_path):
    client, _ = billing_client(tmp_path)
    signup(client)
    uid = "1"
    obj = {"client_reference_id": uid, "customer": "cus_9", "payment_status": "unpaid"}
    body, header = _signed({"type": "checkout.session.completed", "data": {"object": obj}}, "whsec_test")
    client.post("/api/billing/webhook", content=body, headers={"stripe-signature": header})
    assert client.get("/api/me").json()["usage"]["plan"] == "free"
    obj["payment_status"] = "paid"
    body, header = _signed({"type": "checkout.session.async_payment_succeeded", "data": {"object": obj}}, "whsec_test")
    client.post("/api/billing/webhook", content=body, headers={"stripe-signature": header})
    assert client.get("/api/me").json()["usage"]["plan"] == "pro"


@pytest.mark.anyio
async def test_cancelling_a_run_stops_it():
    from boardroom.hub import MeetingHub

    async def endless():
        while True:
            await asyncio.sleep(0.01)
            yield {"type": "tick"}

    hub = MeetingHub()
    run = hub.start(5, user_id=1, events=endless())
    await asyncio.sleep(0.05)
    await hub.cancel(5, user_id=2)  # someone else's: ignored
    assert not run.task.done()
    await hub.cancel_user(1)
    assert run.task.done() and run.finished


# ---- security hardening ----------------------------------------------------


def test_session_tokens_are_hashed_at_rest(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    token = client.cookies.get("boardroom_session")
    with client.app.state.db.conn() as c:
        stored = [r[0] for r in c.execute("SELECT token FROM sessions")]
    assert token not in stored
    assert all(len(t) == 64 for t in stored)
    assert client.get("/api/me").status_code == 200


def test_email_features_need_a_public_url(tmp_path):
    mailer = FakeMailer()
    app = create_app(settings(tmp_path), engine=DemoEngine(delay=0), mailer=mailer)
    client = TestClient(app)
    assert client.get("/api/config").json()["password_reset"] is False
    signup(client)
    r = client.post("/api/password/forgot", json={"email": "ada@example.com"}, headers={"host": "evil.example"})
    assert r.status_code == 404 and mailer.sent == []


def test_reset_links_ignore_the_host_header(tmp_path):
    client, mailer = reset_client(tmp_path)
    signup(client)
    client.post("/api/password/forgot", json={"email": "ada@example.com"}, headers={"host": "evil.example"})
    assert "https://boardroom.app/#/reset/" in mailer.sent[-1][2]
    assert "evil.example" not in mailer.sent[-1][2]


def test_concurrent_meeting_limit(tmp_path):
    client = make_client(tmp_path, max_concurrent_meetings=1)
    signup(client)
    hub = client.app.state.hub
    uid = client.app.state.db.user_by_email("ada@example.com")["id"]
    from boardroom.hub import MeetingRun

    hub.runs[999] = MeetingRun(uid)  # pretend one is still in session
    r = client.post("/api/meetings", json={"question": "One more?"})
    assert r.status_code == 429 and "in session" in r.json()["detail"]
    hub.runs[999].finished = True
    assert client.post("/api/meetings", json={"question": "Now?"}).status_code == 200


def test_pro_fair_use_cap(tmp_path):
    client = make_client(tmp_path, engine=PaidEngine(delay=0), demo_mode=False, pro_daily_limit=2)
    signup(client)
    client.app.state.db.set_plan("ada@example.com", "pro")
    for _ in range(2):
        assert client.post("/api/meetings", json={"question": "Pro question"}).status_code == 200
    r = client.post("/api/meetings", json={"question": "Third"})
    assert r.status_code == 429 and "fair-use" in r.json()["detail"]


def test_installable_app_assets(tmp_path):
    client = make_client(tmp_path)
    page = client.get("/").text
    assert 'rel="manifest"' in page and 'rel="apple-touch-icon"' in page
    manifest = client.get("/static/manifest.webmanifest").json()
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200


def test_advisors_reply_in_the_users_language():
    from boardroom.board import BOARD, CHAIR_SYSTEM, advisor_system

    assert "language the person wrote" in CHAIR_SYSTEM
    assert all("language the person wrote" in advisor_system(a) for a in BOARD)


def test_legal_pages(tmp_path):
    client = make_client(tmp_path, company_name="Acme <LLC>", contact_email="help@acme.test")
    terms = client.get("/terms")
    assert terms.status_code == 200
    assert "Terms of Service" in terms.text and "Not professional advice" in terms.text
    assert "Acme &lt;LLC&gt;" in terms.text and "<LLC>" not in terms.text
    assert "help@acme.test" in terms.text
    privacy = client.get("/privacy").text
    assert "<h1>Privacy Policy</h1>" in privacy and "<strong>We do not sell your personal information.</strong>" in privacy
    assert "{" not in privacy


def test_backup_command(tmp_path, monkeypatch):
    import sqlite3 as sq

    from boardroom.__main__ import main

    db_path = tmp_path / "live.db"
    monkeypatch.setenv("BOARDROOM_DB_PATH", str(db_path))
    client = make_client(tmp_path, db_path=str(db_path))
    signup(client)
    dest = tmp_path / "backups" / "copy.db"
    assert main(["backup", str(dest)]) == 0
    with sq.connect(dest) as c:
        assert c.execute("SELECT email FROM users").fetchone()[0] == "ada@example.com"


# ---- ask an advisor --------------------------------------------------------


def test_ask_an_advisor(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    guest = {"name": "My mentor", "perspective": "Twenty years in the industry."}
    meeting_id = events(client.post("/api/meetings", json={"question": "Should I go freelance?", "guest": guest}))[0]["id"]

    evs = events(client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "skeptic", "question": "What's the worst case?"}))
    assert evs[-1]["type"] == "done"
    answer = "".join(e["text"] for e in evs if e["type"] == "delta")
    assert "The Skeptic" in answer and answer == evs[-1]["answer"]

    events(client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "guest", "question": "What would you do?"}))
    asks = client.get(f"/api/meetings/{meeting_id}").json()["asks"]
    assert [(a["advisor"], a["question"]) for a in asks] == [("skeptic", "What's the worst case?"), ("guest", "What would you do?")]
    assert "My mentor" in asks[1]["answer"]

    # Private: not on the shared page.
    token = client.post(f"/api/meetings/{meeting_id}/share").json()["token"]
    assert client.get(f"/api/shared/{token}").json()["asks"] == []
    assert "worst case" not in client.get(f"/api/shared/{token}").text


def test_ask_validation_and_ownership(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "No guest here"}))[0]["id"]
    assert client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "guest", "question": "Hello?"}).status_code == 404
    assert client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "chair", "question": "Hello?"}).status_code == 422
    with client.app.state.db.conn() as c:
        c.execute("UPDATE meetings SET status = 'running'")
    assert client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "skeptic", "question": "Hello?"}).status_code == 409
    client.post("/api/logout")
    signup(client, email="eve@example.com")
    assert client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "skeptic", "question": "Hello?"}).status_code == 404


def test_ask_daily_limit_and_cost(tmp_path):
    class PaidMetered(MeteredEngine):
        name = "claude"

    client = make_client(tmp_path, engine=PaidMetered(delay=0), demo_mode=False, free_daily_asks=2)
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "Limit me"}))[0]["id"]
    with client.app.state.db.conn() as c:
        before = c.execute("SELECT output_tokens FROM meetings WHERE id = ?", (meeting_id,)).fetchone()[0]
    for _ in range(2):
        assert client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "operator", "question": "Next step?"}).status_code == 200
    r = client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "operator", "question": "Again?"})
    assert r.status_code == 429 and "Upgrade" in r.json()["detail"]
    with client.app.state.db.conn() as c:
        after = c.execute("SELECT output_tokens FROM meetings WHERE id = ?", (meeting_id,)).fetchone()[0]
    assert after == before + 2 * 500


def test_verdict_options_are_sorted_and_clamped(tmp_path):
    class WildOptions(DemoEngine):
        async def verdict(self, prompt, on_usage=None, on_draft=None):
            v = await super().verdict(prompt)
            v.options[0].score = 140
            v.options[1].score = -5
            v.options.append(v.options[0].model_copy(update={"name": "Extra", "score": 50}))
            v.options.append(v.options[0].model_copy(update={"name": "Too many", "score": 10}))
            return v

    client = make_client(tmp_path, engine=WildOptions(delay=0))
    signup(client)
    evs = events(client.post("/api/meetings", json={"question": "Which option?"}))
    opts = next(e["verdict"]["options"] for e in evs if e["type"] == "verdict")
    assert [o["score"] for o in opts] == [100, 50, 35, 10]  # clamped, sorted, lowest dropped
    assert len(opts) == 4


# ---- referrals --------------------------------------------------------------


def test_referrals_grant_bonus_meetings(tmp_path):
    client = make_client(tmp_path, engine=PaidEngine(delay=0), demo_mode=False, free_daily_limit=1, referral_bonus=2, referral_cap=3)
    signup(client)  # ada, the referrer
    info = client.get("/api/referral").json()
    assert info["bonus"] == 2 and info["invited"] == 0
    code = info["code"]
    assert client.get("/api/referral").json()["code"] == code  # stable
    client.post("/api/logout")

    r = client.post("/api/signup", json={"email": "bo@example.com", "name": "Bo", "password": "password1", "ref": code})
    assert r.json()["usage"]["bonus_meetings"] == 2
    db = client.app.state.db
    assert db.user_by_email("ada@example.com")["bonus_meetings"] == 0  # paid only after Bo's first real meeting
    # Bo: 1 free + 2 bonus meetings today, then out. A rejected deep request doesn't spend a bonus.
    assert client.post("/api/meetings", json={"question": "Free one"}).status_code == 200
    assert db.user_by_email("ada@example.com")["bonus_meetings"] == 2
    assert client.post("/api/meetings", json={"question": "Deep", "mode": "deep"}).status_code == 403
    assert client.get("/api/me").json()["usage"]["bonus_meetings"] == 2
    for _ in range(2):
        assert client.post("/api/meetings", json={"question": "Bonus one"}).status_code == 200
    assert client.post("/api/meetings", json={"question": "Too many"}).status_code == 429
    assert db.user_by_email("ada@example.com")["bonus_meetings"] == 2  # still one payout per referral
    client.post("/api/logout")

    # A second referral only tops Ada up to the cap of 3.
    client.post("/api/signup", json={"email": "cy@example.com", "name": "Cy", "password": "password1", "ref": code})
    assert client.post("/api/meetings", json={"question": "Cy's first"}).status_code == 200
    client.post("/api/logout")
    client.post("/api/login", json={"email": "ada@example.com", "password": "correct horse"})
    info = client.get("/api/referral").json()
    assert info["invited"] == 2 and info["earned"] == 3
    assert client.get("/api/me").json()["usage"]["bonus_meetings"] == 3


def test_bad_or_self_referral_codes_do_nothing(tmp_path):
    client = make_client(tmp_path)
    r = client.post("/api/signup", json={"email": "x@example.com", "name": "X", "password": "password1", "ref": "nope"})
    assert r.status_code == 200 and r.json()["usage"]["bonus_meetings"] == 0


# ---- streamed verdict drafts -------------------------------------------------


def test_partial_field_handles_unfinished_json():
    from boardroom.meeting import partial_field

    assert partial_field('{"head', "headline") == ""
    assert partial_field('{"headline": "Test it sm', "headline") == "Test it sm"
    assert partial_field('{"headline": "Say \\"no\\" fir', "headline") == 'Say "no" fir'
    assert partial_field('{"headline": "Line\\', "headline") == "Line"
    assert partial_field('{"headline": "Done.", "verdict": "Because \\u00e9', "verdict") == "Because é"
    assert partial_field('{"headline": "Done.", "verdict": "x"}', "headline") == "Done."


def test_chair_drafts_stream_before_the_verdict(tmp_path):
    client = make_client(tmp_path)
    signup(client)
    evs = events(client.post("/api/meetings", json={"question": "Stream the verdict?"}))
    kinds = [e["type"] for e in evs]
    drafts = [e for e in evs if e["type"] == "chair_draft"]
    assert len(drafts) > 3
    assert kinds.index("chair_start") < kinds.index("chair_draft") < kinds.index("verdict")
    final = next(e["verdict"] for e in evs if e["type"] == "verdict")
    assert drafts[-1]["headline"] == final["headline"]
    assert final["verdict"].startswith(drafts[-1]["verdict"])
    # Drafts only ever grow.
    heads = [d["headline"] for d in drafts]
    assert all(b.startswith(a) for a, b in zip(heads, heads[1:]))


def test_record_decision_outcome(tmp_path):
    client = make_client(tmp_path, admin_emails=("ada@example.com",))
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "Did it work?"}))[0]["id"]
    r = client.patch(f"/api/meetings/{meeting_id}/outcome", json={"outcome": "great", "note": "Got the job!"})
    assert r.status_code == 200
    m = client.get(f"/api/meetings/{meeting_id}").json()
    assert m["outcome"] == "great" and m["outcome_note"] == "Got the job!"
    assert client.get("/api/meetings").json()[0]["outcome"] == "great"
    assert client.get("/api/admin/stats").json()["outcomes"] == {"great": 1, "mixed": 0, "bad": 0}
    token = client.post(f"/api/meetings/{meeting_id}/share").json()["token"]
    assert client.get(f"/api/shared/{token}").json()["outcome"] is None  # private
    assert client.patch(f"/api/meetings/{meeting_id}/outcome", json={"outcome": "meh"}).status_code == 422
    assert client.patch(f"/api/meetings/{meeting_id}/outcome", json={"outcome": None}).status_code == 200
    assert client.get(f"/api/meetings/{meeting_id}").json()["outcome"] is None
    client.post("/api/logout")
    signup(client, email="eve@example.com")
    assert client.patch(f"/api/meetings/{meeting_id}/outcome", json={"outcome": "bad"}).status_code == 404


# ---- board focus -------------------------------------------------------------


class RecordingEngine(DemoEngine):
    def __init__(self):
        super().__init__(delay=0)
        self.prompts = []

    async def take(self, advisor, prompt):
        self.prompts.append(prompt)
        async for event in super().take(advisor, prompt):
            yield event

    async def verdict(self, prompt, on_usage=None, on_draft=None):
        self.prompts.append(prompt)
        return await super().verdict(prompt, on_usage, on_draft)


def test_board_focus_reaches_every_prompt(tmp_path):
    engine = RecordingEngine()
    client = make_client(tmp_path, engine=engine)
    signup(client)
    assert {"key": "money", "label": "Money"} in client.get("/api/config").json()["focus_areas"]
    evs = events(client.post("/api/meetings", json={"question": "Pay off debt or invest?", "focus": "money", "mode": "deep"}))
    assert evs[0]["focus"] == "money"
    assert len(engine.prompts) == 4 + 4 + 1
    assert all("Money board" in p and "cash flow" in p for p in engine.prompts)
    meeting_id = evs[0]["id"]
    assert client.get(f"/api/meetings/{meeting_id}").json()["focus"] == "money"

    engine.prompts.clear()
    events(client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "analyst", "question": "What rate?"}))
    assert "Money board" in engine.prompts[0]

    follow = events(client.post("/api/meetings", json={"question": "And if rates drop?", "parent_id": meeting_id}))
    assert follow[0]["focus"] == "money"
    assert client.post("/api/meetings", json={"question": "Bad focus", "focus": "astrology"}).status_code == 422


def test_no_focus_by_default(tmp_path):
    engine = RecordingEngine()
    client = make_client(tmp_path, engine=engine)
    signup(client)
    events(client.post("/api/meetings", json={"question": "General question"}))
    assert not any("board. " in p and "asked for a" in p for p in engine.prompts)


# ---- regressions from the second review --------------------------------------


def test_deleting_meetings_does_not_restore_quota(tmp_path):
    client = make_client(tmp_path, engine=PaidEngine(delay=0), demo_mode=False, free_daily_limit=1, free_daily_asks=1)
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "Only one today"}))[0]["id"]
    events(client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "skeptic", "question": "Worst case?"}))
    assert client.delete(f"/api/meetings/{meeting_id}").status_code == 200
    assert client.get("/api/me").json()["usage"]["used_today"] == 1
    assert client.post("/api/meetings", json={"question": "Sneaky second"}).status_code == 429


def test_failed_bonus_meeting_is_refunded(tmp_path):
    class PaidBroken(BrokenEngine):
        name = "claude"

    client = make_client(tmp_path, engine=PaidBroken(delay=0), demo_mode=False, free_daily_limit=0)
    signup(client)
    client.app.state.db.conn  # noqa: B018
    with client.app.state.db.conn() as c:
        c.execute("UPDATE users SET bonus_meetings = 1")
    evs = events(client.post("/api/meetings", json={"question": "Will fail"}))
    assert evs[-1]["type"] == "error"
    assert client.get("/api/me").json()["usage"]["bonus_meetings"] == 1


def test_interrupted_meetings_refund_quota_on_restart(tmp_path):
    from boardroom.db import Database

    db = Database(str(tmp_path / "test.db"))
    uid = db.create_user("x@example.com", "X", "h")
    db.create_meeting(uid, "Q?", "", "quick", None)
    assert db.meetings_today(uid) == 1
    make_client(tmp_path)  # restart marks it interrupted
    assert db.meetings_today(uid) == 0


def test_question_limit_is_atomic_and_counted_up_front(tmp_path):
    from boardroom.db import Database

    db = Database(str(tmp_path / "q.db"))
    uid = db.create_user("x@example.com", "X", "h")
    assert db.try_log_ask(uid, 1, 2) and db.try_log_ask(uid, 1, 2)
    assert not db.try_log_ask(uid, 1, 2)
    assert db.try_log_ask(uid, 1, None)  # demo: unlimited, still logged

    class PaidFlaky(FlakySkepticEngine):
        name = "claude"

    client = make_client(tmp_path, engine=PaidFlaky(delay=0), demo_mode=False, free_daily_asks=1)
    signup(client)
    meeting_id = events(client.post("/api/meetings", json={"question": "Ask the flaky skeptic"}))[0]["id"]
    evs = events(client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "skeptic", "question": "Hello?"}))
    assert evs[-1]["type"] == "error"
    # The failed call still used the day's question, and it isn't shown in the thread.
    assert client.post(f"/api/meetings/{meeting_id}/ask", json={"advisor": "operator", "question": "Again?"}).status_code == 429
    assert client.get(f"/api/meetings/{meeting_id}").json()["asks"] == []


def test_partial_unicode_escape_is_hidden():
    from boardroom.meeting import partial_field

    assert partial_field('{"verdict": "Don\\u2019t quit \\u20', "verdict") == "Don\u2019t quit "


def test_backup_does_not_touch_the_live_database(tmp_path, monkeypatch):
    import sqlite3 as sq

    from boardroom.__main__ import main

    live = tmp_path / "live.db"
    with sq.connect(live) as c:
        c.execute("CREATE TABLE sessions (token TEXT, user_id INTEGER, expires_at TEXT)")
        c.execute("INSERT INTO sessions VALUES ('short-old-token', 1, '2999-01-01')")
    monkeypatch.setenv("BOARDROOM_DB_PATH", str(live))
    assert main(["backup", str(tmp_path / "b.db")]) == 0
    with sq.connect(live) as c:
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1  # no migrations ran
        assert [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")] == ["sessions"]
