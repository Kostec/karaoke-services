"""Песни папки результата: индекс, карточка, текст, ноты, аудио, удаление; корзина."""

from __future__ import annotations

import logging
import mimetypes
import re
import time
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from karaoke_core import linealign, naming, ultrastar
from karaoke_core.paths import INPUT_LYRICS
from karaoke_core.storage import StorageError, StorageNotFound
from karaoke_core.storage.base import PART_SUFFIX
from karaoke_core.trash import TrashError

from .api_import import SOURCES as IMPORT_SOURCES
from .api_jobs import ctx_of
from .context import ApiError, AppContext, not_found
from .notes import NotesIn, apply_notes, notes_payload, read_only_reason
from .usdb import BASE_URL as USDB_URL

router = APIRouter(prefix="/api", tags=["Песни"])
log = logging.getLogger(__name__)


def _storage_call(ctx: AppContext, fn, *a, target_id: str | None = None):
    """Вызов хранилища ``target_id``: недоступно → 503 с понятной причиной."""
    try:
        return fn(*a)
    except StorageNotFound as e:
        _not_found_or_unavailable(ctx, e, target_id)
    except StorageError as e:
        ctx.mark_output_error(e, target_id)
        raise ApiError(503, f"Папка результата недоступна: {e}") from None


def _not_found_or_unavailable(ctx: AppContext, e: StorageNotFound, target_id: str | None = None):
    """Нет файла — 404; но если пропал сам корень хранилища — 503."""
    status = ctx.output_status(fresh=True, target_id=target_id)
    if not status["ok"]:
        raise ApiError(503, status["error"]) from None
    raise ApiError(404, str(e)) from None


def _song_storage(ctx: AppContext, item):
    """Хранилище песни (по ``target_id`` её строки индекса)."""
    return _storage_call(ctx, ctx.storage, item.target_id, target_id=item.target_id)


def _read_txt(ctx: AppContext, item) -> bytes:
    return _storage_call(ctx, _song_storage(ctx, item).read, f"{item.rel_dir}/{item.txt_name}",
                         target_id=item.target_id)


_UNREAD = object()


def _pending_copies(ctx: AppContext) -> dict[str, list[dict]]:
    """Активные задания «Копирование» по id песни-источника: ``[{target_id, name, job_id}]``."""
    names = {t.id: t.name or t.label for t in ctx.targets()}
    out: dict[str, list[dict]] = {}
    for job in ctx.jobs.active("copy"):
        to = job.params.get("to_target")
        if job.song_id:
            out.setdefault(job.song_id, []).append({"target_id": to, "name": names.get(to, to),
                                                    "job_id": job.id})
    return out


def _song_out(ctx: AppContext, item, own=_UNREAD, pending=None, tags=None) -> dict:
    """Песня для API + ``source`` (usdb|files|url из params.json своей песни, ``generated`` —
    своя без импорта, None — чужая), ``updated_at`` (ISO из mtime ``.txt``)
    + ``pending_copies`` + ``tags`` (id своих тегов); ``own``/``pending``/``tags`` — уже
    прочитанное (список читает их одним запросом; ``tags`` — ``{ключ песни: [id]}``)."""
    out = ctx.song_dict(item)
    if pending is None:
        pending = _pending_copies(ctx)
    out["pending_copies"] = pending.get(item.song_id, [])
    key = naming.song_tag_key(item.artist, item.title)
    if tags is None:
        tags = ctx.tags.for_songs([key])
    out["tags"] = tags.get(key, [])
    if own is _UNREAD:
        own = ctx.songs.get(item.own_song_id) if item.own_song_id else None
    params = own.params if own and isinstance(own.params, dict) else {}
    # «импорт» — только песни из usdb/файлов/ссылки на архив; generate по ссылке на музыку
    # (source="link") — песня, созданная сервисом; без своей записи — чужая (None)
    if params.get("source") in IMPORT_SOURCES:
        out["source"] = params["source"]
    else:
        out["source"] = "generated" if item.own_song_id else None
    out["updated_at"] = (datetime.fromtimestamp(item.mtime, timezone.utc).isoformat(timespec="seconds")
                         if item.mtime else None)
    return out


