"""FakeHttp — подмена karaoke_core.http.Http в тестах (без сети).

Маршруты: ``(method, префикс полного URL)`` → ответ. Полный URL — с ``params``, закодированными
как у настоящего ``Http`` (``urlencode`` в порядке ключей). Совпадение — самый длинный префикс,
при равенстве — зарегистрированный позже. Ответ — ``HttpResponse``, исключение (будет поднято)
или вызываемый ``fn(FakeRequest) -> HttpResponse | Exception``. Статус ≥400 → ``HttpError``,
как у настоящего. Все запросы пишутся в ``requests`` (общий список у всех ``session()``).

Таски 03/04 дополняют этот файл, не переписывают.
"""

from __future__ import annotations

import json as _json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from karaoke_core.http import HttpError, HttpResponse


@dataclass
class FakeRequest:
    method: str
    url: str                    # полный, с params
    params: dict | None = None
    data: dict | bytes | None = None
    headers: dict = field(default_factory=dict)
    timeout: float | None = None
    max_bytes: int | None = None
    session: int = 0            # 0 — исходный объект, n — n-я session()

    @property
    def query(self) -> dict[str, str]:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.url).query))


def response(status: int = 200, body: bytes | str = b"", *, json=None, url: str = "",
             headers: dict | None = None) -> HttpResponse:
    if json is not None:
        body = _json.dumps(json, ensure_ascii=False)
        headers = {"content-type": "application/json", **(headers or {})}
    if isinstance(body, str):
        body = body.encode("utf-8")
    return HttpResponse(status=status, url=url, headers={k.lower(): v for k, v in (headers or {}).items()},
                        body=body)


class FakeHttp:
    def __init__(self, *, _shared=None, _session: int = 0):
        if _shared is None:
            _shared = {"routes": [], "requests": [], "sessions": 0}
        self._shared = _shared
        self._session = _session

    @property
    def routes(self) -> list:
        return self._shared["routes"]

    @property
    def requests(self) -> list[FakeRequest]:
        return self._shared["requests"]

    def route(self, method: str, prefix: str, resp=None, **kw) -> "FakeHttp":
        """``resp`` — HttpResponse / исключение / callable; иначе ``response(**kw)``."""
        self.routes.append((method.upper(), prefix, resp if resp is not None else response(**kw)))
        return self

    def calls(self, prefix: str = "") -> list[FakeRequest]:
        return [r for r in self.requests if r.url.startswith(prefix)]

    # ------------------------------------------------------------------ интерфейс Http

    def session(self) -> "FakeHttp":
        self._shared["sessions"] += 1
        return FakeHttp(_shared=self._shared, _session=self._shared["sessions"])

    def request(self, method: str, url: str, *, params: dict | None = None,
                data: dict | bytes | None = None, headers: dict | None = None,
                timeout: float = 10, max_bytes: int = 5 * 2**20) -> HttpResponse:
        resp = self._dispatch(FakeRequest(method.upper(), self._full(url, params), params, data,
                                          dict(headers or {}), timeout, max_bytes, self._session))
        if len(resp.body) > max_bytes:
            raise HttpError(f"Ответ сервера слишком большой (больше {max_bytes} байт)", too_large=True)
        return resp

    def download(self, url: str, dest: Path, *, max_bytes: int, timeout: float = 60) -> HttpResponse:
        resp = self._dispatch(FakeRequest("GET", url, None, None, {}, timeout, max_bytes, self._session))
        if len(resp.body) > max_bytes:
            raise HttpError(f"Ответ сервера слишком большой (больше {max_bytes} байт)", too_large=True)
        Path(dest).write_bytes(resp.body)
        return HttpResponse(resp.status, resp.url, resp.headers, b"")

    # ------------------------------------------------------------------ внутреннее

    @staticmethod
    def _full(url: str, params: dict | None) -> str:
        if not params:
            return url
        return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    def _dispatch(self, req: FakeRequest) -> HttpResponse:
        self.requests.append(req)
        best = None
        for i, (method, prefix, resp) in enumerate(self.routes):
            if method == req.method and req.url.startswith(prefix):
                if best is None or len(prefix) >= len(best[0]):
                    best = (prefix, resp)
        if best is None:
            raise HttpError(f"FakeHttp: нет маршрута для {req.method} {req.url}")
        resp = best[1]
        if callable(resp) and not isinstance(resp, HttpResponse):
            resp = resp(req)
        if isinstance(resp, BaseException):
            raise resp
        if not resp.url:
            resp = HttpResponse(resp.status, req.url, resp.headers, resp.body)
        if resp.status >= 400:
            raise HttpError(f"Сервер ответил ошибкой {resp.status}", status=resp.status)
        return resp
