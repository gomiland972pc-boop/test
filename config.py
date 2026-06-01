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
    webhook_secret: str
    webhook_path: str
    webhook_host: str
    webhook_port: int

    @classmethod
    def load(cls) -> "Config":
        token = os.getenv("MAX_BOT_TOKEN", "").strip()
        admin_raw = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0")).strip()
        db_path = os.getenv("DB_PATH", "bot.db").strip()
        api_base = os.getenv("MAX_API_BASE", "https://botapi.max.ru").rstrip("/")
        webhook_url = os.getenv("WEBHOOK_URL", "").strip()
        webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
        webhook_path = os.getenv("WEBHOOK_PATH", "/webhook").strip() or "/webhook"
        webhook_host = os.getenv("WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0"
        webhook_port_raw = (
            os.getenv("WEBHOOK_PORT", "").strip()
            or os.getenv("PORT", "").strip()
            or "8080"
        )

        if not token:
            raise RuntimeError(
                "MAX_BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните."
            )
        if not webhook_url:
            raise RuntimeError(
                "WEBHOOK_URL не задан. Для работы через webhook укажите HTTPS URL,"
                " на который МАКС будет слать обновления."
            )
        if not webhook_url.startswith("https://"):
            raise RuntimeError("WEBHOOK_URL должен начинаться с https://")

        try:
            admin_ids = [int(x.strip()) for x in admin_raw.split(",") if x.strip()]
        except ValueError as exc:
            raise RuntimeError("ADMIN_IDS должен быть списком целых чисел через запятую") from exc

        try:
            webhook_port = int(webhook_port_raw)
        except ValueError as exc:
            raise RuntimeError("WEBHOOK_PORT должен быть целым числом") from exc

        if not webhook_path.startswith("/"):
            webhook_path = "/" + webhook_path

        return cls(
            bot_token=token,
            admin_ids=admin_ids,
            db_path=db_path,
            api_base=api_base,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            webhook_path=webhook_path,
            webhook_host=webhook_host,
            webhook_port=webhook_port,
        )