def _chosen_target(ctx: AppContext, target: str | None):
    """Хранилище из ``?target=`` (нет — основная цель; неизвестное явное — 400)."""
    if not target:
        return ctx.default_target()
    try:
        return ctx.target_of(target)
    except StorageError:
        raise ApiError(400, "Такого хранилища нет в настройках", field="target") from None


@router.get("/songs", summary="Список песен хранилища из индекса")
def list_songs(request: Request, background: BackgroundTasks, q: str | None = None,
               target: str | None = None):
    ctx = ctx_of(request)
    chosen = _chosen_target(ctx, target)
    items = ctx.library.list(chosen.id, q)
    own = ctx.songs.get_many(i.own_song_id for i in items)
    pending = _pending_copies(ctx)
    tags = ctx.tags.for_songs({naming.song_tag_key(i.artist, i.title) for i in items})
    state = ctx.scan_state.get(chosen.id, {})
    if not state and not ctx.library.list(chosen.id):
        background.add_task(ctx.rescan, chosen.id)  # первый показ этой цели — просканировать
    output = ctx.output_status(target_id=None if target is None else chosen.id)
    return {"scanned_at": ctx.scanned_at(chosen.id, items),
            "scanning": bool(state.get("running")),
            "output": output, "target": chosen.public(),
            "targets": [{"id": t.id, "name": t.name or t.label, "kind": t.kind} for t in ctx.targets()],
            "items": [_song_out(ctx, i, own.get(i.own_song_id), pending, tags) for i in items]}


@router.post("/songs/rescan", status_code=202, summary="Пересканировать хранилище в фоне")
def rescan(request: Request, background: BackgroundTasks, target: str | None = None):
    ctx = ctx_of(request)
    background.add_task(ctx.rescan, _chosen_target(ctx, target).id)
    return {"scanning": True}


@router.get("/songs/exists", summary="Есть ли такая песня в папке результата")
def exists(request: Request, artist: str = "", title: str = ""):
    if not artist.strip() or not title.strip():
        raise ApiError(400, "Укажите исполнителя и название", field="artist" if not artist.strip() else "title")
    item = ctx_of(request).find_by_name(artist, title)
    return {"exists": True, "song_id": item.song_id} if item else {"exists": False}


def _own_lyrics(ctx: AppContext, item) -> str | None:
    path = ctx.paths.source(item.rel_dir) / INPUT_LYRICS
    return path.read_text("utf-8") if item.own_song_id and path.is_file() else None


def _song_card(ctx: AppContext, item, own=_UNREAD) -> dict:
    """Карточка песни: элемент списка + у своей песни ``params`` и ``lyrics``."""
    if own is _UNREAD:
        own = ctx.songs.get(item.own_song_id) if item.own_song_id else None
    out = _song_out(ctx, item, own)
    if item.own_song_id:
        out["params"] = own.params if own else None
        out["lyrics"] = _own_lyrics(ctx, item)
    return out


@router.get("/songs/{song_id}", summary="Карточка песни")
def get_song(song_id: str, request: Request):
    ctx = ctx_of(request)
    return _song_card(ctx, ctx.find_song(song_id))


# Заголовки .txt для страницы песни: ключ ответа → заголовок файла.
DETAIL_HEADERS = {"author": "AUTHOR", "bpm": "BPM", "gap": "GAP", "language": "LANGUAGE",
                  "year": "YEAR", "genre": "GENRE", "edition": "EDITION", "creator": "CREATOR",
                  "videogap": "VIDEOGAP"}


def _folder_files(storage, rel_dir: str) -> list:
    """Файлы самой папки песни (без подпапок и недописанных ``.part``) по имени."""
    return sorted((e for e in storage.listdir(rel_dir)
                   if not e.is_dir and not e.name.endswith(PART_SUFFIX)), key=lambda e: e.name)


def _present(names: list[str], value: str | None) -> str | None:
    """Имя файла из заголовка, если он лежит в папке (без учёта регистра; имя — как на диске)."""
    value = (value or "").strip()
    if not value or "/" in value or "\\" in value:
        return None
    if value in names:
        return value
    return next((n for n in names if n.lower() == value.lower()), None)


def _usdb_url(own) -> str | None:
    params = own.params if own and isinstance(own.params, dict) else {}
    try:
        usdb_id = int(params.get("usdb_id") or 0)
    except (TypeError, ValueError):
        return None
    return f"{USDB_URL}index.php?link=detail&id={usdb_id}" if usdb_id > 0 else None


