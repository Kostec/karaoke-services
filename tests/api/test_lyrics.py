"""GET /api/lyrics/search: LRCLIB через FakeHttp (create_app(http=...)), без сети."""

from __future__ import annotations

import pytest
from fakes_http import FakeHttp

from karaoke_core.http import HttpError

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


def search(client, artist="Кино", title="Звезда", source="lrclib"):
    params = {"artist": artist, "title": title, **({"source": source} if source else {})}
    return client.get("/api/lyrics/search", params=params)


def test_success_fields_and_request(lc, http):
    http.route("GET", BY_FIELDS, json=[hit(1)])
    r = search(lc)
    assert r.status_code == 200
    assert r.json() == {"sources": [{"id": "lrclib", "name": "LRCLIB", "ok": True}],
                        "items": [{"id": "lrclib:1", "source": "lrclib", "url": None, "artist": "Кино", "title": "Песня 1", "album": "Группа крови",
                                   "duration": 285.0, "text": "Строка 1\nДальше",
                                   "synced": None}]}
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
    assert [i["id"] for i in items] == [f"lrclib:{n}" for n in range(10, 20)]


def test_fallback_to_q_when_fields_empty(lc, http):
    http.route("GET", BY_FIELDS, json=[hit(1, instrumental=True)])
    http.route("GET", BY_Q, json=[hit(7)])
    items = search(lc).json()["items"]
    assert [i["id"] for i in items] == ["lrclib:7"]
    assert http.requests[-1].query == {"q": "Кино Звезда"}


def test_only_lrc_is_stripped(lc, http):
    synced = "[ar:Кино]\n[00:12.34] Песен ещё не написанных\n[00:15.00]\n[00:17.5]Сколько?\n[01:02:03]Скажи\n"
    http.route("GET", BY_FIELDS, json=[hit(1, plainLyrics=None, syncedLyrics=synced)])
    assert search(lc).json()["items"][0]["text"] == "Песен ещё не написанных\n\nСколько?\nСкажи"


def test_synced_lyrics_are_returned_next_to_plain_text(lc, http):
    synced = "[00:01.00] Строка 1\r\n[00:02.50]Дальше\r\n"
    http.route("GET", BY_FIELDS, json=[hit(1, syncedLyrics=synced), hit(2, syncedLyrics="без меток")])
    a, b = search(lc).json()["items"]
    assert a["text"] == "Строка 1\nДальше"
    assert a["synced"] == "[00:01.00] Строка 1\n[00:02.50]Дальше"
    assert b["synced"] is None, "текст без меток времени — не синхронизация"


def test_nothing_found(lc, http):
    http.route("GET", LRCLIB, json=[])
    assert search(lc).json()["items"] == []
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
    assert r.json()["detail"] == "LRCLIB не ответил"


def test_garbage_json_503(lc, http):
    http.route("GET", LRCLIB, body=b"<html>not json")
    assert search(lc).status_code == 503


# ---------------------------------------------------------------- NetEase, Genius, все источники

NE_SEARCH = "https://music.163.com/api/search/get"
NE_LYRIC = "https://music.163.com/api/song/lyric"
GENIUS = "https://genius.com/api/search/song"
LRC_RU = ("[00:00.00] 作词 : Автор\n[00:01.00] 作曲 : Композитор\n[00:02.00]编曲：Аранжировщик\n"
          "[00:45.91]Тёплое место\n[00:54.80]Но улицы ждут\n")


def ne_song(i: int, **kw) -> dict:
    return {"id": i, "name": f"Песня {i}", "artists": [{"name": "Кино"}, {"name": "Виктор"}],
            "album": {"name": "Альбом"}, "duration": 266773, **kw}


def ne_lyric(lrc: str | None = LRC_RU, **kw) -> dict:
    return {"lrc": {"version": 1, "lyric": lrc}, **kw} if lrc is not None else kw


def genius_body(n: int = 7) -> dict:
    hits = [{"type": "song", "result": {"id": i, "full_title": f"П{i}", "title": f"Песня {i}",
                                         "artist_names": "Кино", "url": f"https://genius.com/kino-{i}"}}
            for i in range(n)]
    return {"meta": {"status": 200}, "response": {"sections": [{"type": "song", "hits": hits}]}}


