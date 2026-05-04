from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:

    bot_token: str
    admin_ids: list[int]
    db_path: str
    api_base: str
    webhook_url: str

    @classmethod
    def load(cls) -> "Config":
        token = os.getenv("MAX_BOT_TOKEN", "").strip()
        admin_raw = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0")).strip()
        db_path = os.getenv("DB_PATH", "bot.db").strip()
        api_base = os.getenv("MAX_API_BASE", "https://botapi.max.ru").rstrip("/")
        webhook_url = os.getenv("WEBHOOK_URL", "").strip()

        if not token:
            raise RuntimeError(
                "MAX_BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните."
            )

        try:
            admin_ids = [int(x.strip()) for x in admin_raw.split(",") if x.strip()]
        except ValueError as exc:
            raise RuntimeError("ADMIN_IDS должен быть списком целых чисел через запятую") from exc

        return cls(
            bot_token=token,
            admin_ids=admin_ids,
            db_path=db_path,
            api_base=api_base,
            webhook_url=webhook_url,
        )
