"""Зеркало хранилища (истории 44–48): «куда» поддерживается копией «откуда».

Задание ``mirror`` (params ``{mirror_id}``) пересканирует оба хранилища тем же кодом, что
«Обновить» (``karaoke_core.scan``), сравнивает песни по ключу «исполнитель — название» и ставит
существующее задание ``copy``: нет в цели — без замены, изменилась в источнике после прошлого
прогона (и размеры файлов не совпали) — с заменой (старая копия уходит в корзину цели). Само
ничего не удаляет: песни, которые есть только в цели, попадают в итог списком.

Планировщик (:func:`schedule_mirrors`) зовёт цикл воркера раз в минуту.
"""

from __future__ import annotations

import time
from datetime import datetime

from karaoke_core import naming
from karaoke_core.db import Job, LibraryItem, Mirror, now
from karaoke_core.scan import scan_target
from karaoke_core.storage import StorageError

from .base import JobContext, JobFailed
from .progress import STAGE_MIRROR_COMPARE, STAGE_MIRROR_SCAN

__all__ = ["MirrorHandler", "MIRROR_EVERY_S", "MIRROR_CHECK_S", "schedule_mirrors",
           "MIRROR_GONE", "MIRROR_TARGET_GONE"]

MIRROR_EVERY_S = 1800  # включённое зеркало синхронизируется раз в 30 минут
MIRROR_CHECK_S = 60.0  # как часто цикл воркера смотрит, не пора ли
MIRROR_GONE = "Зеркало удалено из настроек"
MIRROR_TARGET_GONE = "Хранилище зеркала удалено из настроек"


class _Unavailable(Exception):
    """Хранилище зеркала недоступно — задание ждёт его, как ``copy``."""

    def __init__(self, target_id: str, error: Exception):
        super().__init__(str(error))
        self.target_id, self.error = target_id, error


def _ts(value: str | None) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp() if value else None
    except ValueError:
        return None


def _key(item: LibraryItem) -> str:
    return naming.song_tag_key(item.artist, item.title)


def _mirror_ref(ctx: JobContext, mirror: Mirror) -> dict:
    """Подпись задания в «Очереди»: «откуда» - «куда»."""
    name = _handlers._target_name
    return {"artist": name(ctx, mirror.from_target), "title": name(ctx, mirror.to_target)}


def schedule_mirrors(ctx: JobContext, *, every_s: float = MIRROR_EVERY_S) -> list[Job]:
    """Поставить ``mirror`` каждому включённому зеркалу, которому пора (прошлый прогон старше
    ``every_s`` или его не было), если его задание ещё не в очереди и оба хранилища есть в
    настройках. Возвращает поставленные задания."""
    out: list[Job] = []
    known = {t.id for t in ctx.targets()}
    now_ts = time.time()
    for mirror in ctx.settings.get_mirrors():
        if not mirror.enabled or mirror.from_target not in known or mirror.to_target not in known:
            continue
        last = _ts(mirror.last_run_at)
        if last is not None and now_ts - last < every_s:
            continue
        if ctx.jobs.active_mirror(mirror.id) is not None:
            continue
        out.append(ctx.jobs.enqueue("mirror", _mirror_ref(ctx, mirror), {"mirror_id": mirror.id}))
    return out


