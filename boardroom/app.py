"""Boardroom web app: JSON API + server-sent events + the static single-page UI."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from .billing import Billing, BillingError, verify_signature
from .board import BOARD_BY_KEY, GUEST_COLOR, ask_prompt, board_public, make_guest
from .config import Settings
from .costs import Prices, add_usage
from .db import Database
from .engine import Engine, EngineError, make_engine
from .hub import MeetingHub
from . import legal
from .mailer import Mailer
from .sample import SAMPLE_MEETING
from .meeting import run_meeting

STATIC = Path(__file__).parent / "static"
log = logging.getLogger(__name__)
RESET_MINUTES = 60
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


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class ForgotIn(BaseModel):
    email: str = Field(max_length=254)


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class PreferencesIn(BaseModel):
    remind_emails: bool


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=200)


class MeetingIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    context: str = Field(default="", max_length=6000)
    mode: Literal["quick", "deep"] = "quick"
    parent_id: int | None = None
    guest: GuestIn | None = None


class AskIn(BaseModel):
    advisor: Literal["analyst", "skeptic", "strategist", "operator", "guest"]
    question: str = Field(min_length=3, max_length=1000)


class StepIn(BaseModel):
    done: bool


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    billing: Billing | None = None,
    mailer: Mailer | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if mailer is None and settings.smtp_host:
        mailer = Mailer(
            settings.smtp_host, settings.smtp_port, settings.smtp_username,
            settings.smtp_password, settings.smtp_from,
        )
    if mailer is not None and not settings.public_url:
        # Links in emails must never be built from the request's Host header, which an
        # attacker controls (it would let them receive other people's reset tokens).
        log.warning("email is disabled: set BOARDROOM_PUBLIC_URL to enable password reset and reminders")
        mailer = None
    if billing is None and settings.billing_enabled:
        billing = Billing(settings.stripe_secret_key, settings.stripe_price_id, settings.stripe_webhook_secret)
    db = Database(settings.db_path)
    engine = engine or make_engine(settings)
    demo = engine.name == "demo"

    hub = MeetingHub()
    prices = Prices.from_env()
    # Meetings left "running" by a previous process can't resume.
    db.interrupt_running()

    def send_review_reminders() -> int:
        """Email users whose decisions are due for review. Returns how many were sent."""
        if mailer is None:
            return 0
        sent = 0
        base = settings.public_url
        for due in db.due_reviews(datetime.now(timezone.utc).date().isoformat()):
            try:
                mailer.send(
                    due["email"],
                    f"Time to review: {' '.join(due['question'].split())[:80]}",
                    f"Hi {due['name']},\n\nYour board asked to check back on this decision today:\n\n"
                    f"  {due['question']}\n\nThe Chair's verdict was: {due['headline']}\n\n"
                    f"See how it's going and reconvene the board here:\n{base}/#/m/{due['id']}\n\n"
                    "You can turn these reminders off in your account settings.\n",
                )
            except Exception:
                log.exception("failed to send review reminder for meeting %s", due["id"])
                continue
            db.mark_reminded(due["id"])
            sent += 1
        return sent

    async def reminder_loop() -> None:
        while True:
            try:
                await asyncio.to_thread(send_review_reminders)
            except Exception:
                log.exception("review reminder pass failed")
            await asyncio.sleep(3600)

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(reminder_loop()) if mailer is not None else None
        yield
        if task:
            task.cancel()
        await hub.shutdown()

    app = FastAPI(title="Boardroom", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.db = db
    app.state.hub = hub
    app.state.send_review_reminders = send_review_reminders

    app.state.engine = engine
    login_attempts: dict[str, deque] = defaultdict(deque)

    def throttle(key: str, limit: int = 8, window: float = 300.0) -> None:
        """Slow down password guessing: at most `limit` attempts per key per window."""
        now = time.monotonic()
        if len(login_attempts) > 10_000:
            # Forget keys with no attempts in the last hour so memory stays bounded.
            for k in [k for k, q in login_attempts.items() if not q or now - q[-1] > 3600]:
                del login_attempts[k]
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
            "connect-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
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
            "is_admin": user["email"] in settings.admin_emails,
            "remind_emails": bool(user["remind_emails"]),
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
            "password_reset": mailer is not None,
            "reminders": mailer is not None,
        }

    @app.post("/api/signup")
    def signup(body: SignupIn, request: Request, response: Response):
        throttle(f"signup:{request.client.host if request.client else '?'}", limit=10, window=3600)
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
        if not auth.verify_password_or_dummy(body.password, user["pw_hash"] if user else None):
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
        login_attempts.pop(f"email:{email}", None)
        start_session(response, user["id"])
        return user_out(user)

    @app.post("/api/password/forgot")
    def forgot_password(body: ForgotIn, request: Request):
        if mailer is None:
            raise HTTPException(status_code=404, detail="Password reset isn't set up on this server.")
        email = body.email.strip().lower()
        throttle(f"forgot:{email}", limit=3, window=3600)
        throttle(f"forgot-ip:{request.client.host if request.client else '?'}", limit=20, window=3600)
        user = db.user_by_email(email)
        if user is not None:
            token = secrets.token_urlsafe(32)
            expires = (datetime.now(timezone.utc) + timedelta(minutes=RESET_MINUTES)).isoformat(timespec="seconds")
            db.create_reset(_token_hash(token), user["id"], expires)
            link = f"{settings.public_url}/#/reset/{token}"
            try:
                mailer.send(
                    user["email"],
                    "Reset your Boardroom password",
                    f"Hi {user['name']},\n\nSomeone asked to reset the password for your Boardroom "
                    f"account. To choose a new password, open this link within {RESET_MINUTES} minutes:\n\n"
                    f"{link}\n\nIf this wasn't you, you can ignore this email; your password won't change.\n",
                )
            except Exception:
                log.exception("failed to send password reset email")
                raise HTTPException(status_code=502, detail="We couldn't send the email. Please try again later.")
        # Same answer whether or not the account exists, so emails can't be probed.
        return {"ok": True}

    @app.post("/api/password/reset")
    def reset_password(body: ResetIn, response: Response):
        user_id = db.consume_reset(_token_hash(body.token))
        if user_id is None:
            raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
        db.set_password(user_id, auth.hash_password(body.password))
        db.delete_all_sessions(user_id)
        start_session(response, user_id)
        return user_out(db.user_by_id(user_id))

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

    @app.post("/api/account/password")
    def change_password(body: PasswordChangeIn, request: Request, user=Depends(current_user)):
        throttle(f"pw:{user['id']}")
        if not auth.verify_password(body.current_password, user["pw_hash"]):
            raise HTTPException(status_code=401, detail="Your current password is incorrect.")
        db.set_password(user["id"], auth.hash_password(body.new_password))
        db.delete_other_sessions(user["id"], request.cookies.get(COOKIE, ""))
        return {"ok": True}

    @app.patch("/api/account/preferences")
    def preferences(body: PreferencesIn, user=Depends(current_user)):
        db.set_remind_emails(user["id"], body.remind_emails)
        return {"ok": True}

    @app.delete("/api/account")
    async def delete_account(body: DeleteAccountIn, response: Response, user=Depends(current_user)):
        throttle(f"pw:{user['id']}")
        if not auth.verify_password(body.password, user["pw_hash"]):
            raise HTTPException(status_code=401, detail="Password is incorrect.")
        await hub.cancel_user(user["id"])
        db.delete_user(user["id"])
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/admin/stats")
    def admin_stats(user=Depends(current_user)):
        if user["email"] not in settings.admin_emails:
            raise HTTPException(status_code=403, detail="Admins only.")
        stats = db.stats()
        stats["revenue"] = {
            "mrr_estimate_usd": round(stats["users"]["pro"] * settings.pro_price_usd, 2),
            "pro_price_usd": settings.pro_price_usd,
        }
        stats["engine"] = engine.name
        return stats

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
    async def delete_meeting(meeting_id: int, user=Depends(current_user)):
        await hub.cancel(meeting_id, user["id"])
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

    @app.get("/api/sample")
    def sample():
        return SAMPLE_MEETING

    @app.get("/api/account/export")
    def export_account(user=Depends(current_user)):
        data = {
            "account": {
                "email": user["email"], "name": user["name"], "plan": user["plan"],
                "created_at": user["created_at"],
            },
            "meetings": [
                db.get_meeting(user["id"], m["id"]) for m in db.list_meetings(user["id"], limit=100_000)
            ],
        }
        return Response(
            json.dumps(data, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="boardroom-export.json"'},
        )

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
        paid = obj.get("payment_status") in ("paid", "no_payment_required")
        if (
            kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded")
            and paid
            and obj.get("client_reference_id")
        ):
            # Delayed payment methods complete checkout unpaid; Pro waits for
            # async_payment_succeeded in that case.
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
        if not demo and user["plan"] == "pro" and quota["used_today"] >= settings.pro_daily_limit:
            raise HTTPException(
                status_code=429,
                detail=f"You've reached today's fair-use limit of {settings.pro_daily_limit} meetings. "
                "It resets at midnight UTC.",
            )
        if hub.running_count(user["id"]) >= settings.max_concurrent_meetings:
            raise HTTPException(
                status_code=429,
                detail="You already have meetings in session. Wait for one to finish before starting another.",
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

        meeting_id = await asyncio.to_thread(
            db.create_meeting, user["id"], question, context, body.mode, body.parent_id, guest
        )
        guest_advisor = make_guest(guest["name"], guest["perspective"]) if guest else None

        async def events():
            yield {"type": "meeting", "id": meeting_id, "mode": body.mode, "guest": guest_public(guest_advisor)}
            async for event in run_meeting(
                engine, db, meeting_id, question, context, body.mode, guest_advisor, prices
            ):
                yield event

        run = hub.start(meeting_id, user["id"], events())
        return _event_stream(run)

    @app.post("/api/meetings/{meeting_id}/ask")
    async def ask_advisor(meeting_id: int, body: AskIn, user=Depends(current_user)):
        m = await asyncio.to_thread(db.get_meeting, user["id"], meeting_id)
        if m is None:
            raise HTTPException(status_code=404, detail="Meeting not found.")
        if m["status"] != "done":
            raise HTTPException(status_code=409, detail="You can ask questions once the meeting has finished.")
        if body.advisor == "guest":
            if not m["guest"]:
                raise HTTPException(status_code=404, detail="This meeting had no guest advisor.")
            advisor = make_guest(m["guest"]["name"], m["guest"]["perspective"])
        else:
            advisor = BOARD_BY_KEY[body.advisor]
        if not demo:
            limit = settings.pro_daily_asks if user["plan"] == "pro" else settings.free_daily_asks
            if await asyncio.to_thread(db.asks_today, user["id"]) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"You've asked {limit} questions today. "
                    + ("Upgrade to Pro for more." if user["plan"] != "pro" else "The limit resets at midnight UTC."),
                )
        prompt = ask_prompt(
            advisor,
            m["question"],
            m["context"],
            date.today().strftime("%A, %B %d, %Y"),
            [t["text"] for t in m["takes"] if t["member"] == advisor.key and t["text"]],
            (m["verdict"] or {}).get("headline", ""),
            [(a["question"], a["answer"]) for a in m["asks"] if a["advisor"] == advisor.key],
            body.question,
        )

        async def stream():
            parts: list[str] = []
            usage: dict[str, int] = {}
            try:
                async for kind, payload in engine.take(advisor, prompt):
                    if kind == "text":
                        parts.append(payload)
                        yield _sse({"type": "delta", "text": payload})
                    elif kind == "status":
                        yield _sse({"type": "status", "text": payload})
                    elif kind == "sources":
                        yield _sse({"type": "sources", "sources": payload})
                    elif kind == "usage":
                        add_usage(usage, payload)
            except EngineError as exc:
                yield _sse({"type": "error", "message": str(exc)})
                return
            finally:
                if usage:
                    await asyncio.to_thread(db.add_usage, meeting_id, usage, prices.cost(usage))
            answer = "".join(parts).strip()
            await asyncio.to_thread(db.add_ask, meeting_id, advisor.key, body.question.strip(), answer)
            yield _sse({"type": "done", "answer": answer})

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/meetings/{meeting_id}/events")
    def follow_meeting(meeting_id: int, user=Depends(current_user)):
        run = hub.get(meeting_id, user["id"])
        if run is None:
            raise HTTPException(status_code=404, detail="This meeting isn't in session.")
        return _event_stream(run)

    # ---- UI -----------------------------------------------------------------

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    page = (STATIC / "index.html").read_text()

    def render_page(request: Request, title: str, description: str, path: str) -> HTMLResponse:
        base = settings.public_url or str(request.base_url).rstrip("/")
        values = {
            "__TITLE__": title,
            "__DESCRIPTION__": description,
            "__IMAGE__": f"{base}/static/og.png",
            "__URL__": f"{base}{path}",
        }
        out = page
        for key, value in values.items():
            out = out.replace(key, html.escape(value, quote=True))
        return HTMLResponse(out)

    @app.get("/")
    def index(request: Request):
        return render_page(
            request,
            "Boardroom — your private board of advisors",
            "Bring any hard decision to a private board of AI advisors. Watch them debate it "
            "live, then get a verdict and an action plan.",
            "/",
        )

    @app.get("/terms")
    def terms():
        return HTMLResponse(legal.render(
            "terms", "Boardroom", settings.company_name, settings.contact_email, settings.legal_updated
        ))

    @app.get("/privacy")
    def privacy():
        return HTMLResponse(legal.render(
            "privacy", "Boardroom", settings.company_name, settings.contact_email, settings.legal_updated
        ))

    @app.get("/s/{token}")
    def shared_page(token: str, request: Request):
        found = db.shared_meeting(token)
        if found is None or not found["verdict"]:
            return index(request)
        v = found["verdict"]
        return render_page(
            request,
            f"“{found['question'][:120]}” — the board's verdict",
            f"{v['headline']} ({v['confidence']}% confidence). Debated by an AI board of advisors on Boardroom.",
            f"/s/{token}",
        )

    @app.get("/healthz")
    def health():
        return {"ok": True, "engine": engine.name}

    return app


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
