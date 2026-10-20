"""Корзина в томе ``data``.

Раскладка::

    <DATA_DIR>/trash/<UTC>__<id>/<Исполнитель>/<Исполнитель - Название>/...
    <DATA_DIR>/trash/<UTC>__<id>/meta.json

Запись без ``meta.json`` считается недописанной и в списке не показывается.
Перенос: скопировать в том → сверить размеры → удалить у цели. Восстановление —
в обратном порядке. Версия файла (``save_version``) только копирует файл,
оригинал остаётся на месте.
"""

from __future__ import annotations

import builtins
import json
import math
import os
import secrets
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .storage import Storage, StorageError, StorageNotFound
from .storage.base import norm

META = "meta.json"
DEFAULT_DAYS = 30
OCCUPIED = "Сначала удалите или переименуйте существующую"
_STAMP = "%Y%m%dT%H%M%SZ"


class TrashError(Exception):
    """Ошибка корзины; ``str(e)`` — сообщение пользователю по-русски."""


@dataclass
class TrashItem:
    id: str
    deleted_at: str  # ISO-8601 UTC
    kind: str  # "song" — папка песни, "version" — старая версия одного файла
    rel_dir: str
    rel_file: str | None = None
    reason: str = ""
    target_id: str = ""
    target_label: str = ""
    artist: str = ""
    title: str = ""
    files: dict[str, int] = field(default_factory=dict)  # путь внутри rel_dir → байты
    path: str = ""  # папка записи в томе

    @property
    def deleted(self) -> datetime:
        return datetime.fromisoformat(self.deleted_at)

    @property
    def name(self) -> str:
        """Что удалено — ``<Исполнитель - Название>`` или имя файла версии."""
        if self.kind == "version" and self.rel_file:
            return self.rel_file.rsplit("/", 1)[-1]
        return self.rel_dir.rsplit("/", 1)[-1]

    def days_left(self, days: int | None = None, now: datetime | None = None) -> int:
        days = default_days() if days is None else days
        now = now or datetime.now(timezone.utc)
        left = (self.deleted + timedelta(days=days) - now).total_seconds()
        return max(0, math.ceil(left / 86400))

    def to_dict(self, days: int | None = None) -> dict:
        d = asdict(self)
        d.pop("path")
        d["name"] = self.name
        d["size"] = sum(self.files.values())
        d["days_left"] = self.days_left(days)
        return d


def default_root() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data")) / "trash"


def default_days() -> int:
    try:
        return int(os.environ.get("TRASH_DAYS", DEFAULT_DAYS))
    except ValueError:
        return DEFAULT_DAYS


def _local_sizes(base: Path) -> dict[str, int]:
    return {p.relative_to(base).as_posix(): p.stat().st_size
            for p in base.rglob("*") if p.is_file()}


