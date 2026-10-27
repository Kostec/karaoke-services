"""Поиск обложек в сети (истории 19–22): iTunes Search API, Deezer и MusicBrainz + Cover Art Archive.

Ключи не нужны ни одному сервису. Запросы идут параллельно, у каждого свой таймаут; сбой одного
сервиса остальным не мешает. Исходящий HTTP — только через ``karaoke_core.http.Http``.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from karaoke_core.http import Http, HttpError

__all__ = ["CoverHit", "CoversUnavailable", "SOURCES", "MAX_HITS", "search_covers", "search_report"]

ITUNES_URL = "https://itunes.apple.com/search"
DEEZER_URL = "https://api.deezer.com/search"
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/release"
COVER_ART_URL = "https://coverartarchive.org/release/"
# MusicBrainz отклоняет запросы без осмысленного User-Agent.
USER_AGENT = "karaoke-services/1.0"

SOURCES = ("itunes", "deezer", "musicbrainz")
MAX_HITS = 12          # вариантов в ответе
PER_SOURCE = 8         # запрашивается у каждого сервиса
TIMEOUT_S = 8          # свой таймаут у каждого сервиса
MAX_BYTES = 2 * 2**20

UNAVAILABLE = "Сервисы обложек недоступны, попробуйте позже"


class CoversUnavailable(Exception):
    """Ни один сервис не ответил."""


@dataclass(frozen=True)
class CoverHit:
    source: str           # itunes | deezer | musicbrainz
    url: str              # полная картинка
    thumb: str            # превью
    album: str
    artist: str
    title: str
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _json(http: Http, url: str, params: dict, headers: dict | None = None):
    resp = http.request("GET", url, params=params, headers=headers, timeout=TIMEOUT_S, max_bytes=MAX_BYTES)
    return json.loads(resp.body.decode("utf-8"))


def _text(value) -> str:
    return str(value or "").strip()


def _itunes(http: Http, artist: str, title: str) -> list[CoverHit]:
    term = " ".join(x for x in (artist, title) if x)
    data = _json(http, ITUNES_URL, {"term": term, "media": "music", "entity": "song", "limit": PER_SOURCE * 2})
    hits = []
    for r in data.get("results") or []:
        art = _text(r.get("artworkUrl100"))
        if not art or "100x100" not in art:
            continue
        hits.append(CoverHit("itunes", art.replace("100x100", "1000x1000"), art.replace("100x100", "250x250"),
                             _text(r.get("collectionName")), _text(r.get("artistName")),
                             _text(r.get("trackName")), 1000, 1000))
    return hits


def _deezer(http: Http, artist: str, title: str) -> list[CoverHit]:
    q = " ".join(x for x in (artist, title) if x)
    data = _json(http, DEEZER_URL, {"q": q, "limit": PER_SOURCE * 2})
    hits = []
    for r in data.get("data") or []:
        album = r.get("album") or {}
        url = _text(album.get("cover_xl"))
        if not url:
            continue
        hits.append(CoverHit("deezer", url, _text(album.get("cover_medium")) or url, _text(album.get("title")),
                             _text((r.get("artist") or {}).get("name")), _text(r.get("title")), 1000, 1000))
    return hits


def _lucene(value: str) -> str:
    """Значение поля запроса MusicBrainz (Lucene) в кавычках."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _musicbrainz(http: Http, artist: str, title: str) -> list[CoverHit]:
    parts = []
    if artist:
        parts.append(f"artist:{_lucene(artist)}")
    if title:
        parts.append(f"release:{_lucene(title)}")
    data = _json(http, MUSICBRAINZ_URL, {"query": " AND ".join(parts), "fmt": "json", "limit": PER_SOURCE},
                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    hits = []
    for r in data.get("releases") or []:
        rid = _text(r.get("id"))
        if not rid:
            continue
        credit = r.get("artist-credit") or []
        name = " ".join(_text(c.get("name") or (c.get("artist") or {}).get("name")) for c in credit
                        if isinstance(c, dict)).strip()
        base = f"{COVER_ART_URL}{rid}/"
        hits.append(CoverHit("musicbrainz", base + "front-500", base + "front-250", _text(r.get("title")),
                             name, _text(r.get("title")), 500, 500))
    return hits


_PROVIDERS = {"itunes": _itunes, "deezer": _deezer, "musicbrainz": _musicbrainz}


def _merge(results: dict[str, list[CoverHit]]) -> list[CoverHit]:
    """По очереди из каждого сервиса (первые варианты — от разных), без повторов адреса, до ``MAX_HITS``."""
    lists = [results.get(s) or [] for s in SOURCES]
    seen, out = set(), []
    i = 0
    while len(out) < MAX_HITS and any(i < len(lst) for lst in lists):
        for lst in lists:
            if i < len(lst) and lst[i].url not in seen and len(out) < MAX_HITS:
                seen.add(lst[i].url)
                out.append(lst[i])
        i += 1
    return out


def _dedup(hits: list[CoverHit]) -> list[CoverHit]:
    seen, out = set(), []
    for h in hits:
        if h.url not in seen:
            seen.add(h.url)
            out.append(h)
    return out


def search_report(http: Http, artist: str, title: str) -> tuple[list[CoverHit], list[str]]:
    """Варианты обложек и список упавших сервисов; упали все — ``CoversUnavailable``."""
    artist, title = _text(artist), _text(title)
    results: dict[str, list[CoverHit]] = {}
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=len(_PROVIDERS)) as pool:
        futures = {name: pool.submit(fn, http, artist, title) for name, fn in _PROVIDERS.items()}
        for name in SOURCES:
            try:
                results[name] = _dedup(futures[name].result())
            except (HttpError, ValueError, TypeError, AttributeError, KeyError):
                failed.append(name)
    if len(failed) == len(SOURCES):
        raise CoversUnavailable(UNAVAILABLE)
    return _merge(results), failed


def search_covers(http: Http, artist: str, title: str) -> list[CoverHit]:
    """До ``MAX_HITS`` вариантов обложки по исполнителю и названию; упали все — ``CoversUnavailable``."""
    return search_report(http, artist, title)[0]
