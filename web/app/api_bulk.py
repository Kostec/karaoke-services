"""Действия над несколькими песнями сразу (раздел «Песни», режим выбора): теги, zip, удаление,
минусовка. Ответ — по песням: ошибка одной песни не прерывает остальные."""

from __future__ import annotations

import logging
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from karaoke_core import naming
from karaoke_core.db import instrumental_params
from karaoke_core.storage import StorageError, StorageNotFound
from karaoke_core.trash import TrashError

from .api_jobs import ctx_of
from .api_songs import _ZipSink, _song_files, _zip_time
from .context import ApiError, AppContext
from .params import MAX_BULK_SONGS, MAX_ZIP_SONGS

router = APIRouter(prefix="/api", tags=["Песни: несколько сразу"])
log = logging.getLogger(__name__)

NOT_FOUND = "Песня не найдена"
NOTHING_CHOSEN = "Не выбрано ни одной песни"
NOT_INCLUDED_NAME = "НЕ ВОШЛО.txt"
# Причины пропуска минусовки (видны в итоге «Готово: N. Пропущено: M»)
SKIP_QUEUED = "уже в очереди"
SKIP_NO_AUDIO = "нет звука"
SKIP_HAS_INSTRUMENTAL = "уже есть минусовка"


def _song_ids(raw: list[str], limit: int = MAX_BULK_SONGS) -> list[str]:
    """Id песен без пустых и повторов (порядок сохраняется); пусто или больше ``limit`` — 400."""
    ids = list(dict.fromkeys(s.strip() for s in raw if s and s.strip()))
    if not ids:
        raise ApiError(400, NOTHING_CHOSEN, field="song_ids")
    if len(ids) > limit:
        raise ApiError(400, f"За один раз — не больше {limit} песен", field="song_ids")
    return ids


def _find(ctx: AppContext, song_id: str):
    """Песня по id в хранилище из настроек или ``None``."""
    try:
        return ctx.find_song(song_id)
    except ApiError:
        return None


def _title(item) -> str:
    if item.artist or item.title:
        return f"{item.artist or '?'} — {item.title or '?'}"
    return item.rel_dir


# --------------------------------------------------------------------------- теги


class BulkTagsIn(BaseModel):
    song_ids: list[str]
    add: list[str] = []
    remove: list[str] = []


@router.post("/songs/tags", summary="Добавить и снять свои теги у нескольких песен")
def bulk_tags(body: BulkTagsIn, request: Request):
    """Набор тегов каждой песни меняется, а не заменяется; копии песни делят один ключ."""
    ctx = ctx_of(request)
    ids = _song_ids(body.song_ids)
    keys, updated, errors = [], 0, []
    for song_id in ids:
        item = _find(ctx, song_id)
        if item is None:
            errors.append({"song_id": song_id, "detail": NOT_FOUND})
            continue
        keys.append(naming.song_tag_key(item.artist, item.title))
        updated += 1
    try:
        ctx.tags.change_for_songs(keys, body.add, body.remove)
    except KeyError as e:
        missing = e.args[0] if e.args else ""
        raise ApiError(400, "Такого тега нет — обновите страницу",
                       field="add" if missing in body.add else "remove") from None
    return {"updated": updated, "errors": errors}


# --------------------------------------------------------------------------- zip


def _arc_dir(item, used: set[str]) -> str:
    """Папка песни в архиве — ``<A>/<A - T>`` (как в хранилище); повтор — `` (2)``, `` (3)``…"""
    base = item.rel_dir.strip("/") or naming.base_name(item.artist, item.title)
    name, n = base, 1
    while name.casefold() in used:
        n += 1
        name = f"{base} ({n})"
    used.add(name.casefold())
    return name