class MirrorHandler:
    """«Зеркало»: пересканировать оба хранилища и поставить недостающие и изменённые копии."""
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        mirror_id = job.params.get("mirror_id") or ""
        mirror = next((m for m in ctx.settings.get_mirrors() if m.id == mirror_id), None)
        if mirror is None:
            raise JobFailed("input", MIRROR_GONE)
        known = {t.id for t in ctx.targets()}
        if mirror.from_target not in known or mirror.to_target not in known:
            self._fail(ctx, mirror, MIRROR_TARGET_GONE)
        src_name = _handlers._target_name(ctx, mirror.from_target)
        dst_name = _handlers._target_name(ctx, mirror.to_target)
        ctx.check_cancel(job.id, force=True)
        started_at = now()
        try:
            # цель первой: недоступна — ждём, не пересканировав зря источник
            dst = self._scan(ctx, job, mirror.to_target, dst_name, 10)
            src = self._scan(ctx, job, mirror.from_target, src_name, 35)
            ctx.check_cancel(job.id, force=True)
            ctx.jobs.update(job.id, stage=STAGE_MIRROR_COMPARE[0], percent=STAGE_MIRROR_COMPARE[1])
            result = self._sync(ctx, job, mirror, src, dst)
        except _Unavailable as e:
            _handlers._reset(ctx, e.target_id)
            name = _handlers._target_name(ctx, e.target_id)
            _handlers.wait_retry(ctx, job, f"Ждёт хранилище «{name}»",
                       f"Хранилище «{name}» недоступно: {e.error}; повтор через минуту.")
            return
        result["started_at"] = started_at
        ctx.settings.set_mirror_result(mirror.id, result)
        ctx.log(job.id, f"Зеркало «{src_name}» → «{dst_name}»: добавлено {result['added']}, "
                        f"обновлено {result['updated']}, только в цели {len(result['only_in_target'])}.")
        _handlers._done(ctx, job)

    @staticmethod
    def _fail(ctx: JobContext, mirror: Mirror, message: str) -> None:
        """Итог с ошибкой (планировщик не повторит раньше, чем через 30 минут) и сбой задания."""
        prev = mirror.last_result or {}
        ctx.settings.set_mirror_result(mirror.id, {
            "added": 0, "updated": 0, "only_in_target": prev.get("only_in_target") or [], "error": message,
            **({"started_at": prev["started_at"]} if prev.get("started_at") else {})})
        raise JobFailed("storage", message)

    @staticmethod
    def _scan(ctx: JobContext, job: Job, target_id: str, name: str, percent: int) -> list[LibraryItem]:
        ctx.jobs.update(job.id, state="running", stage=f"{STAGE_MIRROR_SCAN[0]} «{name}»", percent=percent)
        ctx.log(job.id, f"Сканирование «{name}»…")
        try:
            return scan_target(ctx.storage(target_id), ctx.library, target_id, songs=ctx.songs)
        except StorageError as e:
            raise _Unavailable(target_id, e) from None

    @staticmethod
    def _sizes(ctx: JobContext, target_id: str, rel_dir: str) -> list[int]:
        try:
            return sorted(ctx.storage(target_id).sizes(rel_dir).values())
        except StorageError as e:
            raise _Unavailable(target_id, e) from None

    def _sync(self, ctx: JobContext, job: Job, mirror: Mirror, src: list[LibraryItem],
              dst: list[LibraryItem]) -> dict:
        prev = mirror.last_result or {}
        # «новее прошлого прогона» — от начала прошлого скана; первого прогона не было — заменять
        # нечего (только добавить недостающее), иначе зеркало перетёрло бы правки в цели
        since = _ts(prev.get("started_at")) or _ts(mirror.last_run_at)
        by_key: dict[str, list[LibraryItem]] = {}
        for item in dst:
            by_key.setdefault(_key(item), []).append(item)
        src_dirs: dict[str, set[str]] = {}
        for item in src:
            src_dirs.setdefault(_key(item), set()).add(item.rel_dir.casefold())
        added = updated = 0
        for item in src:
            ctx.check_cancel(job.id)
            # копия, чья папка совпадает с другой папкой источника, — чужая: её не заменяем
            own = item.rel_dir.casefold()
            others = src_dirs[_key(item)] - {own}
            copies = [c for c in by_key.get(_key(item), ()) if c.rel_dir.casefold() not in others]
            same = dict(rel_dir=item.rel_dir, from_target=mirror.from_target, to_target=mirror.to_target)
            if not copies:
                if ctx.jobs.active_copy(**same) is None:
                    added += 1
                ctx.jobs.enqueue_copy(item, txt_name=item.txt_name, wait=True, **same)
                continue
            if since is None or (item.mtime is not None and item.mtime <= since):
                continue  # в источнике не менялась
            there = next((c for c in copies if c.rel_dir == item.rel_dir), None) or next(
                (c for c in copies if c.rel_dir.casefold() == item.rel_dir.casefold()), copies[0])
            if self._sizes(ctx, mirror.from_target, item.rel_dir) == self._sizes(ctx, mirror.to_target, there.rel_dir):
                continue
            if ctx.jobs.active_copy(**same) is None:
                updated += 1
                ctx.log(job.id, f"Изменилась: {item.rel_dir} — копия в цели будет заменена "
                                "(прежняя уйдёт в корзину цели).")
            # другая папка — прежняя в корзину цели; отличие только регистром — та же папка на
            # шаре без регистра, второй перенос в корзину унёс бы только что выложенное
            other_dir = there.rel_dir if there.rel_dir.casefold() != item.rel_dir.casefold() else None
            ctx.jobs.enqueue_copy(item, txt_name=item.txt_name, replace=True, wait=True,
                                  replace_rel_dir=other_dir, **same)
        only = [{"song_id": i.song_id, "artist": i.artist, "title": i.title, "rel_dir": i.rel_dir}
                for i in dst if _key(i) not in src_dirs]
        only.sort(key=lambda d: (d["artist"].casefold(), d["title"].casefold()))
        return {"added": added, "updated": updated, "only_in_target": only}


# В конце: handlers подключает этот модуль у себя внизу (реестр HANDLERS) — круговой импорт.
from . import handlers as _handlers  # noqa: E402
