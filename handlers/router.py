from __future__ import annotations

import logging
from typing import Any, Optional

import keyboards as kb
import texts
from handlers import admin as admin_h
from handlers import user as user_h
from handlers.context import BotContext
from states import State

logger = logging.getLogger(__name__)

_SEEN_MID: set[str] = set()
_SEEN_MAX = 500


def _is_duplicate_mid(mid: Optional[str]) -> bool:
    if not mid:
        return False
    if mid in _SEEN_MID:
        return True
    if len(_SEEN_MID) >= _SEEN_MAX:
        _SEEN_MID.clear()
    _SEEN_MID.add(mid)
    return False


def _extract_mid(msg: dict) -> Optional[str]:
    body = msg.get("body") or {}
    mid = body.get("mid") or msg.get("mid")
    return str(mid) if mid else None


def _extract_chat_type(msg: dict) -> str:
    recipient = msg.get("recipient") or msg.get("chat") or {}
    return (recipient.get("chat_type") or "").strip().lower()


def _extract_message(update: dict) -> Optional[dict]:
    return update.get("message") or update.get("new_message")


def _extract_sender(msg: dict) -> dict:
    return msg.get("sender") or msg.get("from") or {}


def _extract_recipient(msg: dict) -> dict:
    return msg.get("recipient") or msg.get("chat") or {}


def _extract_text(msg: dict) -> str:
    body = msg.get("body") or {}
    return (body.get("text") or msg.get("text") or "").strip()


def _extract_attachments(msg: dict) -> Optional[list[dict]]:
    body = msg.get("body") or {}
    atts = body.get("attachments") or msg.get("attachments")
    if isinstance(atts, list) and atts:
        return [a for a in atts if isinstance(a, dict)]
    return None


def _extract_markup(msg: dict) -> Optional[list[dict]]:
    body = msg.get("body") or {}
    markup = body.get("markup") or msg.get("markup")
    if isinstance(markup, list) and markup:
        return [m for m in markup if isinstance(m, dict)]
    return None


def _extract_user_id(obj: dict) -> Optional[int]:
    for key in ("user_id", "id"):
        v = obj.get(key)
        if isinstance(v, int):
            return v
    return None


def _extract_chat_id(obj: dict) -> Optional[int]:
    for key in ("chat_id", "id"):
        v = obj.get(key)
        if isinstance(v, int):
            return v
    return None


def _is_bot(obj: dict) -> bool:
    if obj.get("is_bot"):
        return True
    uname = obj.get("username") or ""
    return isinstance(uname, str) and uname.endswith("_bot")


def _safe_username(obj: dict) -> Optional[str]:
    if _is_bot(obj):
        return None
    uname = obj.get("username")
    return uname if isinstance(uname, str) and uname else None


async def _has_accepted_docs(ctx: BotContext, user_id: int) -> bool:
    profile = await ctx.db.get_user(user_id)
    return bool(profile and profile.consent_accepted and profile.offer_accepted)


async def dispatch(ctx: BotContext, update: dict) -> None:
    try:
        upd_type = update.get("update_type") or update.get("type") or ""
        if upd_type in ("message_created", "message_edited", "bot_started"):
            await _handle_message(ctx, update)
        elif upd_type == "message_callback":
            await _handle_callback(ctx, update)
        else:
            logger.debug("Пропуск обновления типа %s", upd_type)
    except Exception as exc:
        logger.exception("Ошибка обработки update: %s", exc)


