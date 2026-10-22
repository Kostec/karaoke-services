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

    def download(self, url: str, dest: Path, *, max_bytes: int, timeout: float = 60,
                 headers: dict | None = None) -> HttpResponse:
        resp = self._dispatch(FakeRequest("GET", url, None, None, dict(headers or {}), timeout, max_bytes,
                                          self._session))
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
            raise HttpError(f"Сервер ответил ошибкой {resp.status}", status=resp.status, body=resp.body)
        return resp


# --------------------------------------------------------------------------- сетевые хранилища (таск 02)

import base64 as _b64  # noqa: E402
import email.utils as _eu  # noqa: E402
import itertools as _it  # noqa: E402
import re as _re  # noqa: E402
import shutil as _shutil  # noqa: E402
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
from xml.sax.saxutils import escape as _xml_escape  # noqa: E402


def _body_bytes(data) -> bytes:
    if data is None:
        return b""
    if hasattr(data, "read"):
        return data.read()
    return bytes(data)


class FakeWebDav:
    """Маленький WebDAV-сервер поверх папки ``root`` на диске: PROPFIND (Depth 0/1), GET, PUT,
    MOVE (Overwrite), DELETE, MKCOL. Basic-авторизация ``user``/``pw``; ``fail`` — статус
    или исключение для всех следующих запросов (имитация сбоя)."""

    METHODS = ("PROPFIND", "GET", "PUT", "MOVE", "DELETE", "MKCOL")

    def __init__(self, http: FakeHttp, base_url: str, root: Path, user: str = "user", pw: str = "app-pw"):
        self.http, self.base, self.root = http, base_url.rstrip("/"), Path(root)
        self.auth = "Basic " + _b64.b64encode(f"{user}:{pw}".encode()).decode()
        self.fail = None
        self.base_path = urllib.parse.urlsplit(self.base).path.rstrip("/")
        for m in self.METHODS:
            http.route(m, self.base, self._handle)

    def _path(self, url: str) -> Path:
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
        rel = path[len(self.base_path):].strip("/")
        return self.root.joinpath(*rel.split("/")) if rel else self.root

    def _handle(self, req: FakeRequest):
        if self.fail is not None:
            return self.fail if isinstance(self.fail, BaseException) else response(self.fail)
        if req.headers.get("Authorization") != self.auth:
            return response(401)
        return getattr(self, "_" + req.method.lower())(req, self._path(req.url))

    def _propfind(self, req, p):
        if not p.exists():
            return response(404)
        items = [p] + (sorted(p.iterdir()) if p.is_dir() and req.headers.get("Depth") == "1" else [])
        parts = []
        for q in items:
            rel = q.relative_to(self.root).as_posix() if q != self.root else ""
            href = self.base_path + "/" + "/".join(urllib.parse.quote(s) for s in rel.split("/") if s)
            if q.is_dir():
                href = href.rstrip("/") + "/"
            st = q.stat()
            props = ("<d:resourcetype><d:collection/></d:resourcetype>" if q.is_dir() else
                     f"<d:resourcetype/><d:getcontentlength>{st.st_size}</d:getcontentlength>")
            parts.append(f"<d:response><d:href>{_xml_escape(href)}</d:href><d:propstat><d:prop>{props}"
                         f"<d:getlastmodified>{_eu.formatdate(st.st_mtime, usegmt=True)}</d:getlastmodified>"
                         f"</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")
        body = ('<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:">'
                + "".join(parts) + "</d:multistatus>")
        return response(207, body)

    def _get(self, req, p):
        if not p.is_file():
            return response(404)
        return response(200, p.read_bytes())

    def _put(self, req, p):
        if not p.parent.is_dir():
            return response(409)
        p.write_bytes(_body_bytes(req.data))
        return response(201)

    def _mkcol(self, req, p):
        if p.exists():
            return response(405)
        if not p.parent.is_dir():
            return response(409)
        p.mkdir()
        return response(201)

    def _delete(self, req, p):
        if not p.exists():
            return response(404)
        if p.is_dir():
            _shutil.rmtree(p)
        else:
            p.unlink()
        return response(204)

    def _move(self, req, p):
        if not p.exists():
            return response(404)
        dst = self._path(req.headers["Destination"])
        if dst.exists() and req.headers.get("Overwrite", "T") != "T":
            return response(412)
        if not dst.parent.is_dir():
            return response(409)
        p.replace(dst)
        return response(201)


