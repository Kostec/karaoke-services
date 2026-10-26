"""Состояние приложения: БД, папка результата, корзина, индекс песен, ошибки API."""

from __future__ import annotations

import os
import re
import shlex
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Mapping

from karaoke_core import musiclink, naming
from karaoke_core.naming import match_key  # noqa: F401 — реэкспорт (ключ дубля песни)
from karaoke_core.paths import DataPaths
from karaoke_core.http import Http
from karaoke_core.db import (LOCAL_TARGET_ID, Jobs, Library, LibraryItem, Settings, Songs, Tags,
                             Target, connect, now)
from karaoke_core.storage import Storage, StorageError, make_storage
from karaoke_core.storage.registry import StorageRegistry
from karaoke_core.trash import Trash

from .usdb import UsdbClient

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
                 storage_factory: Callable[[Target], Storage] | None = None,
                 trash: Trash | None = None, http: Http | None = None,
                 yandex_factory: Callable[[str], musiclink.YandexMusic] | None = None):
        self.env = dict(os.environ if env is None else env)
        self.paths = DataPaths(data_dir)
        self.data_dir = self.paths.root
        self.storage_factory = storage_factory or (lambda t: make_storage(t, http=self.http))
        self.trash = trash or Trash(self.paths.trash, days=self.int_env("TRASH_DAYS", 30))
        self.http = http or Http()  # исходящие запросы (LRCLIB …); в тестах — FakeHttp
        # Яндекс Музыка: фабрика клиента по токену; в тестах — фейк
        self.yandex_factory = yandex_factory or musiclink.YandexMusic
        self._local = threading.local()
        self._lock = threading.Lock()
        # выбор и кэш хранилищ; фабрика читается при каждом открытии (тесты её подменяют)
        self._registry = StorageRegistry(lambda: self.settings, lambda t: self.storage_factory(t))
        self._usdb: tuple[tuple[str, str], UsdbClient] | None = None  # (учётка, UsdbClient)
        self._probe: dict[str, tuple[float, str | None]] = {}
        self._scan_lock = threading.Lock()
        self._scan_queue_lock = threading.Lock()
        self._scan_queue: list[str] = []  # id хранилищ, ждущих скана
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

    def ytdlp_cmd(self) -> list[str]:
        """Команда yt-dlp из ``YTDLP_CMD``; пусто — ``python -m yt_dlp`` образа web."""
        raw = str(self.env.get("YTDLP_CMD", "") or "").strip()
        return shlex.split(raw) if raw else [sys.executable, "-m", "yt_dlp"]

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
    def tags(self) -> Tags:
        return Tags(self.conn())

    @property
    def settings(self) -> Settings:
        return Settings(self.conn(), self.env)

    def targets(self) -> list[Target]:
        return self._registry.targets()

    def default_target(self) -> Target:
        return self._registry.default_target()

    def target(self) -> Target:
        """Основная цель (куда выкладываются новые песни)."""
        return self.default_target()

    def target_of(self, target_id: str | None) -> Target:
        """Хранилище по id любого формата; ``None`` — основная цель.
        Удалено из настроек — ``StorageError``."""
        return self._registry.target_of(target_id)

    def migrate_targets(self) -> None:
        """Список хранилищ (миграция со старой «папки результата») и корзина на новые id."""
        self._registry.migrate(self.trash)

    def gpu_status(self) -> dict:
        raw = self.settings.get_gpu_status()
        if raw is None:
            return {"ok": None, "name": None, "vram_mb": None,
                    "error": "Воркер ещё не сообщил статус GPU"}
        return {k: raw.get(k) for k in ("ok", "name", "vram_mb", "error")}

    # ------------------------------------------------------------------ папка результата

    def storage(self, target_id: str | None = None) -> Storage:
        """Открытое хранилище по id (``None`` — основная цель); кэш по (id, конфиг)."""
        return self._registry.storage(target_id)

    def local_storage(self) -> Storage:
        return self._registry.local_storage()

    def reset_storage(self, target_id: str | None = None) -> None:
        """Закрыть открытые хранилища (все или одно) и забыть их статус."""
        for tid in self._registry.reset(target_id):
            self._probe.pop(tid, None)

    def _status(self, target: Target, fresh: bool) -> dict:
        cached = self._probe.get(target.id)
        if fresh or cached is None or time.monotonic() - cached[0] > STATUS_TTL:
            try:
                st = self.storage(target.id).stat("")
                error = (None if st is not None and st.is_dir
                         else f"Папка результата недоступна: нет папки {target.label}")
            except StorageError as e:
                error = f"Папка результата недоступна: {e}"
            cached = self._probe[target.id] = (time.monotonic(), error)
        return {"ok": cached[1] is None, "label": target.label, "error": cached[1],
                "id": target.id, "name": target.name}

    def output_status(self, *, fresh: bool = False, target_id: str | None = None) -> dict:
        """``{ok, label, error, id, name}`` хранилища (``None`` — основная цель; кэш на
        STATUS_TTL). Без ``target_id`` ещё ``default`` и ``local`` — оба хранилища."""
        try:
            target = self.target_of(target_id)
        except StorageError as e:
            return {"ok": False, "label": "", "error": f"Папка результата недоступна: {e}",
                    "id": target_id, "name": ""}
        status = self._status(target, fresh)
        if target_id is None:
            local = (status if target.id == LOCAL_TARGET_ID
                     else self._status(self.settings.get_target(LOCAL_TARGET_ID), fresh))
            status = {**status, "default": dict(status), "local": dict(local)}
        return status

    def mark_output_error(self, err: Exception, target_id: str | None = None) -> None:
        try:
            tid = self.target_of(target_id).id
        except StorageError:
            return
        self._probe[tid] = (time.monotonic(), f"Папка результата недоступна: {err}")

    # ------------------------------------------------------------------ usdb

    def usdb(self):
        """Клиент usdb сохранённой учётки (сессия живёт в памяти, пока учётка та же).
        Учётки нет — ``ApiError(400, code="usdb_no_account")``."""
        account = self.settings.get_usdb()
        if not account.configured:
            raise ApiError(400, "Впишите логин и пароль usdb в Настройках", code="usdb_no_account")
        key = (account.user, account.password or "")
        with self._lock:
            if self._usdb is None or self._usdb[0] != key:
                self._usdb = (key, UsdbClient(self.http, *key))
            return self._usdb[1]

    def reset_usdb(self) -> None:
        with self._lock:
            self._usdb = None

    # ------------------------------------------------------------------ Яндекс Музыка

    def yandex(self) -> musiclink.YandexMusic:
        """Клиент Яндекс Музыки по сохранённому токену.
        Токена нет — ``ApiError(400, code="yandex_no_token")``."""
        ym_key = self.settings.get_yandex()
        if not ym_key:
            raise ApiError(400, musiclink.MSG_NEED_LOGIN, code="yandex_no_token")
        return self.yandex_factory(ym_key)

    # ------------------------------------------------------------------ индекс песен

    def rescan(self, target_id: str | None = None) -> None:
        """Пересканировать хранилище ``target_id`` (``None`` — основная цель; фоново).
        Сканы идут по одному: просьба во время чужого скана встаёт в очередь и выполнится
        следом (до тех пор хранилище показывается как ``scanning``)."""
        try:
            tid = self.target_of(target_id).id
        except StorageError:
            return  # хранилища нет в настройках — сканировать нечего
        with self._scan_queue_lock:
            if tid not in self._scan_queue:
                self._scan_queue.append(tid)
            self.scan_state.setdefault(tid, {})["running"] = True
        while self._scan_lock.acquire(blocking=False):
            try:
                while True:
                    with self._scan_queue_lock:
                        if not self._scan_queue:
                            break
                        tid = self._scan_queue.pop(0)
                    self._scan_one(tid)
            finally:
                self._scan_lock.release()
            with self._scan_queue_lock:
                if not self._scan_queue:
                    return  # иначе очередь пополнили между выходом и освобождением — ещё круг

    def _scan_one(self, target_id: str) -> None:
        state = self.scan_state.setdefault(target_id, {})
        try:
            try:
                target = self.target_of(target_id)
            except StorageError:
                return  # удалили из настроек, пока ждало в очереди
            try:
                storage = self.storage(target.id)
                entries = storage.list_songs()
            except StorageError as e:
                state["error"] = str(e)
                self.mark_output_error(e, target.id)
                return
            stamp = now()
            items = [self.library_item(e, target.id, stamp) for e in entries]
            self.library.replace_all(target.id, items)
            state.update(scanned_at=stamp, error=None)
            self._probe.pop(target.id, None)
        finally:
            with self._scan_queue_lock:
                if target_id not in self._scan_queue:  # снова в очереди — по-прежнему «идёт»
                    state.pop("running", None)

    def library_item(self, entry, target_id: str, stamp: str | None = None) -> LibraryItem:
        own = self.songs.by_rel_dir(entry.rel_dir)
        return entry.to_library_item(target_id, own.id if own else None, stamp or now())

    def refresh_song(self, rel_dir: str, target_id: str | None = None) -> LibraryItem | None:
        """Точечно обновить индекс одной папки хранилища после наших изменений."""
        storage = self.storage(target_id)
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
        """Песня по id в любом хранилище из настроек."""
        item = self.library.find(song_id)
        if item is None or self.settings.get_target(item.target_id) is None:
            raise not_found("Песня не найдена")
        return item

    def find_by_name(self, artist: str, title: str) -> LibraryItem | None:
        key, match = song_key(artist, title), match_key(artist, title)
        for item in self.library.list(self.storage().target_id):
            if item.rel_dir.casefold() == key or match_key(item.artist, item.title) == match:
                return item
        return None

    def existing_song_id(self, artist: str, title: str) -> str | None:
        """id песни с таким исполнителем и названием в папке результата; недоступна — ``None``."""
        try:
            item = self.find_by_name(artist, title)
        except StorageError:
            return None
        return item.song_id if item else None

    def song_dict(self, item: LibraryItem) -> dict:
        return {**item.to_dict(), "own": bool(item.own_song_id)}


