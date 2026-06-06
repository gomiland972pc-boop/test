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


async def relay_attachments_now(
    ctx: BotContext, target_user_id: int, attachments: list[dict] | None
) -> None:
    """Прямо сейчас пересылает входящие вложения адресату.
    Скачиваем и заново загружаем через /uploads (иначе Max отказывает,
    т.к. чужие payload медиа имеют короткий срок жизни)."""
    if not attachments:
        return
    try:
        reuploaded = await ctx.api.reupload_attachments(attachments)
    except Exception:
        reuploaded = []
    if not reuploaded:
        return
    try:
        await ctx.api.send_message(
            user_id=target_user_id,
            text="",
            attachments=reuploaded,
        )
    except Exception:
        pass


def _md_escape(s: str) -> str:
    if not s:
        return s
    for ch in ("\\", "*", "_", "`", "[", "]", "(", ")", "~", "#", ">", "+"):
        s = s.replace(ch, "\\" + ch)
    return s


_FMT_WRAP = {
    "strong": ("**", "**"),
    "bold": ("**", "**"),
    "emphasized": ("*", "*"),
    "italic": ("*", "*"),
    "underline": ("__", "__"),
    "strikethrough": ("~~", "~~"),
    "monospaced": ("`", "`"),
    "code": ("`", "`"),
}


def format_with_markup(text: str, markup: list[dict] | None) -> str:
    """Преобразует входящий текст с разметкой Max в Markdown-строку.
    Использует markup-аннотации (from/length/type/url) — поддерживает
    жирный, курсив, подчёрк, зачёркивание, моно, ссылку, цитату, код.
    Перекрывающиеся аннотации не вкладываются: берётся первая по позиции,
    последующие пересекающиеся — пропускаются.
    """
    if not text:
        return ""
    if not markup:
        return _md_escape(text)

    n = len(text)
    spans: list[tuple[int, int, str, str | None]] = []
    for m in markup:
        if not isinstance(m, dict):
            continue
        try:
            start = max(0, int(m.get("from", 0)))
            length = int(m.get("length", 0))
        except (TypeError, ValueError):
            continue
        mtype = (m.get("type") or "").lower()
        end = min(n, start + length)
        if start >= end:
            continue
        url = m.get("url") if isinstance(m.get("url"), str) else None
        spans.append((start, end, mtype, url))

    if not spans:
        return _md_escape(text)

    # выбираем непересекающиеся в порядке слева-направо (длинные приоритетнее
    # на одной точке старта).
    spans.sort(key=lambda s: (s[0], -s[1]))
    chosen: list[tuple[int, int, str, str | None]] = []
    last_end = 0
    for s in spans:
        if s[0] >= last_end:
            chosen.append(s)
            last_end = s[1]

    out: list[str] = []
    pos = 0
    for start, end, mtype, url in chosen:
        if pos < start:
            out.append(_md_escape(text[pos:start]))
        segment = _md_escape(text[start:end])
        out.append(_wrap_segment(segment, mtype, url, raw_segment=text[start:end]))
        pos = end
    if pos < n:
        out.append(_md_escape(text[pos:]))
    return "".join(out)


def _wrap_segment(escaped: str, mtype: str, url: str | None, raw_segment: str) -> str:
    if mtype in _FMT_WRAP:
        open_md, close_md = _FMT_WRAP[mtype]
        return f"{open_md}{escaped}{close_md}"
    if mtype == "link":
        href = url or raw_segment
        return f"[{escaped}]({href})"
    if mtype == "quote":
        # цитата как блочный префикс перед каждой строкой
        return "\n".join("> " + part for part in escaped.split("\n"))
    if mtype == "pre":
        # многострочный код
        return f"```\n{raw_segment}\n```"
    return escaped


def _parse_markup_raw(raw) -> list[dict] | None:
    if not raw or raw in ("null", "[]"):
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        import json as _json
        try:
            data = _json.loads(raw)
        except (ValueError, TypeError):
            return None
        if isinstance(data, list):
            return data
    return None


