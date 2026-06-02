from __future__ import annotations

import texts
from database import STATUS_CLOSED, STATUS_REVIEW, STATUS_SPECIALIST, STATUS_PREPARING


CB_ACCEPT_DOCS = "docs:accept"
CB_CONSENT = "docs:consent"
CB_OFFER = "docs:offer"

CB_MENU_INSTRUCTIONS = "menu:instructions"
CB_MENU_PROFILE = "menu:profile"
CB_MENU_SUPPORT = "menu:support"
CB_MENU_ADMIN = "menu:admin"

CB_INST_ADD_CHANNEL = "inst:add_channel"
CB_INST_CREATE_POLL = "inst:create_poll"
CB_INST_ONETIME = "inst:onetime"
CB_INST_PREMIUM = "inst:premium"
CB_INST_BACK = "inst:back"

CB_PROF_SUBSCRIPTION = "prof:subscription"
CB_PROF_MY_CHANNELS = "prof:my_channels"
CB_PROF_SCHEDULED = "prof:scheduled"
CB_PROF_BACK = "prof:back"

CB_BACK_MAIN = "back:main"
CB_BACK_INSTRUCTIONS = "back:instructions"
CB_BACK_PROFILE = "back:profile"
CB_BACK_FROM_TICKET = "back:ticket"

CB_ADMIN_REFRESH = "admin:refresh"
CB_TICKET_NEW = "ticket:new"
CB_TICKET_ACTIVE = "ticket:active"
CB_TICKET_ARCHIVE = "ticket:archive"
CB_TICKET_LIST_PAGE = "ticket:list:"
CB_TICKET_OPEN = "ticket:open:"
CB_TICKET_BACK_LIST = "ticket:back:"
CB_TICKET_REPLY = "ticket:reply:"
CB_TICKET_PAGE = "ticket:page:"

CB_ADMIN_OPEN = "admin:open:"
CB_ADMIN_ACTIVE = "admin:active"
CB_ADMIN_ARCHIVE = "admin:archive"
CB_ADMIN_LIST_REFRESH = "admin:list_refresh:"
CB_ADMIN_LIST_PAGE = "admin:list:"
CB_ADMIN_PAGE = "admin:page:"
CB_ADMIN_STATUS = "admin:status:"
CB_ADMIN_REPLY = "admin:reply:"
CB_ADMIN_BACK = "admin:back"
CB_ADMIN_USERS = "admin:users"
CB_ADMIN_USERS_PAGE = "admin:users_page:"
CB_ADMIN_WRITE_USER = "admin:write_user"
CB_ADMIN_TEST_NICK = "admin:test_nick"
CB_ADMIN_TEST_NICK_PAGE = "admin:test_nick:page:"
CB_ADMIN_TEST_NICK_SELECT = "admin:test_nick:sel:"


def _btn(text: str, payload: str) -> dict:
    return {"type": "callback", "text": text, "payload": payload}


def _kb(rows: list[list[dict]]) -> list[dict]:
    return [{"type": "inline_keyboard", "payload": {"buttons": rows}}]


def consent_keyboard(consent_done: bool, offer_done: bool) -> list[dict]:
    rows: list[list[dict]] = [
        [{"type": "link", "text": "📄 Открыть документы", "url": texts.DOCUMENTS_URL}]
    ]
    if not consent_done:
        rows.append([_btn("✅ Принять Согласие", CB_CONSENT)])
    if not offer_done:
        rows.append([_btn("✅ Принять Оферту", CB_OFFER)])
    return _kb(rows)


def main_menu(is_admin: bool = False) -> list[dict]:
    rows = [
        [_btn("📖 Инструкции по боту", CB_MENU_INSTRUCTIONS)],
        [_btn("👤 Профиль и каналы", CB_MENU_PROFILE)],
        [_btn("🆘 Связаться с нами", CB_MENU_SUPPORT)],
    ]
    if is_admin:
        rows.append([_btn("🛠 Админ-панель", CB_MENU_ADMIN)])
    return _kb(rows)


def instructions_menu() -> list[dict]:
    return _kb(
        [
            [_btn("📢 Как добавить канал/чат", CB_INST_ADD_CHANNEL)],
            [_btn("📊 Как создать опрос/голосование", CB_INST_CREATE_POLL)],
            [_btn("⚡ Одноразовые функции", CB_INST_ONETIME)],
            [_btn("👑 Premium-статус", CB_INST_PREMIUM)],
            [_btn("⬅️ Назад", CB_INST_BACK)],
        ]
    )


def profile_menu() -> list[dict]:
    return _kb(
        [
            [_btn("📋 Профиль/Подписка", CB_PROF_SUBSCRIPTION)],
            [_btn("📡 Мои каналы", CB_PROF_MY_CHANNELS)],
            [_btn("📅 Отложенные публикации и блок голосов", CB_PROF_SCHEDULED)],
            [_btn("⬅️ Назад", CB_PROF_BACK)],
        ]
    )


def back_to_main() -> list[dict]:
    return _kb([[_btn("⬅️ Назад", CB_BACK_MAIN)]])


