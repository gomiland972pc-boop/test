from __future__ import annotations

import asyncio
import hmac
import logging
import signal

from aiohttp import web

from config import Config
from database import Database
from handlers.context import BotContext
from handlers.router import dispatch
from max_api import MaxApiError, MaxBotApi
from states import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("max_bot")

UPDATE_TYPES = ["message_created", "message_callback", "bot_started"]


async def run() -> None:
    cfg = Config.load()
    db = Database(cfg.db_path)
    await db.connect()

    api = MaxBotApi(token=cfg.bot_token, base_url=cfg.api_base)
    await api.start()

    try:
        me = await api.get_me()
        logger.info(
            "Бот авторизован: id=%s name=%s username=%s",
            me.get("user_id") or me.get("id"),
            me.get("name"),
            me.get("username"),
        )
    except MaxApiError as exc:
        logger.error("GET /me не прошёл — токен невалидный? %s", exc)
        raise

    ctx = BotContext(cfg=cfg, api=api, db=db, states=StateStore())

    app = _build_web_app(ctx)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=cfg.webhook_host, port=cfg.webhook_port)
    await site.start()
    logger.info("Webhook-сервер слушает %s:%d%s", cfg.webhook_host, cfg.webhook_port, cfg.webhook_path)

    await _register_webhook(api, cfg)

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

    try:
        await stop_event.wait()
    finally:
        try:
            await api.delete_webhook(cfg.webhook_url)
        except Exception as exc:
            logger.warning("Не удалось удалить подписку при остановке: %s", exc)
        await runner.cleanup()
        await api.close()
        await db.close()
        logger.info("Бот остановлен")


async def _register_webhook(api: MaxBotApi, cfg: Config) -> None:
    try:
        await api.delete_webhook(cfg.webhook_url)
    except Exception as exc:
        logger.debug("delete_webhook при старте: %s", exc)
    try:
        result = await api.set_webhook(
            cfg.webhook_url,
            update_types=UPDATE_TYPES,
            secret=cfg.webhook_secret or None,
        )
        logger.info("Webhook зарегистрирован на %s: %s", cfg.webhook_url, result)
    except MaxApiError as exc:
        logger.error("Не удалось зарегистрировать webhook: %s", exc)
        raise


def _build_web_app(ctx: BotContext) -> web.Application:
    app = web.Application()
    app["ctx"] = ctx
    app.router.add_post(ctx.cfg.webhook_path, _handle_webhook)
    app.router.add_get(ctx.cfg.webhook_path, _handle_webhook_warmup)
    app.router.add_get("/healthz", _handle_health)
    return app


async def _handle_health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _handle_webhook_warmup(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _handle_webhook(request: web.Request) -> web.Response:
    ctx: BotContext = request.app["ctx"]
    expected_secret = ctx.cfg.webhook_secret
    if expected_secret:
        received = request.headers.get("X-Max-Bot-Api-Secret", "")
        if not hmac.compare_digest(received, expected_secret):
            logger.warning("Неверный X-Max-Bot-Api-Secret на %s", request.path)
            return web.Response(status=403, text="forbidden")

    try:
        update = await request.json()
    except Exception as exc:
        logger.warning("Невалидный JSON в webhook: %s", exc)
        return web.Response(status=400, text="bad json")

    if not isinstance(update, dict):
        logger.warning("Webhook payload не объект: %r", update)
        return web.Response(status=400, text="bad payload")

    asyncio.create_task(_safe_dispatch(ctx, update))
    return web.Response(status=200, text="ok")


async def _safe_dispatch(ctx: BotContext, update: dict) -> None:
    try:
        await dispatch(ctx, update)
    except Exception as exc:
        logger.exception("Ошибка dispatch: %s", exc)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