def test_netease_hit_drops_credit_lines_and_has_synced(lc, http):
    http.route("GET", NE_SEARCH, json={"result": {"songs": [ne_song(5)]}})
    http.route("GET", NE_LYRIC, json=ne_lyric())
    [item] = search(lc, source="netease").json()["items"]
    assert item["text"] == "Тёплое место\nНо улицы ждут"
    assert item["synced"] == "[00:45.91]Тёплое место\n[00:54.80]Но улицы ждут"
    assert (item["id"], item["source"], item["artist"], item["album"], item["duration"]) == \
        ("netease:5", "netease", "Кино, Виктор", "Альбом", 266.773)
    assert http.calls(NE_SEARCH)[0].query == {"s": "Кино Звезда", "type": "1", "limit": "10"}
    assert http.calls(NE_LYRIC)[0].query == {"id": "5", "lv": "1"}


def test_netease_skips_instrumental_empty_and_nolyric_max_5(lc, http):
    songs = [ne_song(i) for i in range(1, 10)]
    http.route("GET", NE_SEARCH, json={"result": {"songs": songs}})
    http.route("GET", NE_LYRIC + "?id=1&", json=ne_lyric("[00:01.00]纯音乐，请欣赏"))
    http.route("GET", NE_LYRIC + "?id=2&", json={"nolyric": True})
    http.route("GET", NE_LYRIC + "?id=3&", json=ne_lyric("[00:00.00] 作词 : Автор\n"))
    http.route("GET", NE_LYRIC, json=ne_lyric("Просто текст без меток"))
    items = search(lc, source="netease").json()["items"]
    assert [i["id"] for i in items] == [f"netease:{n}" for n in range(4, 9)]
    assert items[0]["synced"] is None


@pytest.mark.parametrize("body", [{}, {"result": {}}, {"result": {"songs": None}}])
def test_netease_nothing_found_is_empty_not_error(lc, http, body):
    http.route("GET", NE_SEARCH, json=body)
    r = search(lc, source="netease")
    assert r.status_code == 200 and r.json()["items"] == []


def test_genius_links_only_max_5(lc, http):
    http.route("GET", GENIUS, json=genius_body())
    items = search(lc, source="genius").json()["items"]
    assert len(items) == 5
    assert items[0] == {"id": "genius:0", "artist": "Кино", "title": "Песня 0", "album": None, "duration": None,
                        "text": "", "synced": None, "source": "genius", "url": "https://genius.com/kino-0"}
    assert http.calls(GENIUS)[0].timeout == 15
    assert [r.url for r in http.requests if "genius.com/" in r.url and "/api/search" not in r.url] == []


def test_source_failure_is_503_with_name(lc, http):
    http.route("GET", NE_SEARCH, HttpError("Нет связи", status=None))
    r = search(lc, source="netease")
    assert (r.status_code, r.json()["detail"]) == (503, "NetEase не ответил")


def test_unknown_source_400(lc, http):
    r = search(lc, source="bing")
    assert (r.status_code, r.json()["field"]) == (400, "source")
    assert http.requests == []


def test_all_sources_synced_first_and_one_failure_does_not_drop_others(lc, http):
    http.route("GET", BY_FIELDS, json=[hit(1)])
    http.route("GET", NE_SEARCH, json={"result": {"songs": [ne_song(5)]}})
    http.route("GET", NE_LYRIC, json=ne_lyric())
    http.route("GET", GENIUS, HttpError("Нет связи", status=None))
    r = search(lc, source=None)
    assert r.status_code == 200
    body = r.json()
    assert [i["id"] for i in body["items"]] == ["netease:5", "lrclib:1"], "синхронный первым"
    assert [(s["id"], s["ok"]) for s in body["sources"]] == [("lrclib", True), ("netease", True), ("genius", False)]
    assert body["sources"][2]["name"] == "Genius" and body["sources"][2]["error"]


def test_all_sources_down_503(lc, http):
    http.route("GET", LRCLIB, HttpError("x", status=502))
    http.route("GET", NE_SEARCH, HttpError("x", status=502))
    http.route("GET", GENIUS, HttpError("x", status=502))
    r = search(lc, source=None)
    assert (r.status_code, r.json()["detail"]) == (503, "Сервисы текстов недоступны, попробуйте позже")


def test_all_sources_nothing_found_is_empty_200(lc, http):
    http.route("GET", LRCLIB, json=[])
    http.route("GET", NE_SEARCH, json={"result": {}})
    http.route("GET", GENIUS, json=genius_body(0))
    r = search(lc, source=None)
    assert r.status_code == 200 and r.json()["items"] == []
