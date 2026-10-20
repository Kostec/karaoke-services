"""Поиск текста песни для формы: ``GET /api/lyrics/search?artist=&title=``."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .api_jobs import ctx_of
from .context import ApiError
from .lyrics import LrclibProvider, LyricsUnavailable

router = APIRouter(prefix="/api/lyrics", tags=["Тексты"])


@router.get("/search", summary="Найти текст песни (LRCLIB): до 10 вариантов")
def search(request: Request, artist: str = "", title: str = ""):
    artist, title = artist.strip(), title.strip()
    if not artist or not title:
        raise ApiError(400, "Укажите исполнителя и название", field="artist" if not artist else "title")
    try:
        hits = LrclibProvider(ctx_of(request).http).search(artist, title)
    except LyricsUnavailable:
        raise ApiError(503, "Сервис текстов недоступен, попробуйте позже") from None
    return {"items": [h.to_dict() for h in hits]}
