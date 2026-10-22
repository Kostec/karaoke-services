"""Сетевое хранилище Google Диск (Drive REST v3) через ``karaoke_core.http.Http``.

Путь → id папок с кэшем на время жизни объекта (листинг папки заодно запоминает id детей),
``files.list`` с ``q``, скачивание ``alt=media`` во временный файл, загрузка — resumable
(создание или обновление существующего файла с тем же именем, чтобы не плодить дубли),
``_replace`` — смена имени/родителя (файл с тем же именем в цели удаляется), удаление —
``files.delete``. Access-токен обновляется по refresh-токену при 401 или истечении; новый
access-токен в БД не пишется. Токен OAuth — строка JSON ``{access_token, refresh_token, expiry}``
(``expiry`` — секунды Unix), её выдаёт ``GDriveStorage.exchange_code``; голая строка
считается refresh-токеном.
"""

from __future__ import annotations

import json
import secrets
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from ..http import HttpError
from .base import Entry, Storage, StorageError, StorageNotFound
from .webdav import MAX_FILE_BYTES, ListingCache, UploadOnClose, download_temp

API = "https://www.googleapis.com/drive/v3/files"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
OAUTH_URL = "https://oauth2.googleapis.com/token"
FOLDER = "application/vnd.google-apps.folder"
FIELDS = "id,name,mimeType,size,modifiedTime"
PAGE_SIZE = 1000
TIMEOUT = 60
EXPIRY_MARGIN_S = 60
RATE_LIMITED = "Google Диск: превышен лимит запросов, попробуйте позже"
RATE_DELAYS = (1, 2, 4)        # паузы перед повторами после 429 / 403 rateLimitExceeded
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
SLEEP = time.sleep             # подменяется в тестах
REVOKED = "Google Диск: доступ отозван — подключите заново в «Настройках»"


