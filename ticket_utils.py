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


SUPPORT_NAME = "Служба Поддержки"


def _md_escape(s: str) -> str:
    if not s:
        return s
    for ch in ("\\", "*", "_", "`", "[", "]", "(", ")", "~", "#", ">", "+"):
        s = s.replace(ch, "\\" + ch)
    return s


def _user_display_name(profile) -> str:
    if profile and profile.name:
        return profile.name
    if profile and profile.username:
        return f"@{profile.username}"
    return "—"


def _user_name_md(profile, user_id: int, *, as_link: bool) -> str:
    """Имя пользователя в Markdown — всегда жирным, без ссылки."""
    name = _user_display_name(profile)
    return f"*{_md_escape(name)}*"


def _has_attachments(message: dict) -> bool:
    raw = message.get("attachments")
    return bool(raw) and raw not in ("null", "[]")


def _history_line(message: dict, user_name_md: str) -> str:
    sender = message["sender"]
    text = message.get("text") or ""
    if sender == "system":
        # Системное событие: text закодирован как "status:<label>".
        if text.startswith("status:"):
            label = text.split(":", 1)[1]
            return f"_🔔 Статус тикета изменился на *{_md_escape(label)}*_"
        return f"_{_md_escape(text)}_"
    if sender == "user":
        sender_md = user_name_md
    else:
        sender_md = f"*{SUPPORT_NAME}*"
    safe_text = _md_escape(text)
    suffix = " 📎" if _has_attachments(message) else ""
    return f"{sender_md}: {safe_text}{suffix}".rstrip()


async def build_ticket_history(ctx: BotContext, ticket: Ticket) -> str:
    return await _build_history(ctx, ticket, admin_view=False)


async def build_admin_ticket_history(ctx: BotContext, ticket: Ticket) -> str:
    return await _build_history(ctx, ticket, admin_view=True)


async def _build_history(ctx: BotContext, ticket: Ticket, *, admin_view: bool) -> str:
    messages = await ctx.db.get_last_messages(ticket.id)
    profile = await ctx.db.get_user(ticket.user_id)

    # имя пользователя — ссылкой у админа, обычным у пользователя
    user_md = _user_name_md(profile, ticket.user_id, as_link=admin_view)
    support_md = f"*{SUPPORT_NAME}*"

    if ticket.initiated_by == "support":
        from_label = support_md
        to_label = user_md
    else:
        from_label = user_md
        to_label = support_md

    status_label = STATUS_LABELS.get(ticket.status, ticket.status)
    lines = [
        f"🎫 *Тикет №{ticket.id}*",
        f"От кого: {from_label}",
        f"Кому: {to_label}",
        f"ID: `{ticket.user_id}`",
        f"Статус: *{_md_escape(status_label)}*",
        f"Создан: {format_ticket_date(ticket.created_at)}",
        f"Обновлён: {format_ticket_date(ticket.updated_at)}",
        "",
        "_История:_",
    ]
    if not messages:
        lines.append("_Сообщений пока нет._")
    for message in messages:
        lines.append(_history_line(message, user_md))
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
