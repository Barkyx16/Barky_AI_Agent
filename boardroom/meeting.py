"""Runs one board meeting: opening remarks, optional rebuttals, then the Chair's verdict.

Advisors speak concurrently; their streams are merged into a single event feed that the
web layer forwards to the browser as server-sent events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator

from .board import Advisor, chair_prompt, opening_prompt, rebuttal_prompt, seats
from .costs import Prices, add_usage
from .db import Database
from .engine import Engine, EngineError

_DONE = object()
log = logging.getLogger(__name__)


async def _run_round(
    engine: Engine,
    board: tuple[Advisor, ...],
    round_no: int,
    prompts: dict[str, str],
    db: Database,
    meeting_id: int,
    results: dict[str, str],
    usage: dict[str, int],
) -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue = asyncio.Queue()
    failures: list[EngineError] = []

    async def speak(advisor) -> None:
        parts: list[str] = []
        sources: list[dict] = []
        try:
            async for kind, payload in engine.take(advisor, prompts[advisor.key]):
                if kind == "text":
                    parts.append(payload)
                    await queue.put({"type": "delta", "advisor": advisor.key, "round": round_no, "text": payload})
                elif kind == "status":
                    await queue.put({"type": "status", "advisor": advisor.key, "round": round_no, "text": payload})
                elif kind == "usage":
                    add_usage(usage, payload)
                elif kind == "sources":
                    sources = list(payload)
                    await queue.put({"type": "sources", "advisor": advisor.key, "round": round_no, "sources": sources})
            text = "".join(parts).strip()
            results[advisor.key] = text
            await asyncio.to_thread(db.save_take, meeting_id, advisor.key, round_no, text, sources)
            await queue.put({"type": "advisor_done", "advisor": advisor.key, "round": round_no})
        except EngineError as exc:
            # One advisor failing shouldn't end the meeting; they sit this round out.
            failures.append(exc)
            await queue.put({"type": "advisor_error", "advisor": advisor.key, "round": round_no, "message": str(exc)})
        except Exception as exc:  # surfaced to the client by the round loop
            await queue.put(exc)
        finally:
            await queue.put(_DONE)

    tasks = [asyncio.create_task(speak(a)) for a in board]
    remaining = len(tasks)
    try:
        while remaining:
            item = await queue.get()
            if item is _DONE:
                remaining -= 1
            elif isinstance(item, Exception):
                raise item
            else:
                yield item
        if failures and len(failures) == len(board):
            raise failures[0]
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_meeting(
    engine: Engine,
    db: Database,
    meeting_id: int,
    question: str,
    context: str,
    mode: str,
    guest: Advisor | None = None,
    prices: Prices | None = None,
    focus: str = "",
) -> AsyncIterator[dict[str, Any]]:
    prices = prices or Prices()
    usage: dict[str, int] = {}
    board = seats(guest)
    by_key = {a.key: a for a in board}
    today = date.today().strftime("%A, %B %d, %Y")
    finished = False
    try:
        yield {"type": "round_start", "round": 1}
        opening: dict[str, str] = {}
        prompts = {a.key: opening_prompt(question, context, today, focus) for a in board}
        async for event in _run_round(engine, board, 1, prompts, db, meeting_id, opening, usage):
            yield event
        rounds = [dict((a.key, opening.get(a.key, "")) for a in board)]

        if mode == "deep":
            yield {"type": "round_start", "round": 2}
            rebuttals: dict[str, str] = {}
            prompts = {
                a.key: rebuttal_prompt(a, question, context, today, rounds[0], by_key, focus) for a in board
            }
            async for event in _run_round(engine, board, 2, prompts, db, meeting_id, rebuttals, usage):
                yield event
            rounds.append(dict((a.key, rebuttals.get(a.key, "")) for a in board))

        yield {"type": "chair_start"}
        drafts: asyncio.Queue = asyncio.Queue()
        chair = asyncio.create_task(engine.verdict(
            chair_prompt(question, context, today, rounds, by_key, focus),
            on_usage=lambda u: add_usage(usage, u),
            on_draft=drafts.put_nowait,
        ))
        try:
            shown: dict[str, str] = {}
            while not chair.done() or not drafts.empty():
                getter = asyncio.ensure_future(drafts.get())
                done, _ = await asyncio.wait({chair, getter}, return_when=asyncio.FIRST_COMPLETED)
                if getter not in done:
                    getter.cancel()
                    continue
                text = getter.result()
                while not drafts.empty():  # skip ahead to the newest draft
                    text = drafts.get_nowait()
                draft = {k: partial_field(text, k) for k in ("headline", "verdict")}
                if draft != shown and any(draft.values()):
                    shown = draft
                    yield {"type": "chair_draft", **draft}
            verdict = await chair
        finally:
            if not chair.done():
                chair.cancel()
                await asyncio.gather(chair, return_exceptions=True)
        data = verdict.model_dump()
        data["confidence"] = max(0, min(100, int(data["confidence"])))
        data["votes"] = [v for v in data["votes"] if v["advisor"] in by_key]
        data["review_in_days"] = max(1, min(365, int(data["review_in_days"])))
        data["options"] = sorted(
            ({**o, "score": max(0, min(100, int(o["score"])))} for o in data.get("options", [])),
            key=lambda o: -o["score"],
        )[:4]
        today_utc = datetime.now(timezone.utc).date()
        review_at = (today_utc + timedelta(days=data["review_in_days"])).isoformat()
        await asyncio.to_thread(db.finish_meeting, meeting_id, data, review_at)
        finished = True
        yield {"type": "verdict", "verdict": data}
        yield {"type": "done", "steps": await asyncio.to_thread(db_meeting_steps, db, meeting_id)}
    except EngineError as exc:
        db.fail_meeting(meeting_id)
        finished = True
        yield {"type": "error", "message": str(exc)}
    except Exception:
        log.exception("meeting %s failed", meeting_id)
        db.fail_meeting(meeting_id)
        finished = True
        yield {"type": "error", "message": "Something went wrong during the meeting. Please try again."}
    finally:
        if not finished:
            # The server stopped mid-meeting.
            db.fail_meeting(meeting_id, status="interrupted")
        db.record_usage(meeting_id, usage, prices.cost(usage))


_FIELD_RE = {}


def partial_field(text: str, field: str) -> str:
    """The (possibly unfinished) value of a top-level string field in streaming JSON."""
    pattern = _FIELD_RE.get(field)
    if pattern is None:
        pattern = _FIELD_RE[field] = re.compile(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)')
    match = pattern.search(text)
    if not match:
        return ""
    raw = match.group(1)
    if raw.endswith("\\") and not raw.endswith("\\\\"):
        raw = raw[:-1]  # an escape sequence cut in half
    try:
        return json.loads(f'"{raw}"')
    except ValueError:
        return raw.replace('\\"', '"')


def db_meeting_steps(db: Database, meeting_id: int) -> list[dict[str, Any]]:
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, title, detail, timing, done FROM steps WHERE meeting_id = ? ORDER BY position",
            (meeting_id,),
        ).fetchall()
    return [
        {"id": r["id"], "title": r["title"], "detail": r["detail"], "when": r["timing"], "done": bool(r["done"])}
        for r in rows
    ]
