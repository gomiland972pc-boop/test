from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import keyboards as kb
import pytz
import texts
from database import STATUS_LABELS
from handlers.context import BotContext
from states import State
from ticket_utils import (
    format_with_markup,
    relay_attachments_now,
    send_ticket_history,
)


def _dump_attachments(attachments: Optional[list[dict]]) -> Optional[str]:
    if not attachments:
        return None
    try:
        return json.dumps(attachments, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _dump_markup(markup: Optional[list[dict]]) -> Optional[str]:
    if not markup:
        return None
    try:
        return json.dumps(markup, ensure_ascii=False)
    except (TypeError, ValueError):
        return None

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
        await ctx.api.send_message(user_id=admin_id, text=f"Тикет №{ticket_id} не найден.")
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

    ok = await ctx.db.update_ticket_status(ticket_id, status, manual=True)
    if not ok:
        await ctx.api.send_message(
            user_id=admin_id, text=f"Не удалось обновить тикет №{ticket_id}."
        )
        return

    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None:
        return

    label = STATUS_LABELS.get(status, status)
    await ctx.api.send_message(
        user_id=admin_id,
        text=f"✅ Тикет *№{ticket_id}* -> *{label}*.",
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

    now_utc = datetime.now(timezone.utc)
    online_window = 15 * 60  # секунд — «онлайн», если заходил в этот интервал

    lines: list[str] = []
    for u in users:
        display = u.name or (f"@{u.username}" if u.username else f"id {u.user_id}")
        safe_display = _md_escape(display)
        nick_link = f"[{safe_display}](max://user/{u.user_id})"

        seen_raw = u.last_seen_at or u.created_at
        try:
            dt = datetime.fromisoformat(seen_raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            seconds_ago = (now_utc - dt).total_seconds()
            online = "🟢 " if 0 <= seconds_ago <= online_window else ""
            date_str = dt.astimezone(MSK).strftime("%d.%m.%Y %H:%M") + " MSK"
        except (ValueError, TypeError):
            online = ""
            date_str = seen_raw[:16] if seen_raw else "—"

        lines.append(f"{online}{nick_link} `id {u.user_id}` — {date_str}")

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
            user_id=admin_id, text=f"Тикет №{ticket_id} не найден."
        )
        return
    ctx.states.set(admin_id, State.ADMIN_REPLYING, ticket_id=ticket_id)
    await ctx.api.send_message(
        user_id=admin_id,
        text=texts.ADMIN_ASK_REPLY.format(ticket_id=ticket_id),
        fmt="markdown",
    )


async def show_test_nick_tickets(
    ctx: BotContext, admin_id: int, callback_id: str = "", page: int = 0
) -> None:
    if not _is_admin(ctx, admin_id):
        await ctx.api.send_message(user_id=admin_id, text=texts.NOT_ADMIN)
        return
    total = await ctx.db.count_all_tickets()
    total_pages = max(1, (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    tickets = await ctx.db.list_all_tickets(
        limit=TICKETS_PER_PAGE, offset=page * TICKETS_PER_PAGE
    )
    if not tickets:
        text = "📭 Тикетов пока нет."
    else:
        text = "🧪 *Тест ника*\n\nВыберите тикет — отправлю варианты кликабельного ника владельца."
    await ctx.reply_menu(
        user_id=admin_id,
        text=text,
        attachments=kb.admin_test_nick_tickets_list(tickets, page, total_pages),
        callback_id=callback_id,
    )


def _md_escape(s: str) -> str:
    if not s:
        return s
    for ch in ("\\", "*", "_", "`", "[", "]", "(", ")", "~", "#", ">", "+"):
        s = s.replace(ch, "\\" + ch)
    return s


def _html_escape(s: str) -> str:
    if not s:
        return s
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


async def send_test_nick(
    ctx: BotContext, admin_id: int, ticket_id: int, callback_id: str = ""
) -> None:
    if not _is_admin(ctx, admin_id):
        await ctx.api.send_message(user_id=admin_id, text=texts.NOT_ADMIN)
        return

    if callback_id:
        try:
            await ctx.api.answer_callback(callback_id)
        except Exception as exc:
            logger.warning("answer_callback failed: %s", exc)

    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None:
        await ctx.api.send_message(
            user_id=admin_id, text=f"Тикет №{ticket_id} не найден."
        )
        return

    profile = await ctx.db.get_user(ticket.user_id)
    name = (profile.name if profile and profile.name else "") or "Пользователь"
    username = profile.username if profile and profile.username else ""
    uid = ticket.user_id

    md_name = _md_escape(name)
    html_name = _html_escape(name)

    md_lines = [
        f"🧪 *Тест ника по тикету №{ticket_id}*",
        f"user\\_id: `{uid}`",
        f"name: `{name or '—'}`",
        f"username: `{username or '—'}`",
        "",
        "*Markdown-варианты:*",
        f"1) max://user/id → [{md_name}](max://user/{uid})",
        f"2) max://id → [{md_name}](max://{uid})",
    ]
    if username:
        md_lines.append(f"3) max://username → [{md_name}](max://{username})")
        md_lines.append(
            f"4) https://max.ru/username → [{md_name}](https://max.ru/{username})"
        )
        md_lines.append(f"5) текст @{username}")
    else:
        md_lines.append("3-5) username отсутствует — варианты с username пропущены")

    md_text = "\n".join(md_lines)

    html_parts = [
        f"<b>HTML-варианты (тикет №{ticket_id})</b>",
        f'A) max://user/id → <a href="max://user/{uid}">{html_name}</a>',
        f'B) https://max.ru/id → <a href="https://max.ru/id{uid}">{html_name}</a>',
    ]
    if username:
        html_parts.append(
            f'C) https://max.ru/username → <a href="https://max.ru/{_html_escape(username)}">{html_name}</a>'
        )
    html_text = "<br>".join(html_parts)

    try:
        await ctx.api.send_message(
            user_id=admin_id, text=md_text, fmt="markdown"
        )
    except Exception as exc:
        logger.exception("Не удалось отправить markdown-варианты: %s", exc)
        await ctx.api.send_message(
            user_id=admin_id,
            text=f"⚠️ Markdown-варианты не отправились: {exc}",
        )

    try:
        await ctx.api.send_message(
            user_id=admin_id, text=html_text, fmt="html"
        )
    except Exception as exc:
        logger.exception("Не удалось отправить html-варианты: %s", exc)
        await ctx.api.send_message(
            user_id=admin_id,
            text=f"⚠️ HTML-варианты не отправились: {exc}",
        )


async def start_write_user(
    ctx: BotContext, admin_id: int, callback_id: str = ""
) -> None:
    if not _is_admin(ctx, admin_id):
        await ctx.api.send_message(user_id=admin_id, text=texts.NOT_ADMIN)
        return
    ctx.states.set(admin_id, State.ADMIN_WAITING_USER_ID)
    await ctx.reply_menu(
        user_id=admin_id,
        text=texts.ADMIN_ASK_USER_ID,
        attachments=kb.admin_cancel_to_folders(),
        callback_id=callback_id,
    )


async def handle_user_id_input(
    ctx: BotContext, admin_id: int, text: str
) -> None:
    if not _is_admin(ctx, admin_id):
        ctx.states.reset(admin_id)
        return
    raw = (text or "").strip().lstrip("@#")
    try:
        target_user_id = int(raw)
    except ValueError:
        await ctx.api.send_message(
            user_id=admin_id, text=texts.ADMIN_BAD_USER_ID
        )
        return

    target_profile = await ctx.db.get_user(target_user_id)
    if target_profile is None:
        await ctx.api.send_message(
            user_id=admin_id,
            text=texts.ADMIN_USER_NOT_FOUND.format(user_id=target_user_id),
            fmt="markdown",
        )
        return

    target_name = target_profile.name or (
        f"@{target_profile.username}" if target_profile.username else "—"
    )
    ctx.states.set(
        admin_id,
        State.ADMIN_WAITING_FIRST_MESSAGE,
        target_user_id=target_user_id,
        target_name=target_name,
    )
    await ctx.api.send_message(
        user_id=admin_id,
        text=texts.ADMIN_ASK_FIRST_MESSAGE.format(
            user_name=target_name, user_id=target_user_id
        ),
        attachments=kb.admin_cancel_to_folders(),
        fmt="markdown",
    )


async def send_first_message(
    ctx: BotContext,
    admin_id: int,
    target_user_id: int,
    text: str,
    attachments: Optional[list[dict]] = None,
    markup: Optional[list[dict]] = None,
) -> None:
    if not _is_admin(ctx, admin_id):
        ctx.states.reset(admin_id)
        return

    target_profile = await ctx.db.get_user(target_user_id)
    if target_profile is None:
        await ctx.api.send_message(
            user_id=admin_id,
            text=texts.ADMIN_USER_NOT_FOUND.format(user_id=target_user_id),
            fmt="markdown",
        )
        return

    subject = text or "📎 (вложение)"
    ticket_id = await ctx.db.create_ticket(
        user_id=target_user_id,
        subject=subject,
        initiated_by="support",
        first_sender="admin",
        attachments=_dump_attachments(attachments),
        markup=_dump_markup(markup),
    )
    ctx.states.set(admin_id, State.MAIN_MENU)

    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None:
        await ctx.api.send_message(
            user_id=admin_id, text="⚠️ Не удалось получить созданный тикет."
        )
        return

    try:
        await relay_attachments_now(ctx, target_user_id, attachments)
        await ctx.api.send_message(
            user_id=target_user_id,
            text=texts.USER_SUPPORT_INITIATED.format(ticket_id=ticket_id),
            fmt="markdown",
        )
        from ticket_utils import user_ticket_back_keyboard
        await send_ticket_history(
            ctx,
            target_user_id,
            ticket,
            attachments=user_ticket_back_keyboard(ticket),
        )
    except Exception as exc:
        logger.exception("Не удалось доставить тикет пользователю: %s", exc)
        await ctx.api.send_message(
            user_id=admin_id,
            text="⚠️ Не удалось доставить сообщение пользователю.",
        )

    await send_ticket_history(
        ctx,
        admin_id,
        ticket,
        attachments=kb.admin_ticket_controls(ticket_id),
        is_admin=True,
    )


async def send_reply(
    ctx: BotContext,
    admin_id: int,
    ticket_id: int,
    text: str,
    attachments: Optional[list[dict]] = None,
    markup: Optional[list[dict]] = None,
) -> None:
    if not _is_admin(ctx, admin_id):
        await ctx.api.send_message(user_id=admin_id, text=texts.NOT_ADMIN)
        ctx.states.reset(admin_id)
        return

    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None:
        await ctx.api.send_message(
            user_id=admin_id, text=f"Тикет №{ticket_id} не найден."
        )
        ctx.states.reset(admin_id)
        return

    reply_text = text or "📎"
    await ctx.db.add_message(
        ticket_id, "admin", reply_text,
        attachments=_dump_attachments(attachments),
        markup=_dump_markup(markup),
    )
    ctx.states.set(admin_id, State.MAIN_MENU)

    reply_md = format_with_markup(reply_text, markup) if text else reply_text
    try:
        await relay_attachments_now(ctx, ticket.user_id, attachments)
        await ctx.api.send_message(
            user_id=ticket.user_id,
            text=texts.USER_ADMIN_REPLY.format(ticket_id=ticket_id, text=reply_md),
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
