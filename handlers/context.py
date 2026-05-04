from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import Config
from database import Database
from max_api import MaxBotApi
from states import StateStore

logger = logging.getLogger(__name__)

@dataclass
class BotContext:

    cfg: Config
    api: MaxBotApi
    db: Database
    states: StateStore

    async def reply_menu(
        self,
        user_id: int,
        text: str,
        attachments: Optional[list[dict]] = None,
        fmt: str = "markdown",
        callback_id: str = "",
    ) -> None:
        if callback_id:
            try:
                await self.api.answer_callback(callback_id)
            except Exception as exc:
                logger.warning("answer_callback failed: %s", exc)
        await self.api.send_message(
            user_id=user_id,
            text=text,
            attachments=attachments,
            fmt=fmt,
        )
