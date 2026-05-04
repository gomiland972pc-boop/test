from __future__ import annotations

from enum import Enum
from typing import Any


class State(str, Enum):

    CONSENT_REQUIRED = "consent_required"  # экран согласия/оферты
    MAIN_MENU = "main_menu"
    INSTRUCTIONS_MENU = "instructions_menu"  # подменю «Инструкции по боту»
    PROFILE_MENU = "profile_menu"            # подменю «Профиль и каналы»
    TICKET_WAITING_TEXT = "ticket_waiting_text"
    ADMIN_REPLYING = "admin_replying"  # админ пишет ответ по конкретному тикету


class StateStore:

    def __init__(self) -> None:
        self._store: dict[int, tuple[State, dict[str, Any]]] = {}

    def get(self, user_id: int) -> tuple[State, dict[str, Any]]:
        return self._store.get(user_id, (State.MAIN_MENU, {}))

    def set(self, user_id: int, state: State, **data: Any) -> None:
        self._store[user_id] = (state, dict(data))

    def reset(self, user_id: int) -> None:
        self._store.pop(user_id, None)

    def update_data(self, user_id: int, **data: Any) -> None:
        state, existing = self.get(user_id)
        existing.update(data)
        self._store[user_id] = (state, existing)
