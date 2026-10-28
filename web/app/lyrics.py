"""Поиск текстов песен. Поставщики — за интерфейсом ``LyricsProvider``: LRCLIB, NetEase, Genius.

LRCLIB (https://lrclib.net) — бесплатный, без ключа. Сначала ``track_name+artist_name``,
при пустом результате — ``q=<исполнитель название>``. Инструменталы и записи без текста
отбрасываются; если есть только LRC — метки времени срезаются.
NetEase (music.163.com) — без ключа, бывают LRC, в т.ч. у русских песен. Genius — только ссылки:
страницы текстов серверу недоступны (проверка Cloudflare), обходить её не пытаемся.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Protocol

from karaoke_core.http import HttpError

LRCLIB_SEARCH = "https://lrclib.net/api/search"
MAX_HITS = 10
TIMEOUT_S = 10
NETEASE_SEARCH = "https://music.163.com/api/search/get"
NETEASE_LYRIC = "https://music.163.com/api/song/lyric"
NETEASE_HITS = 5
GENIUS_SEARCH = "https://genius.com/api/search/song"
GENIUS_HITS = 5
GENIUS_TIMEOUT_S = 15  # Genius отвечает медленно (~12 с)
PROVIDERS = ("lrclib", "netease", "genius")

_TIME_TAG = re.compile(r"\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]")
_META_LINE = re.compile(r"^\s*\[[a-zA-Z#]+:[^\]]*\]\s*$")
_BLANKS = re.compile(r"\n{3,}")
# Служебные строки авторов в текстах NetEase: «[00:00.00] 作词 : Имя».
_CREDIT_LINE = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)*(?:作词|作詞|作曲|编曲|編曲|制作人|製作人|监制|混音|母带|录音)\s*[:：]")
_INSTRUMENTAL_MARK = "纯音乐"


@dataclass(frozen=True)
class LyricsHit:
    id: str | int  # "<источник>:<id>", уникален среди источников
    artist: str
    title: str
    album: str | None
    duration: float | None
    text: str  # у Genius пусто: текст отдаётся только браузеру
    synced: str | None = None  # LRC с метками строк (syncedLyrics) или None
    source: str = "lrclib"
    url: str | None = None  # страница варианта (Genius)

    def to_dict(self) -> dict:
        return asdict(self)


class LyricsUnavailable(Exception):
    """Сервис текстов недоступен или ответил непонятно."""


class LyricsProvider(Protocol):
    id: str
    name: str

    def search(self, artist: str, title: str) -> list[LyricsHit]: ...


def clean_text(text: str) -> str:
    """Переводы строк → ``\\n``, без пробелов по краям строк и пустых строк по краям текста."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip("\n").strip()


def strip_lrc(text: str) -> str:
    """LRC → чистый текст: строки метаданных ``[ar:…]`` убираются, метки ``[mm:ss.xx]`` срезаются."""
    out = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _META_LINE.match(line) and not _TIME_TAG.search(line):
            continue
        out.append(_TIME_TAG.sub("", line).strip())
    return clean_text("\n".join(out))


def synced_lrc(raw) -> str | None:
    """syncedLyrics → LRC с переводами строк ``\\n``; без меток времени — None."""
    if not isinstance(raw, str) or not _TIME_TAG.search(raw):
        return None
    return clean_text(raw)


