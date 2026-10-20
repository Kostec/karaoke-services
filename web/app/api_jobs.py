"""Задания: постановка в очередь (воркер исполняет сам), отмена, перезапуск, выкладка, лог."""

from __future__ import annotations

import asyncio
import os
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
from karaoke_core.paths import INPUT_AUDIO, INPUT_COVER_STEM, INPUT_LRC, INPUT_LYRICS
from karaoke_core.storage import StorageError

from .context import ApiError, AppContext, link_api_error, not_found, song_key
from .params import MAX_COVER_MB, MAX_FOLDER_AUDIO_MB, MAX_LYRICS_MB, parse_params

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
             replace: bool = Form(False)):
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
    cover_ext = None
    if cover is not None and cover.filename:
        cover_ext = cover_ext_of(cover.file.read(16))
        if cover_ext is None:
            raise ApiError(400, "Обложка должна быть в формате jpg, png или webp", field="cover")

    rel_dir = naming.song_dir(artist, title)
    storage = ctx.storage()
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
                with storage.open_read(f"{source.rel_dir}/{source.audio}") as f:
                    copy_limited(f, staging.path("audio", INPUT_AUDIO), MAX_FOLDER_AUDIO_MB, "audio")
            except StorageError as e:
                ctx.mark_output_error(e)
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
    except BaseException:
        staging.discard()
        raise

    replace_dir = existing.rel_dir if existing else (source.rel_dir if source else None)
    if link_url:
        p["source"] = "link"
    p.update(rel_dir=rel_dir, replace=bool(replace_dir), replace_rel_dir=replace_dir,
             target_id=storage.target_id)
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