class FakeDrive:
    """Google Drive REST v3 + OAuth-токены поверх папки ``root`` («Мой диск»). Идентификаторы
    выдаются по пути и переезжают вместе с файлом; ``page_size`` — потолок страницы
    ``files.list`` (проверка ``nextPageToken``). ``access`` — действующий access-токен
    (``expire()`` его меняет — следующий запрос получит 401); ``revoked`` — refresh не работает;
    ``codes`` — выданные коды OAuth (code → refresh-токен)."""

    API = "https://www.googleapis.com/drive/v3/files"
    UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
    TOKEN = "https://oauth2.googleapis.com/token"
    FOLDER = "application/vnd.google-apps.folder"

    def __init__(self, http: FakeHttp, root: Path, *, client_id="cid", client_key="ckey",
                 refresh="refresh-1", page_size: int = 1000):
        self.http, self.root = http, Path(root)
        self.client_id, self.client_key, self.refresh = client_id, client_key, refresh
        self.page_size = page_size
        self.revoked = False
        self.codes: dict[str, str] = {}
        self._n = _it.count(1)
        self.access = self._new_access()
        self._ids: dict[str, str] = {}       # id → путь от root
        self._sessions: dict[str, dict] = {}
        http.route("POST", self.TOKEN, self._token)
        for m in ("GET", "POST", "PATCH", "DELETE"):
            http.route(m, self.API, self._api)
        for m in ("POST", "PATCH", "PUT"):
            http.route(m, self.UPLOAD, self._upload)

    def _new_access(self) -> str:
        return f"access-{next(self._n)}"

    def expire(self) -> None:
        self.access = self._new_access()

    # ----------------------------------------------------------- id ↔ путь

    def _id_of(self, rel: str) -> str:
        if rel == "":
            return "root"
        for i, r in self._ids.items():
            if r == rel:
                return i
        i = f"id{next(self._n)}"
        self._ids[i] = rel
        return i

    def _rel(self, file_id: str) -> str | None:
        rel = "" if file_id == "root" else self._ids.get(file_id)
        if rel is None or not self._abs(rel).exists():
            return None
        return rel

    def _abs(self, rel: str) -> Path:
        return self.root.joinpath(*rel.split("/")) if rel else self.root

    @staticmethod
    def _join(parent: str, name: str) -> str:
        return f"{parent}/{name}" if parent else name

    def _meta(self, rel: str) -> dict:
        p = self._abs(rel)
        st = p.stat()
        m = {"id": self._id_of(rel), "name": p.name,
             "mimeType": self.FOLDER if p.is_dir() else "application/octet-stream",
             "modifiedTime": _dt.fromtimestamp(st.st_mtime, _tz.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
        if p.is_file():
            m["size"] = str(st.st_size)
        return m

    def _move_ids(self, old: str, new: str) -> None:
        for i, r in list(self._ids.items()):
            if r == old or r.startswith(old + "/"):
                self._ids[i] = new + r[len(old):]

    @staticmethod
    def _file_id(url: str, base: str) -> str:
        path = urllib.parse.urlsplit(url).path
        return urllib.parse.unquote(path[len(urllib.parse.urlsplit(base).path):].strip("/"))

    # ----------------------------------------------------------- обработчики

    def _authorized(self, req) -> bool:
        return req.headers.get("Authorization") == f"Bearer {self.access}"

    def _token(self, req):
        form = req.data if isinstance(req.data, dict) else dict(
            urllib.parse.parse_qsl(_body_bytes(req.data).decode()))
        if form.get("client_id") != self.client_id or form.get("client_secret") != self.client_key:
            return response(401, json={"error": "invalid_client"})
        if form.get("grant_type") == "authorization_code":
            if form.get("code") not in self.codes:
                return response(400, json={"error": "invalid_grant"})
            self.refresh = self.codes.pop(form["code"])
            self.revoked = False
            self.access = self._new_access()
            return response(json={"access_token": self.access, "refresh_token": self.refresh,
                                  "expires_in": 3599, "token_type": "Bearer"})
        if self.revoked or form.get("refresh_token") != self.refresh:
            return response(400, json={"error": "invalid_grant"})
        self.access = self._new_access()
        return response(json={"access_token": self.access, "expires_in": 3599, "token_type": "Bearer"})

    def _api(self, req):
        if not self._authorized(req):
            return response(401)
        fid = self._file_id(req.url, self.API)
        q = req.query
        if req.method == "GET" and not fid:
            return self._list(q)
        if req.method == "POST" and not fid:
            meta = _json.loads(_body_bytes(req.data))
            parent = self._rel(meta["parents"][0])
            if parent is None or meta.get("mimeType") != self.FOLDER:
                return response(404)
            rel = self._join(parent, meta["name"])
            self._abs(rel).mkdir()
            return response(json=self._meta(rel))
        rel = self._rel(fid)
        if rel is None:
            return response(404)
        if req.method == "GET":
            if q.get("alt") == "media":
                return response(200, self._abs(rel).read_bytes())
            return response(json=self._meta(rel))
        if req.method == "DELETE":
            p = self._abs(rel)
            if p.is_dir():
                _shutil.rmtree(p)
            else:
                p.unlink()
            return response(204)
        # PATCH: имя и/или родитель
        meta = _json.loads(_body_bytes(req.data) or b"{}")
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if q.get("addParents"):
            if q.get("removeParents") != self._id_of(parent):
                return response(400)
            parent = self._rel(q["addParents"])
            if parent is None:
                return response(404)
        new = self._join(parent, meta.get("name") or self._abs(rel).name)
        if new != rel:
            if self._abs(new).exists():
                return response(409)  # у настоящего Drive вышел бы дубль имени
            self._abs(rel).replace(self._abs(new))
            self._move_ids(rel, new)
        return response(json=self._meta(new))

    def _list(self, q: dict):
        query = q.get("q", "")
        m = _re.search(r"'([^']+)' in parents", query)
        parent = self._rel(m.group(1)) if m else None
        if parent is None or not self._abs(parent).is_dir():
            return response(404)
        name = _re.search(r"name\s*=\s*'((?:[^'\\]|\\.)*)'", query)
        name = _re.sub(r"\\(.)", r"\1", name.group(1)) if name else None
        folders_only = f"mimeType='{self.FOLDER}'" in query.replace(" ", "")
        files = []
        for p in sorted(self._abs(parent).iterdir()):
            if (name is not None and p.name != name) or (folders_only and not p.is_dir()):
                continue
            files.append(self._meta(self._join(parent, p.name)))
        start = int(q.get("pageToken") or 0)
        size = min(int(q.get("pageSize") or 100), self.page_size)
        body = {"files": files[start:start + size]}
        if start + size < len(files):
            body["nextPageToken"] = str(start + size)
        return response(json=body)

    def _upload(self, req):
        if not self._authorized(req):
            return response(401)
        q = req.query
        if req.method == "PUT":
            sess = self._sessions.pop(q.get("upload_id", ""), None)
            if sess is None:
                return response(404)
            data = _body_bytes(req.data)
            rel = sess["rel"]
            if rel is None:
                parent = self._rel(sess["parent"])
                if parent is None:
                    return response(404)
                rel = self._join(parent, sess["name"])
                if self._abs(rel).exists():
                    return response(409)  # дубль имени: хранилище должно было обновить существующий
            self._abs(rel).write_bytes(data)
            return response(json=self._meta(rel))
        if q.get("uploadType") != "resumable":
            return response(400)
        meta = _json.loads(_body_bytes(req.data) or b"{}")
        upload_id = f"u{next(self._n)}"
        if req.method == "PATCH":
            rel = self._rel(self._file_id(req.url, self.UPLOAD))
            if rel is None:
                return response(404)
            self._sessions[upload_id] = {"rel": rel}
        else:
            self._sessions[upload_id] = {"rel": None, "parent": meta["parents"][0], "name": meta["name"]}
        return response(200, headers={"Location": f"{self.UPLOAD}?uploadType=resumable&upload_id={upload_id}"})
