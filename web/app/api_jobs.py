"""Задания: постановка в очередь (воркер исполняет сам), отмена, перезапуск, выкладка, лог."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import BinaryIO

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from karaoke_core import musiclink, naming, ultrastar
from karaoke_core.http import HttpError
from karaoke_core.db import ACTIVE_STATES, FINAL_STATES, STAGE_PUBLISH, instrumental_params
from karaoke_core.paths import INPUT_AUDIO, INPUT_COVER_STEM, INPUT_LRC, INPUT_LYRICS, INPUT_VIDEO_STEM
from karaoke_core.storage import StorageError

from .context import ApiError, AppContext, link_api_error, not_found, song_key
from .params import (DEFAULT_VIDEO_HEIGHT, MAX_COVER_MB, MAX_FOLDER_AUDIO_MB, MAX_LYRICS_MB, VIDEO_HEIGHTS,
                     max_video_mb, parse_params)

router = APIRouter(prefix="/api/jobs", tags=["Задания"])
CHUNK = 1 << 16
SSE_TAIL_LINES = 500
MB = 1024 * 1024


def ctx_of(request: Request) -> AppContext:
    return request.app.state.ctx


def _job_or_404(ctx: AppContext, job_id: int):
    job = ctx.jobs.get(job_id)
    if job is None:
        raise not_found("Задание не найдено")
    return job


# --------------------------------------------------------------------------- загрузки

# Помощники загрузки — общие для generate и импорта (api_import).

def is_mp3(head: bytes) -> bool:
    return head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)


_COVER_SIGS = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"))


def cover_ext_of(head: bytes) -> str | None:
    for sig, ext in _COVER_SIGS:
        if head.startswith(sig):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _too_big(limit_mb: int, field: str) -> ApiError:
    return ApiError(413, f"Файл больше {limit_mb} МБ", field=field)


def copy_limited(src: BinaryIO, dest: Path, limit_mb: int, field: str) -> None:
    limit, size = limit_mb * MB, 0
    with open(dest, "wb") as out:
        while chunk := src.read(CHUNK):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise _too_big(limit_mb, field)
            out.write(chunk)


def download_cover(ctx: AppContext, url: str, dest_dir: Path) -> str | None:
    """Обложка по ссылке (миниатюра ссылки на музыку, ``co=`` или usdb) в ``dest_dir`` как
    ``cover.<ext>`` (лимит ``MAX_COVER_MB``, сигнатура jpg/png/webp); не вышло — ``None``,
    без ошибки. Ссылки в домашнюю сеть не качаются."""
    try:
        parts = urllib.parse.urlsplit((url or "").strip())
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        musiclink.check_public_host(parts.hostname)
    except (ValueError, musiclink.MusicLinkError):
        return None
    tmp = dest_dir / ".cover"
    try:
        ctx.http.download(url.strip(), tmp, max_bytes=MAX_COVER_MB * MB, timeout=30)
        with open(tmp, "rb") as f:
            ext = cover_ext_of(f.read(16))
    except (HttpError, OSError):
        tmp.unlink(missing_ok=True)
        return None
    if ext is None:
        tmp.unlink(missing_ok=True)
        return None
    name = f"{INPUT_COVER_STEM}.{ext}"
    tmp.replace(dest_dir / name)
    return name


def _read_text_file(upload: UploadFile, field: str = "lyrics") -> str:
    data = upload.file.read(MAX_LYRICS_MB * MB + 1)
    if len(data) > MAX_LYRICS_MB * MB:
        raise _too_big(MAX_LYRICS_MB, field)
    return ultrastar.decode(data)[0]


class Staging:
    """Вход задания собирается во временной папке песни, а в транзакции постановки
    переезжает в ``songs/<A>/<A - T>/jobs/<id>/in`` (paths.py). Не вышло — всё удаляется."""

    def __init__(self, ctx: AppContext, rel_dir: str):
        self.ctx, self.rel_dir = ctx, rel_dir
        self.dir = ctx.paths.staging(rel_dir)
        self.dir.mkdir(parents=True)
        self.names: dict[str, str] = {}
        self.extra: dict[str, str] = {}  # прочие поля inputs (audio_url — ссылка вместо mp3)

    def path(self, key: str, name: str) -> Path:
        self.names[key] = name
        return self.dir / name

    def drop(self, key: str) -> None:
        name = self.names.pop(key, None)
        if name:
            (self.dir / name).unlink(missing_ok=True)

    def copy_from(self, folder: Path) -> None:
        """Взять вход из прежней папки (in/ родителя или source/)."""
        for key, name in (("audio", INPUT_AUDIO), ("lyrics", INPUT_LYRICS), ("lrc", INPUT_LRC)):
            if (folder / name).is_file():
                shutil.copyfile(folder / name, self.path(key, name))
        for cover in sorted(folder.glob(f"{INPUT_COVER_STEM}.*"))[:1]:
            shutil.copyfile(cover, self.path("cover", cover.name))

    def discard(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def enqueue(self, type_: str, song_ref, params: dict, *, parent_id: int | None = None):
        paths, moved = self.ctx.paths, []

        def make(job_id: int) -> dict:
            dest = paths.job_in(self.rel_dir, job_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.dir, dest)
            moved.append(dest.parent)
            return {**params, "inputs": {"dir": paths.rel(dest), **self.extra,
                                         **{k: paths.rel(dest / n) for k, n in self.names.items()}}}

        try:
            return self.ctx.jobs.enqueue_with(type_, song_ref, make, parent_id=parent_id)
        except BaseException:
            self.discard()
            for d in moved:
                shutil.rmtree(d, ignore_errors=True)
            raise


def queue_duplicate(ctx: AppContext, type_: str, *, key: str | None = None, song_id: str | None = None):
    for job in ctx.jobs.list(1000):
        if job.state not in ACTIVE_STATES or job.type != type_:
            continue
        if (key and song_key(job.artist, job.title) == key) or (song_id and job.song_id == song_id):
            raise ApiError(409, "Эта песня уже в очереди")


@router.post("/generate", status_code=201, summary="Новая песня или перегенерация",
             description="Вход кладётся в songs/<A>/<A - T>/jobs/<id>/in; params.inputs — пути от DATA_DIR.")
def generate(request: Request,
             artist: str = Form(""), title: str = Form(""),
             audio: UploadFile | None = File(None),
             audio_url: str | None = Form(None),
             lyrics: str | None = Form(None),
             lyrics_file: UploadFile | None = File(None),
             cover: UploadFile | None = File(None),
             cover_url: str | None = Form(None),
             lyrics_lrc: UploadFile | None = File(None),
             params: str = Form("{}"),
             song_id: str | None = Form(None),
             replace: bool = Form(False),
             video_mode: str | None = Form(None),
             video_url: str | None = Form(None),
             video_file: UploadFile | None = File(None),
             video_height: str | None = Form(None),
             videogap: str | None = Form(None)):
    ctx = ctx_of(request)
    artist, title = artist.strip(), title.strip()
    if not artist or not title:
        raise ApiError(400, "Укажите исполнителя и название", field="artist" if not artist else "title")
    p = parse_params(ctx, params)
    queue_duplicate(ctx, "generate", key=song_key(artist, title))

    source = ctx.find_song(song_id) if song_id else None
    existing = ctx.find_by_name(artist, title)
    if existing and not replace and not (source and existing.song_id == source.song_id):
        raise ApiError(409, "Такая песня уже есть в папке результата", song_id=existing.song_id)

    text = _read_text_file(lyrics_file) if lyrics_file is not None and lyrics_file.filename else (lyrics or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lrc = None  # None — LRC из формы не пришёл: перегенерация берёт сохранённый из source/
    if lyrics_lrc is not None and lyrics_lrc.filename:
        lrc = _read_text_file(lyrics_lrc, "lyrics_lrc").replace("\r\n", "\n").replace("\r", "\n")
    has_audio = audio is not None and bool(audio.filename)
    link_url = (audio_url or "").strip()
    if has_audio and link_url:
        raise ApiError(400, "Нужно что-то одно: mp3-файл или ссылка", field="audio")
    if link_url:
        try:
            link = musiclink.classify(link_url)
            if link.kind in ("yandex_album", "yandex_playlist"):
                raise musiclink.MusicLinkError("Нужна ссылка на один трек, а не на альбом или плейлист")
            link_url = link.url
        except musiclink.MusicLinkError as e:
            raise link_api_error(e, field="audio_url") from None
    own_src = ctx.paths.source(source.rel_dir) if source and source.own_song_id else None
    if source and not source.own_song_id and not text.strip():
        raise ApiError(400, "Для чужой песни нужен текст", field="lyrics")
    if not has_audio and not link_url and source is None:
        raise ApiError(400, "Загрузите mp3-файл", field="audio")
    if has_audio and not is_mp3(audio.file.read(4)):
        raise ApiError(400, "Это не mp3-файл", field="audio")
    video_params, video_ext = video_choice(video_mode, video_url, video_file, video_height, videogap,
                                           source_url=link_url or None)
    cover_ext = None
    if cover is not None and cover.filename:
        cover_ext = cover_ext_of(cover.file.read(16))
        if cover_ext is None:
            raise ApiError(400, "Обложка должна быть в формате jpg, png или webp", field="cover")

    rel_dir = naming.song_dir(artist, title)
    staging = Staging(ctx, rel_dir)
    try:
        if link_url:
            if own_src is not None:
                staging.copy_from(own_src)  # обложка и LRC — из source/, звук — по ссылке
                staging.drop("audio")
            staging.extra["audio_url"] = link_url
        elif own_src is not None and not has_audio:
            staging.copy_from(own_src)  # своя песня: mp3 и обложка из source/
            if "audio" not in staging.names:
                raise ApiError(409, "Исходный mp3 не найден — загрузите файл")
        elif has_audio:
            audio.file.seek(0)
            copy_limited(audio.file, staging.path("audio", INPUT_AUDIO), ctx.max_upload_mb, "audio")
        else:
            if not source.audio:
                raise ApiError(409, "Исходный mp3 не найден — загрузите файл")
            try:
                with ctx.storage(source.target_id).open_read(f"{source.rel_dir}/{source.audio}") as f:
                    copy_limited(f, staging.path("audio", INPUT_AUDIO), MAX_FOLDER_AUDIO_MB, "audio")
            except StorageError as e:
                ctx.mark_output_error(e, source.target_id)
                raise ApiError(503, f"Папка результата недоступна: {e}") from None
        staging.drop("lyrics")  # текст — всегда из формы
        if text.strip():
            staging.path("lyrics", INPUT_LYRICS).write_text(text, "utf-8")
        if lrc is not None or not text.strip():
            staging.drop("lrc")
        if lrc is not None and lrc.strip() and text.strip():
            staging.path("lrc", INPUT_LRC).write_text(lrc, "utf-8")
        if cover_ext:
            staging.drop("cover")
            cover.file.seek(0)
            copy_limited(cover.file, staging.path("cover", f"{INPUT_COVER_STEM}.{cover_ext}"), MAX_COVER_MB, "cover")
        elif (cover_url or "").strip():
            # обложка со ссылки важнее сохранённой в source/; не скачалась — остаётся прежняя
            name = download_cover(ctx, cover_url, staging.dir)
            if name:
                if staging.names.get("cover") != name:
                    staging.drop("cover")
                staging.path("cover", name)
        if video_ext:
            stage_video_file(ctx, staging, video_file, video_ext)
    except BaseException:
        staging.discard()
        raise

    replace_dir = existing.rel_dir if existing else (source.rel_dir if source else None)
    if video_params:
        p["video"] = video_params
    if link_url:
        p["source"] = "link"
    p.update(rel_dir=rel_dir, replace=bool(replace_dir), replace_rel_dir=replace_dir,
             target_id=replace_target_id(ctx, existing, source))
    ref_id = source.song_id if source else (existing.song_id if existing else None)
    return staging.enqueue("generate", {"artist": artist, "title": title, "song_id": ref_id}, p).to_dict()


class InstrumentalIn(BaseModel):
    song_id: str
    replace: bool = False


@router.post("/instrumental", status_code=201, summary="Минусовка для песни из папки")
def instrumental(body: InstrumentalIn, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(body.song_id)
    queue_duplicate(ctx, "instrumental", song_id=item.song_id)
    if not item.audio:
        raise ApiError(409, "У песни нет аудиофайла (#AUDIO или #MP3)")
    if item.instrumental and not body.replace:
        raise ApiError(409, "Минусовка уже есть — подтвердите пересоздание")
    params = instrumental_params(rel_dir=item.rel_dir, txt_name=item.txt_name, audio=item.audio,
                                 instrumental=item.instrumental, target_id=item.target_id)
    job = ctx.jobs.enqueue("instrumental",
                           {"artist": item.artist, "title": item.title, "song_id": item.song_id}, params)
    return job.to_dict()


MAX_COPY_SONGS = 1000


class CopyIn(BaseModel):
    song_ids: list[str]
    target_id: str
    replace: bool = False
    only_missing: bool = True


@router.post("/copy", status_code=201, summary="Копировать песни в другое хранилище")
def copy(body: CopyIn, request: Request):
    """Задание «Копирование» на каждую песню (Решения §9): ``{queued, skipped, errors}``."""
    ctx = ctx_of(request)
    if len(body.song_ids) > MAX_COPY_SONGS:
        raise ApiError(400, f"За один раз можно копировать не больше {MAX_COPY_SONGS} песен",
                       field="song_ids")
    try:
        target = ctx.target_of(body.target_id)
    except StorageError:
        raise ApiError(400, "Хранилище не найдено", field="target_id") from None
    queued, skipped, errors = [], 0, []
    for song_id in body.song_ids:
        item = ctx.library.find(song_id)
        if item is None:
            errors.append({"song_id": song_id, "detail": "Песня не найдена"})
            continue
        if item.target_id == target.id:
            errors.append({"song_id": song_id, "detail": "Песня уже в этом хранилище"})
            continue
        job = ctx.jobs.active_copy(item.rel_dir, item.target_id, target.id)
        if job is None:
            if body.only_missing and ctx.library.get(target.id, item.rel_dir) is not None:
                skipped += 1
                continue
            job = ctx.jobs.enqueue_copy({"artist": item.artist, "title": item.title, "song_id": item.song_id},
                                        rel_dir=item.rel_dir, txt_name=item.txt_name,
                                        from_target=item.target_id, to_target=target.id, replace=body.replace)
        if job.id not in queued:
            queued.append(job.id)
    return {"queued": queued, "skipped": skipped, "errors": errors}


_VIDEO_EXT_NAMES = [e.lstrip(".") for e in naming.VIDEO_EXT_ORDER]
VIDEO_EXTS_TEXT = ", ".join(_VIDEO_EXT_NAMES[:-1]) + " или " + _VIDEO_EXT_NAMES[-1]  # из naming.VIDEO_EXT_ORDER


def replace_target_id(ctx, existing, source) -> str:
    """Хранилище выкладки: заменяемой песни (её копия меняется там, где лежит),
    иначе основная цель."""
    replaced = existing or source
    return replaced.target_id if replaced is not None else ctx.target().id


def video_link(url: str, field: str = "video_url") -> str:
    """Ссылка на видео для yt-dlp; Яндекс Музыка (только звук), VK-аудио и адреса
    домашней сети — 400 с ``field``. Общая для «Видео…», generate и импорта."""
    try:
        link = musiclink.classify(url)
    except musiclink.MusicLinkError as e:
        raise link_api_error(e, field=field) from None
    if link.kind != "ytdlp":
        raise ApiError(400, "Яндекс Музыка отдаёт только звук — нужна ссылка на видео", field=field)
    return link.url


def is_video_link(url: str | None) -> bool:
    """Годится ли ссылка для видео — то же правило, что у ``video_link`` (для подсказок фронту)."""
    try:
        video_link(url or "")
    except ApiError:
        return False
    return True


def video_ext_of(filename: str | None, field: str = "video") -> str:
    """Расширение видеофайла из ``naming.VIDEO_EXTS`` (нижний регистр, с точкой), иначе 400."""
    ext = Path(filename or "").suffix.lower()
    if ext not in naming.VIDEO_EXTS:
        raise ApiError(400, f"Видео должно быть файлом {VIDEO_EXTS_TEXT}", field=field)
    return ext


def parse_video_height(raw: str | int | None, field: str = "video_height") -> int:
    """Качество видео по ссылке: одно из ``VIDEO_HEIGHTS`` (0 — лучшее); пусто — 720."""
    if raw in (None, ""):
        return DEFAULT_VIDEO_HEIGHT
    try:
        height = int(str(raw).strip())
    except ValueError:
        height = -1
    if height not in VIDEO_HEIGHTS:
        raise ApiError(400, "Качество видео: 360, 480, 720, 1080 или лучшее", field=field)
    return height


# Смещение видео: [+-]цифры[.цифры] или [+-].цифры — то же множество, что у фронта
# (video-block.js::videoError); запятая — точка, экспонента и «_» не принимаются.
_VIDEOGAP_RE = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)", re.ASCII)


def parse_videogap(raw: str | None, field: str = "videogap") -> float | None:
    """Смещение видео в секундах (может быть отрицательным, до 3 знаков); пусто — ``None``."""
    text = (raw or "").strip().replace(",", ".", 1)
    if not text:
        return None
    gap = round(float(text), 3) if _VIDEOGAP_RE.fullmatch(text) else float("nan")
    if gap != gap or gap in (float("inf"), float("-inf")):
        raise ApiError(400, "Смещение видео — число секунд, например 1.5 или -0.25", field=field)
    return gap


VIDEO_MODES = ("none", "source", "url", "file", "pack")
NO_SOURCE_VIDEO = "У песни нет ссылки на видео — выберите другой вариант"
NO_PACK_VIDEO = "В архиве нет видеофайла этой песни — выберите другой вариант"


def video_choice(mode: str | None, url: str | None, file: UploadFile | None, height: str | None,
                 gap: str | None, *, source_url: str | None = None, pack: bool = False,
                 default_gap: float | None = None) -> tuple[dict | None, str | None]:
    """Блок «Видео» generate/import → ``(params.video | None, расширение файла | None)``.

    ``source`` — ``source_url`` (ссылка звука у generate, ссылка usdb/``#VIDEO`` у импорта),
    ``pack`` — видеофайл из архива (допустим, если ``pack``); ``default_gap`` — смещение из
    архива, если поле пустое (только для ``source``/``pack``). Проверки — как у ``/video``.
    """
    mode = (mode or "").strip() or "none"
    if mode not in VIDEO_MODES:
        raise ApiError(400, "Видео: без видео, из ссылки песни, своя ссылка, файл или из архива",
                       field="video_mode")
    if mode == "none":
        return None, None
    video: dict = {"mode": mode}
    ext = None
    if mode == "url":
        link = (url or "").strip()
        if not link:
            raise ApiError(400, "Вставьте ссылку на видео", field="video_url")
        video["url"] = video_link(link)
    elif mode == "source":
        if not source_url:
            raise ApiError(400, NO_SOURCE_VIDEO, field="video_mode")
        video["url"] = video_link(source_url, field="video_mode")
    elif mode == "file":
        if file is None or not file.filename:
            raise ApiError(400, "Выберите видеофайл", field="video_file")
        ext = video_ext_of(file.filename, "video_file")
    elif not pack:
        raise ApiError(400, NO_PACK_VIDEO, field="video_mode")
    if mode in ("url", "source"):  # качество — только у скачивания по ссылке
        video["height"] = parse_video_height(height)
    g = parse_videogap(gap)
    if g is None and mode in ("source", "pack"):
        g = default_gap
    if g is not None:
        video["gap"] = g
    return video, ext


def stage_video_file(ctx: AppContext, staging: Staging, file: UploadFile, ext: str) -> None:
    """Видеофайл из формы → ``in/video.<ext>`` (лимит ``MAX_VIDEO_MB``, 413 — ``field=video_file``)."""
    file.file.seek(0)
    copy_limited(file.file, staging.path("video", f"{INPUT_VIDEO_STEM}{ext}"), max_video_mb(ctx), "video_file")


@router.post("/video", status_code=201, summary="Видео к песне из папки: ссылка, файл или убрать",
             description="Ровно один источник: файл `video` или `video_url` (качество `video_height`), "
                         "либо `remove`. Файл кладётся в songs/<A>/<A - T>/jobs/<id>/in/video.<ext>.")
def video(request: Request,
          song_id: str = Form(...),
          video: UploadFile | None = File(None),
          video_url: str | None = Form(None),
          video_height: str | None = Form(None),
          videogap: str | None = Form(None),
          remove: bool = Form(False)):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    queue_duplicate(ctx, "video", song_id=item.song_id)
    has_file = video is not None and bool(video.filename)
    url = (video_url or "").strip()
    params: dict = {"rel_dir": item.rel_dir, "txt_name": item.txt_name, "target_id": item.target_id}
    ext = None
    if remove:
        if has_file or url:
            raise ApiError(400, "Нужно что-то одно: убрать видео или прикрепить новое", field="video")
        if not item.video:
            raise ApiError(409, "У песни нет видео")
        params["remove"] = True
    else:
        if has_file and url:
            raise ApiError(400, "Нужно что-то одно: видеофайл или ссылка", field="video")
        if not has_file and not url:
            raise ApiError(400, "Загрузите видеофайл или вставьте ссылку", field="video")
        if url:
            params["video_url"] = video_link(url)
            params["video_height"] = parse_video_height(video_height)
        else:
            ext = video_ext_of(video.filename)
        params["videogap"] = parse_videogap(videogap)
    staging = Staging(ctx, item.rel_dir)
    try:
        if ext:
            copy_limited(video.file, staging.path("video", f"{INPUT_VIDEO_STEM}{ext}"), max_video_mb(ctx), "video")
    except BaseException:
        staging.discard()
        raise
    ref = {"artist": item.artist, "title": item.title, "song_id": item.song_id}
    return staging.enqueue("video", ref, params).to_dict()


@router.get("", summary="Очередь и история")
def list_jobs(request: Request, limit: int = Query(50, ge=1, le=1000)):
    return [j.to_dict() for j in ctx_of(request).jobs.list(limit)]


@router.get("/{job_id}", summary="Одно задание")
def get_job(job_id: int, request: Request):
    return _job_or_404(ctx_of(request), job_id).to_dict()


@router.post("/{job_id}/cancel", summary="Отменить")
def cancel(job_id: int, request: Request):
    ctx = ctx_of(request)
    job = _job_or_404(ctx, job_id)
    if job.state in FINAL_STATES:
        raise ApiError(409, "Задание уже завершено")
    return ctx.jobs.request_cancel(job_id).to_dict()


@router.post("/{job_id}/restart", status_code=201, summary="Перезапустить с теми же параметрами")
def restart(job_id: int, request: Request):
    ctx = ctx_of(request)
    job = _job_or_404(ctx, job_id)
    if job.state not in FINAL_STATES:
        raise ApiError(409, "Перезапустить можно только завершённое задание")
    if job.type == "video":
        queue_duplicate(ctx, "video", song_id=job.song_id)
    if job.type == "copy":  # ожидание хранилища начинается заново
        p = job.params
        return ctx.jobs.enqueue_copy(
            job, rel_dir=p.get("rel_dir", ""), txt_name=p.get("txt_name", ""),
            from_target=p.get("from_target", ""), to_target=p.get("to_target", ""),
            replace=bool(p.get("replace")), wait=bool(p.get("wait")),
            replace_rel_dir=p.get("replace_rel_dir"), after_job=p.get("after_job"),
            parent_id=job.id).to_dict()
    if job.type != "generate":
        return ctx.jobs.enqueue(job.type, job, job.params, parent_id=job.id).to_dict()
    queue_duplicate(ctx, "generate", key=song_key(job.artist, job.title))
    rel_dir = job.params.get("rel_dir") or naming.song_dir(job.artist, job.title)
    prev_in = (job.params.get("inputs") or {}).get("dir")
    prev_in = ctx.paths.abs(prev_in) if prev_in else None
    source = ctx.paths.source(rel_dir)
    audio_url = (job.params.get("inputs") or {}).get("audio_url")
    by_link = False  # звук не скачан — воркер скачает по ссылке заново
    if prev_in is not None and (prev_in / INPUT_AUDIO).is_file():
        origin = prev_in  # вход родителя ещё лежит в jobs/<id>/in
    elif audio_url:
        # звук из source/ может быть от прежней версии песни, не по этой ссылке: звук — только
        # по ссылке; текст и обложка — из in/ родителя, иначе из source/
        by_link = True
        origin = next((d for d in (prev_in, source) if d is not None and d.is_dir()), None)
    elif (source / INPUT_AUDIO).is_file():
        origin = source  # после успеха воркер перенёс вход в source/
    else:
        raise ApiError(409, "Исходники задания не сохранились — создайте задание заново")
    staging = Staging(ctx, rel_dir)
    try:
        if origin is not None:
            staging.copy_from(origin)
        if by_link:
            staging.drop("audio")
            staging.extra["audio_url"] = audio_url
    except BaseException:
        staging.discard()
        raise
    params = {k: v for k, v in job.params.items() if k != "inputs"}
    return staging.enqueue("generate", job, params, parent_id=job.id).to_dict()


@router.post("/{job_id}/republish", status_code=201, summary="Выложить повторно (без GPU)")
def republish(job_id: int, request: Request):
    ctx = ctx_of(request)
    job = _job_or_404(ctx, job_id)
    if job.state != "failed" or (job.type != "publish" and job.stage != STAGE_PUBLISH):
        raise ApiError(409, "Повторная выкладка возможна только после ошибки выкладки")
    src = job.params.get("source_job_id", job.id) if job.type == "publish" else job.id
    params = {**job.params, "source_job_id": src}
    new = ctx.jobs.enqueue("publish", job, params, parent_id=job.id)
    return new.to_dict()


# --------------------------------------------------------------------------- лог

def _tail_offset(path: Path, lines: int) -> int:
    """Смещение начала последних ``lines`` строк файла."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        pos, found = size, 0
        while pos > 0:
            step = min(CHUNK, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step)
            end = len(buf) - 1 if pos + step == size and buf.endswith(b"\n") else len(buf)
            for i in range(end - 1, -1, -1):
                if buf[i] == 0x0A:
                    found += 1
                    if found == lines:
                        return pos + i + 1
    return 0


@router.get("/{job_id}/log", response_class=PlainTextResponse, summary="Лог кусками",
            description="`from` — смещение в байтах (из заголовка X-Log-Offset прошлого ответа); "
                        "`tail` — только последние N строк.")
def get_log(job_id: int, request: Request, from_: int = Query(0, alias="from", ge=0),
            tail: int | None = Query(None, ge=1)):
    ctx = ctx_of(request)
    _job_or_404(ctx, job_id)
    path = ctx.paths.log(job_id)
    if not path.is_file():
        return PlainTextResponse("", headers={"X-Log-Offset": "0"})
    start = _tail_offset(path, tail) if tail else from_
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read()
    return PlainTextResponse(data.decode("utf-8", errors="replace"),
                             headers={"X-Log-Offset": str(start + len(data))})


@router.get("/{job_id}/log/stream", summary="Живой лог (SSE)",
            description="Сначала `event: start` (data — смещение начала первой строки); "
                        "события `data:` — строки лога, `id:` — смещение; в конце `event: end` "
                        "с итоговым состоянием. Без `from` начинается с последних 500 строк.")
async def stream_log(job_id: int, request: Request, from_: int | None = Query(None, alias="from", ge=0)):
    ctx = ctx_of(request)
    await asyncio.to_thread(_job_or_404, ctx, job_id)
    path = ctx.paths.log(job_id)
    last_id = request.headers.get("last-event-id")
    if last_id and last_id.isdigit():
        from_ = int(last_id)

    async def events():
        offset = from_
        if offset is None:
            offset = _tail_offset(path, SSE_TAIL_LINES) if path.is_file() else 0
        # смещение начала первой отданной строки: всё до него клиент догружает через ?from=0
        yield f"event: start\ndata: {offset}\n\n"
        idle = 0
        while True:
            data = b""
            if path.is_file():
                with open(path, "rb") as f:
                    f.seek(offset)
                    data = f.read()
            cut = data.rfind(b"\n") + 1
            if cut:
                pos = offset
                for raw in data[:cut].split(b"\n")[:-1]:
                    pos += len(raw) + 1
                    text = raw.decode("utf-8", errors="replace").rstrip("\r")
                    yield f"id: {pos}\ndata: {text}\n\n"
                offset += cut
                idle = 0
                continue
            job = await asyncio.to_thread(ctx.jobs.get, job_id)
            if job is None or job.state in FINAL_STATES:
                if data:  # хвост без перевода строки
                    yield f"id: {offset + len(data)}\ndata: {data.decode('utf-8', 'replace')}\n\n"
                yield f"event: end\ndata: {job.state if job else 'missing'}\n\n"
                return
            if await request.is_disconnected():
                return
            idle += 1
            if idle % 30 == 0:
                yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
