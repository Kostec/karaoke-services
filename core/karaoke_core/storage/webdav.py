"""Сетевое хранилище WebDAV (Яндекс Диск — ``https://webdav.yandex.ru``, Nextcloud, NAS).

Все запросы — через ``karaoke_core.http.Http``: PROPFIND (Depth 0/1), GET потоком во временный
файл, PUT, MOVE (``Overwrite: T``), DELETE, MKCOL по цепочке. Запись идёт во временный файл и
уходит одним PUT при закрытии; ``write_atomic`` кладёт ``<имя>.part`` и переименовывает его
MOVE-ом. Ошибки — ``StorageError``/``StorageNotFound`` по-русски, пароль в них не попадает.

Здесь же общие для сетевых хранилищ помощники: ``UploadOnClose`` (буфер записи),
``download_temp`` (чтение во временный файл) и ``ListingCache`` (один листинг на папку
за время ``list_songs``).
"""

from __future__ import annotations

import base64
import email.utils
import os
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Callable

from ..http import HttpError
from .base import Entry, Storage, StorageBusy, StorageError, StorageNotFound

DAV = "{DAV:}"
PROPFIND_BODY = (b'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop>'
                 b"<d:resourcetype/><d:getcontentlength/><d:getlastmodified/></d:prop></d:propfind>")
MAX_LISTING_BYTES = 64 * 2**20
MAX_FILE_BYTES = 64 * 2**30   # потолок скачивания одного файла (видео бывает большим)
TIMEOUT = 60
WRONG_LOGIN = "Неверный логин или пароль приложения"


# --------------------------------------------------------------------------- общие помощники

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


# --------------------------------------------------------------------------- WebDAV

def _quote_parts(parts: list[str]) -> str:
    return "/".join(urllib.parse.quote(p, safe="") for p in parts)


