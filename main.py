from __future__ import annotations

import asyncio
import logging
import signal

from config import Config
from database import Database
from handlers.context import BotContext
from handlers.router import dispatch
from max_api import MaxBotApi
from states import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("max_bot")


async def run() -> None:
    cfg = Config.load()
    db = Database(cfg.db_path)
    await db.connect()

    api = MaxBotApi(token=cfg.bot_token, base_url=cfg.api_base)
    await api.start()

    await api.delete_webhook(cfg.webhook_url)

    ctx = BotContext(cfg=cfg, api=api, db=db, states=StateStore())

    stop_event = asyncio.Event()

    def _graceful_stop(*_args: object) -> None:
        logger.info("Получен сигнал остановки")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _graceful_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _graceful_stop())

    logger.info("Бот запущен. admin_ids=%s, db=%s", cfg.admin_ids, cfg.db_path)

    poller = asyncio.create_task(_poll_loop(ctx, stop_event))
    try:
        await stop_event.wait()
    finally:
        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass
        await api.close()
        await db.close()
        logger.info("Бот остановлен")


async def _poll_loop(ctx: BotContext, stop_event: asyncio.Event) -> None:
    types = ["message_created", "message_callback", "bot_started"]
    marker = None
    while not stop_event.is_set():
        try:
            data = await ctx.api.get_updates(marker=marker, timeout=30, types=types)
        except Exception as exc:
            logger.error("Ошибка get_updates: %s", exc)
            await asyncio.sleep(3)
            continue

        for upd in data.get("updates") or []:
            await dispatch(ctx, upd)

        new_marker = data.get("marker")
        if new_marker is not None:
            marker = new_marker


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
