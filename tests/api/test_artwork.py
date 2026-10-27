"""POST /api/jobs/artwork — обложка и фон песни (истории 12–18, 20, 24); сеть — FakeHttp."""

from __future__ import annotations

import pytest
from fakes_http import FakeHttp, response
from karaoke_core import musiclink
from karaoke_core.http import HttpError

JPG = b"\xff\xd8\xff\xe0" + b"jpeg-data" * 10
PNG = b"\x89PNG\r\n\x1a\n" + b"png-data"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"webp"
IMG_URL = "https://img.example.com/cover.png"


@pytest.fixture
def http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture
def app(env, http):
    env.put_song("Artist/Artist - Song", env.SONG_TXT, "Artist - Song")
    with env.client(http=http) as c:
        assert c.post("/api/songs/rescan").status_code == 202
        song = next(i for i in c.get("/api/songs").json()["items"] if i["title"] == "Song")
        yield c, song


def post(c, song_id, *, file=None, **fields):
    data = {"song_id": song_id, **{k: str(v) for k, v in fields.items()}}
    return c.post("/api/jobs/artwork", data=data, files={"image": file} if file else None)


def _err(r, status, field=None, text=None):
    assert r.status_code == status, r.text
    if field is not None:
        assert r.json().get("field") == field, r.json()
    if text is not None:
        assert text in r.json()["detail"], r.json()


def test_background_file_is_staged(env, app):
    c, song = app
    r = post(c, song["song_id"], kind="background", file=("Фон.PNG", PNG, "image/png"))
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["type"] == "artwork" and job["song_id"] == song["song_id"]
    assert (job["artist"], job["title"]) == ("Artist", "Song")
    p = job["params"]
    assert (p["kind"], p["rel_dir"], p["txt_name"], p["target_id"]) == (
        "background", "Artist/Artist - Song", "Artist - Song.txt", song["target_id"])
    assert p["inputs"]["dir"].endswith(f"/jobs/{job['id']}/in")
    assert p["inputs"]["image"].endswith("/in/image.png")  # расширение — по содержимому
    assert (env.data / p["inputs"]["image"]).read_bytes() == PNG
    assert not p.get("remove")


def test_cover_by_url_is_downloaded_by_web(env, app, http):
    c, song = app
    http.route("GET", IMG_URL, body=WEBP)
    r = post(c, song["song_id"], kind="cover", url=IMG_URL)
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["kind"] == "cover" and p["inputs"]["image"].endswith("/in/image.webp")
    assert (env.data / p["inputs"]["image"]).read_bytes() == WEBP
    assert [q.url for q in http.calls(IMG_URL)] == [IMG_URL]


def test_remove_needs_no_image(app):
    c, song = app
    r = post(c, song["song_id"], kind="background", remove="true")
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["remove"] is True and "image" not in p["inputs"]


def test_duplicate_is_409(app):
    c, song = app
    assert post(c, song["song_id"], kind="cover", file=("a.jpg", JPG, "image/jpeg")).status_code == 201
    r = post(c, song["song_id"], kind="background", file=("a.jpg", JPG, "image/jpeg"))
    _err(r, 409, text="Эта песня уже в очереди")


def test_restart_reuses_staged_image_and_checks_duplicate(env, app):
    c, song = app
    job = post(c, song["song_id"], kind="cover", file=("a.jpg", JPG, "image/jpeg")).json()
    r = c.post(f"/api/jobs/{job['id']}/restart")
    _err(r, 409)  # ещё не завершено
    c.post(f"/api/jobs/{job['id']}/cancel")
    ctx = c.app.state.ctx
    ctx.jobs.update(job["id"], state="failed")
    r = c.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 201, r.text
    again = r.json()
    assert again["type"] == "artwork" and again["params"]["inputs"] == job["params"]["inputs"]
    # пока перезапуск в очереди — второе задание той же песни 409
    _err(post(c, song["song_id"], kind="cover", file=("a.jpg", JPG, "image/jpeg")), 409)


@pytest.mark.parametrize("fields, file, field, text", [
    ({"kind": "poster"}, ("a.jpg", JPG, "image/jpeg"), "kind", "обложка или фон"),
    ({"kind": "cover"}, None, "image", "Загрузите картинку или вставьте ссылку"),
    ({"kind": "cover", "url": IMG_URL}, ("a.jpg", JPG, "image/jpeg"), "image", "что-то одно"),
    ({"kind": "cover", "remove": "true"}, ("a.jpg", JPG, "image/jpeg"), "image", "что-то одно"),
    ({"kind": "cover"}, ("a.gif", b"GIF89a....", "image/gif"), "image",
     "Это не картинка (нужны jpg, png или webp)"),
    ({"kind": "cover", "url": "ftp://x/y.jpg"}, None, "url", "Нужна ссылка"),
    ({"kind": "cover", "url": "http://[::1"}, None, "url", "Нужна ссылка http(s) на картинку"),
    ({"kind": "cover", "url": "http://example.com:99999/a.jpg"}, None, "url", "Нужна ссылка http(s) на картинку"),
    ({"kind": "cover", "url": "http://192.168.1.5/cover.jpg"}, None, "url", musiclink.MSG_HOME_NETWORK),
])
def test_bad_input_is_400_at_field_and_nothing_queued(app, http, fields, file, field, text):
    c, song = app
    _err(post(c, song["song_id"], file=file, **fields), 400, field, text)
    assert c.get("/api/jobs").json() == []
    assert http.requests == []


def test_too_big_file_and_link_are_400(app, http, monkeypatch):
    import app.api_artwork as api_artwork

    monkeypatch.setattr(api_artwork, "MAX_COVER_MB", 1)
    c, song = app
    big = JPG + b"x" * (1024 * 1024)
    _err(post(c, song["song_id"], kind="cover", file=("a.jpg", big, "image/jpeg")), 400, "image",
         "Файл больше 1 МБ")
    http.route("GET", IMG_URL, body=big)
    _err(post(c, song["song_id"], kind="cover", url=IMG_URL), 400, "url", "больше 1 МБ")
    assert c.get("/api/jobs").json() == []


@pytest.mark.parametrize("resp, text", [
    (response(body=b"<html>not image</html>"), "По ссылке не картинка"),
    (HttpError("Сервер ответил 404", status=404), "Не удалось скачать картинку"),
])
def test_bad_link_is_400_at_url(app, http, resp, text):
    c, song = app
    http.route("GET", IMG_URL, resp)
    _err(post(c, song["song_id"], kind="background", url=IMG_URL), 400, "url", text)
    assert c.get("/api/jobs").json() == []


def test_unknown_song_is_404(app):
    c, _ = app
    _err(post(c, "nope", kind="cover", file=("a.jpg", JPG, "image/jpeg")), 404)
