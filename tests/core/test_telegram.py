"""Telegram-бот: отправка сообщения и поиск чата через FakeHttp; токен не утекает в тексты ошибок."""

import json
import logging

import pytest

from fakes_http import FakeHttp, response
from karaoke_core import telegram
from karaoke_core.http import HttpError

BOT = "123456:AAH-test_Key"
API = f"https://api.telegram.org/bot{BOT}"


def _http(**routes):
    http = FakeHttp()
    for method_path, resp in routes.items():
        method, path = method_path.split("_", 1)
        http.route(method, f"{API}/{path}", resp)
    return http


def test_send_message_posts_chat_and_text():
    http = _http(POST_sendMessage=response(json={"ok": True, "result": {"message_id": 1}}))
    telegram.send_message(http, BOT, "248019337", "✅ Готово: А — Б (генерация)")
    [req] = http.calls(f"{API}/sendMessage")
    assert req.method == "POST"
    assert req.data["chat_id"] == "248019337"
    assert req.data["text"] == "✅ Готово: А — Б (генерация)"
    assert req.timeout is not None and req.timeout <= 15


@pytest.mark.parametrize("status, field", [(401, "bot_token"), (404, "bot_token"), (400, "chat_id"),
                                           (403, "chat_id")])
def test_send_message_rejections_name_the_field_and_hide_key(status, field):
    body = json.dumps({"ok": False, "error_code": status, "description": "Bad Request: chat not found"})
    http = _http(POST_sendMessage=response(status, body))
    with pytest.raises(telegram.TelegramError) as ei:
        telegram.send_message(http, BOT, "1", "x")
    assert ei.value.field == field and not ei.value.network
    assert BOT not in str(ei.value) and "AAH" not in str(ei.value)
    assert str(ei.value)  # текст по-русски для пользователя


def test_send_message_network_error_is_marked_and_hides_key():
    # даже если текст исключения транспорта содержит адрес с токеном — наружу он не выходит
    http = _http(POST_sendMessage=HttpError(f"Сервер не ответил: {API}/sendMessage"))
    with pytest.raises(telegram.TelegramError) as ei:
        telegram.send_message(http, BOT, "1", "x")
    assert ei.value.network is True
    assert BOT not in str(ei.value) and "Telegram" in str(ei.value)


def test_send_message_ok_false_in_body_is_error():
    http = _http(POST_sendMessage=response(json={"ok": False, "description": "что-то не так"}))
    with pytest.raises(telegram.TelegramError):
        telegram.send_message(http, BOT, "1", "x")


@pytest.mark.parametrize("bad", ["", "abc", "123:abc/../x", "123:ab?c=1", "12 3:abc"])
def test_malformed_key_is_rejected_without_request(bad):
    http = FakeHttp()
    with pytest.raises(telegram.TelegramError) as ei:
        telegram.send_message(http, bad, "1", "x")
    assert ei.value.field == "bot_token"
    assert http.requests == []


def test_find_chat_returns_last_chat_id():
    updates = {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": 111}, "text": "a"}},
        {"update_id": 2, "my_chat_member": {"chat": {"id": -100500}}},
        {"update_id": 3, "edited_message": {"chat": {"id": 248019337}}},
        {"update_id": 4, "poll": {"id": "x"}},
    ]}
    http = _http(GET_getUpdates=response(json=updates))
    assert telegram.find_chat(http, BOT) == "248019337"


def test_find_chat_none_when_no_updates():
    http = _http(GET_getUpdates=response(json={"ok": True, "result": []}))
    assert telegram.find_chat(http, BOT) is None


def test_find_chat_bad_key_is_error_without_key():
    http = _http(GET_getUpdates=response(401, json.dumps({"ok": False, "description": "Unauthorized"})))
    with pytest.raises(telegram.TelegramError) as ei:
        telegram.find_chat(http, BOT)
    assert ei.value.field == "bot_token" and BOT not in str(ei.value)


def test_http_log_lines_hide_bot_key(caplog):
    # karaoke_core.http пишет адрес запроса в лог при сбое связи — путь /bot<токен>/ скрывается
    caplog.set_level(logging.INFO, logger="karaoke.http")
    logging.getLogger("karaoke.http").warning("HTTP %s: %s", f"{API}/sendMessage", "timeout")
    logging.getLogger("karaoke.http").info(f"HTTP {API}/getUpdates: повтор")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "api.telegram.org" in text and BOT not in text and "AAH" not in text
