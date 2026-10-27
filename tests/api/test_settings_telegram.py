"""Настройки уведомлений Telegram: токен API не отдаёт, пустой — прежний; проверка и поиск чата
через FakeHttp (настоящий Telegram не трогаем)."""

import json

import pytest

from fakes_http import FakeHttp, response
from karaoke_core.db import Settings, TelegramSettings, connect

BOT = "123456:AAH-test_Key"
OTHER = "654321:BBQ-other_Key"
API = "https://api.telegram.org/bot"


@pytest.fixture
def http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture
def tc(env, http):
    with env.client(http=http) as c:
        yield c


def _settings(env) -> Settings:
    return Settings(connect(env.data / "karaoke.sqlite"))


def test_get_defaults_without_token(tc):
    r = tc.get("/api/settings/telegram")
    assert r.status_code == 200
    assert r.json() == {"has_token": False, "chat_id": "", "on_done": True, "on_failed": True,
                        "on_queue_empty": False}


def test_put_saves_and_get_never_returns_token(env, tc, http):
    r = tc.put("/api/settings/telegram", json={"bot_token": BOT, "chat_id": "248019337", "on_done": False,
                                               "on_failed": True, "on_queue_empty": True})
    assert r.status_code == 200, r.text
    assert BOT not in r.text and "AAH" not in r.text
    assert r.json() == {"has_token": True, "chat_id": "248019337", "on_done": False, "on_failed": True,
                        "on_queue_empty": True}
    g = tc.get("/api/settings/telegram")
    assert BOT not in g.text and g.json()["has_token"] is True
    assert _settings(env).get_telegram().bot_token == BOT
    assert http.requests == []  # сохранение без похода в Telegram


def test_put_empty_token_keeps_previous(env, tc):
    _settings(env).set_telegram(TelegramSettings(BOT, "1"))
    r = tc.put("/api/settings/telegram", json={"bot_token": "", "chat_id": "-100200", "on_done": True,
                                               "on_failed": False, "on_queue_empty": False})
    assert r.status_code == 200, r.text
    saved = _settings(env).get_telegram()
    assert saved.bot_token == BOT and saved.chat_id == "-100200" and saved.on_failed is False
    r = tc.put("/api/settings/telegram", json={"chat_id": "-100200"})  # поля нет — тоже прежний
    assert r.status_code == 200 and _settings(env).get_telegram().bot_token == BOT


def test_put_rejects_malformed_values(tc):
    r = tc.put("/api/settings/telegram", json={"bot_token": "abc/../x", "chat_id": "1"})
    assert r.status_code == 400 and r.json()["field"] == "bot_token"
    r = tc.put("/api/settings/telegram", json={"bot_token": BOT, "chat_id": "мой чат"})
    assert r.status_code == 400 and r.json()["field"] == "chat_id"
    assert tc.get("/api/settings/telegram").json()["has_token"] is False


def test_test_sends_message_with_typed_or_saved_token(env, tc, http):
    http.route("POST", f"{API}{BOT}/sendMessage", response(json={"ok": True, "result": {}}))
    http.route("POST", f"{API}{OTHER}/sendMessage", response(json={"ok": True, "result": {}}))
    r = tc.post("/api/settings/telegram/test", json={"bot_token": OTHER, "chat_id": "42"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    [req] = http.calls(f"{API}{OTHER}/")
    assert req.data["chat_id"] == "42" and req.data["text"]
    assert _settings(env).get_telegram().bot_token is None  # проверка не сохраняет

    _settings(env).set_telegram(TelegramSettings(BOT, "77"))
    r = tc.post("/api/settings/telegram/test", json={"bot_token": "", "chat_id": ""})
    assert r.status_code == 200
    [req] = http.calls(f"{API}{BOT}/")
    assert req.data["chat_id"] == "77"


def test_test_without_any_token_is_400(tc, http):
    r = tc.post("/api/settings/telegram/test", json={"chat_id": "42"})
    assert r.status_code == 400 and r.json()["field"] == "bot_token"
    assert http.requests == []


def test_test_rejected_token_is_400_without_token_in_text(env, tc, http):
    _settings(env).set_telegram(TelegramSettings(BOT, "77"))
    http.route("POST", f"{API}{BOT}/sendMessage",
               response(401, json.dumps({"ok": False, "description": "Unauthorized"})))
    r = tc.post("/api/settings/telegram/test", json={})
    assert r.status_code == 400 and r.json()["field"] == "bot_token"
    assert BOT not in r.text and "AAH" not in r.text


def test_test_network_failure_is_503(env, tc, http):
    from karaoke_core.http import HttpError

    _settings(env).set_telegram(TelegramSettings(BOT, "77"))
    http.route("POST", f"{API}{BOT}/sendMessage", HttpError("Сервер api.telegram.org не ответил вовремя"))
    r = tc.post("/api/settings/telegram/test", json={})
    assert r.status_code == 503 and BOT not in r.text


def test_find_chat_returns_last_chat(tc, http):
    http.route("GET", f"{API}{BOT}/getUpdates", response(json={"ok": True, "result": [
        {"update_id": 5, "message": {"chat": {"id": 248019337}, "text": "привет"}}]}))
    r = tc.post("/api/settings/telegram/find-chat", json={"bot_token": BOT})
    assert r.status_code == 200 and r.json() == {"chat_id": "248019337"}


def test_find_chat_without_messages_is_404(env, tc, http):
    _settings(env).set_telegram(TelegramSettings(BOT, ""))
    http.route("GET", f"{API}{BOT}/getUpdates", response(json={"ok": True, "result": []}))
    r = tc.post("/api/settings/telegram/find-chat", json={})
    assert r.status_code == 404
    assert r.json()["detail"] == "Напишите боту любое сообщение и повторите"
