"""Хранилища песен: единый интерфейс ``Storage`` и реализации по типу хранилища.

``LocalStorage(root)`` — каталог в контейнере (``/output/...`` или ``/host/...``).
``SmbStorage(host, share, base_path, user, password)`` — Samba-шара через
``smbprotocol``/``smbclient`` прямо из контейнера.

Все пути — относительные POSIX-пути от корня хранилища
(``"<Исполнитель>/<Исполнитель - Название>/<файл>"``). Любая ошибка доступа
приходит как ``StorageError`` с понятным русским сообщением; пароль в
сообщения не попадает. ``Storage.target_id`` — ``Target.id`` хранилища.
"""

from __future__ import annotations

from typing import Callable

from ..db import Target
from .base import SongEntry, Storage, StorageBusy, StorageError, StorageNotFound
from .local import LocalStorage
from .smb import SmbStorage

__all__ = ["Storage", "SongEntry", "StorageError", "StorageNotFound", "StorageBusy",
           "LocalStorage", "SmbStorage", "make_storage", "STORAGE_KINDS"]


def _local(target: Target, http=None) -> Storage:
    return LocalStorage(target.path or "/output", target_id=target.id, label=target.label)


def _smb(target: Target, http=None) -> Storage:
    return SmbStorage(target.host, target.share, target.path, target.user, target.secret,
                      target_id=target.id, label=target.label)


# Точка расширения: kind → фабрика(target, http). WebDAV и Google Диск регистрируются здесь же.
STORAGE_KINDS: dict[str, Callable[..., Storage]] = {"local": _local, "smb": _smb}

_NOT_YET = {"webdav": "WebDAV", "gdrive": "Google Диск"}


def make_storage(target: Target, *, http=None) -> Storage:
    """Хранилище для ``Target`` из настроек; ``http`` — ``karaoke_core.http.Http``
    для сетевых хранилищ (контексты передают свой)."""
    factory = STORAGE_KINDS.get(target.kind)
    if factory is None:
        if target.kind in _NOT_YET:
            raise StorageError(f"Тип хранилища «{_NOT_YET[target.kind]}» ещё не поддерживается")
        raise StorageError(f"Неизвестный тип хранилища: «{target.kind}»")
    return factory(target, http)
