from __future__ import annotations

import json
import logging
from typing import Optional

import keyboards as kb
import texts
from database import STATUS_LABELS
from handlers.context import BotContext
from states import State
from ticket_utils import send_ticket_history, user_ticket_back_keyboard


def _dump_attachments(attachments: Optional[list[dict]]) -> Optional[str]:
    if not attachments:
        return None
    try:
        return json.dumps(attachments, ensure_ascii=False)
    except (TypeError, ValueError):
        return None

logger = logging.getLogger(__name__)
TICKETS_PER_PAGE = 5


def _format_consent_text(consent_done: bool, offer_done: bool, docs_sent: bool) -> str:
    consent_status = "✅ Согласие принято" if consent_done else "⬜ Согласие не принято"
    offer_status = "✅ Оферта принята" if offer_done else "⬜ Оферта не принята"
    parts = [texts.CONSENT_INTRO, "", consent_status, offer_status]
    return "\n".join(parts)


async def cmd_start(ctx: BotContext, user_id: int, chat_id: int | None) -> None:
    profile = await ctx.db.get_user(user_id)
    if profile is None or not profile.consent_accepted or not profile.offer_accepted:
        await show_consent(ctx, user_id, profile)
        return
    await show_main_menu(ctx, user_id)


async def show_consent(
    ctx: BotContext, user_id: int, profile=None, callback_id: str = ""
) -> None:
    if profile is None:
        profile = await ctx.db.get_user(user_id)
    consent_done = profile.consent_accepted if profile else False
    offer_done = profile.offer_accepted if profile else False

    docs_sent = True
    ctx.states.set(user_id, State.CONSENT_REQUIRED, docs_sent=docs_sent)
    attachments = kb.consent_keyboard(consent_done, offer_done)
    await ctx.reply_menu(
        user_id=user_id,
        text=_format_consent_text(consent_done, offer_done, docs_sent),
        attachments=attachments,
        callback_id=callback_id,
    )


async def accept_consent(
    ctx: BotContext, user_id: int, field: str, callback_id: str = ""
) -> None:
    if field == "all":
        await ctx.db.set_consent(user_id, "consent_accepted")
        await ctx.db.set_consent(user_id, "offer_accepted")
    elif field in ("consent_accepted", "offer_accepted"):
        await ctx.db.set_consent(user_id, field)
    else:
        logger.warning("Неизвестное поле согласия: %s", field)

    profile = await ctx.db.get_user(user_id)
    if profile and profile.consent_accepted and profile.offer_accepted:
        await show_main_menu(ctx, user_id, callback_id=callback_id)
        return
    await show_consent(ctx, user_id, profile, callback_id=callback_id)


async def show_main_menu(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    ctx.states.set(user_id, State.MAIN_MENU)
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.WELCOME,
        attachments=kb.main_menu(user_id in ctx.cfg.admin_ids),
        callback_id=callback_id,
    )


async def show_instructions_menu(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    ctx.states.set(user_id, State.INSTRUCTIONS_MENU)
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.INSTRUCTIONS_HEADER,
        attachments=kb.instructions_menu(),
        callback_id=callback_id,
    )


async def show_inst_add_channel(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.INST_ADD_CHANNEL,
        attachments=kb.back_to_instructions(),
        callback_id=callback_id,
    )


async def show_inst_create_poll(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.INST_CREATE_POLL,
        attachments=kb.back_to_instructions(),
        callback_id=callback_id,
    )


async def show_inst_onetime(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.INST_ONETIME,
        attachments=kb.back_to_instructions(),
        callback_id=callback_id,
    )


async def show_inst_premium(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.INST_PREMIUM,
        attachments=kb.back_to_instructions(),
        callback_id=callback_id,
    )


async def show_profile_menu(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    ctx.states.set(user_id, State.PROFILE_MENU)
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.PROFILE_HEADER,
        attachments=kb.profile_menu(),
        callback_id=callback_id,
    )