@router.post("/songs/zip", summary="Несколько песен одним .zip (потоком)")
def bulk_zip(request: Request, song_ids: str = Form("")):
    """Форма ``song_ids`` через запятую → ``Песни (N).zip``; что не вошло — в ``НЕ ВОШЛО.txt``."""
    ctx = ctx_of(request)
    ids = _song_ids(song_ids.split(","), MAX_ZIP_SONGS)

    def body():
        sink = _ZipSink()
        missed: list[str] = []
        down: dict[str, str] = {}  # недоступные хранилища: id → причина (не ждать каждую песню)
        used: set[str] = set()
        with zipfile.ZipFile(sink, "w") as zf:
            for song_id in ids:
                item = _find(ctx, song_id)
                if item is None:
                    missed.append(f"{song_id}: {NOT_FOUND}")
                    continue
                if item.target_id in down:
                    missed.append(f"{_title(item)}: {down[item.target_id]}")
                    continue
                try:
                    storage = ctx.storage(item.target_id)
                    files = _song_files(storage, item.rel_dir)
                except StorageNotFound:
                    files = []
                except StorageError as e:
                    ctx.mark_output_error(e, item.target_id)
                    down[item.target_id] = f"хранилище недоступно: {e}"
                    missed.append(f"{_title(item)}: {down[item.target_id]}")
                    continue
                if not files:
                    missed.append(f"{_title(item)}: папка песни пуста или не найдена")
                    continue
                folder = _arc_dir(item, used)
                for sub, entry in files:
                    try:
                        f = storage.open_read(f"{item.rel_dir}/{sub}")
                    except Exception as e:  # noqa: BLE001 — файл не вошёл, остальные пишутся
                        log.error("общий zip: не удалось прочитать «%s/%s»: %s", item.rel_dir, sub, e)
                        missed.append(f"{_title(item)}: файл «{sub}» не прочитан: {e}")
                        continue
                    info = zipfile.ZipInfo(f"{folder}/{sub}", _zip_time(entry.mtime))
                    info.compress_type = (zipfile.ZIP_DEFLATED if sub.lower().endswith(".txt")
                                          else zipfile.ZIP_STORED)
                    info.file_size = entry.size
                    with f, zf.open(info, "w") as out:
                        while True:
                            try:
                                chunk = f.read(1 << 16)
                            except Exception as e:  # noqa: BLE001 — запись файла закрывается как есть
                                log.error("общий zip: сбой чтения «%s/%s»: %s", item.rel_dir, sub, e)
                                missed.append(f"{_title(item)}: файл «{sub}» прочитан не полностью: {e}")
                                break
                            if not chunk:
                                break
                            out.write(chunk)
                            if sink.parts:
                                yield sink.take()
                    yield sink.take()
            if missed:
                text = "Эти песни (или файлы) не вошли в архив:\n\n" + "\n".join(missed) + "\n"
                zf.writestr(NOT_INCLUDED_NAME, text.encode("utf-8-sig"))
        yield sink.take()

    name = f"Песни ({len(ids)}).zip"
    disposition = f"attachment; filename=\"songs-{len(ids)}.zip\"; filename*=UTF-8''{quote(name)}"
    return StreamingResponse(body(), media_type="application/zip",
                             headers={"Content-Disposition": disposition})


# --------------------------------------------------------------------------- удаление


class BulkSongsIn(BaseModel):
    song_ids: list[str]


def _trash_one(ctx: AppContext, item) -> None:
    """Песню — в корзину (как ``DELETE /api/songs/{id}``); сбой — ``ApiError`` с причиной."""
    try:
        ctx.trash.move_to_trash(ctx.storage(item.target_id), item.rel_dir, reason="удалено из веба")
    except StorageNotFound as e:
        status = ctx.output_status(fresh=True, target_id=item.target_id)
        raise ApiError(404 if status["ok"] else 503, str(e) if status["ok"] else status["error"]) from None
    except StorageError as e:
        ctx.mark_output_error(e, item.target_id)
        raise ApiError(503, f"Папка результата недоступна: {e}") from None
    except TrashError as e:
        status = ctx.output_status(fresh=True, target_id=item.target_id)
        raise ApiError(409 if status["ok"] else 503, str(e) if status["ok"] else status["error"]) from None
    ctx.library.remove(item.target_id, item.rel_dir)


@router.post("/songs/delete", summary="Несколько песен — в корзину")
def bulk_delete(body: BulkSongsIn, request: Request):
    """Только в корзину; недоступное хранилище — ошибка у его песен, остальные удаляются."""
    ctx = ctx_of(request)
    ids = _song_ids(body.song_ids)
    removed, errors = [], []
    down: dict[str, str] = {}  # хранилище ответило 503 — его остальные песни не трогаем
    for song_id in ids:
        item = _find(ctx, song_id)
        if item is None:
            errors.append({"song_id": song_id, "detail": NOT_FOUND})
            continue
        if item.target_id in down:
            errors.append({"song_id": song_id, "detail": down[item.target_id]})
            continue
        try:
            _trash_one(ctx, item)
        except ApiError as e:
            if e.status == 503:
                down[item.target_id] = e.detail
            errors.append({"song_id": song_id, "detail": e.detail})
            continue
        removed.append(song_id)
    return {"removed": removed, "errors": errors}


# --------------------------------------------------------------------------- минусовка


class BulkInstrumentalIn(BaseModel):
    song_ids: list[str]
    replace: bool = False


@router.post("/jobs/instrumental/bulk", status_code=201, summary="Минусовка нескольким песням")
def bulk_instrumental(body: BulkInstrumentalIn, request: Request):
    """Задание ``instrumental`` на каждую подходящую песню; неподходящие — в ``skipped`` с причиной."""
    ctx = ctx_of(request)
    ids = _song_ids(body.song_ids)
    active = {j.song_id for j in ctx.jobs.active("instrumental") if j.song_id}
    queued, skipped, errors = [], [], []
    for song_id in ids:
        item = _find(ctx, song_id)
        if item is None:
            errors.append({"song_id": song_id, "detail": NOT_FOUND})
            continue
        reason = (SKIP_QUEUED if item.song_id in active
                  else SKIP_NO_AUDIO if not item.audio
                  else SKIP_HAS_INSTRUMENTAL if item.instrumental and not body.replace
                  else None)
        if reason:
            skipped.append({"song_id": song_id, "reason": reason})
            continue
        params = instrumental_params(rel_dir=item.rel_dir, txt_name=item.txt_name, audio=item.audio,
                                     instrumental=item.instrumental, target_id=item.target_id)
        job = ctx.jobs.enqueue("instrumental",
                               {"artist": item.artist, "title": item.title, "song_id": item.song_id}, params)
        active.add(item.song_id)
        queued.append(job.id)
    return {"queued": queued, "skipped": skipped, "errors": errors}
