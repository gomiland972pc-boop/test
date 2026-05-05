from __future__ import annotations

from datetime import datetime, timezone, timedelta

import keyboards as kb
from database import STATUS_CLOSED, STATUS_LABELS, Ticket
from handlers.context import BotContext


def split_text(text: str, limit: int = 1024) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit + 1)
        if cut <= 0:
            cut = rest.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return parts


def format_ticket_date(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone(timedelta(hours=3)))
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


async def build_ticket_history(ctx: BotContext, ticket: Ticket) -> str:
    messages = await ctx.db.get_last_messages(ticket.id)
    lines = [
        f"Тикет №{ticket.id}",
        f"Статус: {STATUS_LABELS.get(ticket.status, ticket.status)}",
        f"Дата создания: {format_ticket_date(ticket.created_at)}",
        "",
        "--------------------------",
        "История сообщений:",
    ]
    if not messages:
        lines.append("_Сообщений пока нет._")
    for message in messages:
        sender = "Клиент" if message["sender"] == "user" else "Специалист"
        lines.append(f"_{sender}: {message['text']}_")
    return "\n".join(lines)


async def build_admin_ticket_history(ctx: BotContext, ticket: Ticket) -> str:
    messages = await ctx.db.get_last_messages(ticket.id)
    lines = [
        f"🎫 _Тикет_ #{ticket.id}",
        f"👤 [профиль](https://max.ru/id{ticket.user_id}) (id {ticket.user_id})",
        f"📌 Статус: {STATUS_LABELS.get(ticket.status, ticket.status)}",
        f"� Создан: {format_ticket_date(ticket.created_at)}",
        f"�🕘 Обновлён: {format_ticket_date(ticket.updated_at)}",
        "",
        "_История:_",
    ]
    if not messages:
        lines.append("_Сообщений пока нет._")
    for message in messages:
        icon = "👤" if message["sender"] == "user" else "🛠"
        lines.append(f"{icon} _{message['text']}_")
    return "\n".join(lines)


async def send_ticket_history(
    ctx: BotContext,
    user_id: int,
    ticket: Ticket,
    attachments: list[dict] | None = None,
    callback_id: str = "",
    page: int = 0,
    is_admin: bool = False,
) -> None:
    if is_admin:
        text = await build_admin_ticket_history(ctx, ticket)
    else:
        text = await build_ticket_history(ctx, ticket)
    parts = split_text(text, 1024)
    total_pages = len(parts)
    page = max(0, min(page, total_pages - 1))
    if is_admin:
        current_attachments = kb.admin_ticket_page_controls(ticket.id, page, total_pages)
    else:
        current_attachments = kb.user_ticket_page_controls(
            ticket.id, ticket.status == STATUS_CLOSED, page, total_pages
        )
    if attachments is not None and total_pages == 1:
        current_attachments = attachments
    if callback_id:
        await ctx.reply_menu(
            user_id=user_id,
            text=parts[page],
            attachments=current_attachments,
            callback_id=callback_id,
        )
    else:
        await ctx.api.send_message(
            user_id=user_id,
            text=parts[page],
            attachments=current_attachments,
            fmt="markdown",
        )


def user_ticket_back_keyboard(ticket: Ticket) -> list[dict]:
    return kb.user_ticket_controls(ticket.id, ticket.status == STATUS_CLOSED)
