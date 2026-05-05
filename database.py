from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

STATUS_OPEN = "open"
STATUS_REVIEW = "review"
STATUS_SPECIALIST = "specialist"
STATUS_PREPARING = "preparing"
STATUS_CLOSED = "closed"

STATUS_LABELS = {
    STATUS_OPEN: "Открыт",
    STATUS_REVIEW: "На рассмотрении",
    STATUS_SPECIALIST: "Изучает специалист",
    STATUS_PREPARING: "Готовится ответ",
    STATUS_CLOSED: "Закрыт",
}


@dataclass
class Ticket:
    id: int
    user_id: int
    subject: str
    status: str
    created_at: str
    updated_at: str


@dataclass
class UserProfile:
    user_id: int
    name: Optional[str]
    username: Optional[str]
    chat_id: Optional[int]
    is_premium: bool
    premium_expiry: Optional[str]
    consent_accepted: bool
    offer_accepted: bool
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._init_schema()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("БД не инициализирована, вызовите connect()")
        return self._conn

    async def _init_schema(self) -> None:
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id          INTEGER PRIMARY KEY,
                name             TEXT,
                username         TEXT,
                chat_id          INTEGER,
                is_premium       INTEGER NOT NULL DEFAULT 0,
                premium_expiry   TEXT,
                consent_accepted INTEGER NOT NULL DEFAULT 0,
                offer_accepted   INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(user_id),
                subject     TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'open',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
            CREATE INDEX IF NOT EXISTS idx_tickets_user   ON tickets(user_id);

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id   INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                sender      TEXT NOT NULL CHECK (sender IN ('user','admin')),
                text        TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_ticket ON messages(ticket_id);
            """
        )
        await self._migrate_users()
        await self.conn.commit()

    async def _migrate_users(self) -> None:
        cur = await self.conn.execute("PRAGMA table_info(users)")
        existing = {row["name"] for row in await cur.fetchall()}
        for col, definition in [
            ("is_premium", "INTEGER NOT NULL DEFAULT 0"),
            ("premium_expiry", "TEXT"),
            ("consent_accepted", "INTEGER NOT NULL DEFAULT 0"),
            ("offer_accepted", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if col not in existing:
                await self.conn.execute(
                    f"ALTER TABLE users ADD COLUMN {col} {definition}"
                )


    async def upsert_user(
        self,
        user_id: int,
        name: Optional[str],
        username: Optional[str],
        chat_id: Optional[int],
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO users(user_id, name, username, chat_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name     = COALESCE(excluded.name, users.name),
                username = COALESCE(excluded.username, users.username),
                chat_id  = COALESCE(excluded.chat_id, users.chat_id)
            """,
            (user_id, name, username, chat_id, _now()),
        )
        await self.conn.commit()

    async def get_user(self, user_id: int) -> Optional[UserProfile]:
        cur = await self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
        d["is_premium"] = bool(d.get("is_premium", 0))
        d["consent_accepted"] = bool(d.get("consent_accepted", 0))
        d["offer_accepted"] = bool(d.get("offer_accepted", 0))
        return UserProfile(**d)

    async def get_user_chat_id(self, user_id: int) -> Optional[int]:
        cur = await self.conn.execute(
            "SELECT chat_id FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return row["chat_id"] if row and row["chat_id"] is not None else None

    async def set_consent(self, user_id: int, field: str) -> None:
        if field not in ("consent_accepted", "offer_accepted"):
            raise ValueError(f"Неизвестное поле: {field}")
        ts = _now()
        await self.conn.execute(
            f"""
            INSERT INTO users(user_id, {field}, created_at)
            VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                {field} = 1
            """,
            (user_id, ts),
        )
        await self.conn.commit()

    async def set_premium(
        self, user_id: int, is_premium: bool, expiry: Optional[str] = None
    ) -> None:
        await self.conn.execute(
            """
            UPDATE users SET is_premium = ?, premium_expiry = ?
            WHERE user_id = ?
            """,
            (int(is_premium), expiry, user_id),
        )
        await self.conn.commit()


    async def create_ticket(self, user_id: int, subject: str) -> int:
        ts = _now()
        cur = await self.conn.execute(
            """
            INSERT INTO tickets(user_id, subject, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, subject, STATUS_OPEN, ts, ts),
        )
        await self.conn.execute(
            """
            INSERT INTO messages(ticket_id, sender, text, created_at)
            VALUES (?, 'user', ?, ?)
            """,
            (cur.lastrowid, subject, ts),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def get_ticket(self, ticket_id: int) -> Optional[Ticket]:
        cur = await self.conn.execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        return Ticket(**{k: row[k] for k in row.keys()})

    async def list_active_tickets(self, limit: int = 50, offset: int = 0) -> list[Ticket]:
        cur = await self.conn.execute(
            """
            SELECT * FROM tickets
            WHERE status != ?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (STATUS_CLOSED, limit, offset),
        )
        rows = await cur.fetchall()
        return [Ticket(**{k: r[k] for k in r.keys()}) for r in rows]

    async def count_active_tickets(self) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS count FROM tickets WHERE status != ?",
            (STATUS_CLOSED,),
        )
        row = await cur.fetchone()
        return int(row["count"]) if row else 0

    async def list_tickets(
        self, archived: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Ticket]:
        condition = "status = ?" if archived else "status != ?"
        cur = await self.conn.execute(
            f"""
            SELECT * FROM tickets
            WHERE {condition}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (STATUS_CLOSED, limit, offset),
        )
        rows = await cur.fetchall()
        return [Ticket(**{k: r[k] for k in r.keys()}) for r in rows]

    async def count_tickets(self, archived: bool = False) -> int:
        condition = "status = ?" if archived else "status != ?"
        cur = await self.conn.execute(
            f"SELECT COUNT(*) AS count FROM tickets WHERE {condition}",
            (STATUS_CLOSED,),
        )
        row = await cur.fetchone()
        return int(row["count"]) if row else 0

    async def list_user_tickets(
        self, user_id: int, archived: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Ticket]:
        if archived:
            condition = "status = ?"
            params = (user_id, STATUS_CLOSED, limit, offset)
        else:
            condition = "status != ?"
            params = (user_id, STATUS_CLOSED, limit, offset)
        cur = await self.conn.execute(
            f"""
            SELECT * FROM tickets
            WHERE user_id = ? AND {condition}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        rows = await cur.fetchall()
        return [Ticket(**{k: r[k] for k in r.keys()}) for r in rows]

    async def count_user_tickets(self, user_id: int, archived: bool = False) -> int:
        condition = "status = ?" if archived else "status != ?"
        cur = await self.conn.execute(
            f"SELECT COUNT(*) AS count FROM tickets WHERE user_id = ? AND {condition}",
            (user_id, STATUS_CLOSED),
        )
        row = await cur.fetchone()
        return int(row["count"]) if row else 0

    async def update_ticket_status(self, ticket_id: int, status: str) -> bool:
        if status not in STATUS_LABELS:
            raise ValueError(f"Неизвестный статус: {status}")
        cur = await self.conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), ticket_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0


    async def add_message(self, ticket_id: int, sender: str, text: str) -> None:
        if sender not in ("user", "admin"):
            raise ValueError("sender должен быть 'user' или 'admin'")
        await self.conn.execute(
            """
            INSERT INTO messages(ticket_id, sender, text, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (ticket_id, sender, text, _now()),
        )
        await self.conn.execute(
            "UPDATE tickets SET updated_at = ? WHERE id = ?",
            (_now(), ticket_id),
        )
        await self.conn.commit()

    async def get_last_messages(self, ticket_id: int, limit: Optional[int] = None) -> list[dict]:
        params: tuple = (ticket_id,)
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params = (ticket_id, limit)
        cur = await self.conn.execute(
            f"""
            SELECT sender, text, created_at FROM messages
            WHERE ticket_id = ?
            ORDER BY id ASC
            {limit_sql}
            """,
            params,
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def list_users(self, limit: int = 50, offset: int = 0) -> list[UserProfile]:
        cur = await self.conn.execute(
            "SELECT * FROM users ORDER BY created_at ASC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cur.fetchall()
        result: list[UserProfile] = []
        for row in rows:
            d = {k: row[k] for k in row.keys()}
            d["is_premium"] = bool(d.get("is_premium", 0))
            d["consent_accepted"] = bool(d.get("consent_accepted", 0))
            d["offer_accepted"] = bool(d.get("offer_accepted", 0))
            result.append(UserProfile(**d))
        return result

    async def count_users(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) AS count FROM users")
        row = await cur.fetchone()
        return int(row["count"]) if row else 0

    async def find_open_ticket_by_user(self, user_id: int) -> Optional[Ticket]:
        cur = await self.conn.execute(
            """
            SELECT * FROM tickets
            WHERE user_id = ? AND status != ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, STATUS_CLOSED),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return Ticket(**{k: row[k] for k in row.keys()})
