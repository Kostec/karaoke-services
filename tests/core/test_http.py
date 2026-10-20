"""Общий HTTP-модуль karaoke_core.http: локальный http.server в потоке, без внешней сети."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from karaoke_core.http import Http, HttpError, HttpResponse


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # тише в выводе pytest
        pass

    def _send(self, status: int, body: bytes, headers: dict | None = None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/hello":
            q = parse_qs(u.query)
            self._send(200, ("привет " + q.get("name", [""])[0]).encode(), {"X-Test": "Да".encode().decode("latin-1")})
        elif u.path == "/ua":
            self._send(200, (self.headers.get("User-Agent") or "").encode())
        elif u.path == "/redirect":
            self._send(302, b"", {"Location": "/hello?name=r"})
        elif u.path == "/big":
            self._send(200, b"x" * 5000)
        elif u.path == "/slow":
            time.sleep(1.5)
            self._send(200, b"late")
        elif u.path == "/missing":
            self._send(404, b"no such")
        elif u.path == "/set-cookie":
            self._send(200, b"ok", {"Set-Cookie": "sid=abc; Path=/"})
        elif u.path == "/cookie":
            self._send(200, (self.headers.get("Cookie") or "").encode())
        else:
            self._send(500, b"boom")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        self._send(200, (self.headers.get("Content-Type", "") + "|").encode() + body)


@pytest.fixture(scope="module")
def base():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_get_params_headers_and_redirect(base):
    r = Http().request("GET", f"{base}/hello", params={"name": "мир"})
    assert isinstance(r, HttpResponse)
    assert (r.status, r.body.decode()) == (200, "привет мир")
    assert "x-test" in r.headers, "ключи заголовков — в нижнем регистре"
    r = Http().request("GET", f"{base}/redirect")
    assert r.url == f"{base}/hello?name=r"
    assert r.body.decode() == "привет r"


def test_user_agent(base):
    assert Http().request("GET", f"{base}/ua").body == b"karaoke-services"


def test_post_form_and_bytes(base):
    r = Http().request("POST", f"{base}/post", data={"user": "u", "q": "а б"})
    ctype, _, body = r.body.partition(b"|")
    assert ctype == b"application/x-www-form-urlencoded"
    assert parse_qs(body.decode()) == {"user": ["u"], "q": ["а б"]}
    r = Http().request("POST", f"{base}/post", data=b"raw", headers={"Content-Type": "text/plain"})
    assert r.body == b"text/plain|raw"


def test_status_400_plus_is_error(base):
    with pytest.raises(HttpError) as e:
        Http().request("GET", f"{base}/missing")
    assert e.value.status == 404
    assert "404" in str(e.value)


def test_network_error_and_timeout(base):
    with pytest.raises(HttpError) as e:
        Http().request("GET", "http://127.0.0.1:1/never")
    assert e.value.status is None
    with pytest.raises(HttpError) as e:
        Http().request("GET", f"{base}/slow", timeout=0.3)
    assert e.value.status is None
    assert "не ответил" in str(e.value)


def test_max_bytes(base):
    assert len(Http().request("GET", f"{base}/big", max_bytes=5000).body) == 5000
    with pytest.raises(HttpError) as e:
        Http().request("GET", f"{base}/big", max_bytes=4999)
    assert "слишком большой" in str(e.value)


def test_session_has_own_cookie_jar(base):
    s = Http().session()
    s.request("GET", f"{base}/set-cookie")
    assert s.request("GET", f"{base}/cookie").body == b"sid=abc"
    other = Http().session()
    assert other.request("GET", f"{base}/cookie").body == b""


def test_download(base, tmp_path):
    dest = tmp_path / "f.bin"
    r = Http().download(f"{base}/big", dest, max_bytes=5000)
    assert (r.status, r.body) == (200, b"")
    assert dest.read_bytes() == b"x" * 5000
    with pytest.raises(HttpError):
        Http().download(f"{base}/big", tmp_path / "g.bin", max_bytes=100)
    assert not (tmp_path / "g.bin").exists(), "недокачанный файл удаляется"