async def show_prof_subscription(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    profile = await ctx.db.get_user(user_id)
    status = "👑 Premium" if (profile and profile.is_premium) else "Обычный"
    expiry = profile.premium_expiry if (profile and profile.premium_expiry) else "—"

    await ctx.reply_menu(
        user_id=user_id,
        text=texts.PROF_SUBSCRIPTION.format(
            user_id=user_id, status=status, expiry=expiry
        ),
        attachments=kb.back_to_profile(),
        callback_id=callback_id,
    )


async def show_prof_my_channels(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.PROF_MY_CHANNELS,
        attachments=kb.back_to_profile(),
        callback_id=callback_id,
    )


async def show_prof_scheduled(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.PROF_SCHEDULED,
        attachments=kb.back_to_profile(),
        callback_id=callback_id,
    )


async def ask_ticket(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    ctx.states.set(user_id, State.MAIN_MENU)
    active_count = await ctx.db.count_user_tickets(user_id, archived=False)
    archive_count = await ctx.db.count_user_tickets(user_id, archived=True)
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.SUPPORT_MENU_TEXT,
        attachments=kb.support_menu(active_count, archive_count),
        callback_id=callback_id,
    )


async def ask_new_ticket(ctx: BotContext, user_id: int, callback_id: str = "") -> None:
    ctx.states.set(user_id, State.TICKET_WAITING_TEXT)
    await ctx.reply_menu(
        user_id=user_id,
        text=texts.ASK_TICKET_TEXT,
        attachments=kb.back_from_ticket(),
        callback_id=callback_id,
    )


async def show_user_tickets(
    ctx: BotContext, user_id: int, archived: bool, callback_id: str = "", page: int = 0
) -> None:
    total = await ctx.db.count_user_tickets(user_id, archived=archived)
    total_pages = max(1, (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    tickets = await ctx.db.list_user_tickets(
        user_id,
        archived=archived,
        limit=TICKETS_PER_PAGE,
        offset=page * TICKETS_PER_PAGE,
    )
    if tickets:
        text = texts.USER_TICKETS_ARCHIVE_HEADER if archived else texts.USER_TICKETS_ACTIVE_HEADER
    else:
        text = texts.USER_TICKETS_EMPTY_ARCHIVE if archived else texts.USER_TICKETS_EMPTY_ACTIVE
    await ctx.reply_menu(
        user_id=user_id,
        text=text,
        attachments=kb.user_tickets_list(tickets, archived, page, total_pages),
        callback_id=callback_id,
    )


async def open_user_ticket(
    ctx: BotContext, user_id: int, ticket_id: int, callback_id: str = "", page: int = 0
) -> None:
    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None or ticket.user_id != user_id:
        await ask_ticket(ctx, user_id, callback_id=callback_id)
        return
    await send_ticket_history(
        ctx,
        user_id,
        ticket,
        attachments=user_ticket_back_keyboard(ticket),
        callback_id=callback_id,
        page=page,
    )


async def ask_reply_to_ticket(
    ctx: BotContext, user_id: int, ticket_id: int, callback_id: str = ""
) -> None:
    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None or ticket.user_id != user_id:
        await ask_ticket(ctx, user_id, callback_id=callback_id)
        return
    ctx.states.set(user_id, State.TICKET_WAITING_TEXT, ticket_id=ticket_id)
    await ctx.reply_menu(
        user_id=user_id,
        text="💬 Напишите сообщение для тикета одним сообщением. Можно прикрепить фото или файл.",
        attachments=kb.back_from_ticket(),
        callback_id=callback_id,
    )


async def create_ticket(
    ctx: BotContext,
    user_id: int,
    user_name: str,
    text: str,
    attachments: Optional[list[dict]] = None,
) -> None:
    subject = text or "📎 (вложение)"
    ticket_id = await ctx.db.create_ticket(
        user_id=user_id,
        subject=subject,
        attachments=_dump_attachments(attachments),
    )
    ctx.states.set(user_id, State.MAIN_MENU)
    await ctx.db.auto_set_review_if_untouched(ticket_id)
    ticket = await ctx.db.get_ticket(ticket_id)

    try:
        await ctx.api.send_message(
            user_id=user_id,
            text=texts.TICKET_AUTO_REVIEW.format(ticket_id=ticket_id),
            fmt="markdown",
        )
    except Exception as exc:
        logger.exception("Не удалось отправить авто-статус пользователю: %s", exc)

    if ticket:
        await send_ticket_history(
            ctx,
            user_id,
            ticket,
            attachments=user_ticket_back_keyboard(ticket),
        )
    else:
        await ctx.api.send_message(
            user_id=user_id,
            text=texts.TICKET_CREATED.format(ticket_id=ticket_id),
            attachments=kb.support_menu(),
            fmt="markdown",
        )

    for admin_id in ctx.cfg.admin_ids:
        try:
            if attachments:
                await ctx.api.send_message(
                    user_id=admin_id,
                    text="",
                    attachments=attachments,
                )
            await ctx.api.send_message(
                user_id=admin_id,
                text=texts.ADMIN_NEW_TICKET.format(
                    ticket_id=ticket_id,
                    user_name=user_name or "Пользователь",
                    user_id=user_id,
                    subject=subject,
                ),
                attachments=kb.admin_new_ticket(ticket_id),
                fmt="markdown",
            )
        except Exception as exc:
            logger.exception("Не удалось уведомить админа %s: %s", admin_id, exc)


async def reply_to_ticket(
    ctx: BotContext,
    user_id: int,
    text: str,
    ticket_id: int,
    attachments: Optional[list[dict]] = None,
) -> None:
    ticket = await ctx.db.get_ticket(ticket_id)
    if ticket is None or ticket.user_id != user_id:
        ctx.states.set(user_id, State.MAIN_MENU)
        await ctx.api.send_message(user_id=user_id, text="Тикет не найден.")
        return
    await ctx.db.add_message(
        ticket.id, "user", text, attachments=_dump_attachments(attachments)
    )
    ctx.states.set(user_id, State.MAIN_MENU)
    status_changed = await ctx.db.auto_set_review_if_untouched(ticket.id)
    if status_changed:
        try:
            await ctx.api.send_message(
                user_id=user_id,
                text=texts.TICKET_AUTO_REVIEW.format(ticket_id=ticket.id),
                fmt="markdown",
            )
        except Exception as exc:
            logger.exception("Не удалось отправить авто-статус: %s", exc)
    updated = await ctx.db.get_ticket(ticket.id)
    profile = await ctx.db.get_user(user_id)
    user_name = profile.name if profile and profile.name else "—"
    await send_ticket_history(
        ctx,
        user_id,
        updated or ticket,
        attachments=user_ticket_back_keyboard(updated or ticket),
    )
    for admin_id in ctx.cfg.admin_ids:
        try:
            if attachments:
                await ctx.api.send_message(
                    user_id=admin_id,
                    text="",
                    attachments=attachments,
                )
            await ctx.api.send_message(
                user_id=admin_id,
                text=(
                    f"💬 *Сообщение по тикету №{ticket.id}* "
                    f"(статус: {STATUS_LABELS.get(ticket.status, ticket.status)})\n\n"
                    f"👤 {user_name} (id {user_id}): {text}"
                ),
                attachments=kb.admin_new_ticket(ticket.id),
                fmt="markdown",
            )
        except Exception as exc:
            logger.exception("Не удалось уведомить админа %s: %s", admin_id, exc)


async def append_to_open_ticket(
    ctx: BotContext,
    user_id: int,
    text: str,
    attachments: Optional[list[dict]] = None,
) -> bool:
    ticket = await ctx.db.find_open_ticket_by_user(user_id)
    if ticket is None:
        return False
    await ctx.db.add_message(
        ticket.id, "user", text, attachments=_dump_attachments(attachments)
    )
    status_changed = await ctx.db.auto_set_review_if_untouched(ticket.id)
    if status_changed:
        try:
            await ctx.api.send_message(
                user_id=user_id,
                text=texts.TICKET_AUTO_REVIEW.format(ticket_id=ticket.id),
                fmt="markdown",
            )
        except Exception as exc:
            logger.exception("Не удалось отправить авто-статус: %s", exc)
    profile = await ctx.db.get_user(user_id)
    user_name = profile.name if profile and profile.name else "—"
    for admin_id in ctx.cfg.admin_ids:
        try:
            if attachments:
                await ctx.api.send_message(
                    user_id=admin_id,
                    text="",
                    attachments=attachments,
                )
            await ctx.api.send_message(
                user_id=admin_id,
                text=(
                    f"💬 *Сообщение по тикету №{ticket.id}* "
                    f"(статус: {STATUS_LABELS.get(ticket.status, ticket.status)})\n\n"
                    f"👤 {user_name} (id {user_id}): {text}"
                ),
                attachments=kb.admin_new_ticket(ticket.id),
                fmt="markdown",
            )
        except Exception as exc:
            logger.exception("Не удалось уведомить админа %s: %s", admin_id, exc)
    return True
