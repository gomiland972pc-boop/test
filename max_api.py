from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from typing import Any, AsyncIterator, Optional

import aiohttp

logger = logging.getLogger(__name__)


class MaxApiError(Exception):
    pass


class MaxBotApi:

    def __init__(
        self,
        token: str,
        base_url: str = "https://botapi.max.ru",
        request_timeout: int = 60,
        upload_timeout: int = 300,
    ) -> None:
        self._token = token
        self._base = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._upload_timeout = aiohttp.ClientTimeout(
            total=upload_timeout,
            sock_connect=60,
            sock_read=upload_timeout,
        )
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "MaxBotApi":
        await self.start()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={"Authorization": self._token},
            )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("Клиент не запущен, вызовите start()")
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> dict:
        url = f"{self._base}{path}"
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                async with self.session.request(
                    method, url, params=params, json=json
                ) as resp:
                    data: dict
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        text = await resp.text()
                        data = {"raw": text}
                    if resp.status >= 400:
                        raise MaxApiError(
                            f"{method} {path} -> HTTP {resp.status}: {data}"
                        )
                    return data if isinstance(data, dict) else {"result": data}
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                delay = 2 ** (attempt - 1)
                logger.warning(
                    "Сетевая ошибка %s %s (попытка %d): %s. Повтор через %ds",
                    method,
                    path,
                    attempt,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
        raise MaxApiError(f"Сеть недоступна: {last_exc}") from last_exc


    async def get_updates(
        self,
        marker: Optional[int] = None,
        timeout: int = 30,
        limit: int = 100,
        types: Optional[list[str]] = None,
    ) -> dict:
        params: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        return await self._request("GET", "/updates", params=params)

    async def send_message(
        self,
        *,
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        text: str,
        attachments: Optional[list[dict]] = None,
        notify: bool = True,
        fmt: Optional[str] = None,
    ) -> dict:
        if user_id is None and chat_id is None:
            raise ValueError("Нужно указать user_id или chat_id")
        params: dict[str, Any] = {}
        if user_id is not None:
            params["user_id"] = user_id
        if chat_id is not None:
            params["chat_id"] = chat_id
        body: dict[str, Any] = {"text": text, "notify": notify}
        if attachments:
            body["attachments"] = attachments
        if fmt:
            body["format"] = fmt
        return await self._request("POST", "/messages", params=params, json=body)

    async def edit_message(
        self,
        *,
        message_id: int,
        text: str,
        attachments: Optional[list[dict]] = None,
        fmt: Optional[str] = None,
    ) -> dict:
        body: dict[str, Any] = {"text": text}
        if attachments:
            body["attachments"] = attachments
        if fmt:
            body["format"] = fmt
        return await self._request(
            "PUT", "/messages", params={"message_id": message_id}, json=body
        )

    async def answer_callback(
        self,
        callback_id: str,
        *,
        notification: Optional[str] = None,
        message: Optional[dict] = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if notification is not None:
            body["notification"] = notification
        if message is not None:
            body["message"] = message
        return await self._request(
            "POST", "/answers", params={"callback_id": callback_id}, json=body
        )

    async def delete_webhook(self, url: Optional[str] = None) -> dict:
        if not url:
            logger.debug("URL webhook не задан — удаление подписки пропущено")
            return {}
        try:
            return await self._request("DELETE", "/subscriptions", params={"url": url})
        except MaxApiError as exc:
            logger.info("Не удалось удалить подписки (возможно, их не было): %s", exc)
            return {}

    async def upload_file(self, file_path: str) -> dict:
        filename = os.path.basename(file_path)
        ascii_name = filename.encode("ascii", "replace").decode("ascii")
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            data = await self._request("POST", "/uploads", params={"type": "file"})
            upload_url = data.get("url")
            if not upload_url:
                raise MaxApiError(f"POST /uploads не вернул url: {data}")
            form = aiohttp.FormData()
            form.add_field(
                "data",
                file_bytes,
                filename=ascii_name,
                content_type=content_type,
            )
            try:
                async with aiohttp.ClientSession(timeout=self._upload_timeout) as upload_sess:
                    async with upload_sess.post(upload_url, data=form) as resp:
                        if resp.status >= 400:
                            text = await resp.text()
                            raise MaxApiError(f"Upload file -> HTTP {resp.status}: {text}")
                        try:
                            payload = await resp.json(content_type=None)
                        except Exception:
                            payload = {"raw": await resp.text()}
                        return {"type": "file", "payload": payload}
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt == 3:
                    break
                delay = 2 ** (attempt - 1)
                logger.warning(
                    "Сетевая ошибка загрузки файла %s (попытка %d): %s. Повтор через %ds",
                    file_path,
                    attempt,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise MaxApiError(f"Не удалось загрузить файл {file_path}: {last_exc}") from last_exc

    async def poll_updates(
        self,
        types: Optional[list[str]] = None,
        timeout: int = 30,
    ) -> AsyncIterator[dict]:
        marker: Optional[int] = None
        while True:
            try:
                data = await self.get_updates(
                    marker=marker, timeout=timeout, types=types
                )
            except MaxApiError as exc:
                logger.error("Ошибка получения обновлений: %s", exc)
                await asyncio.sleep(3)
                continue
            for upd in data.get("updates", []) or []:
                yield upd
            marker = data.get("marker") or marker