def _copies(ctx: AppContext, item) -> list[dict]:
    """Эта песня во всех хранилищах из настроек (по ``match_key``; только индекс)."""
    order = {t.id: (n, t.name or t.label) for n, t in enumerate(ctx.targets())}
    found = [i for i in ctx.library.copies(item.artist, item.title) if i.target_id in order]
    found.sort(key=lambda i: (order[i.target_id][0], i.rel_dir))
    return [{"song_id": i.song_id, "target_id": i.target_id, "target_name": order[i.target_id][1],
             "current": i.song_id == item.song_id} for i in found]


@router.get("/songs/{song_id}/details", summary="Сведения страницы песни: заголовки, медиа, файлы, копии")
def get_details(song_id: str, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    storage = _song_storage(ctx, item)
    files = _storage_call(ctx, _folder_files, storage, item.rel_dir, target_id=item.target_id)
    song = ultrastar.parse(_read_txt(ctx, item))
    names = [e.name for e in files]
    base = (item.txt_name[:-len(naming.SUFFIX_TXT)]
            if item.txt_name.lower().endswith(naming.SUFFIX_TXT) else item.txt_name)
    headers = {}
    for key, header in DETAIL_HEADERS.items():
        value = (song.header(header) or "").strip()
        if value:
            headers[key] = value
    singers = None
    if song.is_duet:
        p1, p2 = ultrastar.singer_names(song)
        singers = {"p1": p1, "p2": p2}
    media = {
        "audio": _present(names, song.header("AUDIO")) or _present(names, song.header("MP3")),
        "instrumental": _present(names, song.header("INSTRUMENTAL")),
        "vocals": _present(names, base + naming.SUFFIX_VOCALS),
        "video": _present(names, naming.video_file_name(song.header("VIDEO"))),
        "cover": _present(names, song.header("COVER")),
        "background": _present(names, song.header("BACKGROUND")),
        "midi": next((n for n in names if n.lower().endswith(naming.SUFFIX_MIDI)), None),
    }
    own = ctx.songs.get(item.own_song_id) if item.own_song_id else None
    return {"song": _song_card(ctx, item, own), "headers": headers, "singers": singers,
            "media": media,
            "files": [{"name": e.name, "size": e.size, "mtime": e.mtime} for e in files],
            "copies": _copies(ctx, item), "usdb_url": _usdb_url(own)}


@router.get("/songs/{song_id}/lyrics", summary="Текст песни: свой исходный или извлечённый из .txt")
def get_lyrics(song_id: str, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    own = _own_lyrics(ctx, item)
    if own is not None:
        return {"text": own, "source": "own"}
    return {"text": ultrastar.extract_lyrics(ultrastar.parse(_read_txt(ctx, item))),
            "source": "extracted"}


@router.get("/songs/{song_id}/notes", summary="Ноты песни структурой")
def get_notes(song_id: str, request: Request):
    ctx = ctx_of(request)
    return notes_payload(ultrastar.parse(_read_txt(ctx, ctx.find_song(song_id))))


@router.put("/songs/{song_id}/notes", summary="Сохранить правку нот (старая версия — в корзину)")
def put_notes(song_id: str, body: NotesIn, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    original = _read_txt(ctx, item)
    song = ultrastar.parse(original)
    reason = read_only_reason(song)
    if reason:
        raise ApiError(409, reason)
    apply_notes(song, body)
    try:
        data = ultrastar.render(song)
    except UnicodeEncodeError:
        raise ApiError(400, f"Символ не поддерживается кодировкой файла ({song.encoding})") from None
    if data != original:
        rel = f"{item.rel_dir}/{item.txt_name}"
        storage = _song_storage(ctx, item)
        try:
            _storage_call(ctx, lambda: ctx.trash.save_version(storage, rel, reason="правка нот в редакторе"),
                          target_id=item.target_id)
        except TrashError as e:
            raise ApiError(409, str(e)) from None
        _storage_call(ctx, storage.write_atomic, rel, data, target_id=item.target_id)
        item = ctx.refresh_song(item.rel_dir, item.target_id) or item
    return ctx.song_dict(item)


NO_LYRICS_TO_ALIGN = "У песни нет исходного текста — строки выровнять не по чему"


class LinesIn(BaseModel):
    texts: list[str]  # тексты нот соло в порядке редактора
    starts: list[int] = []  # текущие начала строк в редакторе (индексы нот)


@router.post("/songs/{song_id}/notes/lines", summary="Границы строк по исходному тексту (ничего не пишет)")
def align_notes_lines(song_id: str, body: LinesIn, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    if not body.texts:
        raise ApiError(400, "Нет нот — строки выровнять не по чему", field="texts")
    lyrics = _own_lyrics(ctx, item)
    if lyrics is None or not lyrics.strip():
        raise ApiError(409, NO_LYRICS_TO_ALIGN)
    r = linealign.align_line_starts(body.texts, lyrics, body.starts)
    return {"starts": r.starts, "unmatched": r.unmatched, "total": r.total}


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _media(ctx: AppContext, item, name: str | None, request: Request, default_type: str):
    if not name:
        raise not_found("У песни нет такого файла")
    storage = _song_storage(ctx, item)
    rel = f"{item.rel_dir}/{name}"
    st = _storage_call(ctx, storage.stat, rel, target_id=item.target_id)
    if st is None or st.is_dir:
        _not_found_or_unavailable(ctx, StorageNotFound("Файл песни не найден в папке результата"),
                                  item.target_id)
    size = st.size
    ctype = mimetypes.guess_type(name)[0] or default_type
    start, end, status = 0, size - 1, 200
    rng = request.headers.get("range")
    if rng:
        m = _RANGE_RE.match(rng.strip())
        if not m or not (m.group(1) or m.group(2)):
            raise ApiError(416, "Неверный диапазон")
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:
            start = max(0, size - int(m.group(2)))
        if start >= size or start > end:
            return JSONResponse({"detail": "Неверный диапазон"}, status_code=416,
                                headers={"Content-Range": f"bytes */{size}"})
        status = 206
    f = _storage_call(ctx, storage.open_read, rel, target_id=item.target_id)

    def body():
        try:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 16, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk
        finally:
            f.close()

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(body(), status_code=status, media_type=ctype, headers=headers)


@router.get("/songs/{song_id}/audio", summary="Оригинал песни (поддерживает Range)")
def get_audio(song_id: str, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    return _media(ctx, item, item.audio, request, "audio/mpeg")


@router.get("/songs/{song_id}/cover", summary="Обложка")
def get_cover(song_id: str, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    return _media(ctx, item, item.cover, request, "image/jpeg")


NO_SUCH_FILE = "У песни нет такого файла"


@router.get("/songs/{song_id}/file", summary="Любой файл папки песни (Range); ?download=1 — скачать")
def get_file(song_id: str, request: Request, name: str = "", download: bool = False):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise not_found(NO_SUCH_FILE)
    storage = _song_storage(ctx, item)
    files = _storage_call(ctx, _folder_files, storage, item.rel_dir, target_id=item.target_id)
    real = _present([e.name for e in files], name)
    if real is None:
        raise not_found(NO_SUCH_FILE)
    resp = _media(ctx, item, real, request, "application/octet-stream")
    if download:
        resp.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(real)}"
    return resp


class _ZipSink:
    """Поток для ``zipfile``: копит записанное, генератор забирает порциями."""

    def __init__(self):
        self.parts: list[bytes] = []

    def write(self, b) -> int:
        self.parts.append(bytes(b))
        return len(b)

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        data, self.parts = b"".join(self.parts), []
        return data


def _zip_name(item) -> str:
    """``<Исполнитель - Название>`` — имя архива и папки внутри него."""
    if item.artist and item.title:
        return naming.base_name(item.artist, item.title)
    return item.rel_dir.rsplit("/", 1)[-1]


def _song_files(storage, rel_dir: str, sub: str = "") -> list[tuple[str, object]]:
    """Файлы папки песни с подпапками: ``[(путь внутри папки, Entry)]``; ``.part`` — мимо."""
    out = []
    for e in storage.listdir(f"{rel_dir}/{sub}" if sub else rel_dir):
        path = f"{sub}/{e.name}" if sub else e.name
        if e.is_dir:
            out.extend(_song_files(storage, rel_dir, path))
        elif not e.name.endswith(PART_SUFFIX):
            out.append((path, e))
    return sorted(out, key=lambda x: x[0])


def _zip_time(mtime: float | None) -> tuple:
    """Дата файла в архиве — из хранилища (zip не умеет раньше 1980 года)."""
    stamp = time.localtime(mtime) if mtime else time.localtime()
    return max(stamp[:6], (1980, 1, 1, 0, 0, 0))


@router.get("/songs/{song_id}/zip", summary="Папка песни одним .zip (потоком); ?check=1 — только проверка")
def get_zip(song_id: str, request: Request, check: bool = False):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    storage = _song_storage(ctx, item)
    files = _storage_call(ctx, _song_files, storage, item.rel_dir, target_id=item.target_id)
    if not files:
        _not_found_or_unavailable(ctx, StorageNotFound("Папка песни пуста или не найдена"),
                                  item.target_id)
    if check:  # лёгкая проверка перед скачиванием: список получен, файлы не читаются
        return {"ok": True, "files": len(files)}
    name = _zip_name(item)  # список файлов уже получен — хранилище ответило до первого байта

    def body():
        sink = _ZipSink()
        with zipfile.ZipFile(sink, "w") as zf:
            for sub, entry in files:
                try:
                    f = storage.open_read(f"{item.rel_dir}/{sub}")
                except Exception as e:
                    log.error("zip песни %s: не удалось прочитать «%s»: %s", song_id, sub, e)
                    raise
                with f:
                    info = zipfile.ZipInfo(f"{name}/{sub}", _zip_time(entry.mtime))
                    info.compress_type = (zipfile.ZIP_DEFLATED if sub.lower().endswith(".txt")
                                          else zipfile.ZIP_STORED)
                    info.file_size = entry.size
                    with zf.open(info, "w") as out:
                        while True:
                            try:
                                chunk = f.read(1 << 16)
                            except Exception as e:
                                log.error("zip песни %s: сбой чтения «%s»: %s", song_id, sub, e)
                                raise
                            if not chunk:
                                break
                            out.write(chunk)
                            if sink.parts:
                                yield sink.take()
                yield sink.take()
        yield sink.take()

    disposition = f"attachment; filename*=UTF-8''{quote(name + '.zip')}"
    return StreamingResponse(body(), media_type="application/zip",
                             headers={"Content-Disposition": disposition})


@router.delete("/songs/{song_id}", summary="Удалить в корзину")
def delete_song(song_id: str, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    try:
        trash_item = ctx.trash.move_to_trash(ctx.storage(item.target_id), item.rel_dir,
                                             reason="удалено из веба")
    except StorageNotFound as e:
        _not_found_or_unavailable(ctx, e, item.target_id)
    except StorageError as e:
        ctx.mark_output_error(e, item.target_id)
        raise ApiError(503, f"Папка результата недоступна: {e}") from None
    except TrashError as e:
        # «песня не найдена» при пропавшем корне — это 503
        status = ctx.output_status(fresh=True, target_id=item.target_id)
        raise ApiError(409, str(e)) if status["ok"] else ApiError(503, status["error"]) from None
    ctx.library.remove(item.target_id, item.rel_dir)
    return trash_item.to_dict(ctx.trash.days)


@router.get("/trash", tags=["Корзина"], summary="Корзина")
def list_trash(request: Request):
    ctx = ctx_of(request)
    return [i.to_dict(ctx.trash.days) for i in ctx.trash.list()]


@router.post("/trash/{item_id}/restore", tags=["Корзина"], summary="Восстановить на прежнее место")
def restore(item_id: str, request: Request):
    ctx = ctx_of(request)
    try:
        entry = ctx.trash.get(item_id)
    except TrashError:
        raise not_found("Запись корзины не найдена") from None
    target_id = (ctx.settings.resolve_target_id(entry.target_id) if entry.target_id
                 else ctx.target().id)
    if target_id is None:
        raise ApiError(409, f"Хранилище «{entry.target_label or entry.target_id}» удалено из настроек")
    try:
        storage = ctx.storage(target_id)
        item = ctx.trash.restore(storage, item_id)
    except TrashError as e:
        raise ApiError(409, str(e)) from None
    except StorageError as e:
        ctx.mark_output_error(e, target_id)
        raise ApiError(503, f"Папка результата недоступна: {e}") from None
    ctx.refresh_song(item.rel_dir, target_id)
    return item.to_dict(ctx.trash.days)
