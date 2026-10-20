"""Samba-шара через smbprotocol/smbclient прямо из контейнера.

Учётка передаётся в каждый вызов (smbclient сам переподключится после обрыва),
соединения живут в собственном кэше экземпляра — смена цели в настройках не
смешивается со старой сессией. Любая ошибка превращается в ``StorageError``
с русским сообщением; пароль вычищается из всех сообщений.
"""

from __future__ import annotations

import logging
import stat as stat_mod
from contextlib import contextmanager

from .base import Entry, Storage, StorageError, StorageNotFound

log = logging.getLogger(__name__)


def _ntstatus(exc: BaseException) -> int | None:
    for attr in ("ntstatus", "status"):
        try:
            value = getattr(exc, attr, None)
        except Exception:  # SMBResponseException.status читает заголовок
            value = None
        if isinstance(value, int):
            return value
    return None


class SmbStorage(Storage):
    def __init__(self, host: str, share: str, base_path: str = "", user: str = "",
                 password: str | None = None, *, port: int = 445, target_id: str | None = None,
                 label: str | None = None, client=None, timeout: int = 10):
        self.host = (host or "").strip().strip("\\/")
        self.share = (share or "").strip().strip("\\/")
        self.base_parts = [p for p in (base_path or "").replace("\\", "/").split("/") if p]
        self.user = user or ""
        self._pw = password or None
        self.port = port
        self.timeout = timeout
        base = "/".join(self.base_parts)
        self.target_id = target_id or f"smb://{self.host}/{self.share}/{base}".rstrip("/")
        self.label = label or f"//{self.host}/{self.share}/{base}".rstrip("/")
        if client is None:
            import smbclient as client  # noqa: PLC0415 — тяжёлый импорт только для SMB
        self._c = client
        self._cache: dict = {}
        self._registered = False

    def __repr__(self) -> str:  # без пароля
        return f"SmbStorage({self.label!r}, user={self.user!r})"

    # ----------------------------------------------------------------- соединение

    @property
    def _kw(self) -> dict:
        return {"username": self.user or None, "password": self._pw, "port": self.port,
                "connection_timeout": self.timeout, "connection_cache": self._cache}

    def _unc(self, rel: str) -> str:
        parts = [self.host, self.share, *self.base_parts, *(p for p in rel.split("/") if p)]
        return "\\\\" + "\\".join(parts)

    def _connect(self) -> None:
        if self._registered:
            return
        if not self.host or not self.share:
            raise StorageError("Не задан хост или шара Samba")
        with self._errors(""):
            self._c.register_session(self.host, username=self.user or None,
                                     password=self._pw, port=self.port,
                                     connection_timeout=self.timeout,
                                     connection_cache=self._cache)
        self._registered = True

    def close(self) -> None:
        reset = getattr(self._c, "reset_connection_cache", None)
        if reset is not None:
            try:
                reset(connection_cache=self._cache)
            except Exception:
                pass
        self._registered = False

    # ----------------------------------------------------------------- ошибки

    def _scrub(self, text: str) -> str:
        if self._pw:
            text = text.replace(self._pw, "***")
        return text

    def _translate(self, exc: BaseException, rel: str) -> StorageError:
        from smbprotocol.exceptions import SMBAuthenticationError, SMBConnectionClosed, SMBException
        from smbprotocol.header import NtStatus

        where = f"//{self.host}/{self.share}"
        status = _ntstatus(exc)

        def codes(*names: str) -> set[int]:
            return {int(getattr(NtStatus, n)) for n in names if hasattr(NtStatus, n)}

        auth = codes("STATUS_LOGON_FAILURE", "STATUS_ACCOUNT_DISABLED", "STATUS_ACCOUNT_RESTRICTION",
                     "STATUS_PASSWORD_EXPIRED", "STATUS_ACCOUNT_LOCKED_OUT", "STATUS_WRONG_PASSWORD")
        not_found = codes("STATUS_OBJECT_NAME_NOT_FOUND", "STATUS_OBJECT_PATH_NOT_FOUND",
                          "STATUS_NO_SUCH_FILE", "STATUS_NOT_FOUND")
        if isinstance(exc, SMBAuthenticationError) or status in auth:
            return StorageError(f"Неверный логин или пароль Samba для {where}")
        if status in codes("STATUS_BAD_NETWORK_NAME"):
            return StorageError(f"Шара «{self.share}» не найдена на {self.host}")
        if status in not_found:
            return StorageNotFound(f"Не найдено на шаре {where}: {rel or '/'.join(self.base_parts) or '/'}")
        if status in codes("STATUS_ACCESS_DENIED"):
            return StorageError(f"Нет доступа на шаре {where}: {rel or '/'}")
        if status in codes("STATUS_OBJECT_NAME_COLLISION"):
            return StorageError(f"Уже существует на шаре {where}: {rel}")
        if isinstance(exc, SMBConnectionClosed):
            self.close()
            return StorageError(f"Соединение с {self.host} прервано")
        unreachable = (isinstance(exc, ValueError) and "connect" in str(exc).lower()) or (
            isinstance(exc, OSError) and not isinstance(exc, SMBException))
        if unreachable:
            self.close()
            return StorageError(f"Хост {self.host} недоступен (нет связи по SMB)")
        detail = self._scrub(str(exc)) or type(exc).__name__
        return StorageError(f"Ошибка Samba ({where}): {detail}")

    @contextmanager
    def _errors(self, rel: str):
        try:
            yield
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 — всё переводим в понятную ошибку
            err = self._translate(exc, rel)
            log.debug("SMB %s: %s → %s", self.label, type(exc).__name__, err)
            raise err from None

    # ----------------------------------------------------------------- примитивы

    def _call(self, rel: str, fn, *args, **kw):
        self._connect()
        with self._errors(rel):
            return fn(*args, **kw, **self._kw)

    def _scandir(self, rel):
        def run(path, **kw):
            out = []
            for d in self._c.scandir(path, **kw):
                st = d.stat()
                is_dir = d.is_dir()
                out.append(Entry(d.name, is_dir, 0 if is_dir else st.st_size, st.st_mtime))
            return out
        return self._call(rel, run, self._unc(rel))

    def _stat(self, rel):
        try:
            st = self._call(rel, self._c.stat, self._unc(rel))
        except StorageNotFound:
            return None
        name = rel.rsplit("/", 1)[-1]
        is_dir = stat_mod.S_ISDIR(st.st_mode)
        return Entry(name, is_dir, 0 if is_dir else st.st_size, st.st_mtime)

    def _open_read(self, rel):
        return self._call(rel, self._c.open_file, self._unc(rel), mode="rb")

    def _open_write(self, rel):
        return self._call(rel, self._c.open_file, self._unc(rel), mode="wb")

    def _replace(self, src, dst):
        self._call(dst, self._c.replace, self._unc(src), self._unc(dst))

    def _remove(self, rel):
        self._call(rel, self._c.remove, self._unc(rel))

    def _rmdir(self, rel):
        self._call(rel, self._c.rmdir, self._unc(rel))

    def _makedirs(self, rel):
        self._call(rel, self._c.makedirs, self._unc(rel), exist_ok=True)

    def _check_root(self):
        try:
            self._scandir("")
        except StorageNotFound:
            path = "/".join(self.base_parts)
            raise StorageError(f"Папка «{path}» не найдена на шаре //{self.host}/{self.share}") from None
