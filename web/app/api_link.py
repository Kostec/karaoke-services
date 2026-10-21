"""Ссылки на музыку для генерации: ``POST /api/link/inspect`` — метаданные трека/альбома/плейлиста.

Яндекс Музыка — через ``AppContext.yandex()`` (токен из «Настроек»), остальное — yt-dlp
(``YTDLP_CMD``). Звук здесь не качается: это делает воркер по ``audio_url`` задания generate.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from karaoke_core import musiclink

from .api_jobs import ctx_of, is_video_link
from .context import AppContext, link_api_error

router = APIRouter(prefix="/api/link", tags=["Ссылки"])


class LinkIn(BaseModel):
    url: str = ""


def link_info(ctx: AppContext, url: str) -> musiclink.LinkInfo:
    """Разобрать ссылку и получить метаданные; ошибки — ``ApiError``."""
    try:
        link = musiclink.classify(url)
        if musiclink.is_yandex(link):
            client = ctx.yandex()
            return client.info(link)
        return musiclink.ytdlp_info(link.url, ctx.ytdlp_cmd())
    except musiclink.MusicLinkError as e:
        raise link_api_error(e) from None


@router.post("/inspect", summary="Метаданные ссылки на музыку (YouTube, VK-видео, Яндекс Музыка…)")
def inspect(body: LinkIn, request: Request):
    ctx = ctx_of(request)
    info = link_info(ctx, body.url)
    return {"kind": info.kind, "title": info.title,
            "tracks": [{"url": t.url, "artist": t.artist, "title": t.title, "duration": t.duration,
                        "thumbnail": t.thumbnail,
                        "existing_song_id": ctx.existing_song_id(t.artist, t.title)
                        if t.artist and t.title else None,
                        "video": is_video_link(t.url)}
                       for t in info.tracks]}
