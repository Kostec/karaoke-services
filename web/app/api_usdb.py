"""Поиск песен в usdb: ``GET /api/usdb/search``. Учётка — в «Настройках» (``/api/settings/usdb``)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from karaoke_core.storage import StorageError

from .api_jobs import ctx_of
from .context import ApiError, AppContext
from .usdb import UsdbAuthError, UsdbError, UsdbNotFound

DEFAULT_LANGUAGE = "Russian"

router = APIRouter(prefix="/api/usdb", tags=["usdb"])


def usdb_api_error(e: UsdbError) -> ApiError:
    """Ошибка клиента usdb → ответ API (текст без пароля)."""
    if isinstance(e, UsdbAuthError):
        return ApiError(400, "usdb не принял логин или пароль", field="password")
    if isinstance(e, UsdbNotFound):
        return ApiError(404, "Песня в usdb не найдена")
    return ApiError(503, "usdb недоступен, попробуйте позже")


def _existing(ctx: AppContext, artist: str, title: str) -> str | None:
    try:
        item = ctx.find_by_name(artist, title)
    except StorageError:
        return None
    return item.song_id if item else None


@router.get("/search", summary="Найти песни в usdb (по 50, по рейтингу)")
def search(request: Request, artist: str = "", title: str = "", language: str | None = None,
           start: int = 0):
    ctx = ctx_of(request)
    client = ctx.usdb()
    lang = DEFAULT_LANGUAGE if language is None else language.strip()
    try:
        page = client.search(artist.strip(), title.strip(), lang, max(0, start))
    except UsdbError as e:
        raise usdb_api_error(e) from None
    return {"items": [{**h.to_dict(), "existing_song_id": _existing(ctx, h.artist, h.title)}
                      for h in page.items],
            "has_more": page.has_more}
