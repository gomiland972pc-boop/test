from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

STATUS_OPEN = "open"
STATUS_REVIEW = "review"
STATUS_SPECIALIST = "specialist"
STATUS_PREPARING = "preparing"
STATUS_TRANSFERRED = "transferred"
STATUS_CLOSED = "closed"

STATUS_LABELS = {
    STATUS_OPEN: "Открыт",
    STATUS_REVIEW: "На рассмотрении",
    STATUS_SPECIALIST: "Изучает специалист",
    STATUS_PREPARING: "Готовится ответ",
    STATUS_TRANSFERRED: "Передан в другой отдел",
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
    initiated_by: str = "user"
    status_manually_set: bool = False
    recipient_user_id: Optional[int] = None


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
    last_seen_at: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_ticket(row) -> "Ticket":
    return Ticket(
        id=row["id"],
        user_id=row["user_id"],
        subject=row["subject"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        initiated_by=row["initiated_by"] or "user",
        status_manually_set=bool(row["status_manually_set"]),
        recipient_user_id=row["recipient_user_id"],
    )


def _row_to_user(row) -> "UserProfile":
    return UserProfile(
        user_id=row["user_id"],
        name=row["name"],
        username=row["username"],
        chat_id=row["chat_id"],
        is_premium=bool(row["is_premium"]),
        premium_expiry=row["premium_expiry"],
        consent_accepted=bool(row["consent_accepted"]),
        offer_accepted=bool(row["offer_accepted"]),
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
    )


class Database:

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=1,
            max_size=5,
            command_timeout=30,
        )
        await self._init_schema()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("БД не инициализирована, вызовите connect()")
        return self._pool

    async def _init_schema(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id          BIGINT PRIMARY KEY,
                    name             TEXT,
                    username         TEXT,
                    chat_id          BIGINT,
                    is_premium       BOOLEAN NOT NULL DEFAULT FALSE,
                    premium_expiry   TEXT,
                    consent_accepted BOOLEAN NOT NULL DEFAULT FALSE,
                    offer_accepted   BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at       TEXT NOT NULL,
                    last_seen_at     TEXT
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    id                  BIGSERIAL PRIMARY KEY,
                    user_id             BIGINT NOT NULL REFERENCES users(user_id),
                    subject             TEXT NOT NULL,
                    status              TEXT NOT NULL DEFAULT 'open',
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL,
                    initiated_by        TEXT NOT NULL DEFAULT 'user',
                    status_manually_set BOOLEAN NOT NULL DEFAULT FALSE,
                    recipient_user_id   BIGINT
                );

                CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
                CREATE INDEX IF NOT EXISTS idx_tickets_user   ON tickets(user_id);

                CREATE TABLE IF NOT EXISTS messages (
                    id          BIGSERIAL PRIMARY KEY,
                    ticket_id   BIGINT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                    sender      TEXT NOT NULL CHECK (sender IN ('user','admin','system')),
                    text        TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    attachments TEXT,
                    markup      TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_messages_ticket ON messages(ticket_id);
                """
            )
            await self._migrate_schema(conn)

    async def _migrate_schema(self, conn: asyncpg.Connection) -> None:
        await self._add_missing_columns(
            conn,
            "users",
            [
                ("is_premium", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("premium_expiry", "TEXT"),
                ("consent_accepted", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("offer_accepted", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("last_seen_at", "TEXT"),
            ],
        )
        await self._add_missing_columns(
            conn,
            "tickets",
            [
                ("initiated_by", "TEXT NOT NULL DEFAULT 'user'"),
                ("status_manually_set", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("recipient_user_id", "BIGINT"),
            ],
        )
        await self._add_missing_columns(
            conn,
            "messages",
            [
                ("attachments", "TEXT"),
                ("markup", "TEXT"),
            ],
        )

    async def _add_missing_columns(
        self,
        conn: asyncpg.Connection,
        table: str,
        columns: list[tuple[str, str]],
    ) -> None:
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
            table,
        )
        existing = {r["column_name"] for r in rows}
        for col, definition in columns:
            if col not in existing:
                await conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col} {definition}"
                )

    async def upsert_user(
        self,
        user_id: int,
        name: Optional[str],
        username: Optional[str],
        chat_id: Optional[int],
    ) -> None:
        ts = _now()
        await self.pool.execute(
            """
            INSERT INTO users(user_id, name, username, chat_id, created_at, last_seen_at)
            VALUES ($1, $2, $3, $4, $5, $5)
            ON CONFLICT(user_id) DO UPDATE SET
                name         = COALESCE(EXCLUDED.name, users.name),
                username     = COALESCE(EXCLUDED.username, users.username),
                chat_id      = COALESCE(EXCLUDED.chat_id, users.chat_id),
                last_seen_at = EXCLUDED.last_seen_at
            """,
            user_id, name, username, chat_id, ts,
        )

    async def get_user(self, user_id: int) -> Optional[UserProfile]:
        row = await self.pool.fetchrow(
            "SELECT * FROM users WHERE user_id = $1", user_id
        )
        if row is None:
            return None
        return _row_to_user(row)

    async def get_user_chat_id(self, user_id: int) -> Optional[int]:
        row = await self.pool.fetchrow(
            "SELECT chat_id FROM users WHERE user_id = $1", user_id
        )
        return row["chat_id"] if row and row["chat_id"] is not None else None

    async def touch_user_seen(self, user_id: int) -> None:
        await self.pool.execute(
            "UPDATE users SET last_seen_at = $1 WHERE user_id = $2",
            _now(), user_id,
        )

    async def set_consent(self, user_id: int, field: str) -> None:
        if field not in ("consent_accepted", "offer_accepted"):
            raise ValueError(f"Неизвестное поле: {field}")
        ts = _now()
        await self.pool.execute(
            f"""
            INSERT INTO users(user_id, {field}, created_at)
            VALUES ($1, TRUE, $2)
            ON CONFLICT(user_id) DO UPDATE SET
                {field} = TRUE
            """,
            user_id, ts,
        )

    async def set_premium(
        self, user_id: int, is_premium: bool, expiry: Optional[str] = None
    ) -> None:
        await self.pool.execute(
            """
            UPDATE users SET is_premium = $1, premium_expiry = $2
            WHERE user_id = $3
            """,
            is_premium, expiry, user_id,
        )

    async def create_ticket(
        self,
        user_id: int,
        subject: str,
        *,
        initiated_by: str = "user",
        first_sender: str = "user",
        attachments: Optional[str] = None,
        markup: Optional[str] = None,
    ) -> int:
        if initiated_by not in ("user", "support"):
            raise ValueError("initiated_by должен быть 'user' или 'support'")
        if first_sender not in ("user", "admin"):
            raise ValueError("first_sender должен быть 'user' или 'admin'")
        ts = _now()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                ticket_id = await conn.fetchval(
                    """
                    INSERT INTO tickets(
                        user_id, subject, status, created_at, updated_at,
                        initiated_by, status_manually_set, recipient_user_id
                    )
                    VALUES ($1, $2, $3, $4, $4, $5, FALSE, $1)
                    RETURNING id
                    """,
                    user_id, subject, STATUS_OPEN, ts, initiated_by,
                )
                await conn.execute(
                    """
                    INSERT INTO messages(ticket_id, sender, text, created_at, attachments, markup)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    ticket_id, first_sender, subject, ts, attachments, markup,
                )
        return int(ticket_id)

    async def get_ticket(self, ticket_id: int) -> Optional[Ticket]:
        row = await self.pool.fetchrow(
            "SELECT * FROM tickets WHERE id = $1", ticket_id
        )
        if row is None:
            return None
        return _row_to_ticket(row)

    async def list_active_tickets(self, limit: int = 50, offset: int = 0) -> list[Ticket]:
        rows = await self.pool.fetch(
            """
            SELECT * FROM tickets
            WHERE status != $1
            ORDER BY updated_at DESC
            LIMIT $2 OFFSET $3
            """,
            STATUS_CLOSED, limit, offset,
        )
        return [_row_to_ticket(r) for r in rows]

    async def count_active_tickets(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS count FROM tickets WHERE status != $1",
            STATUS_CLOSED,
        )
        return int(row["count"]) if row else 0

    async def list_tickets(
        self, archived: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Ticket]:
        if archived:
            sql = """
                SELECT * FROM tickets
                WHERE status = $1
                ORDER BY updated_at DESC
                LIMIT $2 OFFSET $3
            """
        else:
            sql = """
                SELECT * FROM tickets
                WHERE status != $1
                ORDER BY updated_at DESC
                LIMIT $2 OFFSET $3
            """
        rows = await self.pool.fetch(sql, STATUS_CLOSED, limit, offset)
        return [_row_to_ticket(r) for r in rows]

    async def list_all_tickets(
        self, limit: int = 50, offset: int = 0
    ) -> list[Ticket]:
        rows = await self.pool.fetch(
            """
            SELECT * FROM tickets
            ORDER BY updated_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )
        return [_row_to_ticket(r) for r in rows]

    async def count_all_tickets(self) -> int:
        row = await self.pool.fetchrow("SELECT COUNT(*) AS count FROM tickets")
        return int(row["count"]) if row else 0

    async def count_tickets(self, archived: bool = False) -> int:
        if archived:
            sql = "SELECT COUNT(*) AS count FROM tickets WHERE status = $1"
        else:
            sql = "SELECT COUNT(*) AS count FROM tickets WHERE status != $1"
        row = await self.pool.fetchrow(sql, STATUS_CLOSED)
        return int(row["count"]) if row else 0

    async def list_user_tickets(
        self, user_id: int, archived: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Ticket]:
        if archived:
            sql = """
                SELECT * FROM tickets
                WHERE user_id = $1 AND status = $2
                ORDER BY updated_at DESC
                LIMIT $3 OFFSET $4
            """
        else:
            sql = """
                SELECT * FROM tickets
                WHERE user_id = $1 AND status != $2
                ORDER BY updated_at DESC
                LIMIT $3 OFFSET $4
            """
        rows = await self.pool.fetch(sql, user_id, STATUS_CLOSED, limit, offset)
        return [_row_to_ticket(r) for r in rows]

    async def count_user_tickets(self, user_id: int, archived: bool = False) -> int:
        if archived:
            sql = "SELECT COUNT(*) AS count FROM tickets WHERE user_id = $1 AND status = $2"
        else:
            sql = "SELECT COUNT(*) AS count FROM tickets WHERE user_id = $1 AND status != $2"
        row = await self.pool.fetchrow(sql, user_id, STATUS_CLOSED)
        return int(row["count"]) if row else 0

    async def update_ticket_status(
        self, ticket_id: int, status: str, *, manual: bool = False
    ) -> bool:
        if status not in STATUS_LABELS:
            raise ValueError(f"Неизвестный статус: {status}")
        if manual:
            result = await self.pool.execute(
                """
                UPDATE tickets
                SET status = $1, updated_at = $2, status_manually_set = TRUE
                WHERE id = $3
                """,
                status, _now(), ticket_id,
            )
        else:
            result = await self.pool.execute(
                "UPDATE tickets SET status = $1, updated_at = $2 WHERE id = $3",
                status, _now(), ticket_id,
            )
        # result типа "UPDATE n" — берём n
        try:
            rowcount = int(result.split()[-1])
        except (ValueError, IndexError):
            rowcount = 0
        if rowcount > 0:
            await self.add_status_event(ticket_id, status)
            return True
        return False

    async def auto_set_review_if_untouched(self, ticket_id: int) -> bool:
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            return False
        if ticket.status_manually_set:
            return False
        if ticket.status == STATUS_CLOSED:
            return False
        if ticket.status == STATUS_REVIEW:
            return False
        await self.pool.execute(
            "UPDATE tickets SET status = $1, updated_at = $2 WHERE id = $3",
            STATUS_REVIEW, _now(), ticket_id,
        )
        await self.add_status_event(ticket_id, STATUS_REVIEW)
        return True

    async def add_message(
        self,
        ticket_id: int,
        sender: str,
        text: str,
        attachments: Optional[str] = None,
        markup: Optional[str] = None,
    ) -> None:
        if sender not in ("user", "admin", "system"):
            raise ValueError("sender должен быть 'user', 'admin' или 'system'")
        ts = _now()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO messages(ticket_id, sender, text, created_at, attachments, markup)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    ticket_id, sender, text, ts, attachments, markup,
                )
                await conn.execute(
                    "UPDATE tickets SET updated_at = $1 WHERE id = $2",
                    ts, ticket_id,
                )

    async def add_status_event(self, ticket_id: int, status: str) -> None:
        """Записывает в историю системное сообщение о смене статуса."""
        label = STATUS_LABELS.get(status, status)
        await self.add_message(ticket_id, "system", f"status:{label}")

    async def get_last_messages(self, ticket_id: int, limit: Optional[int] = None) -> list[dict]:
        if limit is not None:
            rows = await self.pool.fetch(
                """
                SELECT sender, text, created_at, attachments, markup FROM messages
                WHERE ticket_id = $1
                ORDER BY id ASC
                LIMIT $2
                """,
                ticket_id, limit,
            )
        else:
            rows = await self.pool.fetch(
                """
                SELECT sender, text, created_at, attachments, markup FROM messages
                WHERE ticket_id = $1
                ORDER BY id ASC
                """,
                ticket_id,
            )
        return [dict(r) for r in rows]

    async def list_users(self, limit: int = 50, offset: int = 0) -> list[UserProfile]:
        rows = await self.pool.fetch(
            """
            SELECT * FROM users
            ORDER BY COALESCE(last_seen_at, created_at) DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )
        return [_row_to_user(r) for r in rows]

    async def count_users(self) -> int:
        row = await self.pool.fetchrow("SELECT COUNT(*) AS count FROM users")
        return int(row["count"]) if row else 0

    async def find_open_ticket_by_user(self, user_id: int) -> Optional[Ticket]:
        row = await self.pool.fetchrow(
            """
            SELECT * FROM tickets
            WHERE user_id = $1 AND status != $2
            ORDER BY id DESC LIMIT 1
            """,
            user_id, STATUS_CLOSED,
        )
        if row is None:
            return None
        return _row_to_ticket(row)
