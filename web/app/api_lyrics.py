"""Поиск текста песни для формы: ``GET /api/lyrics/search?artist=&title=&source=``."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .api_jobs import ctx_of
from .context import ApiError
from .lyrics import LyricsUnavailable, make_providers, search_all

router = APIRouter(prefix="/api/lyrics", tags=["Тексты"])


@router.get("/search", summary="Найти текст песни (LRCLIB, NetEase, Genius)")
def search(request: Request, artist: str = "", title: str = "", source: str = ""):
    artist, title, source = artist.strip(), title.strip(), source.strip()
    if not artist or not title:
        raise ApiError(400, "Укажите исполнителя и название", field="artist" if not artist else "title")
    providers = make_providers(ctx_of(request).http)
    if source:
        provider = providers.get(source)
        if provider is None:
            raise ApiError(400, "Неизвестный источник текстов", field="source")
        try:
            hits = provider.search(artist, title)
        except LyricsUnavailable:
            raise ApiError(503, f"{provider.name} не ответил") from None
        return {"items": [h.to_dict() for h in hits],
                "sources": [{"id": provider.id, "name": provider.name, "ok": True}]}
    hits, sources = search_all(providers, artist, title)
    if not any(s["ok"] for s in sources):
        raise ApiError(503, "Сервисы текстов недоступны, попробуйте позже")
    return {"items": [h.to_dict() for h in hits], "sources": sources}
