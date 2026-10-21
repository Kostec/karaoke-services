"""Постобработка выхода UltraSinger в готовую песню (Решения §6).

1. ``#ARTIST``/``#TITLE`` — строго из формы.
2. Фильтр MusicBrainz: если исполнитель от MusicBrainz после нормализации не
   совпал с исполнителем из формы — удаляются обложка, ``#COVER``,
   ``#COVERURL``, ``#YEAR``, ``#GENRE``. Обложка из формы ставится как ``[CO]``.
3. Ноты нулевой длины исправляются (:func:`ultrastar.fix_zero_length`).
4. Все файлы называются ``<Исполнитель - Название>`` + суффикс, ссылки в
   заголовках указывают на них. В результат попадают только файлы песни
   (без ``cache/``, логов, отладки).
5. .txt пишется в UTF-8 без BOM, с `#VERSION:1.2.0`; порядок заголовков и тело
   сохраняются. Оригинал, вокал и минусовка — только mp3.

Исходная папка не меняется: результат собирается в отдельной папке.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import naming, ultrastar

__all__ = ["finalize", "FinalizedSong", "FinalizeError", "format_videogap"]

# Заголовки, которые приходят от MusicBrainz и удаляются при несовпадении исполнителя.
MB_HEADERS = ("COVER", "COVERURL", "YEAR", "GENRE")

# Версия формата UltraStar в итоговом .txt.
FORMAT_VERSION = "1.2.0"


class FinalizeError(Exception):
    """Выход UltraSinger нельзя превратить в песню (сообщение — для пользователя)."""


@dataclass
class FinalizedSong:
    dir: Path  # папка с готовыми файлами песни
    files: list[str] = field(default_factory=list)  # имена файлов в ``dir``
    mb_dropped: bool = False  # данные MusicBrainz отброшены (исполнитель не совпал)
    zero_fixed: int = 0  # сколько нот нулевой длины исправлено
    base: str = ""  # «Исполнитель - Название» (безопасное имя)
    rel_dir: str = ""  # «Исполнитель/Исполнитель - Название» — куда выкладывать


def _is_song_txt(p: Path) -> bool:
    name = p.name.lower()
    return p.is_file() and name.endswith(".txt") and not name.endswith(".lyrics.txt")


def _find_song_folder(out_dir: Path) -> tuple[Path, Path]:
    """Папка песни и её .txt внутри выхода UltraSinger."""
    candidates = [out_dir] + sorted(p for p in out_dir.iterdir()
                                    if p.is_dir() and p.name != "cache")
    for folder in candidates:
        txts = sorted(p for p in folder.iterdir() if _is_song_txt(p))
        if not txts:
            continue
        for t in txts:
            if t.stem == folder.name:
                return folder, t
        return folder, txts[0]
    raise FinalizeError("UltraSinger не создал файл песни (.txt)")


def _referenced(folder: Path, song: ultrastar.Song, key: str) -> Path | None:
    value = song.header(key)
    if not value:
        return None
    p = folder / value.strip()
    return p if p.is_file() else None


def _by_suffix(folder: Path, marker: str) -> Path | None:
    """Файл вида ``<что угодно> [Marker].<ext>`` в папке (запасной поиск)."""
    found = sorted(p for p in folder.iterdir() if p.is_file() and f" [{marker}]." in p.name)
    return found[0] if found else None


def format_videogap(value) -> str | None:
    """Значение ``#VIDEOGAP`` в секундах: до 3 знаков, без «.0»; 0 или пусто — ``None`` (строки нет)."""
    if value in (None, ""):
        return None
    gap = round(float(value), 3)
    if gap == 0:
        return None
    return f"{gap:.3f}".rstrip("0").rstrip(".")