async def _handle_message(ctx: BotContext, update: dict) -> None:
    msg = _extract_message(update) or {}
    upd_type = update.get("update_type") or update.get("type") or ""

    mid = _extract_mid(msg)
    if _is_duplicate_mid(mid):
        logger.debug("Пропуск дубликата по mid=%s", mid)
        return

    chat_type = _extract_chat_type(msg)
    if upd_type != "bot_started" and chat_type and chat_type != "dialog":
        logger.debug("Пропуск сообщения из %s (бот работает только 1-на-1)", chat_type)
        return

    sender = _extract_sender(msg)
    recipient = _extract_recipient(msg)
    user_id = _extract_user_id(sender)
    chat_id = _extract_chat_id(recipient)
    text = _extract_text(msg)
    attachments = _extract_attachments(msg)
    markup = _extract_markup(msg)

    if user_id is None:
        user_id = update.get("user_id") or update.get("chat_id")
        if not isinstance(user_id, int):
            logger.debug("Update без user_id: %s", update)
            return

    user_name = sender.get("name") or _safe_username(sender) or ""
    username = _safe_username(sender)
    await ctx.db.upsert_user(
        user_id=user_id, name=user_name, username=username, chat_id=chat_id
    )

    if text.startswith("/"):
        await _handle_command(ctx, user_id, chat_id, text)
        return

    if upd_type == "bot_started":
        await user_h.cmd_start(ctx, user_id, chat_id)
        return

    profile = await ctx.db.get_user(user_id)
    if profile is None or not profile.consent_accepted or not profile.offer_accepted:
        await user_h.show_consent(ctx, user_id, profile)
        return

    if not text and not attachments:
        return

    state, data = ctx.states.get(user_id)

    if state == State.ADMIN_REPLYING and user_id in ctx.cfg.admin_ids:
        ticket_id = int(data.get("ticket_id", 0))
        if ticket_id:
            await admin_h.send_reply(
                ctx, user_id, ticket_id, text,
                attachments=attachments, markup=markup,
            )
            return

    if state == State.ADMIN_WAITING_USER_ID and user_id in ctx.cfg.admin_ids:
        await admin_h.handle_user_id_input(ctx, user_id, text)
        return

    if state == State.ADMIN_WAITING_FIRST_MESSAGE and user_id in ctx.cfg.admin_ids:
        target_user_id = int(data.get("target_user_id", 0))
        if target_user_id:
            await admin_h.send_first_message(
                ctx, user_id, target_user_id, text,
                attachments=attachments, markup=markup,
            )
        else:
            ctx.states.reset(user_id)
        return

    if state == State.TICKET_WAITING_TEXT:
        ticket_id = int(data.get("ticket_id", 0))
        if ticket_id:
            await user_h.reply_to_ticket(
                ctx, user_id, text, ticket_id,
                attachments=attachments, markup=markup,
            )
        else:
            await user_h.create_ticket(
                ctx, user_id, user_name, text,
                attachments=attachments, markup=markup,
            )
        return

    if user_id not in ctx.cfg.admin_ids:
        if await user_h.append_to_open_ticket(
            ctx, user_id, text, attachments=attachments, markup=markup,
        ):
            return

    await user_h.show_main_menu(ctx, user_id)


async def _handle_command(
    ctx: BotContext, user_id: int, chat_id: Optional[int], text: str
) -> None:
    cmd = text.split()[0].lower().lstrip("/").split("@")[0]
    if cmd == "start":
        await user_h.cmd_start(ctx, user_id, chat_id)
    elif cmd == "admin":
        await admin_h.cmd_admin(ctx, user_id)
    elif not await _has_accepted_docs(ctx, user_id):
        await user_h.show_consent(ctx, user_id)
    elif cmd == "menu":
        await user_h.show_main_menu(ctx, user_id)
    else:
        await user_h.show_main_menu(ctx, user_id)


