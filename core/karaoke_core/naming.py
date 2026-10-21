"""Правила имён папок и файлов песен.

Иерархия везде одна: ``<Исполнитель>/<Исполнитель - Название>/``, файлы песни
называются ``<Исполнитель - Название>`` + суффикс. Строка исполнителя на обоих
уровнях одна и та же.
"""

from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath

# Символы, недопустимые в именах файлов Windows/Samba (плюс все управляющие, см. ниже).
_FORBIDDEN = frozenset('/\\:*?"<>|')

# Суффиксы файлов готовой песни (после базового имени ``<Исполнитель - Название>``).
SUFFIX_TXT = ".txt"
SUFFIX_AUDIO = ".mp3"
SUFFIX_INSTRUMENTAL = " [Instrumental].mp3"
SUFFIX_VOCALS = " [Vocals].mp3"
SUFFIX_MIDI = ".mid"
_COVER_MARK = " [CO]"


def _bad(ch: str) -> bool:
    return ch in _FORBIDDEN or unicodedata.category(ch) == "Cc"


def safe_name(s: str) -> str:
    """Имя, пригодное для файла или папки: ``/ \\ : * ? " < > |`` и все
    управляющие символы Unicode → ``_``, точки и пробелы в конце убираются;
    пустое имя превращается в ``_``."""
    name = "".join("_" if _bad(ch) else ch for ch in (s or ""))
    name = name.rstrip(". ")
    return name or "_"


def artist_dir(artist: str) -> str:
    """Безопасная строка исполнителя — папка первого уровня и начало базового имени."""
    return safe_name((artist or "").strip())


def base_name(artist: str, title: str) -> str:
    """``<Исполнитель - Название>`` — базовое имя файлов песни и её папки."""
    return f"{artist_dir(artist)} - {safe_name((title or '').strip())}"


def song_dir(artist: str, title: str) -> str:
    """Относительный путь папки песни: ``<Исполнитель>/<Исполнитель - Название>``."""
    return f"{artist_dir(artist)}/{base_name(artist, title)}"


def cover_suffix(ext: str) -> str:
    """Суффикс обложки ``" [CO].<ext>"`` (расширение в нижнем регистре, jpeg → jpg)."""
    ext = (ext or ".jpg").lower()
    if not ext.startswith("."):
        ext = "." + ext
    if ext == ".jpeg":
        ext = ".jpg"
    return f"{_COVER_MARK}{ext}"


# Контейнеры видео, которые кладутся в папку песни как есть (R07).
# Порядок — для подсказок и текста ошибки (сначала самые частые); проверять — по VIDEO_EXTS.
VIDEO_EXT_ORDER = (".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".mpg", ".mpeg")
VIDEO_EXTS = frozenset(VIDEO_EXT_ORDER)


def video_file_name(value: str | None) -> str | None:
    """Видеофайл песни из ``#VIDEO``: имя без папок с расширением из ``VIDEO_EXTS``, иначе ``None``
    (ссылка usdb ``v=…``, путь, не видео). Единое правило для индекса (``SongEntry.video``) и воркера."""
    value = (value or "").strip()
    if not value or "/" in value or "\\" in value:
        return None
    return value if PurePosixPath(value).suffix.lower() in VIDEO_EXTS else None


def video_suffix(ext: str) -> str:
    """Суффикс видео ``".<ext>"`` (расширение в нижнем регистре): файл ``<A - T>.<ext>``."""
    ext = (ext or ".mp4").lower()
    return ext if ext.startswith(".") else "." + ext


def song_file(artist: str, title: str, suffix: str) -> str:
    """Имя файла песни: ``<Исполнитель - Название>`` + суффикс (``SUFFIX_*``, :func:`cover_suffix`)."""
    return base_name(artist, title) + suffix


def normalize_artist(s: str) -> str:
    """Ключ для сравнения исполнителей: регистр, ё→е, пунктуация и пробелы
    не учитываются."""
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = s.replace("ё", "е")
    return "".join(ch for ch in s if ch.isalnum())
