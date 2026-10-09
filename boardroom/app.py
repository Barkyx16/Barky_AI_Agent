"""Boardroom web app: JSON API + server-sent events + the static single-page UI."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from .board import board_public
from .config import Settings
from .db import Database
from .engine import Engine, make_engine
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


class MeetingIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    context: str = Field(default="", max_length=6000)
    mode: Literal["quick", "deep"] = "quick"
    parent_id: int | None = None


class StepIn(BaseModel):
    done: bool


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)
    engine = engine or make_engine(settings)
    demo = engine.name == "demo"

    app = FastAPI(title="Boardroom", docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.engine = engine

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
        return {"email": user["email"], "name": user["name"], "usage": usage(user)}

    # ---- public -----------------------------------------------------------

    @app.get("/api/config")
    def config():
        return {"demo": demo, "board": board_public(), "free_daily_limit": settings.free_daily_limit}

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
    def login(body: LoginIn, response: Response):
        user = db.user_by_email(body.email.strip().lower())
        if user is None or not auth.verify_password(body.password, user["pw_hash"]):
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
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
        return found

    @app.delete("/api/meetings/{meeting_id}")
    def delete_meeting(meeting_id: int, user=Depends(current_user)):
        if not db.delete_meeting(user["id"], meeting_id):
            raise HTTPException(status_code=404, detail="Meeting not found.")
        return {"ok": True}

    @app.patch("/api/steps/{step_id}")
    def update_step(step_id: int, body: StepIn, user=Depends(current_user)):
        if not db.set_step_done(user["id"], step_id, body.done):
            raise HTTPException(status_code=404, detail="Step not found.")
        return {"ok": True}

    @app.post("/api/meetings")
    def convene(body: MeetingIn, user=Depends(current_user)):
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

        meeting_id = db.create_meeting(user["id"], question, context, body.mode, body.parent_id)

        async def stream():
            yield _sse({"type": "meeting", "id": meeting_id, "mode": body.mode})
            async for event in run_meeting(engine, db, meeting_id, question, context, body.mode):
                yield _sse(event)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- UI -----------------------------------------------------------------

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/healthz")
    def health():
        return {"ok": True, "engine": engine.name}

    return app


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