async def _handle_callback(ctx: BotContext, update: dict) -> None:
    callback = update.get("callback") or {}
    callback_id = callback.get("callback_id") or update.get("callback_id") or ""
    button = callback.get("button") or update.get("button") or {}
    payload: str = (
        callback.get("payload")
        or update.get("payload")
        or button.get("payload")
        or ""
    )
    user = callback.get("user") or update.get("user") or {}
    user_id = _extract_user_id(user)
    msg = _extract_message(update) or callback.get("message") or {}
    if user_id is None:
        user_id = _extract_user_id(_extract_sender(msg))
    if user_id is None and isinstance(update.get("user_id"), int):
        user_id = update["user_id"]
    if user_id is None:
        logger.debug("Callback без user_id: %s", update)
        return
    sender = _extract_sender(msg)
    recipient = _extract_recipient(msg)
    await ctx.db.upsert_user(
        user_id=user_id,
        name=user.get("name") or _safe_username(user) or "",
        username=_safe_username(user),
        chat_id=_extract_chat_id(recipient),
    )

    if payload == kb.CB_CONSENT:
        await user_h.accept_consent(
            ctx, user_id, "consent_accepted", callback_id=callback_id
        )
        return
    if payload == kb.CB_OFFER:
        await user_h.accept_consent(
            ctx, user_id, "offer_accepted", callback_id=callback_id
        )
        return
    if payload == kb.CB_ACCEPT_DOCS:
        await user_h.accept_consent(ctx, user_id, "all", callback_id=callback_id)
        return

    if user_id in ctx.cfg.admin_ids:
        if payload == kb.CB_MENU_ADMIN:
            await admin_h.cmd_admin(ctx, user_id, callback_id=callback_id)
            return

        if payload == kb.CB_ADMIN_REFRESH:
            await admin_h.cmd_admin(ctx, user_id, callback_id=callback_id)
            return

        if payload == kb.CB_ADMIN_BACK:
            ctx.states.reset(user_id)
            await admin_h.cmd_admin(ctx, user_id, callback_id=callback_id)
            return

        if payload == kb.CB_ADMIN_ACTIVE:
            await admin_h.show_tickets(ctx, user_id, archived=False, callback_id=callback_id)
            return

        if payload == kb.CB_ADMIN_ARCHIVE:
            await admin_h.show_tickets(ctx, user_id, archived=True, callback_id=callback_id)
            return

        if payload.startswith(kb.CB_ADMIN_LIST_REFRESH):
            kind, page = _parse_list_page(payload[len(kb.CB_ADMIN_LIST_REFRESH):])
            await admin_h.show_tickets(
                ctx,
                user_id,
                archived=kind == "archive",
                callback_id=callback_id,
                page=page,
            )
            return

        if payload.startswith(kb.CB_ADMIN_LIST_PAGE):
            kind, page = _parse_list_page(payload[len(kb.CB_ADMIN_LIST_PAGE):])
            await admin_h.show_tickets(
                ctx,
                user_id,
                archived=kind == "archive",
                callback_id=callback_id,
                page=page,
            )
            return

        if payload.startswith(kb.CB_ADMIN_OPEN):
            ticket_id = _safe_int(payload[len(kb.CB_ADMIN_OPEN):])
            if ticket_id:
                await admin_h.open_ticket(ctx, user_id, ticket_id)
            return

        if payload.startswith(kb.CB_ADMIN_PAGE):
            ticket_id, page = _parse_ticket_page(payload[len(kb.CB_ADMIN_PAGE):])
            if ticket_id is not None:
                await admin_h.open_ticket(
                    ctx, user_id, ticket_id, callback_id=callback_id, page=page
                )
            return

        if payload.startswith(kb.CB_ADMIN_REPLY):
            ticket_id = _safe_int(payload[len(kb.CB_ADMIN_REPLY):])
            if ticket_id:
                await admin_h.ask_reply(ctx, user_id, ticket_id)
            return

        if payload.startswith(kb.CB_ADMIN_STATUS):
            rest = payload[len(kb.CB_ADMIN_STATUS):]
            try:
                tid_str, status = rest.split(":", 1)
                ticket_id = int(tid_str)
            except ValueError:
                return
            await admin_h.set_status(ctx, user_id, ticket_id, status)
            return

        if payload == kb.CB_ADMIN_USERS:
            await admin_h.show_users(ctx, user_id, callback_id=callback_id)
            return

        if payload == kb.CB_ADMIN_WRITE_USER:
            await admin_h.start_write_user(ctx, user_id, callback_id=callback_id)
            return

        if payload == kb.CB_ADMIN_TEST_NICK:
            await admin_h.show_test_nick_tickets(
                ctx, user_id, callback_id=callback_id
            )
            return

        if payload.startswith(kb.CB_ADMIN_TEST_NICK_PAGE):
            page = _safe_int(payload[len(kb.CB_ADMIN_TEST_NICK_PAGE):])
            await admin_h.show_test_nick_tickets(
                ctx, user_id, callback_id=callback_id, page=page or 0
            )
            return

        if payload.startswith(kb.CB_ADMIN_TEST_NICK_SELECT):
            ticket_id = _safe_int(payload[len(kb.CB_ADMIN_TEST_NICK_SELECT):])
            if ticket_id:
                await admin_h.send_test_nick(
                    ctx, user_id, ticket_id, callback_id=callback_id
                )
            return

        if payload.startswith(kb.CB_ADMIN_USERS_PAGE):
            page = _safe_int(payload[len(kb.CB_ADMIN_USERS_PAGE):])
            await admin_h.show_users(
                ctx, user_id, callback_id=callback_id, page=page or 0
            )
            return

    if not await _has_accepted_docs(ctx, user_id):
        await user_h.show_consent(ctx, user_id, callback_id=callback_id)
        return

    if payload == kb.CB_MENU_ADMIN:
        await ctx.api.send_message(user_id=user_id, text=texts.NOT_ADMIN)
        return

    if payload == kb.CB_MENU_INSTRUCTIONS:
        await user_h.show_instructions_menu(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_MENU_PROFILE:
        await user_h.show_profile_menu(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_MENU_SUPPORT:
        await user_h.ask_ticket(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_TICKET_NEW:
        await user_h.ask_new_ticket(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_TICKET_ACTIVE:
        await user_h.show_user_tickets(ctx, user_id, archived=False, callback_id=callback_id)
        return
    if payload == kb.CB_TICKET_ARCHIVE:
        await user_h.show_user_tickets(ctx, user_id, archived=True, callback_id=callback_id)
        return
    if payload.startswith(kb.CB_TICKET_LIST_PAGE):
        kind, page = _parse_list_page(payload[len(kb.CB_TICKET_LIST_PAGE):])
        await user_h.show_user_tickets(
            ctx,
            user_id,
            archived=kind == "archive",
            callback_id=callback_id,
            page=page,
        )
        return
    if payload.startswith(kb.CB_TICKET_OPEN):
        ticket_id = _safe_int(payload[len(kb.CB_TICKET_OPEN):])
        if ticket_id:
            await user_h.open_user_ticket(ctx, user_id, ticket_id, callback_id=callback_id)
        return
    if payload.startswith(kb.CB_TICKET_PAGE):
        ticket_id, page = _parse_ticket_page(payload[len(kb.CB_TICKET_PAGE):])
        if ticket_id is not None:
            await user_h.open_user_ticket(
                ctx, user_id, ticket_id, callback_id=callback_id, page=page
            )
        return
    if payload.startswith(kb.CB_TICKET_REPLY):
        ticket_id = _safe_int(payload[len(kb.CB_TICKET_REPLY):])
        if ticket_id:
            await user_h.ask_reply_to_ticket(ctx, user_id, ticket_id, callback_id=callback_id)
        return
    if payload.startswith(kb.CB_TICKET_BACK_LIST):
        target = payload[len(kb.CB_TICKET_BACK_LIST):]
        await user_h.show_user_tickets(
            ctx, user_id, archived=target == "archive", callback_id=callback_id
        )
        return

    if payload == kb.CB_INST_ADD_CHANNEL:
        await user_h.show_inst_add_channel(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_INST_CREATE_POLL:
        await user_h.show_inst_create_poll(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_INST_ONETIME:
        await user_h.show_inst_onetime(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_INST_PREMIUM:
        await user_h.show_inst_premium(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_INST_BACK:
        await user_h.show_main_menu(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_BACK_INSTRUCTIONS:
        await user_h.show_instructions_menu(ctx, user_id, callback_id=callback_id)
        return

    if payload == kb.CB_PROF_SUBSCRIPTION:
        await user_h.show_prof_subscription(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_PROF_MY_CHANNELS:
        await user_h.show_prof_my_channels(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_PROF_SCHEDULED:
        await user_h.show_prof_scheduled(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_PROF_BACK:
        await user_h.show_main_menu(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_BACK_PROFILE:
        await user_h.show_profile_menu(ctx, user_id, callback_id=callback_id)
        return

    if payload == kb.CB_BACK_MAIN:
        await user_h.show_main_menu(ctx, user_id, callback_id=callback_id)
        return
    if payload == kb.CB_BACK_FROM_TICKET:
        ctx.states.set(user_id, State.MAIN_MENU)
        await user_h.ask_ticket(ctx, user_id, callback_id=callback_id)
        return

    if user_id not in ctx.cfg.admin_ids:
        if callback_id:
            try:
                await ctx.api.answer_callback(callback_id)
            except Exception as exc:
                logger.warning("answer_callback failed: %s", exc)
        return


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _parse_ticket_page(s: str) -> tuple[Optional[int], int]:
    try:
        ticket_id, page = s.split(":", 1)
        return int(ticket_id), max(0, int(page))
    except (TypeError, ValueError):
        return None, 0


def _parse_list_page(s: str) -> tuple[str, int]:
    try:
        kind, page = s.split(":", 1)
        if kind not in ("active", "archive"):
            kind = "active"
        return kind, max(0, int(page))
    except (TypeError, ValueError):
        return "active", 0
