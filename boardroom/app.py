"""Boardroom web app: JSON API + server-sent events + the static single-page UI."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from .billing import Billing, BillingError, verify_signature
from .board import GUEST_COLOR, board_public, make_guest
from .config import Settings
from .db import Database
from .engine import Engine, make_engine
from .hub import MeetingHub
from .meeting import run_meeting

STATIC = Path(__file__).parent / "static"
COOKIE = "boardroom_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class GuestIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    perspective: str = Field(default="", max_length=400)


class MeetingIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    context: str = Field(default="", max_length=6000)
    mode: Literal["quick", "deep"] = "quick"
    parent_id: int | None = None
    guest: GuestIn | None = None


class StepIn(BaseModel):
    done: bool


def create_app(
    settings: Settings | None = None, engine: Engine | None = None, billing: Billing | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    if billing is None and settings.billing_enabled:
        billing = Billing(settings.stripe_secret_key, settings.stripe_price_id, settings.stripe_webhook_secret)
    db = Database(settings.db_path)
    engine = engine or make_engine(settings)
    demo = engine.name == "demo"

    hub = MeetingHub()
    # Meetings left "running" by a previous process can't resume.
    db.interrupt_running()

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await hub.shutdown()

    app = FastAPI(title="Boardroom", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.db = db
    app.state.hub = hub
    app.state.engine = engine
    login_attempts: dict[str, deque] = defaultdict(deque)

    def throttle(key: str, limit: int = 8, window: float = 300.0) -> None:
        """Slow down password guessing: at most `limit` attempts per key per window."""
        now = time.monotonic()
        attempts = login_attempts[key]
        while attempts and now - attempts[0] > window:
            attempts.popleft()
        if len(attempts) >= limit:
            raise HTTPException(
                status_code=429, detail="Too many attempts. Please wait a few minutes and try again."
            )
        attempts.append(now)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    # ---- helpers ----------------------------------------------------------

    def current_user(request: Request) -> sqlite3.Row:
        token = request.cookies.get(COOKIE)
        user = db.session_user(token) if token else None
        if user is None:
            raise HTTPException(status_code=401, detail="Please sign in.")
        return user

    def start_session(response: Response, user_id: int) -> None:
        token, expires = auth.new_session()
        db.create_session(token, user_id, expires)
        response.set_cookie(
            COOKIE,
            token,
            max_age=auth.SESSION_DAYS * 86400,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookies,
        )

    def usage(user: sqlite3.Row) -> dict:
        unlimited = demo or user["plan"] == "pro"
        return {
            "plan": user["plan"],
            "used_today": db.meetings_today(user["id"]),
            "daily_limit": None if unlimited else settings.free_daily_limit,
            "deep_mode": unlimited,
        }

    def user_out(user: sqlite3.Row) -> dict:
        return {
            "email": user["email"],
            "name": user["name"],
            "usage": usage(user),
            "can_manage_billing": billing is not None and bool(user["stripe_customer_id"]),
        }

    # ---- public -----------------------------------------------------------

    @app.get("/api/config")
    def config():
        return {
            "demo": demo,
            "board": board_public(),
            "free_daily_limit": settings.free_daily_limit,
            "billing": billing is not None,
            "pro_price": settings.pro_price_label,
        }

    @app.post("/api/signup")
    def signup(body: SignupIn, response: Response):
        email = body.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="Please enter a valid email address.")
        try:
            user_id = db.create_user(email, body.name.strip(), auth.hash_password(body.password))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="An account with that email already exists.")
        start_session(response, user_id)
        return user_out(db.user_by_id(user_id))

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response):
        email = body.email.strip().lower()
        throttle(f"email:{email}")
        throttle(f"ip:{request.client.host if request.client else '?'}", limit=30)
        user = db.user_by_email(email)
        if user is None or not auth.verify_password(body.password, user["pw_hash"]):
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
        login_attempts.pop(f"email:{email}", None)
        start_session(response, user["id"])
        return user_out(user)

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        if token:
            db.delete_session(token)
        response.delete_cookie(COOKIE)
        return {"ok": True}

    # ---- signed in ----------------------------------------------------------

    @app.get("/api/me")
    def me(user=Depends(current_user)):
        return user_out(user)

    @app.get("/api/meetings")
    def meetings(user=Depends(current_user)):
        return db.list_meetings(user["id"])

    @app.get("/api/meetings/{meeting_id}")
    def meeting(meeting_id: int, user=Depends(current_user)):
        found = db.get_meeting(user["id"], meeting_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Meeting not found.")
        return with_guest_card(found)

    @app.delete("/api/meetings/{meeting_id}")
    def delete_meeting(meeting_id: int, user=Depends(current_user)):
        if not db.delete_meeting(user["id"], meeting_id):
            raise HTTPException(status_code=404, detail="Meeting not found.")
        return {"ok": True}

    @app.post("/api/meetings/{meeting_id}/share")
    def share(meeting_id: int, user=Depends(current_user)):
        found = db.get_meeting(user["id"], meeting_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Meeting not found.")
        if found["status"] != "done":
            raise HTTPException(status_code=409, detail="Only finished meetings can be shared.")
        token = found["share_token"] or secrets.token_urlsafe(12)
        db.set_share_token(user["id"], meeting_id, token)
        return {"token": token}

    @app.delete("/api/meetings/{meeting_id}/share")
    def unshare(meeting_id: int, user=Depends(current_user)):
        if db.get_meeting(user["id"], meeting_id) is None:
            raise HTTPException(status_code=404, detail="Meeting not found.")
        db.set_share_token(user["id"], meeting_id, None)
        return {"ok": True}

    @app.get("/api/shared/{token}")
    def shared(token: str):
        found = db.shared_meeting(token)
        if found is None:
            raise HTTPException(status_code=404, detail="This link is no longer shared.")
        return with_guest_card(found)

    # ---- billing ----------------------------------------------------------

    def base_url(request: Request) -> str:
        return settings.public_url or str(request.base_url).rstrip("/")

    def require_billing() -> Billing:
        if billing is None:
            raise HTTPException(status_code=404, detail="Billing isn't set up on this server.")
        return billing

    @app.post("/api/billing/checkout")
    def checkout(request: Request, user=Depends(current_user)):
        b = require_billing()
        if user["plan"] == "pro":
            raise HTTPException(status_code=409, detail="You're already on Pro.")
        try:
            url = b.checkout_url(user["id"], user["email"], user["stripe_customer_id"], base_url(request))
        except BillingError as exc:
            raise HTTPException(status_code=502, detail=f"Payment setup failed: {exc}")
        return {"url": url}

    @app.post("/api/billing/portal")
    def portal(request: Request, user=Depends(current_user)):
        b = require_billing()
        if not user["stripe_customer_id"]:
            raise HTTPException(status_code=404, detail="No billing account yet.")
        try:
            return {"url": b.portal_url(user["stripe_customer_id"], base_url(request))}
        except BillingError as exc:
            raise HTTPException(status_code=502, detail=f"Couldn't open billing: {exc}")

    @app.post("/api/billing/webhook")
    async def webhook(request: Request):
        b = require_billing()
        payload = await request.body()
        signature = request.headers.get("stripe-signature", "")
        if not b.webhook_secret or not verify_signature(payload, signature, b.webhook_secret):
            raise HTTPException(status_code=400, detail="Invalid signature.")
        event = json.loads(payload)
        obj = event.get("data", {}).get("object", {})
        kind = event.get("type")
        if kind == "checkout.session.completed" and obj.get("client_reference_id"):
            try:
                user_id = int(obj["client_reference_id"])
            except ValueError:
                return {"ok": True}
            db.set_plan_by_id(user_id, "pro", obj.get("customer"))
        elif kind in ("customer.subscription.updated", "customer.subscription.deleted"):
            active = kind == "customer.subscription.updated" and obj.get("status") in (
                "active", "trialing", "past_due"
            )
            if obj.get("customer"):
                db.set_plan_by_customer(obj["customer"], "pro" if active else "free")
        return {"ok": True}

    @app.patch("/api/steps/{step_id}")
    def update_step(step_id: int, body: StepIn, user=Depends(current_user)):
        if not db.set_step_done(user["id"], step_id, body.done):
            raise HTTPException(status_code=404, detail="Step not found.")
        return {"ok": True}

    @app.post("/api/meetings")
    async def convene(body: MeetingIn, user=Depends(current_user)):
        quota = usage(user)
        if quota["daily_limit"] is not None and quota["used_today"] >= quota["daily_limit"]:
            raise HTTPException(
                status_code=429,
                detail=f"You've used all {quota['daily_limit']} free meetings for today. "
                "Upgrade to Pro for unlimited meetings, or come back tomorrow.",
            )
        if body.mode == "deep" and not quota["deep_mode"]:
            raise HTTPException(status_code=403, detail="Deep debates are a Pro feature.")

        question = body.question.strip()
        context = body.context.strip()
        guest = body.guest.model_dump() if body.guest else None
        if guest:
            guest = {"name": " ".join(guest["name"].split()), "perspective": guest["perspective"].strip()}
        if body.parent_id is not None:
            parent = db.get_meeting(user["id"], body.parent_id)
            if parent is None:
                raise HTTPException(status_code=404, detail="Original meeting not found.")
            earlier = f"This is a follow-up to an earlier board meeting about: {parent['question']}"
            if parent["verdict"]:
                v = parent["verdict"]
                earlier += f"\nThe Chair's verdict then: {v['headline']} {v['verdict']}"
            if parent["context"]:
                earlier += f"\nEarlier background: {parent['context']}"
            context = f"{earlier}\n\n{context}".strip()
            guest = guest or parent["guest"]

        meeting_id = db.create_meeting(user["id"], question, context, body.mode, body.parent_id, guest)
        guest_advisor = make_guest(guest["name"], guest["perspective"]) if guest else None

        async def events():
            yield {"type": "meeting", "id": meeting_id, "mode": body.mode, "guest": guest_public(guest_advisor)}
            async for event in run_meeting(engine, db, meeting_id, question, context, body.mode, guest_advisor):
                yield event

        run = hub.start(meeting_id, user["id"], events())
        return _event_stream(run)

    @app.get("/api/meetings/{meeting_id}/events")
    def follow_meeting(meeting_id: int, user=Depends(current_user)):
        run = hub.get(meeting_id, user["id"])
        if run is None:
            raise HTTPException(status_code=404, detail="This meeting isn't in session.")
        return _event_stream(run)

    # ---- UI -----------------------------------------------------------------

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/healthz")
    def health():
        return {"ok": True, "engine": engine.name}

    return app


def with_guest_card(meeting: dict) -> dict:
    g = meeting.get("guest")
    meeting["guest"] = guest_public(make_guest(g["name"], g["perspective"])) if g else None
    return meeting


def guest_public(advisor) -> dict | None:
    if advisor is None:
        return None
    return {"key": "guest", "name": advisor.name, "role": advisor.role, "initials": advisor.initials, "color": GUEST_COLOR}


def _event_stream(run) -> StreamingResponse:
    async def stream():
        async for event in run.follow():
            yield _sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
