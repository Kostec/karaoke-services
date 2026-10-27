"""Задание ``audio`` — «Скачать звук по ссылке #VIDEO» (история 39), без GPU.

params ``{rel_dir, txt_name, target_id, url, inputs: {dir}}``: yt-dlp качает звук по ссылке
YouTube из ``#VIDEO`` (под это видео размечены ноты) → ``in/input.mp3`` (Перезапустить не качает
заново) → ``<A - T>.mp3`` в папку песни; в ``.txt`` ставятся ``#AUDIO`` и ``#MP3`` (те, что есть;
нет ни одного — ``#MP3``), прежняя версия ``.txt`` — в корзину, как у минусовки.
"""

from __future__ import annotations

import os
import shutil
from pathlib import PurePosixPath

from karaoke_core import naming, ultrastar
from karaoke_core.db import Job
from karaoke_core.paths import INPUT_AUDIO
from karaoke_core.storage import StorageError
from karaoke_core.trash import TrashError

from .base import JobContext, JobFailed, remove_tree
from .handlers import (_done, _index, _publish_error, _start_publish, download_youtube, to_mp3)
from .progress import STAGE_AUDIO_DOWNLOAD

__all__ = ["AudioHandler", "publish_audio", "AUDIO_HEADERS", "NO_LINK"]

AUDIO_HEADERS = ("MP3", "AUDIO")
NO_LINK = "В песне нет ссылки на видео YouTube"


def _audio_name(txt_name: str) -> str:
    return PurePosixPath(txt_name).stem + naming.SUFFIX_AUDIO


def publish_audio(ctx: JobContext, job: Job, src: Job) -> None:
    """Звук из ``jobs/<id>/result/`` → папка песни; в ``.txt`` меняются только ``#AUDIO``/``#MP3``."""
    p = src.params
    rel_dir, txt_name = p["rel_dir"], p["txt_name"]
    job_dir = ctx.paths.job(rel_dir, src.id)
    found = [f for f in (job_dir / "result").iterdir() if f.is_file()] if (job_dir / "result").is_dir() else []
    if len(found) != 1:
        raise JobFailed("publish", "ошибка выкладки: звук не найден в томе")
    mp3 = found[0]
    _start_publish(ctx, job)
    txt_rel = f"{rel_dir}/{txt_name}"
    try:
        storage = ctx.storage(p.get("target_id"))
        txt = storage.read(txt_rel)
        song = ultrastar.parse(txt)
        keys = [k for k in AUDIO_HEADERS if song.header(k) is not None] or ["MP3"]
        new_txt = txt
        try:
            for key in keys:
                new_txt = ultrastar.set_header_line(new_txt, key, mp3.name)
        except ValueError:
            raise JobFailed("publish", "ошибка выкладки: имя звука не записать в кодировке .txt") from None
        if storage.exists(f"{rel_dir}/{mp3.name}"):
            ctx.trash.save_version(storage, f"{rel_dir}/{mp3.name}", reason="звук заменён")
            ctx.log(job.id, f"Прежний звук «{mp3.name}» сохранён в корзине.")
        with open(mp3, "rb") as f:
            storage.write_atomic(f"{rel_dir}/{mp3.name}", f)
        if new_txt != txt:
            ctx.trash.save_version(storage, txt_rel, reason="версия до звука по ссылке")
            storage.write_atomic(txt_rel, new_txt)
    except (StorageError, TrashError, OSError) as e:
        raise _publish_error(ctx, e, target_id=p.get("target_id")) from None
    ctx.log(job.id, f"Звук выложен: {rel_dir}/{mp3.name}")
    _index(ctx, job, storage, rel_dir, None)
    remove_tree(job_dir)
    _done(ctx, job)


class AudioHandler:
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        p = job.params
        rel_dir, txt_name = p["rel_dir"], p["txt_name"]
        job_dir = ctx.paths.job(rel_dir, job.id)
        result, work = job_dir / "result", job_dir / "work"
        for d in (result, work):
            shutil.rmtree(d, ignore_errors=True)
        result.mkdir(parents=True)
        inputs = p.get("inputs") or {}
        in_dir = ctx.paths.abs(inputs["dir"]) if inputs.get("dir") else ctx.paths.job_in(rel_dir, job.id)
        saved = in_dir / INPUT_AUDIO
        if saved.is_file():
            ctx.log(job.id, "Звук уже скачан — беру его.")
        else:
            url = (p.get("url") or "").strip()
            if not url:
                raise JobFailed("input", NO_LINK)
            ctx.progress(job.id, STAGE_AUDIO_DOWNLOAD)
            ctx.log(job.id, f"Звук по ссылке: {url}")
            mp3, _thumb = download_youtube(ctx, job.id, url, work, thumbnail=False)
            in_dir.mkdir(parents=True, exist_ok=True)
            part = work / INPUT_AUDIO
            to_mp3(ctx, job.id, mp3, part)
            os.replace(part, saved)  # целиком или никак: restart доверяет in/input.mp3
            shutil.rmtree(work, ignore_errors=True)
        dest = result / _audio_name(txt_name)
        try:
            os.link(saved, dest)
        except OSError:
            shutil.copy2(saved, dest)
        ctx.check_cancel(job.id, force=True)
        publish_audio(ctx, job, job)