def finalize(out_dir, artist: str, title: str, cover_path=None, *,
             dest_dir=None, video_path=None, videogap=None) -> FinalizedSong:
    """Собрать готовую песню из выхода UltraSinger.

    ``out_dir`` — папка песни UltraSinger (``<Artist - Title>/``) или папка,
    в которой она лежит. Результат — в ``dest_dir`` (по умолчанию
    ``<out_dir>/../result``); папка результата пересоздаётся.
    ``video_path`` — видеофайл: копия ``<A - T>.<ext>``, ``#VIDEO`` и ``#VIDEOGAP``
    (если ``videogap`` не 0).
    """
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise FinalizeError("Папка с результатом UltraSinger не найдена")
    folder, txt_path = _find_song_folder(out_dir)
    dest = Path(dest_dir) if dest_dir is not None else out_dir.parent / "result"

    song = ultrastar.parse(txt_path.read_bytes())
    base = naming.base_name(artist, title)

    def file_name(suffix: str) -> str:
        return naming.song_file(artist, title, suffix)

    def require_mp3(src: Path, what: str) -> None:
        if src.suffix.lower() != ".mp3":
            raise FinalizeError(
                f"UltraSinger отдал {what} в формате {src.suffix or 'без расширения'}, "
                "а песне нужен mp3")

    # Формат 1.2.0: #VERSION первой строкой.
    if song.header("VERSION") is None:
        song.headers.insert(0, ultrastar.Header(key="VERSION", value=FORMAT_VERSION,
                                                eol=song.newline))
    else:
        song.set_header("VERSION", FORMAT_VERSION)

    # 1–2. Исполнитель/название из формы, фильтр MusicBrainz.
    mb_artist = song.header("ARTIST")
    mb_dropped = (mb_artist is not None
                  and naming.normalize_artist(mb_artist) != naming.normalize_artist(artist))
    song.set_header("ARTIST", artist)
    song.set_header("TITLE", title)

    copies: list[tuple[Path, str]] = []

    # Оригинал: #MP3 и #AUDIO указывают на один файл.
    audio = _referenced(folder, song, "AUDIO") or _referenced(folder, song, "MP3")
    if audio is None:
        raise FinalizeError("UltraSinger не создал аудиофайл песни")
    require_mp3(audio, "оригинал")
    audio_name = file_name(naming.SUFFIX_AUDIO)
    copies.append((audio, audio_name))
    song.set_header("MP3", audio_name)
    song.set_header("AUDIO", audio_name)

    # Вокал и минусовка — всегда mp3.
    for key, marker, suffix, what in (
            ("VOCALS", "Vocals", naming.SUFFIX_VOCALS, "вокал"),
            ("INSTRUMENTAL", "Instrumental", naming.SUFFIX_INSTRUMENTAL, "минусовку")):
        src = _referenced(folder, song, key) or _by_suffix(folder, marker)
        if src is None:
            song.remove_header(key)
            continue
        require_mp3(src, what)
        name = file_name(suffix)
        copies.append((src, name))
        song.set_header(key, name)

    # Обложка: из формы → от MusicBrainz (если исполнитель совпал) → нет.
    if mb_dropped:
        for key in MB_HEADERS:
            song.remove_header(key)
    cover_src: Path | None = None
    if cover_path is not None:
        cover_src = Path(cover_path)
        if not cover_src.is_file():
            raise FinalizeError("Файл обложки не найден")
    elif not mb_dropped:
        cover_src = _referenced(folder, song, "COVER") or _by_suffix(folder, "CO")
    if cover_src is not None:
        name = file_name(naming.cover_suffix(cover_src.suffix))
        copies.append((cover_src, name))
        song.set_header("COVER", name)
    else:
        song.remove_header("COVER")

    # MIDI — если есть.
    mids = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mid")
    if mids:
        copies.append((mids[0], file_name(naming.SUFFIX_MIDI)))

    # Видео — как есть, с исходным расширением.
    if video_path is not None:
        video_src = Path(video_path)
        if not video_src.is_file():
            raise FinalizeError("Файл видео не найден")
        name = file_name(naming.video_suffix(video_src.suffix))
        copies.append((video_src, name))
        song.set_header("VIDEO", name)
        gap = format_videogap(videogap)
        if gap is None:
            song.remove_header("VIDEOGAP")
        else:
            song.set_header("VIDEOGAP", gap)

    # 3. Нулевые ноты.
    zero_fixed = ultrastar.fix_zero_length(song)

    # 4–5. Сборка результата.
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    files: list[str] = []
    for src, name in copies:
        shutil.copy2(src, dest / name)
        files.append(name)
    song.encoding = "utf-8"
    song.bom = False
    txt_name = file_name(naming.SUFFIX_TXT)
    (dest / txt_name).write_bytes(ultrastar.render(song))
    files.append(txt_name)

    return FinalizedSong(dir=dest, files=sorted(files), mb_dropped=mb_dropped,
                         zero_fixed=zero_fixed, base=base,
                         rel_dir=naming.song_dir(artist, title))
