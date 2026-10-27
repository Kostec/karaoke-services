"""Уведомления в Telegram о заданиях (истории 59, 60, 62).

``after_job`` зовёт ``runner.run_job`` после каждого задания: сообщение о конечном состоянии
(``notify_job``) и сводка, когда очередь опустела (``notify_queue_empty``). Ничего отсюда не
бросает: сбой Telegram — строка в логе задания (без токена), очередь идёт дальше.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from karaoke_core import telegram
from karaoke_core.db import Job, now

from .base import JobContext

__all__ = ["DONE_TYPES", "TYPE_NAMES", "QUEUE_EMPTY_EVERY_S", "job_text", "queue_empty_text",
           "notify_job", "notify_queue_empty", "after_job"]

# О каких заданиях сообщать «готово» (служебные copy/publish/libcheck/mirror — нет); «сбой» — о всех.
DONE_TYPES = frozenset({"generate", "import", "instrumental", "video", "artwork", "audio", "rename"})
TYPE_NAMES = {
    "generate": "генерация", "import": "импорт", "instrumental": "минусовка", "video": "видео",
    "artwork": "обложка", "audio": "звук", "rename": "переименование", "publish": "выкладка",
    "copy": "копирование", "libcheck": "проверка библиотеки", "mirror": "зеркало",
}
QUEUE_EMPTY_EVERY_S = 600.0  # сводка «очередь опустела» — не чаще раза в 10 минут
ERROR_MAX = 300              # сколько текста ошибки идёт в сообщение


@dataclass
class _Summary:
    """Счёт с прошлой сводки (живёт в памяти воркера, по одному на ``JobContext``)."""
    done: int = 0
    failed: int = 0
    last_sent: float | None = None


def _summary(ctx: JobContext) -> _Summary:
    state = getattr(ctx, "_notify_summary", None)
    if state is None:
        state = _Summary()
        ctx._notify_summary = state  # type: ignore[attr-defined]
    return state


def _song(job: Job) -> str:
    if job.artist and job.title:
        return f"{job.artist} — {job.title}"
    return job.artist or job.title or f"задание #{job.id}"


def job_text(job: Job) -> str | None:
    """Текст сообщения о задании в конечном состоянии; ``None`` — сообщать не о чем."""
    what = f"{_song(job)} ({TYPE_NAMES.get(job.type, job.type)})"
    if job.state == "done" and job.type in DONE_TYPES:
        return f"✅ Готово: {what}"
    if job.state == "failed":
        error = " ".join((job.error or "").split("\n", 1)[0].split()) or "причина в логе задания"
        if len(error) > ERROR_MAX:
            error = error[:ERROR_MAX - 1] + "…"
        return f"❌ Сбой: {what} — {error}"
    return None


def queue_empty_text(counts: dict) -> str:
    return f"Очередь опустела: готово {int(counts.get('done', 0))}, сбоев {int(counts.get('failed', 0))}"


def _configured(ctx: JobContext):
    conf = ctx.settings.get_telegram()
    return conf if conf.bot_token and conf.chat_id else None


def _send(ctx: JobContext, conf, text: str, log_job_id: int | None) -> bool:
    try:
        telegram.send_message(ctx.http, conf.bot_token, conf.chat_id, text)
        return True
    except telegram.TelegramError as e:
        reason = str(e)
    except Exception as e:  # noqa: BLE001 — уведомление не должно уронить очередь
        reason = f"внутренняя ошибка ({type(e).__name__})"
    reason = reason.replace(conf.bot_token, "***")
    if log_job_id is not None:
        try:
            ctx.log(log_job_id, f"Уведомление в Telegram не отправлено: {reason}")
        except OSError:
            pass
    return False


def notify_job(ctx: JobContext, job: Job) -> None:
    """Сообщение о задании в конечном состоянии (если событие включено). Никогда не бросает."""
    try:
        text = job_text(job)
        conf = _configured(ctx) if text else None
        if conf is None:
            return
        wanted = conf.on_done if job.state == "done" else conf.on_failed
        if wanted:
            _send(ctx, conf, text, job.id)
    except Exception:  # noqa: BLE001
        pass


def notify_queue_empty(ctx: JobContext, counts: dict, log_job_id: int | None = None) -> bool:
    """Сводка «Очередь опустела: готово N, сбоев M». ``True`` — отправлена или не включена
    (счёт можно сбрасывать). Никогда не бросает."""
    try:
        conf = _configured(ctx)
        if conf is None or not conf.on_queue_empty:
            return True
        return _send(ctx, conf, queue_empty_text(counts), log_job_id)
    except Exception:  # noqa: BLE001
        return False


def _queue_idle(ctx: JobContext) -> bool:
    """Нет заданий к исполнению: ожидающие повтора (``retry_at`` в будущем — хранилище, зеркало,
    другое задание) не в счёт, как и в ``Jobs.claim_next``."""
    current = now()
    for job in ctx.jobs.queued():
        retry_at = job.params.get("retry_at")
        if not (retry_at and str(retry_at) > current):
            return False
    return True


def after_job(ctx: JobContext, job_id: int) -> None:
    """После задания: сообщение о нём и сводка, если очередь опустела. Никогда не бросает."""
    try:
        job = ctx.jobs.get(job_id)
        if job is None:
            return
        summary = _summary(ctx)
        if job.state in ("done", "failed"):
            if job.state == "failed":
                summary.failed += 1
            elif job.type in DONE_TYPES:
                summary.done += 1
            notify_job(ctx, job)
        if not (summary.done or summary.failed) or not _queue_idle(ctx):
            return
        if summary.last_sent is not None and time.monotonic() - summary.last_sent < QUEUE_EMPTY_EVERY_S:
            return  # счёт копится до следующей сводки
        conf = _configured(ctx)
        if conf is None or not conf.on_queue_empty:
            summary.done = summary.failed = 0
            return
        notify_queue_empty(ctx, {"done": summary.done, "failed": summary.failed}, job.id)
        summary.last_sent = time.monotonic()
        summary.done = summary.failed = 0
    except Exception:  # noqa: BLE001
        pass
