"""Состояние приложения: БД, папка результата, корзина, индекс песен, ошибки API."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Mapping

from karaoke_core import naming
from karaoke_core.paths import DataPaths
from karaoke_core.db import Jobs, Library, LibraryItem, OutputTarget, Settings, Songs, connect, now
from karaoke_core.storage import Storage, StorageError, make_storage
from karaoke_core.trash import Trash

STATUS_TTL = 15.0  # с: как часто реально проверять доступность папки результата


class ApiError(Exception):
    """Ошибка API: ``{"detail": "<по-русски>", ...extra}`` с кодом ``status``."""

    def __init__(self, status: int, detail: str, **extra):
        super().__init__(detail)
        self.status, self.detail, self.extra = status, detail, extra


def not_found(what: str = "Не найдено") -> ApiError:
    return ApiError(404, what)


class AppContext:
    def __init__(self, data_dir: str | Path, *, env: Mapping[str, str] | None = None,
                 storage_factory: Callable[[OutputTarget], Storage] | None = None,
                 trash: Trash | None = None):
        self.env = dict(os.environ if env is None else env)
        self.paths = DataPaths(data_dir)
        self.data_dir = self.paths.root
        self.storage_factory = storage_factory or make_storage
        self.trash = trash or Trash(self.paths.trash, days=self.int_env("TRASH_DAYS", 30))
        self._local = threading.local()
        self._lock = threading.Lock()
        self._storage: tuple[str, Storage] | None = None
        self._probe: dict[str, tuple[float, str | None]] = {}
        self._scan_lock = threading.Lock()
        self.scan_state: dict[str, dict] = {}

    # ------------------------------------------------------------------ окружение

    def int_env(self, key: str, default: int) -> int:
        try:
            return int(str(self.env.get(key, "")).strip() or default)
        except ValueError:
            return default

    @property
    def password(self) -> str:
        return self.env.get("WEB_PASSWORD", "") or ""

    @property
    def max_upload_mb(self) -> int:
        return self.int_env("MAX_UPLOAD_MB", 50)

    # ------------------------------------------------------------------ БД

    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = connect(self.paths.db)
        return c

    @property
    def jobs(self) -> Jobs:
        return Jobs(self.conn())

    @property
    def library(self) -> Library:
        return Library(self.conn())

    @property
    def songs(self) -> Songs:
        return Songs(self.conn())

    @property
    def settings(self) -> Settings:
        return Settings(self.conn(), self.env)

    def target(self) -> OutputTarget:
        return self.settings.get_output()

    def gpu_status(self) -> dict:
        raw = self.settings.get_gpu_status()
        if raw is None:
            return {"ok": None, "name": None, "vram_mb": None,
                    "error": "Воркер ещё не сообщил статус GPU"}
        return {k: raw.get(k) for k in ("ok", "name", "vram_mb", "error")}

    # ------------------------------------------------------------------ папка результата

    def storage(self) -> Storage:
        target = self.target()
        key = tuple(asdict(target).items())
        with self._lock:
            if self._storage is None or self._storage[0] != key:
                if self._storage is not None:
                    try:
                        self._storage[1].close()
                    except Exception:
                        pass
                self._storage = (key, self.storage_factory(target))
            return self._storage[1]

    def reset_storage(self) -> None:
        with self._lock:
            if self._storage is not None:
                try:
                    self._storage[1].close()
                except Exception:
                    pass
            self._storage = None
            self._probe.clear()

    def output_status(self, *, fresh: bool = False) -> dict:
        """``{ok, label, error}``: доступен ли корень папки результата (кэш на STATUS_TTL)."""
        target = self.target()
        cached = self._probe.get(target.target_id)
        if fresh or cached is None or time.monotonic() - cached[0] > STATUS_TTL:
            try:
                st = self.storage().stat("")
                error = None if st is not None and st.is_dir else \
                    f"Папка результата недоступна: нет папки {target.label}"
            except StorageError as e:
                error = f"Папка результата недоступна: {e}"
            cached = self._probe[target.target_id] = (time.monotonic(), error)
        return {"ok": cached[1] is None, "label": target.label, "error": cached[1]}

    def mark_output_error(self, err: Exception) -> None:
        self._probe[self.target().target_id] = (time.monotonic(), f"Папка результата недоступна: {err}")

    # ------------------------------------------------------------------ индекс песен

    def rescan(self) -> None:
        """Пересканировать папку результата (фоново). Параллельно — только один скан."""
        if not self._scan_lock.acquire(blocking=False):
            return
        try:
            storage = self.storage()
            state = self.scan_state.setdefault(storage.target_id, {})
            state["running"] = True
            try:
                entries = storage.list_songs()
            except StorageError as e:
                state["error"] = str(e)
                self.mark_output_error(e)
                return
            stamp = now()
            items = [self.library_item(e, storage.target_id, stamp) for e in entries]
            self.library.replace_all(storage.target_id, items)
            state.update(scanned_at=stamp, error=None)
            self._probe.pop(storage.target_id, None)
        finally:
            self.scan_state.get(self.target().target_id, {}).pop("running", None)
            self._scan_lock.release()

    def library_item(self, entry, target_id: str, stamp: str | None = None) -> LibraryItem:
        own = self.songs.by_rel_dir(entry.rel_dir)
        return entry.to_library_item(target_id, own.id if own else None, stamp or now())

    def refresh_song(self, rel_dir: str) -> LibraryItem | None:
        """Точечно обновить индекс одной папки после наших изменений."""
        storage = self.storage()
        entry = storage.read_song(rel_dir)
        if entry is None:
            self.library.remove(storage.target_id, rel_dir)
            return None
        item = self.library_item(entry, storage.target_id)
        self.library.upsert(item)
        return item

    def scanned_at(self, target_id: str, items: list[LibraryItem]) -> str | None:
        st = self.scan_state.get(target_id, {})
        return st.get("scanned_at") or max((i.scanned_at or "" for i in items), default=None) or None

    def find_song(self, song_id: str) -> LibraryItem:
        target_id = self.storage().target_id
        for item in self.library.list(target_id):
            if item.song_id == song_id:
                return item
        raise not_found("Песня не найдена")

    def find_by_name(self, artist: str, title: str) -> LibraryItem | None:
        key, match = song_key(artist, title), match_key(artist, title)
        for item in self.library.list(self.storage().target_id):
            if item.rel_dir.casefold() == key or match_key(item.artist, item.title) == match:
                return item
        return None

    def song_dict(self, item: LibraryItem) -> dict:
        return {**item.to_dict(), "own": bool(item.own_song_id)}


def match_key(artist: str, title: str) -> tuple[str, str]:
    """Ключ «такая песня уже есть»: без учёта регистра и ё/е, запрещённые символы — как в
    naming.safe_name; пробелы и прочая пунктуация значимы («Ма-ма» ≠ «Мама»)."""
    def fold(s: str) -> str:
        return naming.safe_name((s or "").strip().casefold().replace("ё", "е"))
    return fold(artist), fold(title)


def song_key(artist: str, title: str) -> str:
    """Ключ сравнения песен: путь по правилам имён без учёта регистра."""
    return naming.song_dir(artist.strip(), title.strip()).casefold()

