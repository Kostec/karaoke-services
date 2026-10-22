"""Общее для сетевых хранилищ (WebDAV, Google Диск): буфер записи, чтение во временный файл,
кэш листинга на время ``list_songs`` и перевод ошибок ``HttpError``/``OSError`` в
``StorageError``/``StorageNotFound``. Свои протоколы и свои статусы — в ``webdav.py``/``gdrive.py``.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Callable

from ..http import HttpError
from .base import Entry, StorageError, StorageNotFound

MAX_FILE_BYTES = 64 * 2**30   # потолок скачивания одного файла (видео бывает большим)


class UploadOnClose:
    """Файл записи сетевого хранилища: байты копятся во временном файле, при ``close()``
    вызывается ``commit(file, size)``. Выход из ``with`` по исключению — без отправки."""

    def __init__(self, commit: Callable[[BinaryIO, int], None], tmp_dir: str | None = None):
        self._commit = commit
        self._f = tempfile.TemporaryFile(dir=tmp_dir)
        self._done = False

    def write(self, b) -> int:
        try:
            return self._f.write(b)
        except OSError as e:
            raise StorageError(f"Не удалось записать временный файл: {e.strerror or e}") from None

    def close(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            size = self._f.tell()
            self._f.seek(0)
            self._commit(self._f, size)
        finally:
            self._f.close()

    def discard(self) -> None:
        self._done = True
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.close()
        else:
            self.discard()


def download_temp(fetch: Callable[[Path], None], tmp_dir: str | None = None) -> BinaryIO:
    """Открытый на чтение временный файл, заполненный ``fetch(path)``; имя сразу удаляется
    (файл живёт, пока открыт)."""
    fd, name = tempfile.mkstemp(prefix=".karaoke-dl-", dir=tmp_dir)
    os.close(fd)
    try:
        fetch(Path(name))
        return open(name, "rb")
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


class ListingCache:
    """Кэш ``_scandir`` на время ``list_songs``: каждая папка листается одним запросом."""

    _listing: dict | None = None

    def list_songs(self, max_depth: int = 4):
        self._listing = {}
        try:
            return super().list_songs(max_depth)
        finally:
            self._listing = None

    def _cached_scandir(self, rel: str, fetch: Callable[[str], list[Entry]]) -> list[Entry]:
        if self._listing is not None and rel in self._listing:
            return self._listing[rel]
        entries = fetch(rel)
        if self._listing is not None:
            self._listing[rel] = entries
        return entries


class NetErrors:
    """``with self._errors(rel)``: ``StorageError`` — как есть; ``HttpError`` — сначала свои
    статусы хранилища (``_own_error``), затем общие: 404 → ``StorageNotFound``, сеть/таймаут →
    «Хранилище недоступно», прочее — ``_status_error``; ``OSError`` — ошибка временного файла."""

    label: str = ""

    def _own_error(self, e: HttpError, rel: str) -> StorageError | None:
        return None

    def _status_error(self, e: HttpError, rel: str) -> StorageError:
        return StorageError(f"Хранилище «{self.label}» ответило ошибкой {e.status} ({rel or '/'})")

    def _http_error(self, e: HttpError, rel: str) -> StorageError:
        own = self._own_error(e, rel)
        if own is not None:
            return own
        if e.status == 404:
            return StorageNotFound(f"Не найдено в хранилище «{self.label}»: {rel or '/'}")
        if e.status is None:
            return StorageError(f"Хранилище недоступно: {e}")
        return self._status_error(e, rel)

    @contextmanager
    def _errors(self, rel: str):
        try:
            yield
        except StorageError:
            raise
        except HttpError as e:
            raise self._http_error(e, rel) from None
        except OSError as e:
            raise StorageError(f"Ошибка временного файла ({rel or self.label}): "
                               f"{e.strerror or type(e).__name__}") from None
