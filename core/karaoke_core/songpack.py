"""Разбор сборника UltraStar (Решения §5): безопасная распаковка zip и поиск песен."""

from __future__ import annotations

import re
import shutil
import stat
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import ultrastar
from .storage.base import is_song_txt_name

__all__ = ["PackError", "FoundSong", "safe_extract", "find_songs", "youtube_links",
           "AUDIO_EXTS", "IMAGE_EXTS", "ALLOWED_EXTS"]

AUDIO_EXTS = frozenset({".mp3", ".ogg", ".m4a", ".opus", ".wav", ".flac"})
IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
# Белый список распаковки: всё прочее в архиве молча пропускается.
ALLOWED_EXTS = frozenset({".txt"}) | AUDIO_EXTS | IMAGE_EXTS

_CHUNK = 1 << 20
_WATCH = "https://www.youtube.com/watch?v="
_FANART = "https://images.fanart.tv/fanart/"
_URL_RE = re.compile(r"https?://\S+\Z", re.I)
_YT_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
# Форма usdb начинается с короткого ключа и «=» (a=, v=, co=, bg=, v-gap=, p1=…).
_USDB_FORM_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,15}=")


class PackError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class FoundSong:
    txt_rel: str
    artist: str
    title: str
    language: str | None
    duet: bool
    audio_rel: str | None
    cover_rel: str | None
    youtube: list[str] = field(default_factory=list)
    cover_url: str | None = None


def _too_big(max_total_bytes: int) -> PackError:
    return PackError(f"Архив больше {max_total_bytes // 2**20} МБ после распаковки")


def _member_parts(name: str) -> tuple[str, ...]:
    """Части пути элемента архива; выход за папку и абсолютный путь — ``PackError``."""
    norm = name.replace("\\", "/")
    parts = tuple(p for p in norm.split("/") if p not in ("", "."))
    if (norm.startswith("/") or re.match(r"[A-Za-z]:", norm)
            or any(p == ".." for p in parts) or "\0" in norm):
        raise PackError(f"В архиве недопустимый путь: {name}")
    return parts


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)


def _wanted(parts: tuple[str, ...]) -> bool:
    """Файл песни: расширение из белого списка, не служебный мусор macOS и не скрытый."""
    if not parts or any(p.startswith(".") or p == "__MACOSX" for p in parts):
        return False
    return PurePosixPath(parts[-1]).suffix.lower() in ALLOWED_EXTS


def safe_extract(zip_path: str | Path, dest: str | Path, max_total_bytes: int) -> list[str]:
    """Распаковать в ``dest`` только файлы песен; вернуть их пути от ``dest`` (POSIX).

    Путь вне ``dest`` (``..``, абсолютный, с буквой диска) — отказ всего архива;
    симлинки и файлы не из белого списка пропускаются. Лимит — по сумме
    объявленных размеров: ``zipfile`` не отдаёт больше объявленного, а архив,
    где размер подделан, не сходится по CRC и считается повреждённым.
    """
    dest = Path(dest)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            chosen: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
            for info in infos:
                parts = _member_parts(info.filename)
                if info.is_dir() or _is_symlink(info) or not _wanted(parts):
                    continue
                chosen.append((info, parts))
            if sum(i.file_size for i, _ in chosen) > max_total_bytes:
                raise _too_big(max_total_bytes)
            out: list[str] = []
            for info, parts in chosen:
                target = dest.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, _CHUNK)
                out.append(PurePosixPath(*parts).as_posix())
            return out
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError,
            RuntimeError, ValueError) as e:
        raise PackError("Архив повреждён") from e


def youtube_watch_url(video_id: str) -> str:
    """Единственная форма ссылки на ролик: ``https://www.youtube.com/watch?v=<id>``."""
    return _WATCH + video_id


