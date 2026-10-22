"""Песни папки результата: индекс, карточка, текст, ноты, аудио, удаление; корзина."""

from __future__ import annotations

import mimetypes
import re

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from karaoke_core import linealign, ultrastar
from karaoke_core.paths import INPUT_LYRICS
from karaoke_core.storage import StorageError, StorageNotFound
from karaoke_core.trash import TrashError

from .api_import import SOURCES as IMPORT_SOURCES
from .api_jobs import ctx_of
from .context import ApiError, AppContext, not_found
from .notes import NotesIn, apply_notes, notes_payload, read_only_reason

router = APIRouter(prefix="/api", tags=["Песни"])


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


def _song_out(ctx: AppContext, item, own=_UNREAD) -> dict:
    """Песня для API + ``source`` импорта из params.json своей песни (usdb|files|url или None);
    ``own`` — уже прочитанная запись (список читает их одним запросом)."""
    out = ctx.song_dict(item)
    if own is _UNREAD:
        own = ctx.songs.get(item.own_song_id) if item.own_song_id else None
    params = own.params if own and isinstance(own.params, dict) else {}
    # «импорт» — только песни из usdb/файлов/ссылки на архив; generate по ссылке на музыку
    # (source="link") — песня, созданная сервисом
    out["source"] = params.get("source") if params.get("source") in IMPORT_SOURCES else None
    return out


@router.get("/songs", summary="Список песен из индекса")
def list_songs(request: Request, background: BackgroundTasks, q: str | None = None):
    ctx = ctx_of(request)
    target = ctx.target()
    storage = ctx.storage()
    items = ctx.library.list(storage.target_id, q)
    own = ctx.songs.get_many(i.own_song_id for i in items)
    state = ctx.scan_state.get(storage.target_id, {})
    if not state and not ctx.library.list(storage.target_id):
        background.add_task(ctx.rescan)  # первый показ этой цели — просканировать
    return {"scanned_at": ctx.scanned_at(storage.target_id, items),
            "scanning": bool(state.get("running")),
            "output": ctx.output_status(), "target": target.public(),
            "items": [_song_out(ctx, i, own.get(i.own_song_id)) for i in items]}


@router.post("/songs/rescan", status_code=202, summary="Пересканировать папку в фоне")
def rescan(request: Request, background: BackgroundTasks):
    background.add_task(ctx_of(request).rescan)
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


@router.get("/songs/{song_id}", summary="Карточка песни")
def get_song(song_id: str, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    own = ctx.songs.get(item.own_song_id) if item.own_song_id else None
    out = _song_out(ctx, item, own)
    if item.own_song_id:
        out["params"] = own.params if own else None
        out["lyrics"] = _own_lyrics(ctx, item)
    return out


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
