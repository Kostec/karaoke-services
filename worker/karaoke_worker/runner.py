"""Исполнитель очереди заданий (Решения §2, истории 17–24).

Строго одно задание за раз (8 ГБ VRAM): цикл забирает задание атомарно (``Jobs.claim_next``)
и выполняет его в этом же потоке. При старте: проверка GPU → статус в БД,
``Jobs.fail_interrupted()``, уборка брошенных ``jobs/.new-*``, ``imports/*`` старше часа и старых логов.
"""

from __future__ import annotations

import shutil
import signal
import threading
import time
import traceback
from typing import Callable

from karaoke_core import naming
from karaoke_core.db import Job

from .base import JobCancelled, JobContext, JobFailed, remove_tree
from .handlers import HANDLERS, Handler

__all__ = ["handlers", "run_forever", "run_job", "startup", "JobContext", "JobFailed", "JobCancelled",
           "Handler"]

handlers: dict[str, Handler] = HANDLERS

GPU_RECHECK_S = 60.0  # без GPU статус перепроверяется раз в минуту
STALE_STAGING_S = 3600.0  # .new-* старше часа — сбой web между mkdir и постановкой
NO_GPU_MESSAGE = "GPU недоступен — задание ждёт в очереди"


def _default_gpu_check() -> dict:
    from . import gpucheck

    return gpucheck.check()


def _cleanup(ctx: JobContext) -> None:
    now = time.time()
    days = ctx.env.get("LOG_DAYS", "")
    max_age = int(days) * 86400 if days.strip().isdigit() else None
    songs = ctx.paths.root / "songs"
    if songs.is_dir() and max_age is not None:
        # входы отменённых и упавших заданий старше LOG_DAYS (Решения §3)
        for d in songs.glob("**/jobs/*"):
            if not d.name.isdigit() or not d.is_dir():
                continue
            job = ctx.jobs.get(int(d.name))
            try:
                old = now - d.stat().st_mtime > max_age
            except OSError:
                continue
            if old and (job is None or job.state in ("cancelled", "failed")):
                remove_tree(d)
    if songs.is_dir():
        for d in songs.glob("**/jobs/.new-*"):
            try:
                if d.is_dir() and now - d.stat().st_mtime > STALE_STAGING_S:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    imports = ctx.paths.imports_root
    if imports.is_dir():
        # разобранные архивы импорта хранятся час (Решения §9)
        for d in imports.iterdir():
            try:
                if d.is_dir() and now - d.stat().st_mtime > STALE_STAGING_S:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    logs = ctx.paths.log(0).parent
    if max_age is not None and logs.is_dir():
        for f in logs.glob("*.log"):
            try:
                if now - f.stat().st_mtime > max_age:
                    f.unlink()
            except OSError:
                pass


def _check_gpu(ctx: JobContext, gpu_check: Callable[[], dict]) -> bool:
    try:
        status = dict(gpu_check())
    except Exception as e:  # noqa: BLE001 — статус GPU всё равно должен попасть в БД
        status = {"ok": False, "name": None, "vram_mb": None, "error": f"Проверка GPU упала: {e}"}
    ctx.settings.set_gpu_status(status)
    return bool(status.get("ok"))


def startup(ctx: JobContext, gpu_check: Callable[[], dict] | None = None) -> bool:
    """Старт воркера: статус GPU в БД, прерванные задания → failed, уборка. Возвращает «GPU есть»."""
    gpu_ok = _check_gpu(ctx, gpu_check or _default_gpu_check)
    ctx.migrate_targets()
    n = ctx.jobs.fail_interrupted()
    if n:
        print(f"worker: прервано перезапуском заданий: {n}", flush=True)
    _cleanup(ctx)
    return gpu_ok


def _needs_gpu(job: Job) -> bool:
    handler = handlers.get(job.type)
    return bool(getattr(handler, "needs_gpu", True)) if handler is not None else False


def _claim(ctx: JobContext, gpu_ok: bool) -> Job | None:
    if gpu_ok:
        return ctx.jobs.claim_next()
    # Без GPU задания generate/instrumental не берутся — только задания без GPU (выкладка).
    return ctx.jobs.claim_next(types=[t for t, h in handlers.items() if not getattr(h, "needs_gpu", True)])


def _job_dir(ctx: JobContext, job: Job):
    rel_dir = job.params.get("rel_dir") or (naming.song_dir(job.artist, job.title)
                                            if job.artist and job.title else None)
    return ctx.paths.job(rel_dir, job.id) if rel_dir else None


def run_job(ctx: JobContext, job: Job) -> None:
    """Выполнить одно уже забранное задание до конечного состояния."""
    if not job.params.get("retry_at"):  # повтор ожидающего копирования — без заголовка в логе
        ctx.log(job.id, f"=== Задание {job.id}: {job.type} — {job.artist} - {job.title}")
    handler = handlers.get(job.type)
    try:
        if handler is None:
            raise JobFailed("type", f"Неизвестный тип задания: {job.type}")
        handler.run(job, ctx)
    except JobCancelled:
        if job.type != "publish":
            d = _job_dir(ctx, job)
            if d is not None and d.is_dir():
                for child in d.iterdir():  # in/ остаётся: вход нужен «Перезапустить»
                    if child.name != "in":
                        shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
        ctx.jobs.update(job.id, state="cancelled", cancel_requested=False)
        ctx.log(job.id, "Задание отменено.")
    except JobFailed as e:
        ctx.jobs.update(job.id, state="failed", error=e.user_message)
        ctx.log(job.id, f"Ошибка: {e.user_message}")
    except Exception as e:  # noqa: BLE001 — задание не должно зависнуть в running
        ctx.log(job.id, traceback.format_exc())
        ctx.jobs.update(job.id, state="failed", error=f"Внутренняя ошибка воркера: {e}")


def run_forever(ctx: JobContext | None = None, *, gpu_check: Callable[[], dict] | None = None,
                poll: float = 1.0, until: Callable[[], bool] | None = None) -> int:
    """Главный цикл воркера. ``until`` — условие остановки (для тестов)."""
    ctx = ctx or JobContext()
    if threading.current_thread() is threading.main_thread():
        def _stop(signum, _frame):
            raise SystemExit(0)  # дочерняя группа убивается в finally run_command
        signal.signal(signal.SIGTERM, _stop)
    gpu_check = gpu_check or _default_gpu_check
    gpu_ok = startup(ctx, gpu_check)
    print(f"worker: GPU {'доступен' if gpu_ok else 'НЕ доступен'}; жду задания", flush=True)
    try:
        _loop(ctx, gpu_ok, gpu_check, poll, until)
    finally:
        ctx.reset_storage()
    return 0


def _loop(ctx: JobContext, gpu_ok: bool, gpu_check, poll: float, until) -> None:
    last_gpu_check = time.monotonic()
    while until is None or not until():
        if not gpu_ok and time.monotonic() - last_gpu_check > GPU_RECHECK_S:
            gpu_ok = _check_gpu(ctx, gpu_check)
            last_gpu_check = time.monotonic()
        job = _claim(ctx, gpu_ok)
        if job is None:
            time.sleep(poll)
            continue
        run_job(ctx, job)
