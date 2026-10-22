"""Исходящие HTTP-запросы (LRCLIB, usdb, скачивание архивов) на стандартной библиотеке.

``urllib.request`` + ``http.cookiejar``: новой зависимости в образах нет. Ответ ограничен по
размеру (``max_bytes``), у запроса — таймаут; сетевые ошибки и статус ≥400 — ``HttpError``
с русским текстом (без тел запросов и паролей). Этот же класс — шов для тестов: веб
принимает любой объект с тем же интерфейсом (``create_app(http=...)``).
"""

from __future__ import annotations

import http.client
import http.cookiejar
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

USER_AGENT = "karaoke-services"
CHUNK = 64 * 1024
ERROR_BODY_BYTES = 64 * 1024  # сколько тела ответа с ошибкой сохраняется в HttpError.body
RETRY_DELAY_S = 1.0  # пауза перед единственным повтором GET/скачивания после сбоя связи

log = logging.getLogger("karaoke.http")


@dataclass(frozen=True)
class HttpResponse:
    status: int
    url: str                 # итоговый после редиректов
    headers: dict[str, str]  # ключи в нижнем регистре
    body: bytes


class HttpError(Exception):
    """Ошибка запроса; ``status`` — код HTTP или ``None`` (сеть, таймаут, размер);
    ``too_large`` — ответ больше ``max_bytes``; ``body`` — начало тела ответа с ошибкой
    (до 64 КБ: причина отказа API, например ``rateLimitExceeded`` у Google)."""

    def __init__(self, message: str, status: int | None = None, *, too_large: bool = False,
                 body: bytes = b""):
        super().__init__(message)
        self.status = status
        self.too_large = too_large
        self.body = body

    @property
    def retryable(self) -> bool:
        """Сбой связи или таймаут (не код HTTP и не размер) — идемпотентный запрос стоит повторить."""
        return self.status is None and not self.too_large


def _safe_url(url: str) -> str:
    """Адрес для лога: схема, хост, порт и путь — без query и учётки."""
    parts = urllib.parse.urlsplit(url)
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        port = ""
    return f"{parts.scheme}://{parts.hostname or ''}{port}{parts.path}"


def _network_error(message: str, url: str, exc: BaseException) -> HttpError:
    """Ошибка связи для пользователя; настоящая причина (тип, адрес) — в лог, без тел и паролей."""
    reason = getattr(exc, "reason", None)
    cause = reason if isinstance(reason, BaseException) else exc
    log.warning("HTTP %s: %s: %s", _safe_url(url), type(cause).__name__, cause)
    return HttpError(message)


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or url


class Http:
    def __init__(self, cookies: http.cookiejar.CookieJar | None = None):
        self._cookies = cookies
        handlers = [urllib.request.HTTPCookieProcessor(cookies)] if cookies is not None else []
        self._opener = urllib.request.build_opener(*handlers)

    def session(self) -> "Http":
        """Копия со своей cookie-банкой (сессия входа на сайт)."""
        return Http(http.cookiejar.CookieJar())

    def request(self, method: str, url: str, *, params: dict | None = None,
                data: dict | bytes | BinaryIO | None = None, headers: dict | None = None,
                timeout: float = 10, max_bytes: int = 5 * 2**20) -> HttpResponse:
        """Любой метод (в т.ч. PROPFIND/MOVE/MKCOL/PATCH); ``data`` — форма, байты или открытый
        двоичный файл (тело уходит потоком, ``Content-Length`` задаёт вызывающий)."""
        def once() -> HttpResponse:
            with self._open(method, url, params, data, headers, timeout) as resp:
                return self._response(resp, self._read(resp, url, max_bytes, sink=None))
        return self._retry(once, url) if method.upper() in ("GET", "HEAD") else once()

    def download(self, url: str, dest: Path, *, max_bytes: int, timeout: float = 60,
                 headers: dict | None = None) -> HttpResponse:
        """Скачать потоком в ``dest``; при ошибке недокачанный файл удаляется.
        ``headers`` — дополнительные заголовки (авторизация сетевого хранилища)."""
        dest = Path(dest)

        def once() -> HttpResponse:
            try:
                with self._open("GET", url, None, None, headers, timeout) as resp, open(dest, "wb") as f:
                    self._read(resp, url, max_bytes, sink=f)
                    return self._response(resp, b"")
            except BaseException:
                dest.unlink(missing_ok=True)
                raise
        return self._retry(once, url)

    # ------------------------------------------------------------------ внутреннее

    @staticmethod
    def _retry(fn, url: str) -> HttpResponse:
        """Один повтор после сбоя связи или таймаута: DNS Docker Desktop изредка отвечает
        «No address associated with hostname», CDN — обрывает chunked-ответ."""
        try:
            return fn()
        except HttpError as e:
            if not e.retryable:
                raise
            log.info("HTTP %s: повтор после ошибки связи", _safe_url(url))
        time.sleep(RETRY_DELAY_S)
        return fn()

    def _open(self, method, url, params, data, headers, timeout):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
        if isinstance(data, dict):
            data = urllib.parse.urlencode(data).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
        try:
            return self._opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            try:
                body = e.read(ERROR_BODY_BYTES) or b""
            except Exception:
                body = b""
            e.close()
            raise HttpError(f"Сервер {_host(url)} ответил ошибкой {e.code}", status=e.code,
                            body=body) from None
        except (TimeoutError, socket.timeout) as e:
            raise _network_error(f"Сервер {_host(url)} не ответил вовремя", url, e) from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, (TimeoutError, socket.timeout)):
                raise _network_error(f"Сервер {_host(url)} не ответил вовремя", url, e) from None
            raise _network_error(f"Нет связи с сервером {_host(url)}", url, e) from None
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise _network_error(f"Нет связи с сервером {_host(url)}", url, e) from None

    @staticmethod
    def _read(resp, url: str, max_bytes: int, sink) -> bytes:
        too_big = HttpError(f"Ответ сервера {_host(url)} слишком большой (больше {max_bytes} байт)",
                            too_large=True)
        length = resp.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > max_bytes:
            raise too_big
        parts, total = [], 0
        try:
            while chunk := resp.read(CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise too_big
                if sink is None:
                    parts.append(chunk)
                else:
                    sink.write(chunk)
        except (TimeoutError, socket.timeout) as e:
            raise _network_error(f"Сервер {_host(url)} не ответил вовремя", url, e) from None
        except (OSError, http.client.HTTPException) as e:  # IncompleteRead — оборванный chunked-ответ
            raise _network_error(f"Связь с сервером {_host(url)} прервалась", url, e) from None
        return b"".join(parts)

    @staticmethod
    def _response(resp, body: bytes) -> HttpResponse:
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return HttpResponse(status=resp.status, url=resp.geturl(), headers=headers, body=body)
