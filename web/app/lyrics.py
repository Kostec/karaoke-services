"""Поиск текстов песен. Поставщик — за интерфейсом ``LyricsProvider``; сейчас один — LRCLIB.

LRCLIB (https://lrclib.net) — бесплатный, без ключа. Сначала ``track_name+artist_name``,
при пустом результате — ``q=<исполнитель название>``. Инструменталы и записи без текста
отбрасываются; если есть только LRC — метки времени срезаются.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Protocol

from karaoke_core.http import HttpError

LRCLIB_SEARCH = "https://lrclib.net/api/search"
MAX_HITS = 10
TIMEOUT_S = 10

_TIME_TAG = re.compile(r"\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]")
_META_LINE = re.compile(r"^\s*\[[a-zA-Z#]+:[^\]]*\]\s*$")
_BLANKS = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class LyricsHit:
    id: str | int
    artist: str
    title: str
    album: str
    duration: float | None
    text: str
    synced: str | None = None  # LRC с метками строк (syncedLyrics) или None

    def to_dict(self) -> dict:
        return asdict(self)


class LyricsUnavailable(Exception):
    """Сервис текстов недоступен или ответил непонятно."""


class LyricsProvider(Protocol):
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


class LrclibProvider:
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
        return LyricsHit(id=r.get("id"), artist=str(r.get("artistName") or ""), title=str(r.get("trackName") or ""),
                         album=str(r.get("albumName") or ""),
                         duration=float(duration) if isinstance(duration, (int, float)) else None,
                         text=text, synced=synced_lrc(r.get("syncedLyrics")))


def synced_lrc(raw) -> str | None:
    """syncedLyrics → LRC с переводами строк ``\\n``; без меток времени — None."""
    if not isinstance(raw, str) or not _TIME_TAG.search(raw):
        return None
    return clean_text(raw)