def _json_body(resp) -> object:
    try:
        return json.loads(resp.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise LyricsUnavailable(str(e)) from None


class LrclibProvider:
    id = "lrclib"
    name = "LRCLIB"

    def __init__(self, http):
        self.http = http

    def search(self, artist: str, title: str) -> list[LyricsHit]:
        hits = self._query({"track_name": title, "artist_name": artist})
        if not hits:
            hits = self._query({"q": f"{artist} {title}".strip()})
        return hits[:MAX_HITS]

    def _query(self, params: dict) -> list[LyricsHit]:
        try:
            resp = self.http.request("GET", LRCLIB_SEARCH, params=params, timeout=TIMEOUT_S,
                                     headers={"Accept": "application/json"})
            raw = json.loads(resp.body.decode("utf-8"))
        except (HttpError, ValueError, UnicodeDecodeError) as e:
            raise LyricsUnavailable(str(e)) from None
        if not isinstance(raw, list):
            raise LyricsUnavailable("LRCLIB вернул не список")
        return [h for h in (self._hit(r) for r in raw if isinstance(r, dict)) if h is not None]

    @staticmethod
    def _hit(r: dict) -> LyricsHit | None:
        if r.get("instrumental"):
            return None
        text = clean_text(r.get("plainLyrics") or "")
        if not text:
            text = strip_lrc(r.get("syncedLyrics") or "")
        if not text:
            return None
        duration = r.get("duration")
        return LyricsHit(id=f"lrclib:{r.get('id')}", artist=str(r.get("artistName") or ""),
                         title=str(r.get("trackName") or ""), album=str(r.get("albumName") or ""),
                         duration=float(duration) if isinstance(duration, (int, float)) else None,
                         text=text, synced=synced_lrc(r.get("syncedLyrics")), source="lrclib")


class NeteaseProvider:
    """NetEase Cloud Music: поиск ``api/search/get`` + ``api/song/lyric`` (без ключа, бывают LRC)."""

    id = "netease"
    name = "NetEase"

    def __init__(self, http):
        self.http = http

    def search(self, artist: str, title: str) -> list[LyricsHit]:
        try:
            resp = self.http.request("GET", NETEASE_SEARCH,
                                     params={"s": f"{artist} {title}".strip(), "type": 1, "limit": 10},
                                     timeout=TIMEOUT_S, headers={"Accept": "application/json"})
        except HttpError as e:
            raise LyricsUnavailable(str(e)) from None
        raw = _json_body(resp)
        result = raw.get("result") if isinstance(raw, dict) else None
        songs = result.get("songs") if isinstance(result, dict) else None
        if not isinstance(songs, list):
            return []
        hits: list[LyricsHit] = []
        tried = failures = 0
        for song in songs:
            if len(hits) >= NETEASE_HITS:
                break
            if not isinstance(song, dict) or song.get("id") is None:
                continue
            tried += 1
            try:
                hit = self._hit(song)
            except LyricsUnavailable:
                failures += 1
                continue
            if hit is not None:
                hits.append(hit)
        if tried and failures == tried:
            raise LyricsUnavailable("NetEase не отдал тексты")
        return hits

    def _hit(self, song: dict) -> LyricsHit | None:
        try:
            resp = self.http.request("GET", NETEASE_LYRIC, params={"id": song["id"], "lv": 1}, timeout=TIMEOUT_S,
                                     headers={"Accept": "application/json"})
        except HttpError as e:
            raise LyricsUnavailable(str(e)) from None
        raw = _json_body(resp)
        lrc = raw.get("lrc") if isinstance(raw, dict) else None
        body = lrc.get("lyric") if isinstance(lrc, dict) else None
        if not isinstance(body, str) or _INSTRUMENTAL_MARK in body:
            return None
        lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        kept = "\n".join(ln for ln in lines if not _CREDIT_LINE.match(ln))
        text = strip_lrc(kept)
        if not text:
            return None
        duration = song.get("duration")
        album = song.get("album")
        artists = song.get("artists")
        names = ([str(a["name"]) for a in artists if isinstance(a, dict) and a.get("name")]
                 if isinstance(artists, list) else [])
        return LyricsHit(id=f"netease:{song['id']}", artist=", ".join(names), title=str(song.get("name") or ""),
                         album=str(album.get("name") or "") if isinstance(album, dict) else "",
                         duration=duration / 1000 if isinstance(duration, (int, float)) else None,
                         text=text, synced=synced_lrc(kept), source="netease")


class GeniusProvider:
    """Genius: поиск без ключа; страницы текстов серверу недоступны (Cloudflare) — только ссылки."""

    id = "genius"
    name = "Genius"

    def __init__(self, http):
        self.http = http

    def search(self, artist: str, title: str) -> list[LyricsHit]:
        try:
            resp = self.http.request("GET", GENIUS_SEARCH, params={"q": f"{artist} {title}".strip()},
                                     timeout=GENIUS_TIMEOUT_S, headers={"Accept": "application/json"})
        except HttpError as e:
            raise LyricsUnavailable(str(e)) from None
        raw = _json_body(resp)
        body = raw.get("response") if isinstance(raw, dict) else None
        sections = body.get("sections") if isinstance(body, dict) else None
        if not isinstance(sections, list):
            raise LyricsUnavailable("Genius вернул неожиданный ответ")
        hits: list[LyricsHit] = []
        for section in sections:
            if not isinstance(section, dict) or section.get("type") != "song":
                continue
            for item in section.get("hits") or []:
                r = item.get("result") if isinstance(item, dict) else None
                if not isinstance(r, dict) or not r.get("url") or r.get("id") is None:
                    continue
                hits.append(LyricsHit(id=f"genius:{r['id']}", artist=str(r.get("artist_names") or ""),
                                      title=str(r.get("title") or ""), album=None, duration=None, text="",
                                      source="genius", url=str(r["url"])))
                if len(hits) >= GENIUS_HITS:
                    return hits
        return hits


def make_providers(http) -> dict[str, LyricsProvider]:
    """Источники текстов по id, в порядке показа."""
    return {"lrclib": LrclibProvider(http), "netease": NeteaseProvider(http), "genius": GeniusProvider(http)}


def search_all(providers: dict, artist: str, title: str) -> tuple[list[LyricsHit], list[dict]]:
    """Спросить все источники параллельно → (варианты, статус каждого).

    Сбой одного источника не роняет остальные. Порядок: синхронные первыми, затем порядок источников."""
    def one(p):
        try:
            return p.search(artist, title), None
        except LyricsUnavailable as e:
            return [], str(e) or "нет ответа"

    items = list(providers.values())
    with ThreadPoolExecutor(max_workers=max(len(items), 1)) as pool:
        results = list(pool.map(one, items))
    hits: list[LyricsHit] = []
    sources: list[dict] = []
    for p, (found, error) in zip(items, results):
        hits.extend(found)
        sources.append({"id": p.id, "name": p.name, "ok": error is None, **({"error": error} if error else {})})
    hits.sort(key=lambda h: h.synced is None)  # sort стабилен: внутри групп порядок источников
    return hits, sources
