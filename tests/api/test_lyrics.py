"""GET /api/lyrics/search: LRCLIB через FakeHttp (create_app(http=...)), без сети."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fakes_http import FakeHttp  # noqa: E402

from karaoke_core.http import HttpError  # noqa: E402

LRCLIB = "https://lrclib.net/api/search"
BY_FIELDS = LRCLIB + "?track_name="
BY_Q = LRCLIB + "?q="


def hit(i: int, **kw) -> dict:
    return {"id": i, "trackName": f"Песня {i}", "artistName": "Кино", "albumName": "Группа крови",
            "duration": 285.0, "instrumental": False, "plainLyrics": f"Строка {i}\nДальше",
            "syncedLyrics": None, **kw}


@pytest.fixture
def http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture
def lc(env, http):
    with env.client(http=http) as c:
        yield c


def search(client, artist="Кино", title="Звезда"):
    return client.get("/api/lyrics/search", params={"artist": artist, "title": title})


def test_success_fields_and_request(lc, http):
    http.route("GET", BY_FIELDS, json=[hit(1)])
    r = search(lc)
    assert r.status_code == 200
    assert r.json() == {"items": [{"id": 1, "artist": "Кино", "title": "Песня 1", "album": "Группа крови",
                                   "duration": 285.0, "text": "Строка 1\nДальше"}]}
    [req] = http.requests
    assert req.query == {"track_name": "Звезда", "artist_name": "Кино"}


def test_instrumental_and_empty_dropped_max_10(lc, http):
    http.route("GET", BY_FIELDS, json=[
        hit(1, instrumental=True, plainLyrics=None),
        hit(2, plainLyrics="", syncedLyrics=None),
        hit(3, plainLyrics="   \n "),
        *[hit(i) for i in range(10, 25)],
    ])
    items = search(lc).json()["items"]
    assert [i["id"] for i in items] == list(range(10, 20))


def test_fallback_to_q_when_fields_empty(lc, http):
    http.route("GET", BY_FIELDS, json=[hit(1, instrumental=True)])
    http.route("GET", BY_Q, json=[hit(7)])
    items = search(lc).json()["items"]
    assert [i["id"] for i in items] == [7]
    assert http.requests[-1].query == {"q": "Кино Звезда"}


def test_only_lrc_is_stripped(lc, http):
    synced = "[ar:Кино]\n[00:12.34] Песен ещё не написанных\n[00:15.00]\n[00:17.5]Сколько?\n[01:02:03]Скажи\n"
    http.route("GET", BY_FIELDS, json=[hit(1, plainLyrics=None, syncedLyrics=synced)])
    assert search(lc).json()["items"][0]["text"] == "Песен ещё не написанных\n\nСколько?\nСкажи"


def test_nothing_found(lc, http):
    http.route("GET", LRCLIB, json=[])
    assert search(lc).json() == {"items": []}
    assert len(http.requests) == 2, "сначала по полям, потом q="


@pytest.mark.parametrize("artist,title,field", [("", "Звезда", "artist"), ("Кино", "  ", "title"),
                                                ("", "", "artist")])
def test_empty_fields_400(lc, http, artist, title, field):
    r = search(lc, artist, title)
    assert r.status_code == 400
    assert r.json()["field"] == field
    assert http.requests == []


@pytest.mark.parametrize("resp", [HttpError("Нет связи", status=None), HttpError("ошибка", status=502)])
def test_unavailable_503(lc, http, resp):
    http.route("GET", LRCLIB, resp)
    r = search(lc)
    assert r.status_code == 503
    assert r.json()["detail"] == "Сервис текстов недоступен, попробуйте позже"


def test_garbage_json_503(lc, http):
    http.route("GET", LRCLIB, body=b"<html>not json")
    assert search(lc).status_code == 503
