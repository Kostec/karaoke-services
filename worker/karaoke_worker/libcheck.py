"""Задание ``libcheck`` — проверка библиотеки (истории 34–43), без GPU.

Проходит выбранные хранилища (``params.target_ids``, ``None`` — все), снимает каждую песню
(``karaoke_core.libcheck.scan_song``), заодно обновляет индекс хранилища, как «Обновить», и
пишет отчёт ``reports/libcheck.json`` атомарно. Недоступное хранилище не валит проверку:
оно попадает в ``skipped``, остальные проверяются.
"""

from __future__ import annotations

import json
import os

from karaoke_core import scan
from karaoke_core.db import Job, now
from karaoke_core.libcheck import find_problems, make_report, scan_song
from karaoke_core.storage import StorageError, StorageNotFound

from .base import JobContext
from .progress import STAGE_LIBCHECK

__all__ = ["LibCheckHandler", "write_report", "SKIPPED_LINE", "TARGET_GONE"]

SKIPPED_LINE = "Хранилище «{name}» недоступно — пропущено: {error}"
TARGET_GONE = "хранилище удалено из настроек"
PROGRESS_EVERY = 20  # прогресс в БД — раз в столько песен


def write_report(ctx: JobContext, report: dict) -> None:
    """Отчёт — во временный файл рядом и ``os.replace``: читатель не увидит половину."""
    path = ctx.paths.libcheck_report()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, path)


class LibCheckHandler:
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        started = now()
        wanted = job.params.get("target_ids") or None
        known = {t.id: t for t in ctx.targets()}
        ids = [i for i in wanted if i] if wanted else list(known)
        names = {i: (known[i].name or known[i].label) if i in known else i for i in ids}
        scans, skipped, checked = [], [], []
        for n, tid in enumerate(ids):
            name = names[tid]
            ctx.jobs.update(job.id, stage=STAGE_LIBCHECK.format(name=name), percent=round(100 * n / len(ids), 1))
            ctx.log(job.id, f"Проверка «{name}»…")
            if tid not in known:
                skipped.append({"target_id": tid, "name": name, "error": TARGET_GONE})
                ctx.log(job.id, SKIPPED_LINE.format(name=name, error=TARGET_GONE))
                continue
            try:
                found = self._scan_target(ctx, job, tid, n, len(ids))
            except StorageError as e:
                ctx.reset_storage(tid)
                skipped.append({"target_id": tid, "name": name, "error": str(e)})
                ctx.log(job.id, SKIPPED_LINE.format(name=name, error=e))
                continue
            scans.extend(found)
            checked.append(tid)
            ctx.log(job.id, f"«{name}»: песен — {len(found)}")
        ctx.check_cancel(job.id, force=True)
        findings = find_problems(scans, names)
        write_report(ctx, make_report(job_id=job.id, target_ids=checked, skipped=skipped, findings=findings,
                                      started_at=started, finished_at=now()))
        ctx.log(job.id, f"Находок: {len(findings)}" if findings else "Проблем не найдено.")
        ctx.jobs.update(job.id, state="done", percent=100)
        ctx.log(job.id, "Готово.")

    @staticmethod
    def _scan_target(ctx: JobContext, job: Job, tid: str, n: int, total: int) -> list:
        """Снимки песен хранилища и свежий индекс; сбой связи посреди — ``StorageError`` наружу."""
        storage = ctx.storage(tid)
        entries = storage.list_songs()
        stamp = now()
        items, scans = [], []
        for j, entry in enumerate(entries):
            ctx.check_cancel(job.id)
            if j and j % PROGRESS_EVERY == 0:
                ctx.jobs.update(job.id, percent=round(100 * (n + j / len(entries)) / total, 1))
            items.append(scan.library_item(entry, tid, ctx.songs, stamp))
            try:
                scans.append(scan_song(storage, entry))
            except StorageNotFound:
                continue  # папку убрали во время проверки
        ctx.library.replace_all(tid, items)
        return scans