def _q(value: str) -> str:
    """Строка для ``q`` Drive: обратная косая и апостроф экранируются."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _mtime(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _entry(meta: dict) -> Entry:
    is_dir = meta.get("mimeType") == FOLDER
    size = str(meta.get("size") or "0")
    return Entry(meta.get("name", ""), is_dir, 0 if is_dir else int(size) if size.isdigit() else 0,
                 _mtime(meta.get("modifiedTime")))


def _rate_limited(e: HttpError) -> bool:
    """429 или 403 с причиной ``rateLimitExceeded``/``userRateLimitExceeded`` в теле ответа."""
    if e.status == 429:
        return True
    if e.status != 403 or not getattr(e, "body", b""):
        return False
    try:
        err = json.loads(e.body).get("error") or {}
    except (ValueError, AttributeError):
        return False
    reasons = {x.get("reason") for x in (err.get("errors") or []) if isinstance(x, dict)}
    if isinstance(err.get("status"), str) and err["status"] == "RESOURCE_EXHAUSTED":
        reasons.add("rateLimitExceeded")
    return bool(reasons & RATE_REASONS)


def _oauth_form(client_id: str, client_key: str, **fields) -> dict:
    form = {"client_id": client_id, "client_secret": client_key}
    form.update(fields)
    return form


class GDriveStorage(ListingCache, Storage):
    """``GDriveStorage(client_id, client_secret, token_json, path, *, http, target_id, label)``
    (аргументы позиционные); ``path`` — папка на «Моём диске» (``Karaoke/Песни``)."""

    def __init__(self, client_id, client_key, oauth_json, path="", *, http, target_id: str = "",
                 label: str = "", tmp_dir: str | None = None):
        self.client_id = client_id or ""
        self._ck = client_key or ""
        self.base_parts = [p for p in (path or "").replace("\\", "/").split("/") if p]
        self.http = http
        self.tmp_dir = tmp_dir
        base = "/".join(self.base_parts)
        self.target_id = target_id or f"gdrive:{base}"
        self.label = label or f"Google Диск/{base}"
        self._access, self._rt, self._expiry = self._parse_oauth(oauth_json)
        self._meta: dict[str, dict] = {"": {"id": "root", "name": "", "mimeType": FOLDER}}

    def __repr__(self) -> str:  # без секрета и токенов
        return f"GDriveStorage({self.label!r})"

    @staticmethod
    def _parse_oauth(raw) -> tuple[str, str, float]:
        raw = (raw or "").strip() if isinstance(raw, str) else raw
        if not raw:
            return "", "", 0.0
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except ValueError:
            return "", raw, 0.0
        if not isinstance(data, dict):
            return "", str(raw), 0.0
        try:
            expiry = float(data.get("expiry") or 0)
        except (TypeError, ValueError):
            expiry = 0.0
        return data.get("access_token") or "", data.get("refresh_token") or "", expiry

    # ----------------------------------------------------------------- OAuth

    @staticmethod
    def exchange_code(http, client_id, client_secret, code, redirect_uri) -> str:
        """Код из возврата Google → строка JSON ``{access_token, refresh_token, expiry}``.
        Отказ Google или нет refresh-токена — ``StorageError`` «Google не дал доступ: …»."""
        form = _oauth_form(client_id, client_secret, code=code, redirect_uri=redirect_uri,
                           grant_type="authorization_code")
        try:
            resp = http.request("POST", OAUTH_URL, data=form, timeout=TIMEOUT)
            data = json.loads(resp.body)
        except HttpError as e:
            raise StorageError(f"Google не дал доступ: {e}") from None
        except ValueError:
            raise StorageError("Google не дал доступ: непонятный ответ сервера") from None
        if not data.get("refresh_token"):
            raise StorageError("Google не дал доступ: нет refresh-токена — удалите доступ приложения "
                               "в аккаунте Google и войдите заново")
        return json.dumps({"access_token": data.get("access_token") or "",
                           "refresh_token": data["refresh_token"],
                           "expiry": time.time() + float(data.get("expires_in") or 0)})

    def _refresh_access(self) -> None:
        if not self._rt:
            raise StorageError(REVOKED)
        form = _oauth_form(self.client_id, self._ck, grant_type="refresh_token")
        form["refresh_token"] = self._rt
        try:
            resp = self.http.request("POST", OAUTH_URL, data=form, timeout=TIMEOUT)
            data = json.loads(resp.body)
        except HttpError as e:
            if e.status is None:
                raise StorageError(f"Хранилище недоступно: {e}") from None
            raise StorageError(REVOKED) from None
        except ValueError:
            raise StorageError(REVOKED) from None
        if not data.get("access_token"):
            raise StorageError(REVOKED)
        self._access = data["access_token"]
        self._expiry = time.time() + float(data.get("expires_in") or 3600)

    def _auth(self) -> dict:
        if not self._access or (self._expiry and self._expiry < time.time() + EXPIRY_MARGIN_S):
            self._refresh_access()
        return {"Authorization": f"Bearer {self._access}"}

    def _authed(self, call):
        """``call(headers)`` с авторизацией и повторами при превышении лимита запросов
        (паузы ``RATE_DELAYS``; не помогло — ``StorageError`` ``RATE_LIMITED``)."""
        for delay in (*RATE_DELAYS, None):
            try:
                return self._authed_once(call)
            except HttpError as e:
                if not _rate_limited(e):
                    raise
                if delay is None:
                    raise StorageError(RATE_LIMITED) from None
            SLEEP(delay)

    def _authed_once(self, call):
        """``call(headers)`` с авторизацией; 401 — обновить access-токен и повторить один раз."""
        try:
            return call(self._auth())
        except HttpError as e:
            if e.status != 401:
                raise
        self._refresh_access()
        try:
            return call(self._auth())
        except HttpError as e:
            if e.status == 401:
                raise StorageError(REVOKED) from None
            raise

    def _req(self, method: str, url: str, *, params: dict | None = None, body: dict | None = None,
             data=None, headers: dict | None = None, max_bytes: int = 16 * 2**20):
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json; charset=UTF-8", **(headers or {})}

        def call(auth: dict):
            if hasattr(data, "seek"):
                data.seek(0)
            return self.http.request(method, url, params=params, data=data,
                                     headers={**auth, **(headers or {})}, timeout=TIMEOUT,
                                     max_bytes=max_bytes)
        return self._authed(call)

    def _json(self, *a, **kw) -> dict:
        resp = self._req(*a, **kw)
        try:
            return json.loads(resp.body) if resp.body else {}
        except ValueError:
            raise StorageError("Google Диск вернул непонятный ответ") from None

    @contextmanager
    def _errors(self, rel: str):
        try:
            yield
        except StorageError:
            raise
        except HttpError as e:
            if e.status == 404:
                raise StorageNotFound(f"Не найдено в хранилище «{self.label}»: {rel or '/'}") from None
            if e.status == 403:
                raise StorageError("Google Диск: нет доступа к файлу или превышен лимит запросов "
                                   f"({rel or '/'})") from None
            if e.status is None:
                raise StorageError(f"Хранилище недоступно: {e}") from None
            raise StorageError(f"Google Диск ответил ошибкой {e.status} ({rel or '/'})") from None
        except OSError as e:
            raise StorageError(f"Ошибка временного файла ({rel or self.label}): "
                               f"{e.strerror or type(e).__name__}") from None

    # ----------------------------------------------------------------- путь → id

    def _abs(self, rel: str) -> str:
        return "/".join(self.base_parts + [p for p in rel.split("/") if p])

    @staticmethod
    def _split(abs_path: str) -> tuple[str, str]:
        return (abs_path.rsplit("/", 1)[0], abs_path.rsplit("/", 1)[1]) if "/" in abs_path else ("", abs_path)

    def _list(self, query: str) -> list[dict]:
        out, page = [], None
        while True:
            params = {"q": query, "fields": f"nextPageToken,files({FIELDS})", "pageSize": PAGE_SIZE,
                      "spaces": "drive"}
            if page:
                params["pageToken"] = page
            data = self._json("GET", API, params=params)
            out.extend(data.get("files") or [])
            page = data.get("nextPageToken")
            if not page:
                return out

    def _lookup(self, abs_path: str) -> dict | None:
        """Метаданные файла/папки по пути от «Моего диска» (кэш); нет — ``None``."""
        if abs_path in self._meta:
            return self._meta[abs_path]
        parent_path, name = self._split(abs_path)
        parent = self._lookup(parent_path)
        if parent is None or parent.get("mimeType") != FOLDER:
            return None
        found = self._list(f"name='{_q(name)}' and '{parent['id']}' in parents and trashed=false")
        if not found:
            return None
        found.sort(key=lambda m: m.get("mimeType") != FOLDER)  # папка важнее одноимённого файла
        self._meta[abs_path] = found[0]
        return found[0]

    def _forget(self, abs_path: str) -> None:
        for k in [k for k in self._meta if k == abs_path or k.startswith(abs_path + "/")]:
            if k:
                del self._meta[k]

    def _need(self, rel: str) -> dict:
        meta = self._lookup(self._abs(rel))
        if meta is None:
            raise StorageNotFound(f"Не найдено в хранилище «{self.label}»: {rel or '/'}")
        return meta

    # ----------------------------------------------------------------- примитивы

    def _scandir(self, rel):
        return self._cached_scandir(rel, self._fetch_dir)

    def _fetch_dir(self, rel: str) -> list[Entry]:
        with self._errors(rel):
            meta = self._need(rel)
            if meta.get("mimeType") != FOLDER:
                raise StorageError(f"Это файл, а не папка: {rel}")
            base = self._abs(rel)
            out = []
            for child in self._list(f"'{meta['id']}' in parents and trashed=false"):
                name = child.get("name") or ""
                if not name or "/" in name:
                    continue
                key = f"{base}/{name}" if base else name
                if key not in self._meta or child.get("mimeType") == FOLDER:
                    self._meta[key] = child
                out.append(_entry(child))
            return out

    def _stat(self, rel):
        with self._errors(rel):
            meta = self._lookup(self._abs(rel))
            if meta is None:
                return None
            e = _entry(meta)
            return Entry(rel.rsplit("/", 1)[-1], e.is_dir, e.size, e.mtime)

    def _open_read(self, rel):
        with self._errors(rel):
            meta = self._need(rel)
            if meta.get("mimeType") == FOLDER:
                raise StorageError(f"Это папка, а не файл: {rel}")

            def fetch(dest: Path) -> None:
                self._authed(lambda auth: self.http.download(
                    f"{API}/{meta['id']}?alt=media", dest, max_bytes=MAX_FILE_BYTES, timeout=TIMEOUT,
                    headers=auth))
            return download_temp(fetch, self.tmp_dir)

    def _open_write(self, rel):
        def commit(f: BinaryIO, size: int) -> None:
            with self._errors(rel):
                self._upload(rel, f, size)
        with self._errors(rel):
            return UploadOnClose(commit, self.tmp_dir)

    def _upload(self, rel: str, f: BinaryIO, size: int) -> None:
        abs_path = self._abs(rel)
        parent_path, name = self._split(abs_path)
        existing = self._lookup(abs_path)
        params = {"uploadType": "resumable", "fields": FIELDS}
        if existing is not None and existing.get("mimeType") != FOLDER:
            resp = self._req("PATCH", f"{UPLOAD_API}/{existing['id']}", params=params, body={})
        else:
            parent = self._lookup(parent_path)
            if parent is None:
                raise StorageNotFound(f"Нет папки в хранилище «{self.label}»: {rel}")
            resp = self._req("POST", UPLOAD_API, params=params,
                             body={"name": name, "parents": [parent["id"]]})
        session = resp.headers.get("location")
        if not session:
            raise StorageError("Google Диск не начал загрузку файла")
        put = self._req("PUT", session, data=f,
                        headers={"Content-Length": str(size), "Content-Type": "application/octet-stream"})
        try:
            meta = json.loads(put.body)
        except ValueError:
            meta = None
        if isinstance(meta, dict) and meta.get("id"):
            self._meta[abs_path] = meta
        else:
            self._meta.pop(abs_path, None)

    def _replace(self, src, dst):
        """Перенос файла на место ``dst``. Прежний одноимённый файл сначала отодвигается
        (``<имя>.old-*``) и удаляется только после успешного переноса; сбой — возвращается."""
        with self._errors(dst):
            src_abs, dst_abs = self._abs(src), self._abs(dst)
            meta = self._need(src)
            old = self._lookup(dst_abs)
            if old is not None and old.get("id") == meta.get("id"):
                old = None
            if old is not None:
                _, dst_name0 = self._split(dst_abs)
                self._patch(old, {"name": f"{dst_name0}.old-{secrets.token_hex(4)}"})
                self._forget(dst_abs)
            try:
                new = self._move(meta, src_abs, dst_abs, dst)
            except BaseException:
                if old is not None:
                    try:
                        self._patch(old, {"name": dst_name0})
                        self._meta[dst_abs] = old
                    except Exception:
                        pass  # первая ошибка важнее
                raise
            self._forget(src_abs)
            self._meta[dst_abs] = new if new.get("id") else {**meta, "name": self._split(dst_abs)[1]}
            if old is not None:
                try:
                    self._req("DELETE", f"{API}/{old['id']}")
                except (HttpError, StorageError):
                    pass  # хвост «.old-*» не мешает: это не .txt песни

    def _patch(self, meta: dict, body: dict, params: dict | None = None) -> dict:
        return self._json("PATCH", f"{API}/{meta['id']}", params={"fields": FIELDS, **(params or {})},
                          body=body)

    def _move(self, meta: dict, src_abs: str, dst_abs: str, dst: str) -> dict:
        src_parent, _ = self._split(src_abs)
        dst_parent, dst_name = self._split(dst_abs)
        params = {}
        if src_parent != dst_parent:
            to = self._lookup(dst_parent)
            if to is None:
                raise StorageNotFound(f"Нет папки в хранилище «{self.label}»: {dst}")
            params.update(addParents=to["id"], removeParents=self._lookup(src_parent)["id"])
        return self._patch(meta, {"name": dst_name}, params)

    def _remove(self, rel):
        with self._errors(rel):
            meta = self._need(rel)
            try:
                self._req("DELETE", f"{API}/{meta['id']}")
            finally:
                self._forget(self._abs(rel))

    def _rmdir(self, rel):
        self._remove(rel)

    def _makedirs(self, rel):
        parts = self._abs(rel).split("/") if self._abs(rel) else []
        for i in range(1, len(parts) + 1):
            abs_path = "/".join(parts[:i])
            with self._errors(rel):
                meta = self._lookup(abs_path)
                if meta is not None:
                    if meta.get("mimeType") != FOLDER:
                        raise StorageError(f"На месте папки лежит файл: {abs_path}")
                    continue
                parent = self._lookup("/".join(parts[:i - 1]))
                self._meta[abs_path] = self._json(
                    "POST", API, params={"fields": FIELDS},
                    body={"name": parts[i - 1], "mimeType": FOLDER, "parents": [parent["id"]]})

    def _check_root(self):
        """Корень доступен; нет папки пути — создаётся (новая папка из «Настроек»)."""
        with self._errors(""):
            meta = self._lookup(self._abs(""))
        if meta is None:
            self._makedirs("")
            meta = self._lookup(self._abs(""))
        if meta is None or meta.get("mimeType") != FOLDER:
            path = "/".join(self.base_parts) or "/"
            raise StorageError(f"Папка «{path}» не найдена на Google Диске")
