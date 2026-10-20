"""Папка результата на диске контейнера (обычно внутри примонтированного ``/output``)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from ..db import local_label, local_target_id
from .base import Entry, GuardedFile, Storage, StorageError, StorageNotFound


class LocalStorage(Storage):
    def __init__(self, root: str | Path, *, target_id: str | None = None, label: str | None = None):
        self.root = Path(root)
        self.target_id = target_id or local_target_id(self.root.as_posix())
        self.label = label or local_label(self.root.as_posix())

    def _abs(self, rel: str) -> Path:
        return self.root.joinpath(*rel.split("/")) if rel else self.root

    @contextmanager
    def _errors(self, rel: str):
        try:
            yield
        except StorageError:
            raise
        except FileNotFoundError:
            raise StorageNotFound(f"Не найдено в папке результата: {rel or self.label}") from None
        except PermissionError:
            raise StorageError(f"Нет доступа к папке результата: {rel or self.label}") from None
        except OSError as e:
            raise StorageError(f"Ошибка папки результата ({rel or self.label}): "
                               f"{e.strerror or type(e).__name__}") from None

    def _scandir(self, rel):
        with self._errors(rel):
            out = []
            with os.scandir(self._abs(rel)) as it:
                for d in it:
                    st = d.stat()
                    is_dir = d.is_dir()
                    out.append(Entry(d.name, is_dir, 0 if is_dir else st.st_size, st.st_mtime))
            return out

    def _stat(self, rel):
        with self._errors(rel):
            p = self._abs(rel)
            try:
                st = p.stat()
            except FileNotFoundError:
                return None
            return Entry(p.name, p.is_dir(), st.st_size, st.st_mtime)

    def _open_read(self, rel):
        with self._errors(rel):
            if self._abs(rel).is_dir():
                raise StorageError(f"Это папка, а не файл: {rel}")
            return GuardedFile(open(self._abs(rel), "rb"), self._errors, rel)

    def _open_write(self, rel):
        with self._errors(rel):
            return GuardedFile(open(self._abs(rel), "wb"), self._errors, rel)

    def _replace(self, src, dst):
        with self._errors(dst):
            os.replace(self._abs(src), self._abs(dst))

    def _remove(self, rel):
        with self._errors(rel):
            os.remove(self._abs(rel))

    def _rmdir(self, rel):
        with self._errors(rel):
            os.rmdir(self._abs(rel))

    def _makedirs(self, rel):
        with self._errors(rel):
            self._abs(rel).mkdir(parents=True, exist_ok=True)

    def _check_root(self):
        if not self.root.is_dir():
            raise StorageError(f"Папка не найдена: {self.label}")
