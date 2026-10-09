"""Runs one board meeting: opening remarks, optional rebuttals, then the Chair's verdict.

Advisors speak concurrently; their streams are merged into a single event feed that the
web layer forwards to the browser as server-sent events.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, AsyncIterator

from .board import BOARD, chair_prompt, opening_prompt, rebuttal_prompt
from .db import Database
from .engine import Engine, EngineError

_DONE = object()
log = logging.getLogger(__name__)


async def _run_round(
    engine: Engine,
    round_no: int,
    prompts: dict[str, str],
    db: Database,
    meeting_id: int,
    results: dict[str, str],
) -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue = asyncio.Queue()

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
                elif kind == "sources":
                    sources = list(payload)
                    await queue.put({"type": "sources", "advisor": advisor.key, "round": round_no, "sources": sources})
            text = "".join(parts).strip()
            results[advisor.key] = text
            db.save_take(meeting_id, advisor.key, round_no, text, sources)
            await queue.put({"type": "advisor_done", "advisor": advisor.key, "round": round_no})
        except Exception as exc:  # surfaced to the client by the round loop
            await queue.put(exc)
        finally:
            await queue.put(_DONE)

    tasks = [asyncio.create_task(speak(a)) for a in BOARD]
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
) -> AsyncIterator[dict[str, Any]]:
    today = date.today().strftime("%A, %B %d, %Y")
    finished = False
    try:
        yield {"type": "round_start", "round": 1}
        opening: dict[str, str] = {}
        prompts = {a.key: opening_prompt(question, context, today) for a in BOARD}
        async for event in _run_round(engine, 1, prompts, db, meeting_id, opening):
            yield event
        rounds = [dict((a.key, opening.get(a.key, "")) for a in BOARD)]

        if mode == "deep":
            yield {"type": "round_start", "round": 2}
            rebuttals: dict[str, str] = {}
            prompts = {
                a.key: rebuttal_prompt(a, question, context, today, rounds[0]) for a in BOARD
            }
            async for event in _run_round(engine, 2, prompts, db, meeting_id, rebuttals):
                yield event
            rounds.append(dict((a.key, rebuttals.get(a.key, "")) for a in BOARD))

        yield {"type": "chair_start"}
        verdict = await engine.verdict(chair_prompt(question, context, today, rounds))
        data = verdict.model_dump()
        data["confidence"] = max(0, min(100, int(data["confidence"])))
        db.finish_meeting(meeting_id, data)
        finished = True
        yield {"type": "verdict", "verdict": data}
        yield {"type": "done", "steps": db_meeting_steps(db, meeting_id)}
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
            # The client went away mid-meeting.
            db.fail_meeting(meeting_id, status="interrupted")


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
