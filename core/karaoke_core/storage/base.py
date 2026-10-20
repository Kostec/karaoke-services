"""Общая часть хранилища: интерфейс, сканирование песен, выгрузка папок.

Реализации дают только примитивы (``_scandir``, ``_open_read``, ``_open_write``,
``_replace``, ``_remove``, ``_rmdir``, ``_makedirs``, ``_stat``) и сами
переводят свои ошибки в ``StorageError``/``StorageNotFound``.
"""

from __future__ import annotations

import io
import secrets
import shutil
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

from .. import ultrastar
from ..db import LibraryItem

PART_SUFFIX = ".part"
LYRICS_SUFFIX = ".lyrics.txt"
MAX_TXT_BYTES = 2 * 1024 * 1024  # больше — точно не UltraStar .txt
CHUNK = 1024 * 1024


class StorageError(Exception):
    """Ошибка папки результата; ``str(e)`` — готовое сообщение пользователю по-русски."""


class StorageNotFound(StorageError):
    """Файла или папки нет."""


@dataclass
class Entry:
    name: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0


@dataclass
class SongEntry:
    """Песня, найденная в папке результата (поля совпадают с таблицей ``library``)."""
    rel_dir: str
    txt_name: str
    artist: str = ""
    title: str = ""
    audio: str | None = None
    instrumental: str | None = None
    cover: str | None = None
    is_duet: bool = False
    mtime: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_library_item(self, target_id: str, own_song_id: str | None = None,
                        scanned_at: str | None = None) -> LibraryItem:
        return LibraryItem(target_id=target_id, own_song_id=own_song_id, scanned_at=scanned_at,
                           **self.to_dict())


def norm(rel: str | Path, *, allow_root: bool = False) -> str:
    """Относительный POSIX-путь внутри папки результата; выход за её пределы — ошибка."""
    raw = str(rel).replace("\\", "/")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise StorageError(f"Недопустимый путь: «{rel}»")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise StorageError(f"Недопустимый путь: «{rel}»")
    if not parts and not allow_root:
        raise StorageError("Недопустимый путь: корень папки результата")
    return "/".join(parts)


def join(*parts: str) -> str:
    return "/".join(p for p in parts if p)


