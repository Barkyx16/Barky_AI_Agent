"""SQLite storage. One short-lived connection per operation keeps things simple and safe."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash  TEXT PRIMARY KEY,
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
CREATE TABLE IF NOT EXISTS asks (
    id          INTEGER PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    advisor     TEXT NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    created_at  TEXT NOT NULL
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


def _h(token: str) -> str:
    """Session tokens are stored hashed, so a leaked database can't be used to sign in."""
    return hashlib.sha256(token.encode()).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)
            user_cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
            if "stripe_customer_id" not in user_cols:
                c.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")
            for col, kind in (
                ("referral_code", "TEXT"), ("referred_by", "INTEGER"),
                ("bonus_meetings", "INTEGER NOT NULL DEFAULT 0"), ("referral_bonus_earned", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if col not in user_cols:
                    c.execute(f"ALTER TABLE users ADD COLUMN {col} {kind}")
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS users_referral ON users(referral_code) WHERE referral_code IS NOT NULL"
            )
            if "remind_emails" not in user_cols:
                c.execute("ALTER TABLE users ADD COLUMN remind_emails INTEGER NOT NULL DEFAULT 1")
            cols = {r["name"] for r in c.execute("PRAGMA table_info(meetings)")}
            if "share_token" not in cols:
                c.execute("ALTER TABLE meetings ADD COLUMN share_token TEXT")
            if "guest" not in cols:
                c.execute("ALTER TABLE meetings ADD COLUMN guest TEXT")
            if "focus" not in cols:
                c.execute("ALTER TABLE meetings ADD COLUMN focus TEXT NOT NULL DEFAULT ''")
            if "review_at" not in cols:
                c.execute("ALTER TABLE meetings ADD COLUMN review_at TEXT")
            for col in ("outcome", "outcome_note", "outcome_at"):
                if col not in cols:
                    c.execute(f"ALTER TABLE meetings ADD COLUMN {col} TEXT")
            if "reminded" not in cols:
                c.execute("ALTER TABLE meetings ADD COLUMN reminded INTEGER NOT NULL DEFAULT 0")
            for col, kind in (
                ("input_tokens", "INTEGER"), ("output_tokens", "INTEGER"), ("cache_write_tokens", "INTEGER"),
                ("cache_read_tokens", "INTEGER"), ("web_searches", "INTEGER"), ("cost_usd", "REAL"),
            ):
                if col not in cols:
                    c.execute(f"ALTER TABLE meetings ADD COLUMN {col} {kind} NOT NULL DEFAULT 0")
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS meetings_share ON meetings(share_token) "
                "WHERE share_token IS NOT NULL"
            )
            c.execute("DELETE FROM sessions WHERE expires_at <= ? OR length(token) != 64", (now_iso(),))

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

    def referral_code(self, user_id: int) -> str:
        """The user's invite code, created on first use."""
        with self.conn() as c:
            row = c.execute("SELECT referral_code FROM users WHERE id = ?", (user_id,)).fetchone()
            if row and row["referral_code"]:
                return row["referral_code"]
            while True:
                code = secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
                try:
                    c.execute("UPDATE users SET referral_code = ? WHERE id = ?", (code, user_id))
                    return code
                except sqlite3.IntegrityError:
                    continue

    def apply_referral(self, new_user_id: int, code: str, bonus: int, cap: int) -> bool:
        """Credit both sides of a referral. The referrer earns at most `cap` bonus meetings in total."""
        with self.conn() as c:
            ref = c.execute(
                "SELECT id, referral_bonus_earned FROM users WHERE referral_code = ? AND id != ?",
                (code, new_user_id),
            ).fetchone()
            if ref is None:
                return False
            c.execute(
                "UPDATE users SET referred_by = ?, bonus_meetings = bonus_meetings + ? WHERE id = ?",
                (ref["id"], bonus, new_user_id),
            )
            grant = max(0, min(bonus, cap - ref["referral_bonus_earned"]))
            if grant:
                c.execute(
                    "UPDATE users SET bonus_meetings = bonus_meetings + ?, "
                    "referral_bonus_earned = referral_bonus_earned + ? WHERE id = ?",
                    (grant, grant, ref["id"]),
                )
            return True

    def referral_count(self, user_id: int) -> int:
        with self.conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)).fetchone()[0])

    def use_bonus_meeting(self, user_id: int) -> bool:
        with self.conn() as c:
            return c.execute(
                "UPDATE users SET bonus_meetings = bonus_meetings - 1 WHERE id = ? AND bonus_meetings > 0",
                (user_id,),
            ).rowcount > 0

    def set_remind_emails(self, user_id: int, enabled: bool) -> None:
        with self.conn() as c:
            c.execute("UPDATE users SET remind_emails = ? WHERE id = ?", (int(enabled), user_id))

    def due_reviews(self, today: str) -> list[dict[str, Any]]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT m.id, m.question, m.verdict, u.email, u.name FROM meetings m "
                "JOIN users u ON u.id = m.user_id "
                "WHERE m.status = 'done' AND m.reminded = 0 AND m.review_at IS NOT NULL "
                "AND m.review_at <= ? AND u.remind_emails = 1 ORDER BY m.id",
                (today,),
            ).fetchall()
        return [
            {
                "id": r["id"], "question": r["question"], "email": r["email"], "name": r["name"],
                "headline": (json.loads(r["verdict"]) or {}).get("headline", "") if r["verdict"] else "",
            }
            for r in rows
        ]

    def mark_reminded(self, meeting_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE meetings SET reminded = 1 WHERE id = ?", (meeting_id,))

    def set_plan_by_id(self, user_id: int, plan: str, customer_id: str | None = None) -> bool:
        with self.conn() as c:
            if customer_id:
                return c.execute(
                    "UPDATE users SET plan = ?, stripe_customer_id = ? WHERE id = ?",
                    (plan, customer_id, user_id),
                ).rowcount > 0
            return c.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id)).rowcount > 0

    def set_plan_by_customer(self, customer_id: str, plan: str) -> bool:
        with self.conn() as c:
            return c.execute(
                "UPDATE users SET plan = ? WHERE stripe_customer_id = ?", (plan, customer_id)
            ).rowcount > 0

    def set_password(self, user_id: int, pw_hash: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (pw_hash, user_id))

    def delete_other_sessions(self, user_id: int, keep_token: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM sessions WHERE user_id = ? AND token != ?", (user_id, _h(keep_token)))

    def create_reset(self, token_hash: str, user_id: int, expires_at: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
            c.execute(
                "INSERT INTO password_resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, user_id, expires_at),
            )

    def consume_reset(self, token_hash: str) -> int | None:
        """Return the user id for a valid reset token and invalidate it."""
        with self.conn() as c:
            row = c.execute(
                "SELECT user_id FROM password_resets WHERE token_hash = ? AND expires_at > ?",
                (token_hash, now_iso()),
            ).fetchone()
            c.execute("DELETE FROM password_resets WHERE token_hash = ?", (token_hash,))
            return int(row["user_id"]) if row else None

    def delete_all_sessions(self, user_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def delete_user(self, user_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def create_session(self, token: str, user_id: int, expires_at: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (_h(token), user_id, expires_at),
            )

    def session_user(self, token: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token = ? AND s.expires_at > ?",
                (_h(token), now_iso()),
            ).fetchone()

    def delete_session(self, token: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM sessions WHERE token = ?", (_h(token),))

    # ---- meetings ---------------------------------------------------------

    def create_meeting(
        self,
        user_id: int,
        question: str,
        context: str,
        mode: str,
        parent_id: int | None,
        guest: dict[str, str] | None = None,
        focus: str = "",
    ) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO meetings (user_id, parent_id, question, context, mode, guest, focus, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, parent_id, question, context, mode, json.dumps(guest) if guest else None, focus, now_iso()),
            )
            return int(cur.lastrowid)

    def meetings_today(self, user_id: int) -> int:
        day = datetime.now(timezone.utc).date().isoformat()
        with self.conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM meetings WHERE user_id = ? AND created_at >= ? "
                "AND status IN ('running', 'done')",
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

    def finish_meeting(self, meeting_id: int, verdict: dict[str, Any], review_at: str | None = None) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE meetings SET status = 'done', verdict = ?, review_at = ? WHERE id = ?",
                (json.dumps(verdict), review_at, meeting_id),
            )
            for i, step in enumerate(verdict.get("steps", [])):
                c.execute(
                    "INSERT INTO steps (meeting_id, position, title, detail, timing) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (meeting_id, i, step["title"], step.get("detail", ""), step.get("when", "")),
                )

    def set_outcome(self, user_id: int, meeting_id: int, outcome: str | None, note: str) -> bool:
        with self.conn() as c:
            return c.execute(
                "UPDATE meetings SET outcome = ?, outcome_note = ?, outcome_at = ? "
                "WHERE id = ? AND user_id = ? AND status = 'done'",
                (outcome, note if outcome else None, now_iso() if outcome else None, meeting_id, user_id),
            ).rowcount > 0

    def add_ask(self, meeting_id: int, advisor: str, question: str, answer: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO asks (meeting_id, advisor, question, answer, created_at) VALUES (?, ?, ?, ?, ?)",
                (meeting_id, advisor, question, answer, now_iso()),
            )

    def asks_today(self, user_id: int) -> int:
        day = datetime.now(timezone.utc).date().isoformat()
        with self.conn() as c:
            return int(c.execute(
                "SELECT COUNT(*) FROM asks a JOIN meetings m ON m.id = a.meeting_id "
                "WHERE m.user_id = ? AND a.created_at >= ?",
                (user_id, day),
            ).fetchone()[0])

    def add_usage(self, meeting_id: int, usage: dict, cost_usd: float) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE meetings SET input_tokens = input_tokens + ?, output_tokens = output_tokens + ?, "
                "cache_write_tokens = cache_write_tokens + ?, cache_read_tokens = cache_read_tokens + ?, "
                "web_searches = web_searches + ?, cost_usd = cost_usd + ? WHERE id = ?",
                (
                    usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                    usage.get("cache_write_tokens", 0), usage.get("cache_read_tokens", 0),
                    usage.get("web_searches", 0), round(cost_usd, 6), meeting_id,
                ),
            )

    def record_usage(self, meeting_id: int, usage: dict, cost_usd: float) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE meetings SET input_tokens = ?, output_tokens = ?, cache_write_tokens = ?, "
                "cache_read_tokens = ?, web_searches = ?, cost_usd = ? WHERE id = ?",
                (
                    usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                    usage.get("cache_write_tokens", 0), usage.get("cache_read_tokens", 0),
                    usage.get("web_searches", 0), round(cost_usd, 6), meeting_id,
                ),
            )

    def fail_meeting(self, meeting_id: int, status: str = "failed") -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE meetings SET status = ? WHERE id = ? AND status = 'running'",
                (status, meeting_id),
            )

    def backup(self, dest: str) -> None:
        """Copy the live database to `dest` using SQLite's online backup (safe while serving)."""
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as src:
            target = sqlite3.connect(dest)
            try:
                src.backup(target)
            finally:
                target.close()

    def interrupt_running(self) -> None:
        with self.conn() as c:
            c.execute("UPDATE meetings SET status = 'interrupted' WHERE status = 'running'")

    def list_meetings(self, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT c.id, c.question, c.status, c.created_at, c.verdict, c.parent_id, c.review_at, c.outcome, "
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
                    "review_at": r["review_at"],
                    "outcome": r["outcome"],
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
            asks = c.execute(
                "SELECT advisor, question, answer, created_at FROM asks WHERE meeting_id = ? ORDER BY id",
                (meeting_id,),
            ).fetchall()
        return {
            "id": row["id"],
            "parent_id": row["parent_id"],
            "question": row["question"],
            "context": row["context"],
            "mode": row["mode"],
            "focus": row["focus"],
            "status": row["status"],
            "created_at": row["created_at"],
            "share_token": row["share_token"],
            "review_at": row["review_at"],
            "outcome": row["outcome"],
            "outcome_note": row["outcome_note"] or "",
            "guest": json.loads(row["guest"]) if row["guest"] else None,
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
            "asks": [dict(a) for a in asks],
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

    def set_share_token(self, user_id: int, meeting_id: int, token: str | None) -> bool:
        with self.conn() as c:
            return (
                c.execute(
                    "UPDATE meetings SET share_token = ? WHERE id = ? AND user_id = ? AND status = 'done'",
                    (token, meeting_id, user_id),
                ).rowcount
                > 0
            )

    def shared_meeting(self, token: str) -> dict[str, Any] | None:
        with self.conn() as c:
            row = c.execute(
                "SELECT id, user_id FROM meetings WHERE share_token = ?", (token,)
            ).fetchone()
        if row is None:
            return None
        meeting = self.get_meeting(row["user_id"], row["id"])
        if meeting is None:
            return None
        # Public view: drop private background, ownership, and progress details.
        return {
            "question": meeting["question"],
            "mode": meeting["mode"],
            "focus": meeting["focus"],
            "guest": meeting["guest"],
            "created_at": meeting["created_at"],
            "verdict": meeting["verdict"],
            "takes": meeting["takes"],
            "asks": [],
            "outcome": None,
            "outcome_note": "",
            "steps": [{**s, "id": 0, "done": False} for s in meeting["steps"]],
        }

    # ---- owner dashboard ------------------------------------------------------

    def stats(self, days: int = 14) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=days - 1)).isoformat()
        d7 = (today - timedelta(days=6)).isoformat()
        d30 = (today - timedelta(days=29)).isoformat()
        with self.conn() as c:
            one = lambda sql, *a: c.execute(sql, a).fetchone()[0] or 0  # noqa: E731
            users = one("SELECT COUNT(*) FROM users")
            pro = one("SELECT COUNT(*) FROM users WHERE plan = 'pro'")
            new_7d = one("SELECT COUNT(*) FROM users WHERE created_at >= ?", d7)
            active_7d = one("SELECT COUNT(DISTINCT user_id) FROM meetings WHERE created_at >= ?", d7)
            total = one("SELECT COUNT(*) FROM meetings")
            m_today = one("SELECT COUNT(*) FROM meetings WHERE created_at >= ?", today.isoformat())
            m_7d = one("SELECT COUNT(*) FROM meetings WHERE created_at >= ?", d7)
            failed_7d = one(
                "SELECT COUNT(*) FROM meetings WHERE created_at >= ? AND status IN ('failed', 'interrupted')", d7
            )
            shared = one("SELECT COUNT(*) FROM meetings WHERE share_token IS NOT NULL")
            outcomes = dict(c.execute(
                "SELECT outcome, COUNT(*) FROM meetings WHERE outcome IS NOT NULL GROUP BY outcome"
            ).fetchall())
            cost_30d = one("SELECT SUM(cost_usd) FROM meetings WHERE created_at >= ?", d30)
            cost_today = one("SELECT SUM(cost_usd) FROM meetings WHERE created_at >= ?", today.isoformat())
            avg_cost = one(
                "SELECT AVG(cost_usd) FROM meetings WHERE created_at >= ? AND status = 'done' AND cost_usd > 0", d30
            )
            meetings_by_day = dict(c.execute(
                "SELECT substr(created_at, 1, 10) AS d, COUNT(*) FROM meetings WHERE created_at >= ? GROUP BY d",
                (start,),
            ).fetchall())
            cost_by_day = dict(c.execute(
                "SELECT substr(created_at, 1, 10) AS d, SUM(cost_usd) FROM meetings WHERE created_at >= ? GROUP BY d",
                (start,),
            ).fetchall())
            signups_by_day = dict(c.execute(
                "SELECT substr(created_at, 1, 10) AS d, COUNT(*) FROM users WHERE created_at >= ? GROUP BY d",
                (start,),
            ).fetchall())
        daily = []
        for i in range(days):
            d = (today - timedelta(days=days - 1 - i)).isoformat()
            daily.append({
                "date": d,
                "meetings": meetings_by_day.get(d, 0),
                "signups": signups_by_day.get(d, 0),
                "cost_usd": round(cost_by_day.get(d, 0) or 0, 4),
            })
        return {
            "users": {"total": users, "pro": pro, "new_7d": new_7d, "active_7d": active_7d},
            "meetings": {
                "total": total, "today": m_today, "last_7d": m_7d,
                "failure_rate_7d": round(failed_7d / m_7d, 4) if m_7d else 0.0,
                "shared": shared,
            },
            "outcomes": {k: outcomes.get(k, 0) for k in ("great", "mixed", "bad")},
            "cost": {
                "today_usd": round(cost_today, 4),
                "last_30d_usd": round(cost_30d, 4),
                "avg_per_meeting_usd": round(avg_cost, 4),
            },
            "daily": daily,
        }
