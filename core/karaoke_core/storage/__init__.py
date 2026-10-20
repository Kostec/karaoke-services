"""Папка результата: единый интерфейс ``Storage`` и две реализации.

``LocalStorage(root)`` — каталог, примонтированный в контейнер (``/output/...``).
``SmbStorage(host, share, base_path, user, password)`` — Samba-шара через
``smbprotocol``/``smbclient`` прямо из контейнера.

Все пути — относительные POSIX-пути от корня папки результата
(``"<Исполнитель>/<Исполнитель - Название>/<файл>"``). Любая ошибка доступа
приходит как ``StorageError`` с понятным русским сообщением; пароль в
сообщения не попадает.
"""

from __future__ import annotations

from ..db import OutputTarget
from .base import SongEntry, Storage, StorageBusy, StorageError, StorageNotFound
from .local import LocalStorage
from .smb import SmbStorage

__all__ = ["Storage", "SongEntry", "StorageError", "StorageNotFound", "StorageBusy",
           "LocalStorage", "SmbStorage", "make_storage"]


def make_storage(target: OutputTarget) -> Storage:
    """Хранилище для цели из настроек (``Settings.get_output()``)."""
    if target.kind == "local":
        return LocalStorage(target.local_root, target_id=target.target_id, label=target.label)
    if target.kind == "smb":
        return SmbStorage(target.host, target.share, target.path, target.user, target.password,
                          target_id=target.target_id, label=target.label)
    raise StorageError(f"Неизвестный тип папки результата: «{target.kind}»")
