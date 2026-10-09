"""SQLite storage. One short-lived connection per operation keeps things simple and safe."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    pw_hash     TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'free',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meetings (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_id   INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
    question    TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '',
    mode        TEXT NOT NULL DEFAULT 'quick',
    status      TEXT NOT NULL DEFAULT 'running',
    verdict     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS meetings_user ON meetings(user_id, created_at);
CREATE TABLE IF NOT EXISTS takes (
    id          INTEGER PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    member      TEXT NOT NULL,
    round       INTEGER NOT NULL,
    text        TEXT NOT NULL,
    sources     TEXT NOT NULL DEFAULT '[]',
    UNIQUE(meeting_id, member, round)
);
CREATE TABLE IF NOT EXISTS steps (
    id          INTEGER PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    timing      TEXT NOT NULL DEFAULT '',
    done        INTEGER NOT NULL DEFAULT 0
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA journal_mode = WAL")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- users & sessions -------------------------------------------------

    def create_user(self, email: str, name: str, pw_hash: str) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO users (email, name, pw_hash, created_at) VALUES (?, ?, ?, ?)",
                (email, name, pw_hash, now_iso()),
            )
            return int(cur.lastrowid)

    def user_by_email(self, email: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    def user_by_id(self, user_id: int) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def set_plan(self, email: str, plan: str) -> bool:
        with self.conn() as c:
            return c.execute("UPDATE users SET plan = ? WHERE email = ?", (plan, email)).rowcount > 0

    def create_session(self, token: str, user_id: int, expires_at: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, expires_at),
            )

    def session_user(self, token: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token = ? AND s.expires_at > ?",
                (token, now_iso()),
            ).fetchone()

    def delete_session(self, token: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM sessions WHERE token = ?", (token,))

    # ---- meetings ---------------------------------------------------------

    def create_meeting(
        self, user_id: int, question: str, context: str, mode: str, parent_id: int | None
    ) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO meetings (user_id, parent_id, question, context, mode, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, parent_id, question, context, mode, now_iso()),
            )
            return int(cur.lastrowid)

    def meetings_today(self, user_id: int) -> int:
        day = datetime.now(timezone.utc).date().isoformat()
        with self.conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM meetings WHERE user_id = ? AND created_at >= ?",
                (user_id, day),
            ).fetchone()
            return int(row[0])

    def save_take(
        self, meeting_id: int, member: str, round_no: int, text: str, sources: list[dict]
    ) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO takes (meeting_id, member, round, text, sources) "
                "VALUES (?, ?, ?, ?, ?)",
                (meeting_id, member, round_no, text, json.dumps(sources)),
            )

    def finish_meeting(self, meeting_id: int, verdict: dict[str, Any]) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE meetings SET status = 'done', verdict = ? WHERE id = ?",
                (json.dumps(verdict), meeting_id),
            )
            for i, step in enumerate(verdict.get("steps", [])):
                c.execute(
                    "INSERT INTO steps (meeting_id, position, title, detail, timing) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (meeting_id, i, step["title"], step.get("detail", ""), step.get("when", "")),
                )

    def fail_meeting(self, meeting_id: int, status: str = "failed") -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE meetings SET status = ? WHERE id = ? AND status = 'running'",
                (status, meeting_id),
            )

    def list_meetings(self, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT c.id, c.question, c.status, c.created_at, c.verdict, c.parent_id, "
                "(SELECT COUNT(*) FROM steps s WHERE s.meeting_id = c.id) AS total_steps, "
                "(SELECT COUNT(*) FROM steps s WHERE s.meeting_id = c.id AND s.done) AS done_steps "
                "FROM meetings c WHERE c.user_id = ? ORDER BY c.id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            verdict = json.loads(r["verdict"]) if r["verdict"] else None
            out.append(
                {
                    "id": r["id"],
                    "question": r["question"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "parent_id": r["parent_id"],
                    "headline": verdict.get("headline") if verdict else None,
                    "total_steps": r["total_steps"],
                    "done_steps": r["done_steps"],
                }
            )
        return out

    def get_meeting(self, user_id: int, meeting_id: int) -> dict[str, Any] | None:
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM meetings WHERE id = ? AND user_id = ?", (meeting_id, user_id)
            ).fetchone()
            if row is None:
                return None
            takes = c.execute(
                "SELECT member, round, text, sources FROM takes WHERE meeting_id = ? "
                "ORDER BY round, id",
                (meeting_id,),
            ).fetchall()
            steps = c.execute(
                "SELECT id, title, detail, timing, done FROM steps WHERE meeting_id = ? "
                "ORDER BY position",
                (meeting_id,),
            ).fetchall()
        return {
            "id": row["id"],
            "parent_id": row["parent_id"],
            "question": row["question"],
            "context": row["context"],
            "mode": row["mode"],
            "status": row["status"],
            "created_at": row["created_at"],
            "verdict": json.loads(row["verdict"]) if row["verdict"] else None,
            "takes": [
                {
                    "member": t["member"],
                    "round": t["round"],
                    "text": t["text"],
                    "sources": json.loads(t["sources"]),
                }
                for t in takes
            ],
            "steps": [
                {
                    "id": s["id"],
                    "title": s["title"],
                    "detail": s["detail"],
                    "when": s["timing"],
                    "done": bool(s["done"]),
                }
                for s in steps
            ],
        }

    def delete_meeting(self, user_id: int, meeting_id: int) -> bool:
        with self.conn() as c:
            return (
                c.execute(
                    "DELETE FROM meetings WHERE id = ? AND user_id = ?", (meeting_id, user_id)
                ).rowcount
                > 0
            )

    def set_step_done(self, user_id: int, step_id: int, done: bool) -> bool:
        with self.conn() as c:
            return (
                c.execute(
                    "UPDATE steps SET done = ? WHERE id = ? AND meeting_id IN "
                    "(SELECT id FROM meetings WHERE user_id = ?)",
                    (int(done), step_id, user_id),
                ).rowcount
                > 0
            )
