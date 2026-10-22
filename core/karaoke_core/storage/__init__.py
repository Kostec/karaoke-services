"""Хранилища песен: единый интерфейс ``Storage`` и реализации по типу хранилища.

``LocalStorage(root)`` — каталог в контейнере (``/output/...`` или ``/host/...``).
``SmbStorage(host, share, base_path, user, password)`` — Samba-шара через
``smbprotocol``/``smbclient`` прямо из контейнера.
``WebDavStorage`` (Яндекс Диск, Nextcloud, NAS) и ``GDriveStorage`` (Google Диск) — сетевые,
через ``karaoke_core.http.Http``.

Все пути — относительные POSIX-пути от корня хранилища
(``"<Исполнитель>/<Исполнитель - Название>/<файл>"``). Любая ошибка доступа
приходит как ``StorageError`` с понятным русским сообщением; пароль в
сообщения не попадает. ``Storage.target_id`` — ``Target.id`` хранилища.
"""

from __future__ import annotations

from typing import Callable

from ..db import Target
from .base import SongEntry, Storage, StorageBusy, StorageError, StorageNotFound
from .gdrive import GDriveStorage
from .local import LocalStorage
from .smb import SmbStorage
from .webdav import WebDavStorage

__all__ = ["Storage", "SongEntry", "StorageError", "StorageNotFound", "StorageBusy",
           "LocalStorage", "SmbStorage", "WebDavStorage", "GDriveStorage", "make_storage", "STORAGE_KINDS"]


def _local(target: Target, http=None) -> Storage:
    return LocalStorage(target.path or "/output", target_id=target.id, label=target.label)


def _smb(target: Target, http=None) -> Storage:
    return SmbStorage(target.host, target.share, target.path, target.user, target.secret,
                      target_id=target.id, label=target.label)


def _webdav(target: Target, http=None) -> Storage:
    return WebDavStorage(target.url, target.user, target.secret, target.path, http=_need_http(http),
                         target_id=target.id, label=target.label)


def _gdrive(target: Target, http=None) -> Storage:
    return GDriveStorage(target.client_id, target.secret, target.token, target.path,
                         http=_need_http(http), target_id=target.id, label=target.label)


def _need_http(http):
    if http is None:  # контексты передают свой Http; прямой вызов без него — стандартный
        from ..http import Http
        return Http()
    return http


# Точка расширения: kind → фабрика(target, http). 
STORAGE_KINDS: dict[str, Callable[..., Storage]] = {"local": _local, "smb": _smb, "webdav": _webdav,
                                                    "gdrive": _gdrive}


def make_storage(target: Target, *, http=None) -> Storage:
    """Хранилище для ``Target`` из настроек; ``http`` — ``karaoke_core.http.Http``
    для сетевых хранилищ (контексты передают свой)."""
    factory = STORAGE_KINDS.get(target.kind)
    if factory is None:
        raise StorageError(f"Неизвестный тип хранилища: «{target.kind}»")
    return factory(target, http)
