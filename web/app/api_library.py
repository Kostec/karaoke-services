"""Проверка библиотеки (истории 34–43) и её исправления, которых нет у других разделов:
кодировка ``.txt`` (синхронно, как «Редактор нот») и звук по ссылке ``#VIDEO`` (задание ``audio``).
Остальные исправления — существующие задания (copy, video remove, удаление в корзину)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from pydantic import BaseModel

from karaoke_core import ultrastar
from karaoke_core.libcheck import audio_link
from karaoke_core.trash import TrashError

from .api_jobs import Staging, ctx_of, queue_duplicate
from .api_songs import read_txt, song_storage, storage_call
from .context import ApiError

router = APIRouter(prefix="/api", tags=["Проверка библиотеки"])

CHECK_RUNNING = "Проверка уже идёт"
ENCODING_OK = "Кодировка в порядке"
ENCODING_NOT_GUESSED = "Не удалось угадать кодировку"
NO_YOUTUBE = "В песне нет ссылки на видео YouTube"
HAS_AUDIO = "У песни уже есть звук"


class CheckIn(BaseModel):
    target_ids: list[str] | None = None  # None или пусто — все хранилища


@router.post("/library/check", status_code=201, summary="Запустить проверку библиотеки")
def start_check(request: Request, body: CheckIn | None = None):
    ctx = ctx_of(request)
    ids = [i for i in (body.target_ids if body else None) or [] if i]
    known = {t.id: t for t in ctx.targets()}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ApiError(400, f"Хранилище не найдено: {unknown[0]}", field="target_ids")
    if ctx.jobs.active("libcheck"):
        raise ApiError(409, CHECK_RUNNING)
    ids = list(dict.fromkeys(ids))
    title = ", ".join(known[i].name or known[i].label for i in ids) if ids else "все"
    job = ctx.jobs.enqueue("libcheck", {"artist": "Хранилища", "title": title}, {"target_ids": ids or None})
    return job.to_dict()


@router.get("/library/check", summary="Отчёт последней проверки и идущая проверка")
def get_check(request: Request):
    ctx = ctx_of(request)
    active = ctx.jobs.active("libcheck")
    path = ctx.paths.libcheck_report()
    report: dict = {"findings": None}
    if path.is_file():
        try:
            report = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            report = {"findings": None}  # недописанный/испорченный отчёт — как будто проверки не было
    return {**report, "job": active[-1].to_dict() if active else None}


@router.post("/songs/{song_id}/encoding", summary="Перекодировать .txt песни в UTF-8 (старая версия — в корзину)")
def fix_encoding(song_id: str, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    original = read_txt(ctx, item)
    problem = ultrastar.encoding_problem(original)
    if problem is None:
        raise ApiError(409, ENCODING_OK)
    if not problem.fixed_text:
        raise ApiError(409, ENCODING_NOT_GUESSED)
    rel = f"{item.rel_dir}/{item.txt_name}"
    storage = song_storage(ctx, item)
    try:
        storage_call(ctx, lambda: ctx.trash.save_version(storage, rel, reason="версия до исправления кодировки"),
                      target_id=item.target_id)
    except TrashError as e:
        raise ApiError(409, str(e)) from None
    storage_call(ctx, storage.write_atomic, rel, problem.fixed_text.encode("utf-8"), target_id=item.target_id)
    item = storage_call(ctx, ctx.refresh_song, item.rel_dir, item.target_id, target_id=item.target_id) or item
    return ctx.song_dict(item)


class AudioIn(BaseModel):
    song_id: str


@router.post("/jobs/audio", status_code=201, summary="Скачать звук песни по ссылке YouTube из #VIDEO")
def audio_from_video(body: AudioIn, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(body.song_id)
    queue_duplicate(ctx, "audio", song_id=item.song_id)
    if item.audio:
        raise ApiError(409, HAS_AUDIO)
    url = audio_link(ultrastar.parse(read_txt(ctx, item)).header("VIDEO"))
    if not url:
        raise ApiError(409, NO_YOUTUBE)
    params = {"rel_dir": item.rel_dir, "txt_name": item.txt_name, "target_id": item.target_id, "url": url}
    ref = {"artist": item.artist, "title": item.title, "song_id": item.song_id}
    return Staging(ctx, item.rel_dir).enqueue("audio", ref, params).to_dict()
