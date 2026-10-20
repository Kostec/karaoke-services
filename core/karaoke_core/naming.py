"""Правила имён папок и файлов песен.

Иерархия везде одна: ``<Исполнитель>/<Исполнитель - Название>/``, файлы песни
называются ``<Исполнитель - Название>`` + суффикс.
"""

from __future__ import annotations

import re
import unicodedata

# Символы, недопустимые в именах файлов Windows/Samba, и управляющие символы.
_FORBIDDEN = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f]')

# Суффиксы файлов готовой песни (после базового имени).
SUFFIX_TXT = ".txt"
SUFFIX_AUDIO = ".mp3"
SUFFIX_INSTRUMENTAL = " [Instrumental].mp3"
SUFFIX_VOCALS = " [Vocals].mp3"
SUFFIX_COVER = " [CO]"  # + расширение картинки
SUFFIX_MIDI = ".mid"


def safe_name(s: str) -> str:
    """Имя, пригодное для файла или папки: запрещённые символы → ``_``,
    точки и пробелы в конце убираются; пустое имя превращается в ``_``."""
    name = _FORBIDDEN.sub("_", s or "")
    name = name.rstrip(". ")
    return name or "_"


def base_name(artist: str, title: str) -> str:
    """``<Исполнитель - Название>`` — базовое имя файлов песни и её папки."""
    return safe_name(f"{(artist or '').strip()} - {(title or '').strip()}")


def artist_dir(artist: str) -> str:
    """Папка исполнителя (первый уровень иерархии)."""
    return safe_name((artist or "").strip())


def song_dir(artist: str, title: str) -> str:
    """Относительный путь папки песни: ``<Исполнитель>/<Исполнитель - Название>``."""
    return f"{artist_dir(artist)}/{base_name(artist, title)}"


def normalize_artist(s: str) -> str:
    """Ключ для сравнения исполнителей: регистр, ё→е, пунктуация и пробелы
    не учитываются."""
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = s.replace("ё", "е")
    # Пунктуацию и прочие символы убираем, буквы и цифры оставляем.
    return "".join(ch for ch in s if ch.isalnum())