class Trash:
    def __init__(self, root: str | Path | None = None, *, days: int | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.root = Path(root) if root is not None else default_root()
        self.days = default_days() if days is None else days
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ----------------------------------------------------------------- запись

    def _new_entry(self) -> tuple[str, datetime, Path]:
        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        item_id = secrets.token_hex(4)
        entry = self.root / f"{now.strftime(_STAMP)}__{item_id}"
        entry.mkdir(parents=True)
        return item_id, now, entry

    def _commit(self, entry: Path, item: TrashItem) -> TrashItem:
        item.path = str(entry)
        meta = asdict(item)
        meta.pop("path")
        tmp = entry / (META + ".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, entry / META)
        return item

    @staticmethod
    def _song_names(storage: Storage, rel_dir: str) -> tuple[str, str]:
        """Исполнитель и название из .txt песни (поиск .txt — в storage); нет — пусто."""
        try:
            song = storage.read_song(rel_dir) if rel_dir else None
        except StorageError:
            song = None  # имя для списка корзины — не повод отказать в удалении
        return (song.artist, song.title) if song else ("", "")

    def move_to_trash(self, storage: Storage, rel_dir: str, reason: str = "") -> TrashItem:
        """Перенести папку песни в корзину. У цели она удаляется только после
        того, как размеры всех файлов копии совпали с оригиналом."""
        rel_dir = norm(rel_dir)
        try:
            remote = storage.sizes(rel_dir)
        except StorageNotFound:
            raise TrashError(f"Песня не найдена в папке результата: {rel_dir}") from None
        except StorageError as e:
            raise TrashError(str(e)) from None
        artist, title = self._song_names(storage, rel_dir)
        item_id, now, entry = self._new_entry()
        try:
            dest = entry.joinpath(*rel_dir.split("/"))
            storage.download_dir(rel_dir, dest)
            if _local_sizes(dest) != remote:
                raise TrashError("Копия песни в корзине не совпала с оригиналом по размеру — "
                                 "песня не удалена")
            item = self._commit(entry, TrashItem(
                id=item_id, deleted_at=now.isoformat(), kind="song", rel_dir=rel_dir,
                reason=reason, target_id=storage.target_id, target_label=storage.label,
                artist=artist, title=title, files=remote))
        except BaseException as e:
            shutil.rmtree(entry, ignore_errors=True)
            if isinstance(e, StorageError):
                raise TrashError(str(e)) from None
            raise
        try:
            storage.delete_dir(rel_dir)
        except StorageError as e:
            raise TrashError(f"Копия в корзине сохранена, но удалить песню не удалось: {e}") from None
        return item

    def save_version(self, storage: Storage, rel_file: str, reason: str = "версия до изменения") -> TrashItem:
        """Сохранить текущую версию одного файла (оригинал остаётся на месте)."""
        rel_file = norm(rel_file)
        rel_dir, _, fname = rel_file.rpartition("/")
        item_id, now, entry = self._new_entry()
        try:
            dest = entry.joinpath(*rel_file.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            with storage.open_read(rel_file) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            original = storage.stat(rel_file)
            if original is None or original.size != dest.stat().st_size:
                raise TrashError("Копия файла в корзине не совпала с оригиналом по размеру")
            artist, title = self._song_names(storage, rel_dir)
            return self._commit(entry, TrashItem(
                id=item_id, deleted_at=now.isoformat(), kind="version", rel_dir=rel_dir,
                rel_file=rel_file, reason=reason, target_id=storage.target_id,
                target_label=storage.label, artist=artist, title=title,
                files={fname: dest.stat().st_size}))
        except BaseException as e:
            shutil.rmtree(entry, ignore_errors=True)
            if isinstance(e, StorageNotFound):
                raise TrashError(f"Файл не найден в папке результата: {rel_file}") from None
            if isinstance(e, StorageError):
                raise TrashError(str(e)) from None
            raise

    # ----------------------------------------------------------------- чтение

    def list(self) -> builtins.list[TrashItem]:
        """Все записи, новые первыми."""
        if not self.root.is_dir():
            return []
        items = []
        for entry in self.root.iterdir():
            item = self._load(entry)
            if item is not None:
                items.append(item)
        items.sort(key=lambda i: (i.deleted_at, i.path), reverse=True)
        return items

    def _load(self, entry: Path) -> TrashItem | None:
        meta = entry / META
        if not meta.is_file():
            return None
        try:
            data = json.loads(meta.read_text("utf-8"))
            return TrashItem(**data, path=str(entry))
        except (ValueError, TypeError):
            return None

    def get(self, item_id: str) -> TrashItem:
        for item in self.list():
            if item.id == item_id:
                return item
        raise TrashError("Запись в корзине не найдена")

    # ----------------------------------------------------------------- восстановление

    def restore(self, storage: Storage, item_id: str) -> TrashItem:
        """Вернуть запись на прежнее место у цели ``storage``.

        Папка песни: если на месте уже что-то есть — ``TrashError(OCCUPIED)``.
        Версия файла: текущий файл сначала сам уходит в корзину как версия,
        затем на его место встаёт сохранённый."""
        item = self.get(item_id)
        if item.target_id and item.target_id != storage.target_id:
            raise TrashError(f"Песня была удалена из другой папки результата: {item.target_label}. "
                             "Выберите эту папку в настройках, чтобы восстановить её")
        entry = Path(item.path)
        try:
            if item.kind == "version":
                self._restore_version(storage, item, entry)
            else:
                self._restore_song(storage, item, entry)
        except StorageError as e:
            raise TrashError(str(e)) from None
        shutil.rmtree(entry, ignore_errors=True)
        return item

    def _restore_song(self, storage: Storage, item: TrashItem, entry: Path) -> None:
        if storage.exists(item.rel_dir):
            raise TrashError(OCCUPIED)
        src = entry.joinpath(*item.rel_dir.split("/"))
        try:
            storage.upload_dir(src, item.rel_dir)
            if storage.sizes(item.rel_dir) != _local_sizes(src):
                raise TrashError("Восстановленная песня не совпала с копией по размеру")
        except BaseException:
            try:
                storage.delete_dir(item.rel_dir)  # места до нас не было — убираем недописанное
            except Exception:
                pass
            raise

    def _restore_version(self, storage: Storage, item: TrashItem, entry: Path) -> None:
        if storage.exists(item.rel_file):
            self.save_version(storage, item.rel_file, reason="заменено восстановленной версией")
        with open(entry.joinpath(*item.rel_file.split("/")), "rb") as f:
            storage.write_atomic(item.rel_file, f)

    # ----------------------------------------------------------------- очистка

    def purge(self, older_than_days: int | None = None, now: datetime | None = None) -> int:
        """Окончательно удалить записи старше N дней (по умолчанию ``TRASH_DAYS``).
        Возвращает число удалённых записей."""
        days = self.days if older_than_days is None else older_than_days
        limit = (now or self._clock()) - timedelta(days=days)
        removed = 0
        for item in self.list():
            if item.deleted < limit:
                shutil.rmtree(item.path, ignore_errors=True)
                removed += 1
        return removed


# --------------------------------------------------------------------------- модульный API

def move_to_trash(storage: Storage, rel_dir: str, reason: str = "") -> TrashItem:
    return Trash().move_to_trash(storage, rel_dir, reason)


def save_version(storage: Storage, rel_file: str, reason: str = "версия до изменения") -> TrashItem:
    return Trash().save_version(storage, rel_file, reason)


def list_items() -> builtins.list[TrashItem]:
    return Trash().list()


def restore(storage: Storage, item_id: str) -> TrashItem:
    return Trash().restore(storage, item_id)


def purge(older_than_days: int | None = None) -> int:
    return Trash().purge(older_than_days)


list = list_items  # noqa: A001 — имя из «Границ» спецификации: trash.list()
