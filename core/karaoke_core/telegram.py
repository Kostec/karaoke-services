"""Telegram-бот для уведомлений: отправка сообщения и поиск чата (``getUpdates``).

Токен бота стоит в пути адреса (``/bot<токен>/метод``), поэтому он не должен попасть ни в текст
ошибки, ни в лог: ``TelegramError`` пишется своими словами, любой посторонний текст чистится
от токена, а лог ``karaoke.http`` (адрес запроса при сбое связи) прячет путь ``/bot…/``.
Аргумент с токеном — позиционный ``bot_key`` (сканер секретов репозитория).
"""

from __future__ import annotations

import json
import logging
import re

from .http import HttpError

__all__ = ["TelegramError", "send_message", "find_chat", "API_BASE", "TIMEOUT_S", "valid_key",
           "valid_chat_id"]

API_BASE = "https://api.telegram.org"
TIMEOUT_S = 10.0  # воркер один: зависший Telegram не должен держать очередь
TEXT_MAX = 4000   # предел Telegram — 4096 символов

KEY_RE = re.compile(r"^\d{3,}:[A-Za-z0-9_-]{10,}$")
CHAT_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{3,})$")
_BOT_PATH_RE = re.compile(r"(telegram\.org/bot)[^/\s'\"]+")
_MASK = r"\g<1>***"

MSG_BAD_KEY = "Telegram не принял токен бота — скопируйте его заново у @BotFather"
MSG_KEY_FORMAT = "Токен бота выглядит как 123456:ABC… — скопируйте его у @BotFather"
MSG_CHAT_FORMAT = "Chat id — число (например 248019337) или @имя_канала"
MSG_NETWORK = "Telegram недоступен — нет связи с api.telegram.org"
MSG_WEBHOOK = "У бота включён webhook — «Найти чат» не работает, впишите chat id вручную"


class TelegramError(Exception):
    """Отказ Telegram по-русски, без токена. ``field`` — какое поле формы виновато
    (``bot_token``/``chat_id``) или ``None``; ``network`` — нет связи (не ответ Telegram)."""

    def __init__(self, message: str, *, field: str | None = None, network: bool = False):
        super().__init__(message)
        self.field = field
        self.network = network


def valid_key(bot_key: str | None) -> bool:
    return bool(bot_key) and bool(KEY_RE.match(bot_key))


def valid_chat_id(chat_id: str | None) -> bool:
    return bool(chat_id) and bool(CHAT_RE.match(chat_id))


def _hide(text: str, bot_key: str) -> str:
    text = _BOT_PATH_RE.sub(_MASK, text)
    return text.replace(bot_key, "***") if bot_key else text


def _description(body: bytes) -> str:
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return ""
    return str(data.get("description") or "") if isinstance(data, dict) else ""


def _call(http, bot_key: str, method: str, *, data: dict | None = None) -> object:
    """Вызов метода Bot API → ``result``; любой сбой — ``TelegramError`` без токена."""
    if not valid_key(bot_key):
        raise TelegramError(MSG_KEY_FORMAT, field="bot_token")
    url = f"{API_BASE}/bot{bot_key}/{method}"
    try:
        if data is None:
            resp = http.request("GET", url, timeout=TIMEOUT_S, max_bytes=2 * 2**20)
        else:
            resp = http.request("POST", url, data=data, timeout=TIMEOUT_S, max_bytes=2 * 2**20)
    except HttpError as e:
        desc = _hide(_description(e.body), bot_key)
        if e.status in (401, 404):
            raise TelegramError(MSG_BAD_KEY, field="bot_token") from None
        if e.status == 409:
            raise TelegramError(MSG_WEBHOOK) from None
        if e.status in (400, 403):
            raise TelegramError(f"Telegram отказал: {desc or f'ошибка {e.status}'} — проверьте chat id "
                                "и что вы написали боту", field="chat_id") from None
        if e.status is None:
            raise TelegramError(MSG_NETWORK, network=True) from None
        raise TelegramError(f"Telegram ответил ошибкой {e.status}"
                            + (f": {desc}" if desc else ""), network=e.status >= 500) from None
    try:
        payload = json.loads(resp.body.decode("utf-8", "replace"))
    except ValueError:
        raise TelegramError("Telegram прислал непонятный ответ") from None
    if not isinstance(payload, dict) or not payload.get("ok"):
        desc = _hide(str(payload.get("description") or "") if isinstance(payload, dict) else "", bot_key)
        raise TelegramError(f"Telegram отказал{': ' + desc if desc else ''}")
    return payload.get("result")


def send_message(http, bot_key: str, chat_id: str, text: str) -> None:
    """Отправить сообщение в чат. Ошибка — ``TelegramError`` (текст без токена)."""
    if not valid_chat_id(chat_id):
        if not valid_key(bot_key):
            raise TelegramError(MSG_KEY_FORMAT, field="bot_token")
        raise TelegramError(MSG_CHAT_FORMAT, field="chat_id")
    if len(text) > TEXT_MAX:
        text = text[:TEXT_MAX - 1] + "…"
    _call(http, bot_key, "sendMessage",
          data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"})


_CHAT_KEYS = ("message", "edited_message", "channel_post", "edited_channel_post", "my_chat_member",
              "chat_member", "chat_join_request")


def find_chat(http, bot_key: str) -> str | None:
    """Chat id из последнего обновления бота (``getUpdates``) или ``None`` — боту ещё не писали."""
    result = _call(http, bot_key, "getUpdates")
    found = None
    for update in result if isinstance(result, list) else []:
        if not isinstance(update, dict):
            continue
        for key in _CHAT_KEYS:
            chat = (update.get(key) or {}).get("chat") if isinstance(update.get(key), dict) else None
            if isinstance(chat, dict) and chat.get("id") is not None:
                found = str(chat["id"])
                break
    return found


class _HideBotPath(logging.Filter):
    """Фильтр лога ``karaoke.http``: адрес ``…/bot<токен>/метод`` → ``…/bot***/метод``."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and "/bot" in record.msg:
            record.msg = _BOT_PATH_RE.sub(_MASK, record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_BOT_PATH_RE.sub(_MASK, a) if isinstance(a, str) else a
                                for a in record.args)
        return True


_http_log = logging.getLogger("karaoke.http")
if not any(isinstance(f, _HideBotPath) for f in _http_log.filters):
    _http_log.addFilter(_HideBotPath())
