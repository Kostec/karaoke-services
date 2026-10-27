"""GET /api/covers/search — обложки iTunes, Deezer и MusicBrainz (истории 19–22), сеть — FakeHttp."""

from __future__ import annotations

from fakes_http import FakeHttp, response
from karaoke_core.http import HttpError

ITUNES = "https://itunes.apple.com/search"
DEEZER = "https://api.deezer.com/search"
MB = "https://musicbrainz.org/ws/2/release"
CAA = "https://coverartarchive.org/release/"

ITUNES_JSON = {"resultCount": 3, "results": [
    {"artistName": "Градусы", "trackName": "Режиссёр", "collectionName": "Режиссёр (Single)",
     "artworkUrl100": "https://is1.mzstatic.com/image/thumb/a/100x100bb.jpg"},
    # тот же альбом второй раз — дубль по адресу картинки
    {"artistName": "Градусы", "trackName": "Режиссёр (Remix)", "collectionName": "Режиссёр (Single)",
     "artworkUrl100": "https://is1.mzstatic.com/image/thumb/a/100x100bb.jpg"},
    {"artistName": "Градусы", "trackName": "Режиссёр", "collectionName": "Лучшее",
     "artworkUrl100": "https://is1.mzstatic.com/image/thumb/b/100x100bb.jpg"},
]}
DEEZER_JSON = {"data": [
    {"title": "Режиссёр", "artist": {"name": "Градусы"},
     "album": {"title": "Режиссёр", "cover_xl": "https://e-cdns.dzcdn.net/xl.jpg",
               "cover_medium": "https://e-cdns.dzcdn.net/m.jpg"}},
]}
MB_JSON = {"releases": [
    {"id": "11111111-2222-3333-4444-555555555555", "title": "Режиссёр", "score": 100,
     "artist-credit": [{"name": "Градусы"}]},
]}


def _http(itunes=None, deezer=None, mb=None) -> FakeHttp:
    http = FakeHttp()
    http.route("GET", ITUNES, itunes if itunes is not None else None, json=ITUNES_JSON)
    http.route("GET", DEEZER, deezer if deezer is not None else None, json=DEEZER_JSON)
    http.route("GET", MB, mb if mb is not None else None, json=MB_JSON)
    return http


def _search(env, http, **params):
    with env.client(http=http) as c:
        return c.get("/api/covers/search", params=params)


def test_search_collects_three_services(env):
    http = _http()
    r = _search(env, http, artist="Градусы", title="Режиссёр")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    by_source = {}
    for it in items:
        by_source.setdefault(it["source"], []).append(it)
    assert set(by_source) == {"itunes", "deezer", "musicbrainz"}
    # iTunes: 100x100 → 1000x1000, дубль альбома убран
    assert [i["url"] for i in by_source["itunes"]] == [
        "https://is1.mzstatic.com/image/thumb/a/1000x1000bb.jpg",
        "https://is1.mzstatic.com/image/thumb/b/1000x1000bb.jpg"]
    first = by_source["itunes"][0]
    assert (first["album"], first["artist"], first["title"]) == ("Режиссёр (Single)", "Градусы", "Режиссёр")
    assert (first["width"], first["height"]) == (1000, 1000) and first["thumb"]
    dz = by_source["deezer"][0]
    assert (dz["url"], dz["thumb"], dz["album"]) == ("https://e-cdns.dzcdn.net/xl.jpg",
                                                     "https://e-cdns.dzcdn.net/m.jpg", "Режиссёр")
    mb = by_source["musicbrainz"][0]
    assert mb["url"] == CAA + "11111111-2222-3333-4444-555555555555/front-500"
    assert mb["thumb"] == CAA + "11111111-2222-3333-4444-555555555555/front-250"
    assert mb["artist"] == "Градусы"
    # у MusicBrainz свой User-Agent, запрос по исполнителю и названию
    (req,) = http.calls(MB)
    assert req.headers.get("User-Agent", "").startswith("karaoke-services/1.0")
    assert "Градусы" in req.query["query"] and "Режиссёр" in req.query["query"]
    assert req.query["fmt"] == "json"
    # первые варианты — от разных сервисов, а не три подряд iTunes
    assert {i["source"] for i in items[:3]} == {"itunes", "deezer", "musicbrainz"}


def test_search_is_limited_to_twelve(env):
    many = {"results": [{"artistName": "A", "trackName": "T", "collectionName": f"Альбом {n}",
                         "artworkUrl100": f"https://img.example/{n}/100x100bb.jpg"} for n in range(20)]}
    r = _search(env, _http(itunes=None).route("GET", ITUNES, json=many), artist="A", title="T")
    assert r.status_code == 200 and len(r.json()["items"]) == 12


def test_one_service_failing_does_not_break_others(env):
    http = _http(deezer=HttpError("timeout"), mb=HttpError("Сервер ответил 503", status=503))
    r = _search(env, http, artist="Градусы", title="Режиссёр")
    assert r.status_code == 200
    body = r.json()
    assert {i["source"] for i in body["items"]} == {"itunes"}
    assert sorted(body["failed"]) == ["deezer", "musicbrainz"]


def test_broken_json_counts_as_failure(env):
    http = _http(itunes=response(body=b"<html>"))
    r = _search(env, http, artist="Градусы", title="Режиссёр")
    assert r.status_code == 200 and r.json()["failed"] == ["itunes"]


def test_all_failed_is_503(env):
    err = HttpError("нет сети")
    r = _search(env, _http(itunes=err, deezer=err, mb=err), artist="Градусы", title="Режиссёр")
    assert r.status_code == 503
    assert r.json()["detail"] == "Сервисы обложек недоступны, попробуйте позже"


def test_nothing_found_is_empty_list(env):
    http = _http(itunes=None, deezer=None, mb=None)
    http.route("GET", ITUNES, json={"resultCount": 0, "results": []})
    http.route("GET", DEEZER, json={"data": []})
    http.route("GET", MB, json={"releases": []})
    r = _search(env, http, artist="Никто", title="Ничего")
    assert r.status_code == 200 and r.json()["items"] == []


def test_empty_query_is_400(env):
    http = _http()
    r = _search(env, http, artist=" ", title="")
    assert r.status_code == 400 and r.json()["field"] == "title"
    assert http.requests == []


def test_artist_only_or_title_only_searches(env):
    http = _http()
    assert _search(env, http, title="Режиссёр").status_code == 200
    assert http.calls(ITUNES)[0].query["term"] == "Режиссёр"
