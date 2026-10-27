"""Уведомления воркера в Telegram (истории 59, 60, 62): сообщение по конечному состоянию задания,
сводка «очередь опустела»; сбой Telegram не роняет задание и очередь, токен не попадает в лог."""

import json

import pytest

from fakes_http import FakeHttp, response
from karaoke_core.db import Settings, TelegramSettings, connect
from karaoke_core.http import HttpError

BOT = "123456:AAH-test_Key"
SEND = f"https://api.telegram.org/bot{BOT}/sendMessage"


@pytest.fixture
def tg(world):
    http = FakeHttp()
    http.route("POST", SEND, response(json={"ok": True, "result": {}}))
    world.ctx.http = http
    return http


def _configure(world, **events):
    Settings(world.conn).set_telegram(TelegramSettings(BOT, "248019337", **events))


def _texts(http) -> list[str]:
    return [r.data["text"] for r in http.calls(SEND)]


def test_done_job_sends_message(world, tg):
    _configure(world)
    job = world.enqueue_generate()
    world.run()
    assert world.jobs.get(job.id).state == "done"
    assert _texts(tg) == ["✅ Готово: Тестовая Группа — Песня Ёлки (генерация)"]
    assert tg.calls(SEND)[0].data["chat_id"] == "248019337"


def test_failed_job_sends_message_with_error(world, tg):
    _configure(world)
    world.storage_ok = False
    job = world.enqueue_generate()
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    [text] = _texts(tg)
    assert text.startswith("❌ Сбой: Тестовая Группа — Песня Ёлки (генерация) — ошибка выкладки")
    assert "\n" not in text


def test_only_selected_events_are_sent(world, tg):
    _configure(world, on_done=False, on_failed=True)
    world.enqueue_generate()
    world.run()
    assert _texts(tg) == []


def test_not_configured_makes_no_requests(world, tg):
    world.enqueue_generate()
    world.run()
    assert tg.requests == []


def test_queue_empty_summary_once_after_last_job(world, tg):
    _configure(world, on_done=False, on_failed=False, on_queue_empty=True)
    a = world.enqueue_generate("Группа А", "Первая")
    b = world.enqueue_generate("Группа Б", "Вторая")
    world.run()
    assert [world.jobs.get(j.id).state for j in (a, b)] == ["done", "done"]
    assert _texts(tg) == ["Очередь опустела: готово 2, сбоев 0"]


def test_queue_empty_summary_counts_failures(world, tg):
    _configure(world, on_queue_empty=True)
    world.storage_ok = False
    world.enqueue_generate()
    world.run()
    texts = _texts(tg)
    assert texts[-1] == "Очередь опустела: готово 0, сбоев 1"
    assert texts[0].startswith("❌ Сбой:")


@pytest.mark.parametrize("failure", [
    HttpError("Сервер api.telegram.org не ответил вовремя"),
    response(401, json.dumps({"ok": False, "description": "Unauthorized"})),
])
def test_telegram_failure_does_not_break_job_or_queue(world, failure):
    http = FakeHttp()
    http.route("POST", SEND, failure)
    world.ctx.http = http
    _configure(world, on_queue_empty=True)
    a = world.enqueue_generate("Группа А", "Первая")
    b = world.enqueue_generate("Группа Б", "Вторая")
    world.run()
    assert [world.jobs.get(j.id).state for j in (a, b)] == ["done", "done"]
    assert len(http.calls(SEND)) >= 2  # очередь шла дальше и пробовала снова
    for job in (a, b):
        log = world.log(job.id)
        assert "Telegram" in log and "Уведомление" in log
        assert BOT not in log and "AAH" not in log
        assert world.jobs.get(job.id).error is None


def test_waiting_job_with_future_retry_does_not_block_summary(world, tg):
    """Ждущее зеркало (``retry_at`` в будущем, без ``wait``) не мешает сводке."""
    from karaoke_core.db import now

    _configure(world, on_done=False, on_failed=False, on_queue_empty=True)
    waiting = world.jobs.enqueue("mirror", {"artist": "Локальное", "title": "Pi"},
                                 {"mirror_id": "m_x", "retry_at": now(3600)})
    job = world.enqueue_generate()
    world.run(timeout=15, until=lambda: world.jobs.get(job.id).state == "done" and bool(_texts(tg)))
    assert world.jobs.get(waiting.id).state == "queued"
    assert _texts(tg) == ["Очередь опустела: готово 1, сбоев 0"]
