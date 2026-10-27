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
_BACKGROUND_MARK = " [BG]"


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


def _image_ext(ext: str) -> str:
    """Расширение картинки: с точкой, в нижнем регистре, jpeg → jpg."""
    ext = (ext or ".jpg").lower()
    if not ext.startswith("."):
        ext = "." + ext
    return ".jpg" if ext == ".jpeg" else ext


def cover_suffix(ext: str) -> str:
    """Суффикс обложки ``" [CO].<ext>"`` (расширение в нижнем регистре, jpeg → jpg)."""
    return f"{_COVER_MARK}{_image_ext(ext)}"


def background_suffix(ext: str) -> str:
    """Суффикс фона ``" [BG].<ext>"`` (расширение в нижнем регистре, jpeg → jpg)."""
    return f"{_BACKGROUND_MARK}{_image_ext(ext)}"


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


def match_key(artist: str, title: str) -> tuple[str, str]:
    """Ключ «такая песня уже есть»: без учёта регистра и ё/е, запрещённые символы — как в
    :func:`safe_name`; пробелы и прочая пунктуация значимы («Ма-ма» ≠ «Мама»)."""
    def fold(s: str) -> str:
        return safe_name((s or "").strip().casefold().replace("ё", "е"))
    return fold(artist), fold(title)


def song_tag_key(artist: str, title: str) -> str:
    """Ключ своих тегов песни: :func:`match_key` строкой через перевод строки —
    общий для всех копий «исполнитель — название» во всех хранилищах."""
    return "\n".join(match_key(artist, title))


# Латинские буквы, неотличимые на вид от кириллических (после casefold).
_LOOKALIKES = str.maketrans("aeopcxykmthb", "аеорсхукмтнв")


def _has_cyrillic(s: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in s)


def rough_key(artist: str, title: str) -> str:
    """Грубый ключ дублей для проверки библиотеки: :func:`match_key` без всех не-букв и не-цифр,
    а в строке с кириллицей латинские двойники (``a e o p c x y k m t h b``) — кириллицей
    («Kино» = «Кино», «Ленинград!» = «ленинград»). Исполнитель и название — через перевод строки."""
    def rough(s: str) -> str:
        s = "".join(ch for ch in s if ch.isalnum())
        return s.translate(_LOOKALIKES) if _has_cyrillic(s) else s
    return "\n".join(rough(part) for part in match_key(artist, title))


def rename_plan(names, old_bases, new_base: str, fallback=()) -> dict[str, str]:
    """Новые имена файлов папки при переименовании песни: имя, начинающееся (без учёта регистра)
    с прежней основы, за которой идёт ``.`` или пробел (``.txt``, `` [Instrumental].mp3``,
    `` (duet).txt``…), получает ``new_base`` с тем же хвостом; прочие — как есть. Сначала —
    самая длинная подходящая из ``old_bases``, только потом — из ``fallback`` (стем ``.txt``
    пакета вроде ``song``)."""
    groups = [sorted({b for b in bases if b}, key=len, reverse=True) for bases in (old_bases, fallback)]
    out = {}
    for name in names:
        out[name] = name
        for base in (b for group in groups for b in group):
            rest = name[len(base):]
            if name[:len(base)].casefold() == base.casefold() and rest[:1] in (".", " "):
                out[name] = new_base + rest
                break
    return out


def renamed_txt_name(txt_name: str, rel_dir: str, old_artist: str, old_title: str,
                     artist: str, title: str) -> str:
    """Новое имя ``.txt`` песни по :func:`rename_plan` — одно правило у веба и воркера."""
    return rename_plan([txt_name], rename_bases(rel_dir, old_artist, old_title), base_name(artist, title),
                       fallback=[PurePosixPath(txt_name).stem])[txt_name]


def rename_bases(rel_dir: str, old_artist: str, old_title: str) -> list[str]:
    """Прежние основы имён файлов песни: имя её папки и ``base_name`` прежнего имени."""
    return [PurePosixPath(rel_dir).name, base_name(old_artist, old_title)]
