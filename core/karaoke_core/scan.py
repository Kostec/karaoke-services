"""Сканирование хранилища в индекс песен — общее у «Обновить» веба (``AppContext.rescan``)
и задания ``mirror`` воркера."""

from __future__ import annotations

from typing import Protocol

from .db import Library, LibraryItem, now
from .storage import Storage

__all__ = ["library_item", "scan_target"]


class _OwnSongs(Protocol):
    def by_rel_dir(self, rel_dir: str): ...


def library_item(entry, target_id: str, songs: _OwnSongs | None = None,
                 stamp: str | None = None) -> LibraryItem:
    """Строка индекса по найденной песне; ``songs`` — свои песни сервиса (``own_song_id``)."""
    own = songs.by_rel_dir(entry.rel_dir) if songs is not None else None
    return entry.to_library_item(target_id, own.id if own else None, stamp or now())


def scan_target(storage: Storage, library: Library, target_id: str, *,
                songs: _OwnSongs | None = None) -> list[LibraryItem]:
    """Пересканировать хранилище целиком и заменить его строки индекса. Хранилище
    недоступно — ``StorageError`` наружу, индекс не трогается."""
    entries = storage.list_songs()
    stamp = now()
    items = [library_item(e, target_id, songs, stamp) for e in entries]
    library.replace_all(target_id, items)
    return items