def back_to_instructions() -> list[dict]:
    return _kb([[_btn("⬅️ Назад", CB_BACK_INSTRUCTIONS)]])


def back_to_profile() -> list[dict]:
    return _kb([[_btn("⬅️ Назад", CB_BACK_PROFILE)]])


def back_from_ticket() -> list[dict]:
    return _kb([[_btn("⬅️ Назад", CB_BACK_FROM_TICKET)], [_btn("🏠 Меню", CB_BACK_MAIN)]])


def support_menu(active_count: int = 0, archive_count: int = 0) -> list[dict]:
    return _kb(
        [
            [_btn("➕ Открыть новый тикет", CB_TICKET_NEW)],
            [_btn(f"📂 Активные: {active_count}", CB_TICKET_ACTIVE)],
            [_btn(f"🗄 Архив: {archive_count}", CB_TICKET_ARCHIVE)],
            [_btn("⬅️ Назад", CB_BACK_MAIN)],
        ]
    )


def user_tickets_list(tickets, archived: bool, page: int = 0, total_pages: int = 1) -> list[dict]:
    rows: list[list[dict]] = []
    for t in tickets:
        from database import STATUS_LABELS
        label = f"№{t.id} | {_format_ticket_date(t.created_at)} | {STATUS_LABELS.get(t.status, t.status)}"
        rows.append([_btn(label, f"{CB_TICKET_OPEN}{t.id}")])
    nav: list[dict] = []
    kind = "archive" if archived else "active"
    if page > 0:
        nav.append(_btn("⬅️", f"{CB_TICKET_LIST_PAGE}{kind}:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{total_pages}", f"{CB_TICKET_LIST_PAGE}{kind}:{page}"))
    if page + 1 < total_pages:
        nav.append(_btn("➡️", f"{CB_TICKET_LIST_PAGE}{kind}:{page + 1}"))
    if total_pages > 1:
        rows.append(nav)
    rows.append([_btn("⬅️ Назад", CB_MENU_SUPPORT)])
    rows.append([_btn("🏠 Меню", CB_BACK_MAIN)])
    return _kb(rows)


def ticket_history_back(archived: bool) -> list[dict]:
    target = "archive" if archived else "active"
    return _kb(
        [
            [_btn("⬅️ Назад в список", f"{CB_TICKET_BACK_LIST}{target}")],
            [_btn("🏠 Меню", CB_BACK_MAIN)],
        ]
    )


def user_ticket_controls(ticket_id: int, archived: bool) -> list[dict]:
    target = "archive" if archived else "active"
    rows: list[list[dict]] = []
    if not archived:
        rows.append([_btn("💬 Ответить", f"{CB_TICKET_REPLY}{ticket_id}")])
    rows.append([_btn("⬅️ Назад в список", f"{CB_TICKET_BACK_LIST}{target}")])
    rows.append([_btn("🏠 Меню", CB_BACK_MAIN)])
    return _kb(rows)


def user_ticket_page_controls(
    ticket_id: int, archived: bool, page: int, total_pages: int
) -> list[dict]:
    rows: list[list[dict]] = []
    nav: list[dict] = []
    if page > 0:
        nav.append(_btn("⬅️", f"{CB_TICKET_PAGE}{ticket_id}:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{total_pages}", f"{CB_TICKET_PAGE}{ticket_id}:{page}"))
    if page + 1 < total_pages:
        nav.append(_btn("➡️", f"{CB_TICKET_PAGE}{ticket_id}:{page + 1}"))
    if total_pages > 1:
        rows.append(nav)
    target = "archive" if archived else "active"
    if not archived:
        rows.append([_btn("💬 Ответить", f"{CB_TICKET_REPLY}{ticket_id}")])
    rows.append([_btn("⬅️ Назад в список", f"{CB_TICKET_BACK_LIST}{target}")])
    rows.append([_btn("🏠 Меню", CB_BACK_MAIN)])
    return _kb(rows)


def admin_ticket_page_controls(ticket_id: int, page: int, total_pages: int) -> list[dict]:
    rows: list[list[dict]] = []
    nav: list[dict] = []
    if page > 0:
        nav.append(_btn("⬅️", f"{CB_ADMIN_PAGE}{ticket_id}:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{total_pages}", f"{CB_ADMIN_PAGE}{ticket_id}:{page}"))
    if page + 1 < total_pages:
        nav.append(_btn("➡️", f"{CB_ADMIN_PAGE}{ticket_id}:{page + 1}"))
    if total_pages > 1:
        rows.append(nav)
    rows.extend(admin_ticket_controls_rows(ticket_id))
    return _kb(rows)


def _format_ticket_date(value: str) -> str:
    try:
        from datetime import datetime, timezone, timedelta
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone(timedelta(hours=3)))
        return dt.strftime("%d.%m %H:%M")
    except ValueError:
        return value[:16]


def admin_new_ticket(ticket_id: int) -> list[dict]:
    return _kb([[_btn("➡️ Перейти к диалогу", f"{CB_ADMIN_OPEN}{ticket_id}")]])


