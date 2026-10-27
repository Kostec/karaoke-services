"""Задание ``artwork`` (истории 12–18, 20): обложка (``#COVER``) или фон (``#BACKGROUND``) песни без GPU.

Картинку (свой файл или скачанную по ссылке) web уже положил в ``jobs/<id>/in/image.<ext>``.
Выкладка устроена как у видео: в ``.txt`` меняется одна строка заголовка, прежняя версия ``.txt``
уходит в корзину, старый файл с другим именем удаляется.

Помощники выкладки берутся из ``handlers`` внутри функций: ``handlers`` сам подключает этот
модуль в ``HANDLERS``, импорт на уровне модуля дал бы цикл.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from karaoke_core import naming, ultrastar
from karaoke_core.db import Job
from karaoke_core.storage import StorageError
from karaoke_core.trash import TrashError

from .base import JobContext, JobFailed, remove_tree
from .progress import STAGE_BACKGROUND, STAGE_COVER

__all__ = ["ArtworkHandler", "publish_artwork", "KIND_HEADERS", "IMAGE_EXTS"]

KIND_HEADERS = {"cover": "COVER", "background": "BACKGROUND"}
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_WHAT = {"cover": ("обложка", "обложки", "Обложка"), "background": ("фон", "фона", "Фон")}


def _kind(job: Job) -> str:
    kind = job.params.get("kind")
    if kind not in KIND_HEADERS:
        raise JobFailed("input", "Неизвестно, что ставить: обложку или фон")
    return kind


def _suffix(kind: str, ext: str) -> str:
    return naming.cover_suffix(ext) if kind == "cover" else naming.background_suffix(ext)


def _own_file(value: str | None) -> str | None:
    """Имя файла из заголовка, если это файл в папке песни (не путь и не ссылка)."""
    value = (value or "").strip()
    if not value or "/" in value or "\\" in value or value in (".", ".."):
        return None
    return value


def _input_image(ctx: JobContext, job: Job) -> Path:
    inputs = job.params.get("inputs") or {}
    src = ctx.paths.abs(inputs["image"]) if inputs.get("image") else None
    if src is None or not src.is_file():
        raise JobFailed("input", "Картинка задания не сохранилась — поставьте обложку или фон заново")
    if src.suffix.lower() not in IMAGE_EXTS:
        raise JobFailed("input", "Картинка должна быть jpg, png или webp")
    return src


def publish_artwork(ctx: JobContext, job: Job, src: Job) -> None:
    """Картинка из ``jobs/<id>/result/`` задания ``src`` → папка песни; в ``.txt`` меняется только
    ``#COVER``/``#BACKGROUND`` (``remove`` — строка снимается и файл удаляется)."""
    from .handlers import _done, _index, _publish_error, _start_publish

    p = src.params
    kind = _kind(src)
    header = KIND_HEADERS[kind]
    rel_dir, txt_name = p["rel_dir"], p["txt_name"]
    job_dir = ctx.paths.job(rel_dir, src.id)
    result = job_dir / "result"
    remove = bool(p.get("remove"))
    image = None
    if not remove:
        found = [f for f in result.iterdir() if f.is_file()] if result.is_dir() else []
        if len(found) != 1:
            raise JobFailed("publish", "ошибка выкладки: картинка не найдена в томе")
        image = found[0]
    _start_publish(ctx, job)
    what, of_what, title = _WHAT[kind]
    txt_rel = f"{rel_dir}/{txt_name}"
    try:
        storage = ctx.storage(p.get("target_id"))
        txt = storage.read(txt_rel)
        song = ultrastar.parse(txt)
        old = _own_file(song.header(header))
        if remove:
            new_txt = ultrastar.render(song) if song.remove_header(header) else txt
        else:
            try:
                new_txt = ultrastar.set_header_line(txt, header, image.name)
            except ValueError:
                raise JobFailed("publish", f"ошибка выкладки: имя {of_what} не записать в кодировке .txt") from None
            with open(image, "rb") as f:
                storage.write_atomic(f"{rel_dir}/{image.name}", f)
        if new_txt != txt:
            reason = f"версия до удаления {of_what}" if remove else f"версия до {of_what}"
            ctx.trash.save_version(storage, txt_rel, reason=reason)
            storage.write_atomic(txt_rel, new_txt)
        if old and (remove or old.casefold() != image.name.casefold()) and storage.exists(f"{rel_dir}/{old}"):
            storage.delete_file(f"{rel_dir}/{old}")
            ctx.log(job.id, f"Прежний файл «{old}» удалён.")
    except (StorageError, TrashError, OSError) as e:
        raise _publish_error(ctx, e, target_id=p.get("target_id")) from None
    if remove:
        ctx.log(job.id, f"{title} убран{'а' if kind == 'cover' else ''}: {rel_dir}")
    else:
        ctx.log(job.id, f"{title} выложен{'а' if kind == 'cover' else ''}: {rel_dir}/{image.name}")
    _index(ctx, job, storage, rel_dir, None)
    remove_tree(job_dir)
    _done(ctx, job)


class ArtworkHandler:
    """Обложка или фон песни в её хранилище: ``inputs.image`` или ``remove``; без GPU.
    «Перезапустить» берёт картинку из ``in/`` родителя (web заново её не принимает)."""
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        p = job.params
        kind = _kind(job)
        stage = STAGE_COVER if kind == "cover" else STAGE_BACKGROUND
        ctx.jobs.update(job.id, stage=stage[0], percent=stage[1])
        rel_dir = p["rel_dir"]
        job_dir = ctx.paths.job(rel_dir, job.id)
        result = job_dir / "result"
        shutil.rmtree(result, ignore_errors=True)
        result.mkdir(parents=True)
        if not p.get("remove"):
            src = _input_image(ctx, job)
            name = naming.song_file(job.artist, job.title, _suffix(kind, src.suffix))
            dest = result / name
            try:
                os.link(src, dest)  # тот же том: без второй копии
            except OSError:
                shutil.copy2(src, dest)
            ctx.log(job.id, f"{_WHAT[kind][2]} песни: {dest.name}")
        ctx.check_cancel(job.id, force=True)
        publish_artwork(ctx, job, job)
