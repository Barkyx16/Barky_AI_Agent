"""Keeps meetings running independently of browser connections.

Each meeting runs as a background task that appends events to an in-memory log. Any
number of clients can attach, replay from the start, and follow along live — so a
refresh, a dropped connection, or a second tab never interrupts the meeting.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

KEEP_FINISHED_SECONDS = 600


class MeetingRun:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.events: list[dict[str, Any]] = []
        self.finished = False
        self.finished_at = 0.0
        self.changed = asyncio.Condition()
        self.task: asyncio.Task | None = None

    async def publish(self, event: dict[str, Any]) -> None:
        async with self.changed:
            self.events.append(event)
            self.changed.notify_all()

    async def finish(self) -> None:
        async with self.changed:
            self.finished = True
            self.finished_at = time.monotonic()
            self.changed.notify_all()

    async def follow(self, start: int = 0) -> AsyncIterator[dict[str, Any]]:
        index = start
        while True:
            async with self.changed:
                await self.changed.wait_for(lambda: index < len(self.events) or self.finished)
                batch = self.events[index:]
                done = self.finished
            for event in batch:
                yield event
            index += len(batch)
            if done and index >= len(self.events):
                return


class MeetingHub:
    def __init__(self) -> None:
        self.runs: dict[int, MeetingRun] = {}

    def start(self, meeting_id: int, user_id: int, events: AsyncIterator[dict[str, Any]]) -> MeetingRun:
        self._prune()
        run = MeetingRun(user_id)
        self.runs[meeting_id] = run

        async def pump() -> None:
            try:
                async for event in events:
                    await run.publish(event)
            finally:
                await run.finish()

        run.task = asyncio.create_task(pump())
        return run

    def get(self, meeting_id: int, user_id: int) -> MeetingRun | None:
        run = self.runs.get(meeting_id)
        return run if run and run.user_id == user_id else None

    async def cancel(self, meeting_id: int, user_id: int) -> None:
        run = self.get(meeting_id, user_id)
        if run and run.task and not run.task.done():
            run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)

    async def cancel_user(self, user_id: int) -> None:
        for mid, run in list(self.runs.items()):
            if run.user_id == user_id:
                await self.cancel(mid, user_id)

    def _prune(self) -> None:
        now = time.monotonic()
        for mid in [m for m, r in self.runs.items() if r.finished and now - r.finished_at > KEEP_FINISHED_SECONDS]:
            del self.runs[mid]

    async def shutdown(self) -> None:
        tasks = [r.task for r in self.runs.values() if r.task and not r.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