def _parse_time(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return email.utils.parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


class WebDavStorage(ListingCache, Storage):
    """``WebDavStorage(url, user, password, path, *, http, target_id, label)``; ``path`` —
    папка внутри сервера (``Karaoke/Песни``)."""

    def __init__(self, url, user, password, path="", *, http, target_id: str = "", label: str = "",
                 tmp_dir: str | None = None):
        self.url = (url or "").strip().rstrip("/")
        self.user = user or ""
        self.base_parts = [p for p in (path or "").replace("\\", "/").split("/") if p]
        self.http = http
        self.tmp_dir = tmp_dir
        base = "/".join(self.base_parts)
        self.target_id = target_id or f"webdav:{self.url}/{base}"
        self.label = label or f"{self.url}/{base}"
        cred = f"{self.user}:{password or ''}".encode("utf-8")
        self._auth = "Basic " + base64.b64encode(cred).decode("ascii")
        self._root_path = urllib.parse.urlsplit(self.url).path.rstrip("/")
        self._known_dirs: set[str] = set()

    def __repr__(self) -> str:  # без пароля
        return f"WebDavStorage({self.label!r}, user={self.user!r})"

    # ----------------------------------------------------------------- адреса и запросы

    def _parts(self, rel: str) -> list[str]:
        return self.base_parts + [p for p in rel.split("/") if p]

    def _url(self, rel: str, *, is_dir: bool = False) -> str:
        parts = self._parts(rel)
        url = self.url + ("/" + _quote_parts(parts) if parts else "")
        return url + "/" if is_dir or not parts else url

    def _headers(self, extra: dict | None = None) -> dict:
        return {"Authorization": self._auth, **(extra or {})}

    def _call(self, method: str, url: str, *, headers: dict | None = None, data=None,
              max_bytes: int = 5 * 2**20):
        return self.http.request(method, url, data=data, headers=self._headers(headers),
                                 timeout=TIMEOUT, max_bytes=max_bytes)

    @contextmanager
    def _errors(self, rel: str):
        try:
            yield
        except StorageError:
            raise
        except HttpError as e:
            raise self._translate(e, rel) from None
        except OSError as e:
            raise StorageError(f"Ошибка временного файла ({rel or self.label}): "
                               f"{e.strerror or type(e).__name__}") from None

    def _translate(self, e: HttpError, rel: str) -> StorageError:
        if e.status in (401, 403):
            return StorageError(f"{WRONG_LOGIN} — хранилище «{self.label}»")
        if e.status == 404:
            return StorageNotFound(f"Не найдено в хранилище «{self.label}»: {rel or '/'}")
        if e.status == 423:
            return StorageBusy(f"Файл заблокирован на сервере: {rel}")
        if e.status == 507:
            return StorageError(f"В хранилище «{self.label}» закончилось место")
        if e.status is None:
            return StorageError(f"Хранилище недоступно: {e}")
        return StorageError(f"Хранилище «{self.label}» ответило ошибкой {e.status} ({rel or '/'})")

    # ----------------------------------------------------------------- PROPFIND

    def _propfind(self, rel: str, depth: str, *, is_dir: bool) -> list[tuple[list[str], Entry]]:
        resp = self._call("PROPFIND", self._url(rel, is_dir=is_dir), data=PROPFIND_BODY,
                          headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
                          max_bytes=MAX_LISTING_BYTES)
        try:
            root = ET.fromstring(resp.body)
        except ET.ParseError:
            raise StorageError(f"Хранилище «{self.label}» вернуло непонятный ответ") from None
        out = []
        for r in root.iter(f"{DAV}response"):
            href = (r.findtext(f"{DAV}href") or "").strip()
            path = urllib.parse.unquote(urllib.parse.urlsplit(href).path)
            parts = [p for p in path.split("/") if p]
            prop = None
            for ps in r.iter(f"{DAV}propstat"):
                if " 200 " in f"{ps.findtext(f'{DAV}status') or ''} ":
                    prop = ps.find(f"{DAV}prop")
                    break
            if prop is None:
                prop = r.find(f".//{DAV}prop")
            if prop is None:
                continue
            rt = prop.find(f"{DAV}resourcetype")
            is_coll = rt is not None and rt.find(f"{DAV}collection") is not None
            size = prop.findtext(f"{DAV}getcontentlength") or "0"
            entry = Entry(parts[-1] if parts else "", is_coll,
                          0 if is_coll else int(size) if size.strip().isdigit() else 0,
                          _parse_time(prop.findtext(f"{DAV}getlastmodified")))
            out.append((parts, entry))
        return out

    def _self_parts(self, rel: str) -> list[str]:
        root = [p for p in self._root_path.split("/") if p]
        return root + self._parts(rel)

    # ----------------------------------------------------------------- примитивы

    def _scandir(self, rel):
        return self._cached_scandir(rel, self._fetch_dir)

    def _fetch_dir(self, rel: str) -> list[Entry]:
        with self._errors(rel):
            own = self._self_parts(rel)
            items = self._propfind(rel, "1", is_dir=True)
            out = []
            for parts, entry in items:
                if parts == own:
                    if not entry.is_dir:
                        raise StorageError(f"Это файл, а не папка: {rel}")
                    continue
                if parts[:-1] == own and entry.name:
                    out.append(entry)
            self._known_dirs.add(rel)
            return out

    def _stat(self, rel):
        with self._errors(rel):
            try:
                items = self._propfind(rel, "0", is_dir=not rel)
            except HttpError as e:
                if e.status == 404:
                    return None
                raise
            if not items:
                return None
            entry = items[0][1]
            return Entry(rel.rsplit("/", 1)[-1], entry.is_dir, entry.size, entry.mtime)

    def _open_read(self, rel):
        with self._errors(rel):
            def fetch(dest: Path) -> None:
                self.http.download(self._url(rel), dest, max_bytes=MAX_FILE_BYTES, timeout=TIMEOUT,
                                   headers=self._headers())
            return download_temp(fetch, self.tmp_dir)

    def _open_write(self, rel):
        def commit(f: BinaryIO, size: int) -> None:
            with self._errors(rel):
                self._call("PUT", self._url(rel), data=f,
                           headers={"Content-Length": str(size),
                                    "Content-Type": "application/octet-stream"})
        with self._errors(rel):
            return UploadOnClose(commit, self.tmp_dir)

    def _replace(self, src, dst):
        with self._errors(dst):
            self._call("MOVE", self._url(src),
                       headers={"Destination": self._url(dst), "Overwrite": "T"})

    def _remove(self, rel):
        with self._errors(rel):
            self._call("DELETE", self._url(rel))

    def _rmdir(self, rel):
        with self._errors(rel):
            self._call("DELETE", self._url(rel, is_dir=True))
        self._known_dirs = {d for d in self._known_dirs if d != rel and not d.startswith(rel + "/")}
        if not rel:
            self._known_dirs.clear()

    def _makedirs(self, rel):
        """MKCOL по цепочке, начиная с папок пути хранилища; известные папки не трогаются."""
        parts = [p for p in rel.split("/") if p]
        if "" not in self._known_dirs:
            for i in range(1, len(self.base_parts) + 1):
                self._mkcol(self.url + "/" + _quote_parts(self.base_parts[:i]) + "/", "")
        for i in range(len(parts) + 1):
            sub = "/".join(parts[:i])
            if sub not in self._known_dirs:
                self._mkcol(self._url(sub, is_dir=True), sub)
                self._known_dirs.add(sub)

    def _mkcol(self, url: str, rel: str) -> None:
        with self._errors(rel):
            try:
                self._call("MKCOL", url)
            except HttpError as e:
                # 405 — папка уже есть; прочие ответы (кроме входа и сети) — переспросить PROPFIND-ом
                if e.status != 405:
                    if e.status in (None, 401, 403):
                        raise
                    items = self._call("PROPFIND", url, headers={"Depth": "0"}, data=PROPFIND_BODY)
                    if b"collection" not in items.body:
                        raise

    def _check_root(self):
        """Корень доступен; нет папки пути — создаётся цепочкой MKCOL (новая папка из «Настроек»)."""
        st = self._stat("")
        if st is None:
            self._makedirs("")
            st = self._stat("")
        if st is None or not st.is_dir:
            path = "/".join(self.base_parts) or "/"
            raise StorageError(f"Папка «{path}» не найдена в хранилище «{self.label}»")