# Сетевой сбой yt-dlp (не «ссылка плохая», а «сеть/сайт недоступны») → 503.
_NETWORK_FAILURE = re.compile(
    r"unable to download (?:webpage|api page|json)|failed to resolve|name resolution|resolve host"
    r"|name or service not known|nodename nor servname|getaddrinfo|timed out"
    r"|connection (?:refused|reset|aborted|error)|network is unreachable|no route to host"
    r"|remote end closed|urlopen error", re.I)


def link_api_error(e: musiclink.MusicLinkError, field: str = "url") -> ApiError:
    """Ошибка ссылки на музыку → ответ API: сеть/недоступность — 503, нет токена — 400
    ``code="yandex_no_token"``, прочее — 400 с ``field``."""
    text = str(e)
    if text == musiclink.MSG_NEED_LOGIN:
        return ApiError(400, text, code="yandex_no_token")
    if text == musiclink.MSG_UNAVAILABLE or text.endswith("истекло время ожидания") or (
            text.startswith(musiclink.MSG_YTDLP) and _NETWORK_FAILURE.search(text)):
        return ApiError(503, text)
    return ApiError(400, text, field=field)


def song_key(artist: str, title: str) -> str:
    """Ключ сравнения песен: путь по правилам имён без учёта регистра."""
    return naming.song_dir(artist.strip(), title.strip()).casefold()
