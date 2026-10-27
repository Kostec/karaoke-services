"""Обложка и фон песни (истории 12–24): задание ``artwork`` и поиск обложек в сети.

``POST /api/jobs/artwork`` — свой файл, ссылка на картинку (качает web при постановке) или
``remove``; ``GET /api/covers/search`` — варианты iTunes, Deezer и MusicBrainz.
Роутер ``router`` подключается в ``main.py`` раньше ``jobs_router``.
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, File, Form, Query, Request, UploadFile

from karaoke_core import musiclink
from karaoke_core.http import HttpError

from . import covers
from .api_jobs import MB, Staging, cover_ext_of, ctx_of, queue_duplicate
from .context import ApiError, AppContext
from .params import MAX_COVER_MB

KINDS = ("cover", "background")
INPUT_IMAGE_STEM = "image"  # вход задания: jobs/<id>/in/image.<ext>
NOT_IMAGE = "Это не картинка (нужны jpg, png или webp)"
CHUNK = 1024 * 1024

router = APIRouter(prefix="/api/jobs", tags=["Задания"])
covers_router = APIRouter(prefix="/api/covers", tags=["Обложки"])


@covers_router.get("/search", summary="Обложки iTunes, Deezer и MusicBrainz",
                   description="До 12 вариантов; сбой одного сервиса — в `failed`, все упали — 503.")
def search(request: Request, artist: str = Query(""), title: str = Query("")):
    if not artist.strip() and not title.strip():
        raise ApiError(400, "Укажите исполнителя или название", field="title")
    try:
        hits, failed = covers.search_report(ctx_of(request).http, artist, title)
    except covers.CoversUnavailable:
        raise ApiError(503, covers.UNAVAILABLE) from None
    return {"items": [h.to_dict() for h in hits], "failed": failed}


# --------------------------------------------------------------------------- задание artwork

def _too_big(field: str, what: str = "Файл") -> ApiError:
    return ApiError(400, f"{what} больше {MAX_COVER_MB} МБ", field=field)


def _stage_file(upload: UploadFile, staging: Staging) -> None:
    """Свой файл → ``in/image.<ext>``: только jpg/png/webp по содержимому, до ``MAX_COVER_MB``."""
    limit = MAX_COVER_MB * MB
    tmp = staging.dir / ".image"
    size = 0
    with open(tmp, "wb") as out:
        while chunk := upload.file.read(CHUNK):
            size += len(chunk)
            if size > limit:
                raise _too_big("image")
            out.write(chunk)
    with open(tmp, "rb") as f:
        ext = cover_ext_of(f.read(16))
    if ext is None:
        raise ApiError(400, NOT_IMAGE, field="image")
    tmp.replace(staging.path("image", f"{INPUT_IMAGE_STEM}.{ext}"))


NEED_IMAGE_URL = "Нужна ссылка http(s) на картинку"


def _public_url(url: str) -> str:
    try:  # битая ссылка («http://[::1», порт вне 0…65535) — ValueError из urllib
        parts = urllib.parse.urlsplit(url)
        host, _port = parts.hostname, parts.port
    except ValueError:
        raise ApiError(400, NEED_IMAGE_URL, field="url") from None
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise ApiError(400, NEED_IMAGE_URL, field="url")
    try:
        musiclink.check_public_host(host)
    except musiclink.MusicLinkError as e:
        raise ApiError(400, str(e), field="url") from None
    return url


def _stage_url(ctx: AppContext, url: str, staging: Staging) -> None:
    """Картинка по ссылке качается сразу (как ``cover_url`` у generate) → ``in/image.<ext>``."""
    tmp = staging.dir / ".image"
    try:
        ctx.http.download(url, tmp, max_bytes=MAX_COVER_MB * MB, timeout=30)
    except HttpError as e:
        if e.too_large:
            raise _too_big("url", "Картинка по ссылке") from None
        raise ApiError(400, f"Не удалось скачать картинку: {e}", field="url") from None
    except OSError as e:
        raise ApiError(400, f"Не удалось скачать картинку: {e}", field="url") from None
    if tmp.stat().st_size > MAX_COVER_MB * MB:
        raise _too_big("url", "Картинка по ссылке")
    with open(tmp, "rb") as f:
        ext = cover_ext_of(f.read(16))
    if ext is None:
        raise ApiError(400, "По ссылке не картинка (нужны jpg, png или webp)", field="url")
    tmp.replace(staging.path("image", f"{INPUT_IMAGE_STEM}.{ext}"))


@router.post("/artwork", status_code=201, summary="Обложка или фон песни: файл, ссылка или убрать",
             description="`kind` — `cover` или `background`; ровно один источник: файл `image` "
                         "(jpg/png/webp), `url` (картинку качает web) или `remove`. Задание без GPU.")
def artwork(request: Request,
            song_id: str = Form(...),
            kind: str = Form(""),
            image: UploadFile | None = File(None),
            url: str | None = Form(None),
            remove: bool = Form(False)):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    kind = (kind or "").strip()
    if kind not in KINDS:
        raise ApiError(400, "Нужно указать, что ставить: обложка или фон", field="kind")
    has_file = image is not None and bool(image.filename)
    link = (url or "").strip()
    if has_file + bool(link) + bool(remove) > 1:
        raise ApiError(400, "Нужно что-то одно: файл, ссылка или убрать", field="image")
    if not (has_file or link or remove):
        raise ApiError(400, "Загрузите картинку или вставьте ссылку", field="image")
    if link:
        link = _public_url(link)
    queue_duplicate(ctx, "artwork", song_id=item.song_id)
    params: dict = {"rel_dir": item.rel_dir, "txt_name": item.txt_name, "target_id": item.target_id,
                    "kind": kind}
    if remove:
        params["remove"] = True
    staging = Staging(ctx, item.rel_dir)
    try:
        if has_file:
            _stage_file(image, staging)
        elif link:
            _stage_url(ctx, link, staging)
        (staging.dir / ".image").unlink(missing_ok=True)
    except BaseException:
        staging.discard()
        raise
    ref = {"artist": item.artist, "title": item.title, "song_id": item.song_id}
    return staging.enqueue("artwork", ref, params).to_dict()
