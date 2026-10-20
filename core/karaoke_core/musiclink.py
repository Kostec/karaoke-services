"""Ссылки на музыку: разбор, метаданные (yt-dlp, Яндекс Музыка) и загрузка трека Яндекса.

``classify`` решает, кто обслуживает ссылку: Яндекс Музыка (трек, альбом, плейлист — через
библиотеку ``yandex-music`` и OAuth-токен пользователя) или yt-dlp (YouTube, видео VK, RuTube,
SoundCloud…). Аудиозаписи ВКонтакте не поддерживаются — понятная ошибка.

CLI для воркера (отменяемый подпроцесс)::

    python -m karaoke_core.musiclink download <url> <dest.mp3>

Токен — только из переменной окружения ``YANDEX_MUSIC_TOKEN`` (не в argv и не в лог).
Код возврата ≠ 0 и последняя строка stderr — русский текст ошибки.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = [
    "MusicLinkError", "LinkKind", "LinkTrack", "LinkInfo", "classify", "ytdlp_info",
    "YandexMusic", "is_yandex", "main", "check_public_host", "RESOLVER",
    "YANDEX_KINDS", "MSG_NEED_LOGIN", "MSG_REJECTED", "MSG_NO_RIGHTS", "MSG_UNAVAILABLE",
]

YANDEX_KINDS = ("yandex_track", "yandex_album", "yandex_playlist")

MSG_NOT_HTTP = "Нужна ссылка вида https://…"
MSG_VK_AUDIO = ("Аудиозаписи ВКонтакте не поддерживаются: VK не отдаёт их сторонним программам. "
                "Видео и клипы VK — можно")
MSG_NEED_LOGIN = "Впишите токен Яндекс Музыки в Настройках"
MSG_REJECTED = "Яндекс Музыка не приняла токен"
MSG_NO_RIGHTS = "Яндекс Музыка не отдала трек: нужна подписка Плюс (и, возможно, российский IP)"
MSG_UNAVAILABLE = "Яндекс Музыка недоступна, попробуйте позже"
MSG_NOT_FOUND = "Яндекс Музыка не нашла ничего по этой ссылке"
MSG_YTDLP = "Не удалось получить данные по ссылке: "
MSG_HOME_NETWORK = "Ссылки на адреса домашней сети не поддерживаются"


class MusicLinkError(Exception):
    """Ошибка ссылки на музыку; текст — по-русски для пользователя, без токена."""


@dataclass(frozen=True)
class LinkKind:
    kind: str            # "yandex_track" | "yandex_album" | "yandex_playlist" | "ytdlp"
    url: str             # нормализованная ссылка (без utm_* и прочего мусора)
    ids: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LinkTrack:
    url: str                     # ссылка на один трек (её и передают в generate как audio_url)
    artist: str                  # может быть "" — тогда UI подсвечивает
    title: str
    duration: float | None       # секунды
    thumbnail: str | None        # URL обложки


@dataclass(frozen=True)
class LinkInfo:
    kind: str
    title: str
    tracks: list[LinkTrack]


def is_yandex(link: LinkKind) -> bool:
    return link.kind in YANDEX_KINDS


# --------------------------------------------------------------------------- classify

_YANDEX_HOST = re.compile(r"^(?:[a-z0-9-]+\.)*music\.yandex\.(?:ru|com|by|kz)$")
_VK_HOST = re.compile(r"^(?:[a-z0-9-]+\.)*vk\.(?:com|ru)$")
_Y_ALBUM_TRACK = re.compile(r"^/album/(\d+)/track/(\d+)/?$")
_Y_TRACK = re.compile(r"^/track/(\d+)/?$")
_Y_ALBUM = re.compile(r"^/album/(\d+)/?$")
_Y_USER_PLAYLIST = re.compile(r"^/users/([^/]+)/playlists/(\d+)/?$")
_Y_UUID_PLAYLIST = re.compile(r"^/playlists/([A-Za-z0-9._-]+)/?$")
# Параметры-метки из «Поделиться», не влияющие на содержимое ссылки.
_JUNK_PARAMS = {"si", "fbclid", "gclid", "yclid"}


def _is_vk_audio(path: str, query: str) -> bool:
    if re.match(r"^/(?:audios?|music)(?:[-_/\d]|$)", path):
        return True
    return any(k in ("z", "w") and v.startswith("audio") for k, v in parse_qsl(query))


def _clean_query(query: str) -> str:
    kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in _JUNK_PARAMS]
    return urlencode(kept)


def _system_resolve(host: str) -> list[str]:
    """Адреса хоста по DNS; не резолвится — пустой список (пусть дальше скажет yt-dlp)."""
    try:
        return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]
    except (OSError, UnicodeError):
        return []


# Резолвер classify: хост → список IP-строк. Шов для тестов (подменяется в tests/conftest.py).
RESOLVER: Callable[[str], list[str]] = _system_resolve


def _is_home_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified


def check_public_host(host: str, resolver: Callable[[str], list[str]] | None = None) -> None:
    """Защита от SSRF: адреса домашней сети (loopback, частные, link-local, ``.local``) —
    ``MusicLinkError``; и по литералу IP, и по результату DNS."""
    host = (host or "").strip().strip("[]").rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local")) or _is_home_ip(host):
        raise MusicLinkError(MSG_HOME_NETWORK)
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return  # литерал IP уже проверен
    except ValueError:
        pass
    if any(_is_home_ip(a) for a in (resolver or RESOLVER)(host)):
        raise MusicLinkError(MSG_HOME_NETWORK)


_YT_HOST = re.compile(r"^(?:(?:www|m|music)\.)?youtube\.com$")
# Параметры списка у ссылки на одно видео («…watch?v=X&list=Y»): трек — один, список — нет.
_YT_LIST_PARAMS = {"list", "index", "start_radio"}


def _single_video_query(host: str, path: str, query: str) -> str:
    """У ссылки YouTube на одно видео убрать параметры плейлиста."""
    pairs = parse_qsl(query, keep_blank_values=True)
    single = ((_YT_HOST.match(host) and path.rstrip("/") == "/watch" and any(k == "v" and v for k, v in pairs))
              or (host == "youtu.be" and path.strip("/") != ""))
    if not single:
        return query
    return urlencode([(k, v) for k, v in pairs if k not in _YT_LIST_PARAMS])


def classify(url: str, resolver: Callable[[str], list[str]] | None = None) -> LinkKind:
    """Определить, кто обслуживает ссылку; ``MusicLinkError`` — ссылка не годится.
    ``resolver`` — хост → IP (по умолчанию ``RESOLVER``): ссылки в домашнюю сеть отклоняются."""
    raw = (url or "").strip()
    try:
        parts = urlsplit(raw)
        hostname = parts.hostname
    except ValueError:  # «http://[bad/» и подобное
        raise MusicLinkError(MSG_NOT_HTTP) from None
    if parts.scheme.lower() not in ("http", "https") or not hostname:
        raise MusicLinkError(MSG_NOT_HTTP)
    host = hostname.lower()
    check_public_host(host, resolver)
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if _VK_HOST.match(host) and _is_vk_audio(path, parts.query):
        raise MusicLinkError(MSG_VK_AUDIO)
    if _YANDEX_HOST.match(host):
        base = f"https://{host}"
        if m := _Y_ALBUM_TRACK.match(path):
            return LinkKind("yandex_track", f"{base}/album/{m[1]}/track/{m[2]}",
                            {"track": m[2], "album": m[1]})
        if m := _Y_TRACK.match(path):
            return LinkKind("yandex_track", f"{base}/track/{m[1]}", {"track": m[1]})
        if m := _Y_ALBUM.match(path):
            return LinkKind("yandex_album", f"{base}/album/{m[1]}", {"album": m[1]})
        if m := _Y_USER_PLAYLIST.match(path):
            return LinkKind("yandex_playlist", f"{base}/users/{m[1]}/playlists/{m[2]}",
                            {"user": m[1], "kind": m[2]})
        if m := _Y_UUID_PLAYLIST.match(path):
            return LinkKind("yandex_playlist", f"{base}/playlists/{m[1]}", {"uuid": m[1]})
    query = _single_video_query(host, path, _clean_query(parts.query))
    clean = urlunsplit((parts.scheme.lower(), parts.netloc, parts.path, query, ""))
    return LinkKind("ytdlp", clean, {})


# --------------------------------------------------------------------------- yt-dlp

def _strip_topic(name: str) -> str:
    return re.sub(r"\s+-\s+Topic$", "", name.strip())


def _thumbnail(data: dict) -> str | None:
    if isinstance(data.get("thumbnail"), str) and data["thumbnail"]:
        return data["thumbnail"]
    thumbs = [t.get("url") for t in data.get("thumbnails") or [] if isinstance(t, dict) and t.get("url")]
    return thumbs[-1] if thumbs else None


def _duration(value: Any) -> float | None:
    try:
        d = float(value)
    except (TypeError, ValueError):
        return None
    return d if d > 0 else None


def _entry_url(data: dict) -> str | None:
    for key in ("webpage_url", "url", "original_url"):
        value = data.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    vid = data.get("id") or data.get("url")
    if vid and str(data.get("ie_key") or data.get("extractor_key") or "").lower().startswith("youtube"):
        return f"https://www.youtube.com/watch?v={vid}"
    return None


# Пометки видео в названии: «(Official Music Video)», «[4K UPGRADE]», «(Lyrics)», «(клип)»…
_DECOR = re.compile(r"\s*[(\[][^)\]]*\b(?:official|video|audio|lyrics?|visuali[sz]er|mv|hd|4k|клип|"
                    r"видео|премьера)\b[^)\]]*[)\]]", re.I)
_DASH = re.compile(r"\s+[-–—]\s+")


def _clean_title(title: str, artist: str) -> str:
    """Убрать повтор исполнителя из названия («Песня – Исполнитель», «Исполнитель - Песня»)."""
    parts = [p.strip() for p in _DASH.split(title, maxsplit=1)]
    if artist and len(parts) == 2 and all(parts):
        if parts[1].casefold() == artist.casefold():
            return parts[0]
        if parts[0].casefold() == artist.casefold():
            return parts[1]
    return title


def _ytdlp_track(data: dict, url: str) -> LinkTrack:
    track = str(data.get("track") or "").strip()
    title = track or str(data.get("title") or "").strip()
    artist = str(data.get("artist") or data.get("creator") or "").strip()
    if not artist and isinstance(data.get("artists"), list) and data["artists"]:
        artist = ", ".join(str(a) for a in data["artists"] if a)
    uploader = _strip_topic(str(data.get("uploader") or data.get("channel") or ""))
    if not track:
        title = _DECOR.sub("", title).strip() or title
        parts = [p.strip() for p in _DASH.split(title, maxsplit=1)]
        if not artist and len(parts) == 2 and all(parts):
            # «Исполнитель - Песня»; если исполнитель — второй (совпадает с каналом), наоборот
            swap = uploader and parts[1].casefold() == uploader.casefold()
            artist, title = (parts[1], parts[0]) if swap else (parts[0], parts[1])
        elif artist:
            title = _clean_title(title, artist)
    if not artist:
        artist = uploader
    return LinkTrack(url=url, artist=artist, title=title,
                     duration=_duration(data.get("duration")), thumbnail=_thumbnail(data))


def _ytdlp_error(stderr: str) -> str:
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.startswith("ERROR:")]
    line = (errors or lines or ["yt-dlp завершился с ошибкой"])[-1]
    return re.sub(r"^ERROR:\s*", "", line)[:500]


def ytdlp_info(url: str, cmd: list[str], timeout: float = 60) -> LinkInfo:
    """Метаданные ссылки через yt-dlp (``-J --flat-playlist``), без загрузки звука."""
    args = list(cmd) + ["-4", "-J", "--flat-playlist", "--no-warnings", "--", url]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise MusicLinkError(MSG_YTDLP + "истекло время ожидания") from None
    except OSError as e:
        raise MusicLinkError(MSG_YTDLP + f"не запускается yt-dlp ({e.strerror or e})") from None
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise MusicLinkError(MSG_YTDLP + _ytdlp_error(err))
    try:
        data = json.loads(out)
    except ValueError:
        raise MusicLinkError(MSG_YTDLP + "yt-dlp вернул не JSON") from None
    if not isinstance(data, dict):
        raise MusicLinkError(MSG_YTDLP + "yt-dlp вернул не JSON")
    if data.get("_type") == "playlist" or isinstance(data.get("entries"), list):
        tracks = []
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            entry_url = _entry_url(entry)
            if entry_url:
                tracks.append(_ytdlp_track(entry, entry_url))
        if not tracks:
            raise MusicLinkError(MSG_YTDLP + "в списке нет треков")
        return LinkInfo("ytdlp", str(data.get("title") or "").strip(), tracks)
    track = _ytdlp_track(data, _entry_url(data) or url)
    return LinkInfo("ytdlp", track.title, [track])


# --------------------------------------------------------------------------- Яндекс Музыка

def _default_client_factory(key: str):
    from yandex_music import Client
    return Client(key)


def _map_yandex_error(exc: BaseException) -> MusicLinkError:
    """Исключение yandex-music → понятная ``MusicLinkError`` (текст библиотеки без токена)."""
    try:
        from yandex_music import exceptions as ym
    except ImportError:  # pragma: no cover — библиотека — зависимость core
        return MusicLinkError(MSG_UNAVAILABLE)
    text = str(exc).lower()
    if isinstance(exc, ym.UnauthorizedError):
        return MusicLinkError(MSG_REJECTED)
    if "451" in text or "no-rights" in text or "not-allowed" in text or "unavailable-for-legal" in text:
        return MusicLinkError(MSG_NO_RIGHTS)
    if isinstance(exc, ym.NotFoundError):
        return MusicLinkError(MSG_NOT_FOUND)
    if isinstance(exc, (ym.NetworkError, ym.TimedOutError)):
        return MusicLinkError(MSG_UNAVAILABLE)
    if isinstance(exc, ym.BadRequestError):
        return MusicLinkError(MSG_NOT_FOUND)
    return MusicLinkError(MSG_UNAVAILABLE)


def _yandex_errors() -> tuple[type[BaseException], ...]:
    try:
        from yandex_music.exceptions import YandexMusicError
    except ImportError:  # pragma: no cover
        return (OSError,)
    return (YandexMusicError, OSError)


def _artists(obj: Any) -> str:
    names = [str(getattr(a, "name", "") or "").strip() for a in getattr(obj, "artists", None) or []]
    return ", ".join(n for n in names if n)


def _cover(obj: Any, size: str = "400x400") -> str | None:
    uri = getattr(obj, "cover_uri", None) or getattr(obj, "og_image", None)
    if not isinstance(uri, str) or not uri:
        return None
    uri = uri.replace("%%", size)
    return uri if uri.startswith(("http://", "https://")) else f"https://{uri}"


class YandexMusic:
    """Яндекс Музыка по OAuth-токену пользователя (библиотека ``yandex-music``, MarshalX)."""

    def __init__(self, token: str | None, client_factory: Callable[[str], Any] | None = None):
        self._key = (token or "").strip()
        self._factory = client_factory or _default_client_factory
        self._client: Any = None

    # -- служебное

    def _call(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except MusicLinkError:
            raise
        except _yandex_errors() as e:
            raise _map_yandex_error(e) from None

    def client(self) -> Any:
        """Инициализированный клиент (``Client(token).init()``); ошибки — ``MusicLinkError``."""
        if not self._key:
            raise MusicLinkError(MSG_NEED_LOGIN)
        if self._client is None:
            self._client = self._call(lambda: self._factory(self._key).init())
        return self._client

    def check(self) -> None:
        """Проверить токен: клиент инициализируется, и аккаунт не анонимный (есть ``uid``)."""
        account = getattr(getattr(self.client(), "me", None), "account", None)
        if getattr(account, "uid", None) is None:
            raise MusicLinkError(MSG_REJECTED)

    def _track_obj(self, link: LinkKind) -> Any:
        tid = link.ids.get("track")
        if not tid:
            raise MusicLinkError("Нужна ссылка на один трек Яндекс Музыки")
        ref = f"{tid}:{link.ids['album']}" if link.ids.get("album") else str(tid)
        c = self.client()
        tracks = self._call(lambda: c.tracks([ref]))
        if not tracks:
            raise MusicLinkError(MSG_NOT_FOUND)
        return tracks[0]

    def _link_track(self, t: Any, host: str, album_id: Any = None) -> LinkTrack:
        tid = getattr(t, "id", None)
        if album_id is None:
            albums = getattr(t, "albums", None) or []
            album_id = getattr(albums[0], "id", None) if albums else None
        url = f"{host}/album/{album_id}/track/{tid}" if album_id else f"{host}/track/{tid}"
        title = str(getattr(t, "title", "") or "").strip()
        version = str(getattr(t, "version", "") or "").strip()
        if version and version.lower() not in title.lower():
            title = f"{title} ({version})"
        ms = getattr(t, "duration_ms", None)
        return LinkTrack(url=url, artist=_artists(t), title=title,
                         duration=(ms / 1000.0) if isinstance(ms, (int, float)) and ms > 0 else None,
                         thumbnail=_cover(t) or _cover((getattr(t, "albums", None) or [None])[0]))

    @staticmethod
    def _host(link: LinkKind) -> str:
        parts = urlsplit(link.url)
        return f"https://{parts.hostname or 'music.yandex.ru'}"

    # -- контракт

    def info(self, link: LinkKind) -> LinkInfo:
        host = self._host(link)
        if link.kind == "yandex_track":
            t = self._track_obj(link)
            lt = self._link_track(t, host, link.ids.get("album"))
            return LinkInfo(link.kind, lt.title, [lt])
        c = self.client()
        if link.kind == "yandex_album":
            album = self._call(lambda: c.albums_with_tracks(link.ids["album"]))
            if album is None:
                raise MusicLinkError(MSG_NOT_FOUND)
            tracks = [self._link_track(t, host, getattr(album, "id", None) or link.ids["album"])
                      for volume in getattr(album, "volumes", None) or [] for t in volume or []]
            return LinkInfo(link.kind, str(getattr(album, "title", "") or ""), tracks)
        if link.kind == "yandex_playlist":
            if link.ids.get("uuid"):
                pl = self._call(lambda: c.playlist(link.ids["uuid"]))
            else:
                pl = self._call(lambda: c.users_playlists(link.ids["kind"], link.ids["user"]))
            if isinstance(pl, list):
                pl = pl[0] if pl else None
            if pl is None:
                raise MusicLinkError(MSG_NOT_FOUND)
            shorts = getattr(pl, "tracks", None) or []
            if not shorts and (getattr(pl, "track_count", 0) or 0) > 0:
                shorts = self._call(lambda: pl.fetch_tracks()) or []
            tracks = []
            for s in shorts:
                t = getattr(s, "track", None)
                if t is None:
                    t = self._call(lambda: s.fetch_track())
                if t is not None:
                    tracks.append(self._link_track(t, host))
            return LinkInfo(link.kind, str(getattr(pl, "title", "") or ""), tracks)
        raise MusicLinkError("Это не ссылка Яндекс Музыки")

    def download(self, link: LinkKind, dest_mp3: Path) -> None:
        """Скачать лучший mp3 трека в ``dest_mp3`` (через временный ``.part``)."""
        if link.kind != "yandex_track":
            raise MusicLinkError("Скачать можно только один трек Яндекс Музыки")
        t = self._track_obj(link)
        if getattr(t, "available", True) is False:
            raise MusicLinkError(MSG_NO_RIGHTS)
        infos = self._call(lambda: t.get_download_info()) or []
        full = [i for i in infos if str(getattr(i, "codec", "")).lower() == "mp3"
                and not getattr(i, "preview", False)]
        if not full:
            raise MusicLinkError(MSG_NO_RIGHTS)
        best = max(full, key=lambda i: getattr(i, "bitrate_in_kbps", 0) or 0)
        dest = Path(dest_mp3)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            self._call(lambda: best.download(str(part)))
            if not part.is_file() or part.stat().st_size == 0:
                raise MusicLinkError(MSG_UNAVAILABLE)
            os.replace(part, dest)
        finally:
            if part.exists():
                part.unlink()


# --------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None, env: dict | None = None,
         client_factory: Callable[[str], Any] | None = None) -> int:
    """``download <url> <dest.mp3>``; токен — из ``YANDEX_MUSIC_TOKEN``. Код 0 — успех."""
    args = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if env is None else env
    if len(args) != 3 or args[0] != "download":
        print("Использование: python -m karaoke_core.musiclink download <url> <dest.mp3>", file=sys.stderr)
        return 2
    _, url, dest = args
    try:
        link = classify(url)
        if not is_yandex(link):
            raise MusicLinkError("Это не ссылка Яндекс Музыки: такие ссылки качает yt-dlp")
        YandexMusic(environ.get("YANDEX_MUSIC_TOKEN"), client_factory).download(link, Path(dest))
    except MusicLinkError as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:  # неожиданное — тоже по-русски и без токена
        print(f"Ошибка загрузки с Яндекс Музыки: {type(e).__name__}", file=sys.stderr)
        return 1
    print(f"musiclink: OK {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