def resolve_file(base: Path, value: str | None, exts: frozenset[str]) -> Path | None:
    """Файл из заголовка песни (путь от папки ``base`` с .txt) без учёта регистра имён:
    точное имя важнее; ``..``, чужое расширение, симлинк, отсутствие — ``None``."""
    parts = [p for p in (value or "").strip().replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or ".." in parts or PurePosixPath(parts[-1]).suffix.lower() not in exts:
        return None
    cur = Path(base)
    for part in parts:
        try:
            names = {c.name: c for c in cur.iterdir()}
        except OSError:
            return None
        nxt = names.get(part) or next(
            (c for n, c in sorted(names.items()) if n.casefold() == part.casefold()), None)
        if nxt is None:
            return None
        cur = nxt
    return cur if cur.is_file() and not cur.is_symlink() else None


def _resolve(root: Path, base: Path, value: str | None, exts: frozenset[str]) -> str | None:
    """:func:`resolve_file`, путь — от ``root``."""
    found = resolve_file(base, value, exts)
    return found.relative_to(root).as_posix() if found is not None else None


def _co_cover(root: Path, txt: Path) -> str | None:
    """Обложка по суффиксу `` [CO].`` рядом с .txt: сначала с тем же началом имени."""
    found = sorted(p for p in txt.parent.iterdir()
                   if p.is_file() and not p.is_symlink() and p.suffix.lower() in IMAGE_EXTS
                   and " [co]." in p.name.casefold())
    if not found:
        return None
    stem = txt.stem.casefold()
    best = next((p for p in found if p.name.casefold().startswith(stem)), found[0])
    return best.relative_to(root).as_posix()


def _header(song: ultrastar.Song, key: str) -> str:
    return (song.header(key) or "").strip()


def find_songs(directory: str | Path) -> list[FoundSong]:
    """Песни UltraStar в папке (рекурсивно): ``.txt`` с ``#TITLE`` и нотами.

    ``*.lyrics.txt``, скрытые файлы и папки пропускаются; порядок — по пути.
    Нет песен — пустой список (что с этим делать, решает вызывающий).
    """
    root = Path(directory)
    out: list[FoundSong] = []
    txts = sorted((p for p in root.rglob("*") if p.is_file() and not p.is_symlink()
                   and is_song_txt_name(p.name)),
                  key=lambda p: p.relative_to(root).as_posix())
    for txt in txts:
        rel = txt.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            song = ultrastar.parse(txt.read_bytes())
        except (OSError, ValueError):
            continue
        title = _header(song, "TITLE")
        if not title or not song.notes():
            continue
        base = txt.parent
        audio = (_resolve(root, base, song.header("AUDIO"), AUDIO_EXTS)
                 or _resolve(root, base, song.header("MP3"), AUDIO_EXTS))
        cover = _resolve(root, base, song.header("COVER"), IMAGE_EXTS) or _co_cover(root, txt)
        youtube, cover_url = youtube_links(song.header("VIDEO"))
        out.append(FoundSong(
            txt_rel=rel.as_posix(), artist=_header(song, "ARTIST"), title=title,
            language=_header(song, "LANGUAGE") or None, duet=song.is_duet,
            audio_rel=audio, cover_rel=cover, youtube=youtube, cover_url=cover_url))
    return out


def _media_url(value: str) -> str | None:
    """URL как есть или ID YouTube → ссылка на просмотр; прочее (имя файла) — ``None``."""
    value = value.strip()
    if _URL_RE.match(value):
        return value
    if _YT_ID_RE.fullmatch(value):
        return youtube_watch_url(value)
    return None


def _cover_link(value: str) -> str | None:
    """``co=`` формы usdb: URL как есть, иначе имя файла на fanart.tv (так его пишет usdb)."""
    value = value.strip()
    if _URL_RE.match(value):
        return value
    if value and "/" not in value and "." in value and not value.startswith("."):
        return _FANART + value
    return None


def youtube_links(video_header: str | None) -> tuple[list[str], str | None]:
    """Ссылки из ``#VIDEO``: ``(ссылки на звук — a= раньше v=, ссылка на обложку из co=)``.

    Форма usdb — ``a=…,v=…,co=…`` (значения — ID YouTube или URL); иначе заголовок
    целиком — URL или ID. Имя локального видеофайла ссылкой не считается.
    """
    text = (video_header or "").strip()
    if not text:
        return [], None
    if not _USDB_FORM_RE.match(text):
        url = _media_url(text)
        return ([url] if url else []), None
    tags: dict[str, str] = {}
    for part in text.split(","):
        key, sep, value = part.partition("=")
        if sep:
            tags.setdefault(key.strip().lower(), value.strip())
    urls: list[str] = []
    for key in ("a", "v"):
        url = _media_url(tags.get(key, ""))
        if url and url not in urls:
            urls.append(url)
    return urls, _cover_link(tags.get("co", ""))