def _user_display_name(profile) -> str:
    if profile and profile.name:
        return profile.name
    if profile and profile.username:
        return f"@{profile.username}"
    return "—"


def _user_name_md(profile, user_id: int, *, as_link: bool) -> str:
    """Имя пользователя жирным. У админа — ещё и кликабельной ссылкой на профиль."""
    name = _user_display_name(profile)
    safe = _md_escape(name)
    if as_link:
        return f"**[{safe}](max://user/{user_id})**"
    return f"**{safe}**"


def _has_attachments(message: dict) -> bool:
    raw = message.get("attachments")
    return bool(raw) and raw not in ("null", "[]")


def _history_line(message: dict, user_name_md: str) -> str | None:
    sender = message["sender"]
    text = message.get("text") or ""
    if sender == "system":
        # системные события (смена статуса) — статус всегда виден в шапке,
        # поэтому в истории их не показываем
        return None
    if sender == "user":
        sender_md = user_name_md
    else:
        sender_md = f"**{SUPPORT_NAME}**"
    markup = _parse_markup_raw(message.get("markup"))
    formatted = format_with_markup(text, markup)
    suffix = " 📎" if _has_attachments(message) else ""
    return f"{sender_md}: {formatted}{suffix}".rstrip()


async def build_ticket_history(ctx: BotContext, ticket: Ticket) -> str:
    return await _build_history(ctx, ticket, admin_view=False)


async def build_admin_ticket_history(ctx: BotContext, ticket: Ticket) -> str:
    return await _build_history(ctx, ticket, admin_view=True)


async def _build_history(ctx: BotContext, ticket: Ticket, *, admin_view: bool) -> str:
    messages = await ctx.db.get_last_messages(ticket.id)
    profile = await ctx.db.get_user(ticket.user_id)

    # имя пользователя — ссылкой у админа, обычным у пользователя
    user_md = _user_name_md(profile, ticket.user_id, as_link=admin_view)
    support_md = f"**{SUPPORT_NAME}**"

    if ticket.initiated_by == "support":
        from_label = support_md
        to_label = user_md
    else:
        from_label = user_md
        to_label = support_md

    status_label = STATUS_LABELS.get(ticket.status, ticket.status)
    lines = [
        f"🎫 **Тикет №{ticket.id}**",
        f"👤 **От кого:** {from_label}",
        f"📨 **Кому:** {to_label}",
        f"🆔 **ID:** `{ticket.user_id}`",
        f"📅 **Создан:** {format_ticket_date(ticket.created_at)}",
        f"🔄 **Обновлён:** {format_ticket_date(ticket.updated_at)}",
        "",
        f"🔖 **Статус:** {_md_escape(status_label)}",
        "",
        "💬 **История:**",
    ]
    if not messages:
        lines.append("_Сообщений пока нет._")
    for message in messages:
        line = _history_line(message, user_md)
        if line is not None:
            lines.append(line)
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

    # Если это первая страница истории — после самой истории шлём вложения
    # каждого сообщения отдельным постом «📎 Вложение N к тикету №X».
    if page == 0:
        await _send_ticket_attachments(ctx, user_id, ticket)


async def _send_ticket_attachments(
    ctx: BotContext, user_id: int, ticket: Ticket
) -> None:
    import json as _json

    messages = await ctx.db.get_last_messages(ticket.id)
    counter = 0
    for msg in messages:
        raw = msg.get("attachments")
        if not raw or raw in ("null", "[]"):
            continue
        try:
            attachments = _json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            continue
        if not isinstance(attachments, list) or not attachments:
            continue
        counter += 1
        try:
            reuploaded = await ctx.api.reupload_attachments(attachments)
        except Exception:
            reuploaded = []
        caption = f"📎 Вложение {counter} к тикету №{ticket.id}"
        try:
            await ctx.api.send_message(
                user_id=user_id,
                text=caption,
                attachments=reuploaded or None,
                fmt="markdown",
            )
        except Exception:
            pass


def user_ticket_back_keyboard(ticket: Ticket) -> list[dict]:
    return kb.user_ticket_controls(ticket.id, ticket.status == STATUS_CLOSED)
