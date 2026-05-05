from __future__ import annotations

import logging
from datetime import datetime, timezone

import keyboards as kb
import pytz
import texts
from database import STATUS_LABELS
from handlers.context import BotContext
from states import State
from ticket_utils import send_ticket_history

logger = logging.getLogger(__name__)
TICKETS_PER_PAGE = 5
USERS_PER_PAGE = 10

MSK = pytz.timezone("Europe/Moscow")


def _is_admin(ctx: BotContext, user_id: int) -> bool:
    return user_id in ctx.cfg.admin_ids


async def cmd_admin(ctx: BotContext, user_id: int, callback_id: str = "", page: int = 0) -> None:
    if not _is_admin(ctx, user_id):
        await ctx.api.send_message(user_id=user_id, text=texts.NOT_ADMIN)
        return

    active_count = await ctx.db.count_tickets(archived=False)
    archive_count = await ctx.db.count_tickets(archived=True)
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.ADMIN_TICKETS_HEADER,
        attachments=kb.admin_folders(active_count, archive_count),
        callback_id=callback_id,
    )


async def show_tickets(
    ctx: BotContext,
    user_id: int,
    archived: bool = False,
    callback_id: str = "",
    page: int = 0,
) -> None:
    if not _is_admin(ctx, user_id):
        await ctx.api.send_message(user_id=user_id, text=texts.NOT_ADMIN)
        return

    total = await ctx.db.count_tickets(archived=archived)
    total_pages = max(1, (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    tickets = await ctx.db.list_tickets(
        archived=archived,
        limit=TICKETS_PER_PAGE,
        offset=page * TICKETS_PER_PAGE,
    )
    if tickets:
        text = texts.ADMIN_TICKETS_ARCHIVE_HEADER if archived else texts.ADMIN_TICKETS_ACTIVE_HEADER
    else:
        text = texts.ADMIN_TICKETS_EMPTY_ARCHIVE if archived else texts.ADMIN_TICKETS_EMPTY_ACTIVE
    await ctx.reply_menu(
        user_id=user_id,
        text=text,
        attachments=kb.admin_tickets_list(tickets, archived, page, total_pages),
        callback_id=callback_id,
    )


async def open_ticket(
    ctx: BotContext, admin_id: int, ticket_id: int, callback_id: str = "", page: int = 0
) -> None:
    if not _is_admin(ctx, admin_id):
        await ctx.api.send_message(user_id=admin_id, text=texts.NOT_ADMIN)
        return

    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None:
        await ctx.api.send_message(user_id=admin_id, text=f"Тикет #{ticket_id} не найден.")
        return

    await send_ticket_history(
        ctx,
        admin_id,
        ticket,
        attachments=kb.admin_ticket_controls(ticket_id),
        callback_id=callback_id,
        page=page,
        is_admin=True,
    )


async def set_status(
    ctx: BotContext,
    admin_id: int,
    ticket_id: int,
    status: str,
) -> None:
    if not _is_admin(ctx, admin_id):
        await ctx.api.send_message(user_id=admin_id, text=texts.NOT_ADMIN)
        return

    ok = await ctx.db.update_ticket_status(ticket_id, status)
    if not ok:
        await ctx.api.send_message(
            user_id=admin_id, text=f"Не удалось обновить тикет #{ticket_id}."
        )
        return

    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None:
        return

    label = STATUS_LABELS.get(status, status)
    await ctx.api.send_message(
        user_id=admin_id,
        text=f"✅ Тикет *#{ticket_id}* -> *{label}*.",
        fmt="markdown",
    )

    try:
        await ctx.api.send_message(
            user_id=ticket.user_id,
            text=texts.TICKET_STATUS_CHANGED.format(
                ticket_id=ticket_id, status=label
            ),
            fmt="markdown",
        )
    except Exception as exc:
        logger.exception("Не удалось уведомить пользователя о статусе: %s", exc)


async def show_users(
    ctx: BotContext,
    admin_id: int,
    callback_id: str = "",
    page: int = 0,
) -> None:
    if not _is_admin(ctx, admin_id):
        await ctx.api.send_message(user_id=admin_id, text=texts.NOT_ADMIN)
        return

    total = await ctx.db.count_users()
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    users = await ctx.db.list_users(
        limit=USERS_PER_PAGE, offset=page * USERS_PER_PAGE
    )

    if not users:
        await ctx.reply_menu(
            user_id=admin_id,
            text=texts.ADMIN_USERS_EMPTY,
            attachments=kb.admin_users_list(page, total_pages),
            callback_id=callback_id,
        )
        return

    lines: list[str] = []
    for u in users:
        nick = f"@{u.username}" if u.username else "—"
        try:
            dt = datetime.fromisoformat(u.created_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(MSK)
            date_str = dt.strftime("%d.%m.%Y %H:%M") + " MSK"
        except (ValueError, TypeError):
            date_str = u.created_at[:16]
        lines.append(f"{u.user_id} | {nick} | {date_str}")

    await ctx.reply_menu(
        user_id=admin_id,
        text=texts.ADMIN_USERS_HEADER.format(users="\n".join(lines)),
        attachments=kb.admin_users_list(page, total_pages),
        callback_id=callback_id,
    )


async def ask_reply(ctx: BotContext, admin_id: int, ticket_id: int) -> None:
    if not _is_admin(ctx, admin_id):
        await ctx.api.send_message(user_id=admin_id, text=texts.NOT_ADMIN)
        return

    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None:
        await ctx.api.send_message(
            user_id=admin_id, text=f"Тикет #{ticket_id} не найден."
        )
        return
    ctx.states.set(admin_id, State.ADMIN_REPLYING, ticket_id=ticket_id)
    await ctx.api.send_message(
        user_id=admin_id,
        text=texts.ADMIN_ASK_REPLY.format(ticket_id=ticket_id),
        fmt="markdown",
    )


async def send_reply(
    ctx: BotContext,
    admin_id: int,
    ticket_id: int,
    text: str,
) -> None:
    if not _is_admin(ctx, admin_id):
        await ctx.api.send_message(user_id=admin_id, text=texts.NOT_ADMIN)
        ctx.states.reset(admin_id)
        return

    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None:
        await ctx.api.send_message(
            user_id=admin_id, text=f"Тикет #{ticket_id} не найден."
        )
        ctx.states.reset(admin_id)
        return

    await ctx.db.add_message(ticket_id, "admin", text)
    ctx.states.set(admin_id, State.MAIN_MENU)

    try:
        await ctx.api.send_message(
            user_id=ticket.user_id,
            text=texts.USER_ADMIN_REPLY.format(ticket_id=ticket_id, text=text),
            fmt="markdown",
        )
    except Exception as exc:
        logger.exception("Не удалось отправить ответ пользователю: %s", exc)
        await ctx.api.send_message(
            user_id=admin_id,
            text="⚠️ Не удалось доставить ответ пользователю.",
        )
        return

    await ctx.api.send_message(
        user_id=admin_id,
        text=texts.ADMIN_REPLY_SENT.format(ticket_id=ticket_id),
        fmt="markdown",
    )