def admin_folders(active_count: int = 0, archive_count: int = 0) -> list[dict]:
    return _kb(
        [
            [_btn(f"📂 Активные: {active_count}", CB_ADMIN_ACTIVE)],
            [_btn(f"🗄 Архив: {archive_count}", CB_ADMIN_ARCHIVE)],
            [_btn("👥 Пользователи", CB_ADMIN_USERS)],
            [_btn("✍️ Написать пользователю", CB_ADMIN_WRITE_USER)],
            [_btn("🏠 Меню", CB_BACK_MAIN)],
        ]
    )


def admin_test_nick_tickets_list(
    tickets, page: int = 0, total_pages: int = 1
) -> list[dict]:
    rows: list[list[dict]] = []
    for t in tickets:
        from database import STATUS_LABELS
        label = f"№{t.id} | {_format_ticket_date(t.created_at)} | {STATUS_LABELS.get(t.status, t.status)}"
        rows.append([_btn(label, f"{CB_ADMIN_TEST_NICK_SELECT}{t.id}")])
    nav: list[dict] = []
    if page > 0:
        nav.append(_btn("⬅️", f"{CB_ADMIN_TEST_NICK_PAGE}{page - 1}"))
    nav.append(_btn(f"{page + 1}/{total_pages}", f"{CB_ADMIN_TEST_NICK_PAGE}{page}"))
    if page + 1 < total_pages:
        nav.append(_btn("➡️", f"{CB_ADMIN_TEST_NICK_PAGE}{page + 1}"))
    if total_pages > 1:
        rows.append(nav)
    rows.append([_btn("⬅️ Назад к папкам", CB_ADMIN_BACK)])
    rows.append([_btn("🏠 Меню", CB_BACK_MAIN)])
    return _kb(rows)


def admin_cancel_to_folders() -> list[dict]:
    return _kb([[_btn("⬅️ Отмена", CB_ADMIN_BACK)]])


def admin_tickets_list(
    tickets, archived: bool = False, page: int = 0, total_pages: int = 1
) -> list[dict]:
    kind = "archive" if archived else "active"
    rows: list[list[dict]] = [[_btn("🔄 Обновить список", f"{CB_ADMIN_LIST_REFRESH}{kind}:{page}")]]
    for t in tickets:
        from database import STATUS_LABELS
        label = f"№{t.id} | {_format_ticket_date(t.created_at)} | {STATUS_LABELS.get(t.status, t.status)}"
        rows.append([_btn(label, f"{CB_ADMIN_OPEN}{t.id}")])
    nav: list[dict] = []
    if page > 0:
        nav.append(_btn("⬅️", f"{CB_ADMIN_LIST_PAGE}{kind}:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{total_pages}", f"{CB_ADMIN_LIST_PAGE}{kind}:{page}"))
    if page + 1 < total_pages:
        nav.append(_btn("➡️", f"{CB_ADMIN_LIST_PAGE}{kind}:{page + 1}"))
    if total_pages > 1:
        rows.append(nav)
    rows.append([_btn("⬅️ Назад к папкам", CB_ADMIN_BACK)])
    rows.append([_btn("🏠 Меню", CB_BACK_MAIN)])
    return _kb(rows)


def admin_users_list(page: int = 0, total_pages: int = 1) -> list[dict]:
    rows: list[list[dict]] = []
    nav: list[dict] = []
    if page > 0:
        nav.append(_btn("⬅️", f"{CB_ADMIN_USERS_PAGE}{page - 1}"))
    nav.append(_btn(f"{page + 1}/{total_pages}", f"{CB_ADMIN_USERS_PAGE}{page}"))
    if page + 1 < total_pages:
        nav.append(_btn("➡️", f"{CB_ADMIN_USERS_PAGE}{page + 1}"))
    if total_pages > 1:
        rows.append(nav)
    rows.append([_btn("⬅️ Назад к папкам", CB_ADMIN_BACK)])
    rows.append([_btn("🏠 Меню", CB_BACK_MAIN)])
    return _kb(rows)


def admin_ticket_controls(ticket_id: int) -> list[dict]:
    return _kb(admin_ticket_controls_rows(ticket_id))


def admin_ticket_controls_rows(ticket_id: int) -> list[list[dict]]:
    return [
        [
            _btn("🔎 На рассмотрении", f"{CB_ADMIN_STATUS}{ticket_id}:{STATUS_REVIEW}"),
            _btn("🧑‍💻 Изучает специалист", f"{CB_ADMIN_STATUS}{ticket_id}:{STATUS_SPECIALIST}"),
        ],
        [
            _btn("✍️ Готовится ответ", f"{CB_ADMIN_STATUS}{ticket_id}:{STATUS_PREPARING}"),
            _btn("✅ Закрыто", f"{CB_ADMIN_STATUS}{ticket_id}:{STATUS_CLOSED}"),
        ],
        [_btn("💬 Ответить пользователю", f"{CB_ADMIN_REPLY}{ticket_id}")],
        [_btn("⬅️ К списку", CB_ADMIN_BACK)],
        [_btn("🏠 Меню", CB_BACK_MAIN)],
    ]