def _parent(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def is_song_txt_name(name: str) -> bool:
    """Кандидат в .txt песни: ``*.txt``, но не ``*.lyrics.txt`` и не скрытый файл."""
    low = name.lower()
    return low.endswith(".txt") and not low.endswith(LYRICS_SUFFIX) and not name.startswith(".")


class GuardedFile:
    """Открытый файл хранилища: ошибки посреди чтения/записи/закрытия переводятся
    в ``StorageError`` тем же правилом, что и остальные операции."""

    def __init__(self, f, errors, rel: str):
        self._f, self._errors, self._rel = f, errors, rel

    def read(self, *a):
        with self._errors(self._rel):
            return self._f.read(*a)

    def write(self, b):
        with self._errors(self._rel):
            return self._f.write(b)

    def close(self):
        with self._errors(self._rel):
            self._f.close()

    def __getattr__(self, name):  # seek, tell, readinto… — с тем же переводом ошибок
        attr = getattr(self._f, name)
        if not callable(attr):
            return attr

        def call(*a, **kw):
            with self._errors(self._rel):
                return attr(*a, **kw)
        return call

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.close()
        else:
            try:
                self._f.close()
            except Exception:
                pass


class Storage(ABC):
    """Папка результата. Все пути — относительные, через ``/``."""

    target_id: str = ""
    label: str = ""

    # ----------------------------------------------------------------- примитивы

    @abstractmethod
    def _scandir(self, rel: str) -> list[Entry]: ...

    @abstractmethod
    def _stat(self, rel: str) -> Entry | None: ...

    @abstractmethod
    def _open_read(self, rel: str) -> BinaryIO: ...

    @abstractmethod
    def _open_write(self, rel: str) -> BinaryIO: ...

    @abstractmethod
    def _replace(self, src: str, dst: str) -> None: ...

    @abstractmethod
    def _remove(self, rel: str) -> None: ...

    @abstractmethod
    def _rmdir(self, rel: str) -> None: ...

    @abstractmethod
    def _makedirs(self, rel: str) -> None: ...

    @abstractmethod
    def _errors(self, rel: str):
        """Контекст, переводящий ошибки реализации в ``StorageError``."""

    @abstractmethod
    def _check_root(self) -> None:
        """Проверить, что корень папки результата доступен (иначе ``StorageError``)."""

    def close(self) -> None:
        """Освободить соединения (для SMB)."""

    # ----------------------------------------------------------------- чтение

    def read(self, rel: str) -> bytes:
        with self._open_read(norm(rel)) as f:
            return f.read()

    def open_read(self, rel: str) -> BinaryIO:
        return self._open_read(norm(rel))

    def exists(self, rel: str) -> bool:
        return self._stat(norm(rel, allow_root=True)) is not None

    def stat(self, rel: str) -> Entry | None:
        """Сведения о файле или папке (``size``, ``is_dir``, ``mtime``); нет — ``None``."""
        return self._stat(norm(rel, allow_root=True))

    def listdir(self, rel_dir: str = "") -> list[Entry]:
        return self._scandir(norm(rel_dir, allow_root=True))

    def sizes(self, rel_dir: str) -> dict[str, int]:
        """Размеры всех файлов папки: ``{"<путь внутри папки>": байты}``."""
        base = norm(rel_dir)
        out: dict[str, int] = {}
        for sub, entry in self._walk_files(base):
            out[sub] = entry.size
        return out

    def _walk_files(self, base: str, sub: str = "") -> Iterable[tuple[str, Entry]]:
        for e in self._scandir(join(base, sub)):
            if e.is_dir:
                yield from self._walk_files(base, join(sub, e.name))
            else:
                yield join(sub, e.name), e

    # ----------------------------------------------------------------- запись

    def write_atomic(self, rel: str, data: bytes | BinaryIO) -> None:
        """Записать файл через ``<имя>.part`` и переименование: готовый файл
        появляется целиком или не появляется вовсе."""
        rel = norm(rel)
        part = rel + PART_SUFFIX
        self._makedirs(_parent(rel))
        src = io.BytesIO(data) if isinstance(data, (bytes, bytearray, memoryview)) else data
        try:
            with self._open_write(part) as out:
                shutil.copyfileobj(src, out, CHUNK)
            self._replace(part, rel)
        except BaseException:
            try:
                self._remove(part)
            except Exception:
                pass
            raise

    def upload_dir(self, local: str | Path, rel_dir: str) -> list[str]:
        """Выложить локальную папку песни: сначала медиа, последними ``.txt``.
        Возвращает записанные относительные пути."""
        local = Path(local)
        base = norm(rel_dir)
        files = sorted((p for p in local.rglob("*") if p.is_file()),
                       key=lambda p: (p.suffix.lower() == ".txt", p.as_posix()))
        written = []
        for p in files:
            rel = join(base, p.relative_to(local).as_posix())
            with open(p, "rb") as f:
                self.write_atomic(rel, f)
            written.append(rel)
        return written

    def download_dir(self, rel_dir: str, local: str | Path) -> list[Path]:
        """Скопировать папку из хранилища в локальную папку (создаётся)."""
        local = Path(local)
        base = norm(rel_dir)
        got = []
        for sub, _ in self._walk_files(base):
            dst = local / sub
            dst.parent.mkdir(parents=True, exist_ok=True)
            with self._open_read(join(base, sub)) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
            got.append(dst)
        local.mkdir(parents=True, exist_ok=True)
        return got

    def delete_dir(self, rel_dir: str) -> None:
        """Удалить папку целиком (корень папки результата удалить нельзя).
        Если после этого папка исполнителя (родитель) опустела — удаляется и она."""
        base = norm(rel_dir)
        self._delete_tree(base)
        parent = _parent(base)
        if parent:
            try:
                if not self._scandir(parent):
                    self._rmdir(parent)
            except StorageError:
                pass  # пустая папка исполнителя — не повод считать удаление неудачным

    def _delete_tree(self, rel: str) -> None:
        for e in self._scandir(rel):
            child = join(rel, e.name)
            if e.is_dir:
                self._delete_tree(child)
            else:
                self._remove(child)
        self._rmdir(rel)

    def delete_file(self, rel: str) -> None:
        self._remove(norm(rel))

    def probe(self) -> None:
        """Проверка цели: корень доступен, пробный файл пишется и удаляется."""
        self._check_root()
        name = f".karaoke-probe-{secrets.token_hex(4)}.tmp"
        payload = b"karaoke-services probe"
        self.write_atomic(name, payload)
        try:
            if self.read(name) != payload:
                raise StorageError("Пробный файл прочитан с ошибкой")
        except BaseException:
            try:
                self._remove(name)
            except Exception:
                pass  # первая ошибка важнее ошибки уборки
            raise
        self._remove(name)

    # ----------------------------------------------------------------- сканирование

    def read_song(self, rel_dir: str) -> SongEntry | None:
        """Песня в одной папке (без вложенных) или ``None``, если её там нет."""
        rel = norm(rel_dir)
        try:
            entries = self._scandir(rel)
        except StorageNotFound:
            return None
        return self._song_in(rel, entries)

    def list_songs(self, max_depth: int = 4) -> list[SongEntry]:
        """Все песни: папки с ``*.txt``, где есть ``#TITLE`` и строки нот, на
        глубине до ``max_depth`` папок от корня. ``.lyrics.txt`` и ``.txt`` без
        нот пропускаются; в одной папке берётся первая подходящая по имени."""
        out: list[SongEntry] = []
        self._scan("", 0, max_depth, out)
        return out

    def _scan(self, rel: str, depth: int, max_depth: int, out: list[SongEntry]) -> None:
        try:
            entries = self._scandir(rel)
        except StorageNotFound:
            if rel == "":
                raise
            return  # папку удалили во время сканирования
        entry = self._song_in(rel, entries)
        if entry is not None:
            out.append(entry)
        if depth < max_depth:
            for e in sorted((e for e in entries if e.is_dir), key=lambda e: e.name):
                if not e.name.startswith("."):
                    self._scan(join(rel, e.name), depth + 1, max_depth, out)

    def _song_in(self, rel: str, entries: list[Entry]) -> SongEntry | None:
        """Первый по имени .txt папки с ``#TITLE`` и нотами."""
        names = {e.name for e in entries if not e.is_dir}
        for e in sorted((e for e in entries if not e.is_dir and is_song_txt_name(e.name)),
                        key=lambda e: e.name):
            song = self._read_song(join(rel, e.name), e)
            if song is not None:
                return self._entry(rel, e, song, names)
        return None

    def _read_song(self, rel: str, e: Entry):
        if e.size > MAX_TXT_BYTES:
            return None
        try:
            data = self.read(rel)
        except StorageNotFound:
            return None
        try:
            song = ultrastar.parse(data)
        except Exception:
            return None
        if not (song.header("TITLE") or "").strip() or not song.notes():
            return None
        return song

    @staticmethod
    def _entry(rel: str, e: Entry, song, names: set[str]) -> SongEntry:
        lower = {n.lower(): n for n in names}

        def present(key: str) -> str | None:
            value = (song.header(key) or "").strip()
            if not value or "/" in value or "\\" in value:
                return None
            return value if value in names else lower.get(value.lower())

        return SongEntry(
            rel_dir=rel, txt_name=e.name,
            artist=(song.header("ARTIST") or "").strip(),
            title=(song.header("TITLE") or "").strip(),
            audio=present("AUDIO") or present("MP3"),
            instrumental=present("INSTRUMENTAL"),
            cover=present("COVER"),
            is_duet=bool(song.is_duet),
            mtime=e.mtime or None,
        )
