"""Выбор хранилища по id и кэш открытых ``Storage`` — общее правило веба и воркера.

``AppContext`` (web) и ``JobContext`` (worker) держат по ``StorageRegistry`` и зовут его:
id любого формата (новый ``t_…``/``local`` или прежний ``smb://…``/``local:/output…``),
``None`` — основная цель; хранилище, удалённое из настроек, — ``StorageError``. Открытое
хранилище живёт в кэше, пока конфиг ``Target`` тот же; при смене конфига старое закрывается.
"""

from __future__ import annotations

import threading
from typing import Callable

from ..db import LOCAL_TARGET_ID, Settings, Target
from .base import Storage, StorageError


def deleted_target_error(target_id: str) -> StorageError:
    return StorageError(f"Хранилище «{target_id}» удалено из настроек")


class StorageRegistry:
    """``StorageRegistry(settings, factory)``: ``settings()`` — ``Settings`` текущего потока,
    ``factory(target)`` — открыть ``Storage`` (контексты передают свою ``storage_factory``)."""

    def __init__(self, settings: Callable[[], Settings], factory: Callable[[Target], Storage]):
        self._settings = settings
        self._factory = factory
        self._lock = threading.Lock()
        self._open: dict[str, tuple[Target, Storage]] = {}  # id → (конфиг, Storage)

    # ------------------------------------------------------------------ выбор

    def targets(self) -> list[Target]:
        return self._settings().get_targets()

    def default_target(self) -> Target:
        settings = self._settings()
        return settings.get_target(settings.get_default_target_id()) or settings.get_targets()[0]

    def target_of(self, target_id: str | None) -> Target:
        """Хранилище по id любого формата; ``None`` — основная цель.
        Удалено из настроек — ``StorageError``."""
        if target_id is None:
            return self.default_target()
        settings = self._settings()
        target = settings.get_target(settings.resolve_target_id(target_id))
        if target is None:
            raise deleted_target_error(target_id)
        return target

    def migrate(self, trash) -> None:
        """Список хранилищ (миграция со старой «папки результата») и корзина на новые id."""
        settings = self._settings()
        settings.get_targets()
        trash.retarget(settings.resolve_target_id)

    # ------------------------------------------------------------------ кэш

    def storage(self, target_id: str | None = None) -> Storage:
        """Открытое хранилище по id (``None`` — основная цель); кэш, пока конфиг тот же."""
        target = self.target_of(target_id)
        with self._lock:
            cached = self._open.get(target.id)
            if cached is not None and cached[0] == target:
                return cached[1]
            if cached is not None:
                _close(cached[1])
            storage = self._factory(target)
            self._open[target.id] = (target, storage)
            return storage

    def local_storage(self) -> Storage:
        return self.storage(LOCAL_TARGET_ID)

    def reset(self, target_id: str | None = None) -> list[str]:
        """Закрыть открытые хранилища — все или одно; вернуть id, которых это касалось
        (для одного — всегда ``[target_id]``, даже если оно не было открыто)."""
        with self._lock:
            ids = [target_id] if target_id else list(self._open)
            for tid in ids:
                cached = self._open.pop(tid, None)
                if cached is not None:
                    _close(cached[1])
            return ids


def _close(storage: Storage) -> None:
    try:
        storage.close()
    except Exception:  # noqa: BLE001
        pass
