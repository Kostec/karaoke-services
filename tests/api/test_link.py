"""Ссылки на музыку: /api/link/inspect, токен Яндекс Музыки в настройках, generate с audio_url."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from fakes_http import FakeHttp
from karaoke_core import musiclink
from karaoke_core.db import Settings, Songs, connect
from karaoke_core.musiclink import LinkInfo, LinkTrack, MusicLinkError

FAKE_YTDLP = Path(__file__).resolve().parents[1] / "core" / "fixtures" / "fake_ytdlp_info.py"
GOOD = "ym-good-key"
# Ключи-маркеры поведения фейка: уникальные строки, чтобы «нет в ответе» проверяло именно ключ.
REJECTED = "ym-rejected-key-7f3a91"
OFFLINE = "ym-offline-key-c24e08"
YT = "https://www.youtube.com/watch?v=kXYiU_JCYtU"


class FakeYandex:
    """Подмена ``YandexMusic``: журнал ключей и ссылок, поведение — по ключу."""

    calls: list = []

    def __init__(self, ym_key: str):
        self.key = ym_key
        FakeYandex.calls.append(("init", ym_key))

    def _guard(self):
        if self.key == OFFLINE:
            raise MusicLinkError(musiclink.MSG_UNAVAILABLE)
        if self.key != GOOD:
            raise MusicLinkError(musiclink.MSG_REJECTED)

    def check(self):
        self._guard()

    def info(self, link):
        self._guard()
        FakeYandex.calls.append(("info", link.kind, link.url))
        if link.kind == "yandex_track":
            t = LinkTrack(link.url, "Кино", "Группа крови", 285.5, "https://avatars.example/c.jpg")
            return LinkInfo(link.kind, t.title, [t])
        tracks = [LinkTrack(f"https://music.yandex.ru/album/1/track/{i}", "Кино", f"Песня {i}", None, None)
                  for i in (1, 2, 3)]
        return LinkInfo(link.kind, "Альбом", tracks)


@pytest.fixture
def http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture
def lc(env, http):
    FakeYandex.calls = []
    with env.client(extra_env={"YTDLP_CMD": f"{sys.executable} {FAKE_YTDLP}"},
                    yandex_factory=FakeYandex, http=http) as c:
        yield c


def _store_key(env, value):
    Settings(connect(env.data / "karaoke.sqlite")).set_yandex(value)


def _inspect(c, url):
    return c.post("/api/link/inspect", json={"url": url})


# --------------------------------------------------------------------------- inspect: yt-dlp

def test_inspect_ytdlp_single_track_and_existing_song(env, lc):
    env.put_song("Linkin Park/Linkin Park - Numb", env.SONG_TXT.replace(b"Artist", b"Linkin Park")
                 .replace(b"#TITLE:Song", b"#TITLE:Numb"), "Linkin Park - Numb")
    assert lc.post("/api/songs/rescan").status_code == 202
    sid = lc.get("/api/songs").json()["items"][0]["song_id"]
    r = _inspect(lc, YT + "&utm_source=share")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "ytdlp" and body["title"] == "Numb"
    assert body["tracks"] == [{"url": YT, "artist": "Linkin Park", "title": "Numb", "duration": 187.0,
                               "thumbnail": "https://i.ytimg.com/vi/kXYiU_JCYtU/maxresdefault.jpg",
                               "existing_song_id": sid}]
    assert FakeYandex.calls == []


def test_inspect_ytdlp_playlist(lc):
    r = _inspect(lc, "https://www.youtube.com/playlist?list=PL123")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Мой плейлист"
    assert [t["url"] for t in body["tracks"]] == ["https://www.youtube.com/watch?v=aaa",
                                                  "https://www.youtube.com/watch?v=bbb"]
    assert body["tracks"][0]["artist"] == "Кино" and body["tracks"][0]["existing_song_id"] is None


@pytest.mark.parametrize("url, start", [
    ("https://example.com/error", "Не удалось получить данные по ссылке: [generic] Unsupported URL"),
    ("https://vk.com/audio123_456", "Аудиозаписи ВКонтакте не поддерживаются"),
    ("ftp://x/y", "Нужна ссылка вида https://"),
    ("", "Нужна ссылка вида https://"),
])
def test_inspect_errors_are_400_field_url(lc, url, start):
    r = _inspect(lc, url)
    assert r.status_code == 400, r.text
    assert r.json()["field"] == "url" and r.json()["detail"].startswith(start)


@pytest.mark.parametrize("marker", ["net-webpage", "net-dns", "net-timeout", "net-conn"])
def test_inspect_ytdlp_network_failure_is_503(lc, marker):
    r = _inspect(lc, f"https://www.youtube.com/watch?v={marker}")
    assert r.status_code == 503, r.text
    assert r.json()["detail"].startswith(musiclink.MSG_YTDLP) and "field" not in r.json()


def test_inspect_rejects_home_network(lc, monkeypatch):
    for url in ("http://192.168.1.20:8090/api/status", "http://localhost/x", "https://nas.local/a.mp3"):
        r = _inspect(lc, url)
        assert r.status_code == 400 and r.json()["field"] == "url", r.text
        assert r.json()["detail"] == "Ссылки на адреса домашней сети не поддерживаются"
    monkeypatch.setattr(musiclink, "RESOLVER", lambda host: ["10.0.0.7"] if host == "evil.example" else [])
    r = _inspect(lc, "https://evil.example/watch?v=1")
    assert r.status_code == 400 and "домашней сети" in r.json()["detail"]
    assert _gen(lc, "https://evil.example/watch?v=1").json()["field"] == "audio_url"


def test_inspect_youtube_video_from_list_is_one_track(lc):
    body = _inspect(lc, YT + "&list=RDkXYiU_JCYtU&start_radio=1").json()
    assert body["kind"] == "ytdlp" and len(body["tracks"]) == 1 and body["tracks"][0]["url"] == YT
    p = _gen(lc, "https://youtu.be/kXYiU_JCYtU?list=PL1&index=4").json()["params"]
    assert p["inputs"]["audio_url"] == "https://youtu.be/kXYiU_JCYtU"


def test_inspect_ytdlp_missing_command_is_400(env):
    with env.client(extra_env={"YTDLP_CMD": "/nonexistent/yt-dlp"}) as c:
        r = _inspect(c, YT)
    assert r.status_code == 400 and "не запускается yt-dlp" in r.json()["detail"]


# --------------------------------------------------------------------------- inspect: Яндекс

def test_inspect_yandex_needs_token(lc):
    r = _inspect(lc, "https://music.yandex.ru/album/40620828/track/148124289")
    assert r.status_code == 400
    assert r.json()["code"] == "yandex_no_token" and r.json()["detail"] == musiclink.MSG_NEED_LOGIN
    assert FakeYandex.calls == []


def test_inspect_yandex_track_and_album(env, lc):
    _store_key(env, GOOD)
    r = _inspect(lc, "https://music.yandex.ru/album/40620828/track/148124289?utm_source=web")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "yandex_track" and body["title"] == "Группа крови"
    assert body["tracks"][0]["duration"] == 285.5 and body["tracks"][0]["artist"] == "Кино"
    assert ("init", GOOD) in FakeYandex.calls
    assert ("info", "yandex_track", "https://music.yandex.ru/album/40620828/track/148124289") in FakeYandex.calls
    album = _inspect(lc, "https://music.yandex.ru/album/40620828").json()
    assert album["kind"] == "yandex_album" and len(album["tracks"]) == 3


@pytest.mark.parametrize("stored, status", [(REJECTED, 400), (OFFLINE, 503)])
def test_inspect_yandex_errors(env, lc, stored, status):
    _store_key(env, stored)
    r = _inspect(lc, "https://music.yandex.ru/track/1")
    assert r.status_code == status
    assert stored not in r.text
    if status == 400:
        assert r.json()["field"] == "url" and r.json()["detail"] == musiclink.MSG_REJECTED


# --------------------------------------------------------------------------- настройки

def test_yandex_settings_never_return_token(env, lc):
    assert lc.get("/api/settings/yandex").json() == {"has_token": False}
    r = lc.put("/api/settings/yandex", json={"token": f"  {GOOD} "})
    assert r.status_code == 200 and r.json() == {"has_token": True} and GOOD not in r.text
    assert Settings(connect(env.data / "karaoke.sqlite")).get_yandex() == GOOD
    assert GOOD not in lc.get("/api/settings/yandex").text

    r = lc.put("/api/settings/yandex", json={"token": REJECTED})
    assert r.status_code == 400 and r.json()["field"] == "token" and REJECTED not in r.text
    assert r.json()["detail"] == musiclink.MSG_REJECTED
    assert Settings(connect(env.data / "karaoke.sqlite")).get_yandex() == GOOD  # старый не тронут

    r = lc.put("/api/settings/yandex", json={"token": OFFLINE})
    assert r.status_code == 503 and OFFLINE not in r.text

    assert lc.put("/api/settings/yandex", json={"token": ""}).json() == {"has_token": False}
    assert Settings(connect(env.data / "karaoke.sqlite")).get_yandex() is None


def test_yandex_settings_test_endpoint(env, lc):
    r = lc.post("/api/settings/yandex/test", json={})
    assert r.status_code == 400 and r.json()["field"] == "token"
    assert lc.post("/api/settings/yandex/test", json={"token": GOOD}).json() == {"ok": True}
    assert Settings(connect(env.data / "karaoke.sqlite")).get_yandex() is None  # не сохраняет
    r = lc.post("/api/settings/yandex/test", json={"token": REJECTED})
    assert r.status_code == 400 and r.json()["field"] == "token" and REJECTED not in r.text
    _store_key(env, GOOD)
    assert lc.post("/api/settings/yandex/test", json={}).json() == {"ok": True}  # сохранённый


# --------------------------------------------------------------------------- generate по ссылке

MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


def _gen(c, audio_url=None, audio=None, artist="Linkin Park", title="Numb", **form):
    data = {"artist": artist, "title": title, **form}
    if audio_url is not None:
        data["audio_url"] = audio_url
    files = {"audio": ("song.mp3", audio, "audio/mpeg")} if audio is not None else None
    return c.post("/api/jobs/generate", data=data, files=files)


def test_generate_with_audio_url(env, lc):
    r = _gen(lc, YT + "&utm_medium=x", lyrics="Текст")
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["source"] == "link"
    assert p["inputs"]["audio_url"] == YT and "audio" not in p["inputs"]
    assert p["inputs"]["lyrics"] == p["inputs"]["dir"] + "/lyrics.txt"
    in_dir = env.data / p["inputs"]["dir"]
    assert in_dir.is_dir() and not (in_dir / "input.mp3").exists()

    y = _gen(lc, "https://music.yandex.ru/album/1/track/2", title="Другая").json()["params"]
    assert y["inputs"]["audio_url"] == "https://music.yandex.ru/album/1/track/2"

    plain = _gen(lc, audio=MP3, title="Файлом").json()["params"]
    assert "source" not in plain and "audio_url" not in plain["inputs"]


def test_generate_audio_url_validation(lc):
    r = _gen(lc, YT, audio=MP3)
    assert r.status_code == 400 and r.json()["field"] == "audio"
    r = _gen(lc)
    assert r.status_code == 400 and r.json()["field"] == "audio"
    r = _gen(lc, "   ")
    assert r.status_code == 400 and r.json()["field"] == "audio"
    r = _gen(lc, "https://vk.com/audio123_456")
    assert r.status_code == 400 and r.json()["detail"].startswith("Аудиозаписи ВКонтакте")
    r = _gen(lc, "https://music.yandex.ru/album/1")
    assert r.status_code == 400 and "один трек" in r.json()["detail"]
    assert lc.get("/api/jobs").json() == []


def test_generate_audio_url_duplicates(env, lc, song):
    r = _gen(lc, YT, artist="Artist", title="Song")
    assert r.status_code == 409 and r.json()["song_id"] == song["song_id"]
    assert _gen(lc, YT).status_code == 201
    r = _gen(lc, YT)
    assert r.status_code == 409 and r.json()["detail"] == "Эта песня уже в очереди"


def test_restart_link_job_without_downloaded_audio(env, lc):
    job = _gen(lc, YT, lyrics="Текст").json()
    lc.post(f"/api/jobs/{job['id']}/cancel")
    new = lc.post(f"/api/jobs/{job['id']}/restart")
    assert new.status_code == 201, new.text
    p = new.json()["params"]
    assert p["inputs"]["audio_url"] == YT and p["source"] == "link"
    assert (env.data / p["inputs"]["lyrics"]).read_text("utf-8") == "Текст"
    lc.post(f"/api/jobs/{new.json()['id']}/cancel")

    # воркер уже скачал звук — перезапуск берёт файл, ссылку не повторяет
    (env.data / p["inputs"]["dir"] / "input.mp3").write_bytes(MP3)
    again = lc.post(f"/api/jobs/{new.json()['id']}/restart").json()["params"]
    assert "audio_url" not in again["inputs"] and again["inputs"]["audio"].endswith("/input.mp3")
    assert json.dumps(again, ensure_ascii=False).count(YT) == 0


# --------------------------------------------------------------------------- своя песня и обложка

OLD_MP3 = MP3 + b"old-version"
OLD_JPG = b"\xff\xd8\xff\xe0old-cover"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
THUMB = "https://i.ytimg.com/vi/kXYiU_JCYtU/maxresdefault.jpg"


def _own_song(env, c, params=None) -> str:
    """Своя песня «Linkin Park - Numb»: в папке результата и с source/ (старый mp3, текст, обложка)."""
    rel = "Linkin Park/Linkin Park - Numb"
    env.put_song(rel, env.SONG_TXT.replace(b"Artist", b"Linkin Park").replace(b"#TITLE:Song", b"#TITLE:Numb"),
                 "Linkin Park - Numb")
    Songs(connect(env.data / "karaoke.sqlite")).upsert(artist="Linkin Park", title="Numb", rel_dir=rel,
                                                       params=params or {"language": "en"})
    src = env.data / "songs" / "Linkin Park" / "Linkin Park - Numb" / "source"
    src.mkdir(parents=True)
    (src / "input.mp3").write_bytes(OLD_MP3)
    (src / "lyrics.txt").write_text("Старый текст", "utf-8")
    (src / "cover.jpg").write_bytes(OLD_JPG)
    assert c.post("/api/songs/rescan").status_code == 202
    return c.get("/api/songs").json()["items"][0]["song_id"]


def test_restart_link_job_of_existing_song_uses_link_not_old_source_audio(env, lc):
    sid = _own_song(env, lc)
    job = _gen(lc, YT, lyrics="Новый текст", song_id=sid).json()
    assert job["params"]["inputs"]["audio_url"] == YT
    lc.post(f"/api/jobs/{job['id']}/cancel")
    new = lc.post(f"/api/jobs/{job['id']}/restart").json()
    p = new["params"]
    assert p["inputs"]["audio_url"] == YT and "audio" not in p["inputs"]
    in_dir = env.data / p["inputs"]["dir"]
    assert not (in_dir / "input.mp3").exists()
    assert (env.data / p["inputs"]["lyrics"]).read_text("utf-8") == "Новый текст"

    # in/ родителя уже нет (убран по сроку) — всё равно ссылка, текст и обложка — из source/
    lc.post(f"/api/jobs/{new['id']}/cancel")
    shutil.rmtree(in_dir)
    again = lc.post(f"/api/jobs/{new['id']}/restart")
    assert again.status_code == 201, again.text
    q = again.json()["params"]["inputs"]
    assert q["audio_url"] == YT and "audio" not in q
    assert (env.data / q["cover"]).read_bytes() == OLD_JPG


def test_regenerate_own_song_with_audio_url(env, lc, http):
    sid = _own_song(env, lc)
    r = _gen(lc, YT, lyrics="Новый текст", song_id=sid)
    assert r.status_code == 201, r.text
    inputs = r.json()["params"]["inputs"]
    assert inputs["audio_url"] == YT and "audio" not in inputs
    assert not (env.data / inputs["dir"] / "input.mp3").exists()
    assert (env.data / inputs["cover"]).read_bytes() == OLD_JPG  # обложка из source/
    assert (env.data / inputs["lyrics"]).read_text("utf-8") == "Новый текст"
    assert r.json()["params"]["replace_rel_dir"] == "Linkin Park/Linkin Park - Numb"
    lc.post(f"/api/jobs/{r.json()['id']}/cancel")

    # явная обложка со ссылки важнее обложки из source/
    http.route("GET", "https://img.example/thumb.png", body=PNG)
    r = _gen(lc, YT, lyrics="Новый текст", song_id=sid, cover_url="https://img.example/thumb.png")
    inputs = r.json()["params"]["inputs"]
    assert inputs["cover"].endswith("/in/cover.png") and (env.data / inputs["cover"]).read_bytes() == PNG
    assert not (env.data / inputs["dir"] / "cover.jpg").exists()
    lc.post(f"/api/jobs/{r.json()['id']}/cancel")

    # обложка со ссылки не скачалась — остаётся обложка из source/
    http.route("GET", "https://img.example/gone.jpg", status=404)
    r = _gen(lc, YT, lyrics="Новый текст", song_id=sid, cover_url="https://img.example/gone.jpg")
    assert (env.data / r.json()["params"]["inputs"]["cover"]).read_bytes() == OLD_JPG


def test_generate_downloads_cover_url(env, lc, http):
    jpg = b"\xff\xd8\xff\xe0thumb"
    http.route("GET", THUMB, body=jpg)
    inputs = _gen(lc, YT, cover_url=THUMB).json()["params"]["inputs"]
    assert inputs["cover"].endswith("/in/cover.jpg") and (env.data / inputs["cover"]).read_bytes() == jpg
    assert [c.url for c in http.calls()] == [THUMB]
    assert not (env.data / inputs["dir"] / ".cover").exists()


def test_generate_own_cover_file_beats_cover_url(env, lc, http):
    data = {"artist": "Linkin Park", "title": "Numb", "audio_url": YT, "cover_url": THUMB}
    r = lc.post("/api/jobs/generate", data=data, files={"cover": ("c.png", PNG, "image/png")})
    assert r.status_code == 201, r.text
    inputs = r.json()["params"]["inputs"]
    assert (env.data / inputs["cover"]).read_bytes() == PNG and http.calls() == []


@pytest.mark.parametrize("url, route", [
    ("https://img.example/404.jpg", {"status": 404}),
    ("https://img.example/html.jpg", {"body": b"<html>not an image</html>"}),
    ("https://img.example/huge.jpg", {"body": b"\xff\xd8\xff" + b"\x00" * (2 * 1024 * 1024)}),
    ("http://192.168.1.1/cover.jpg", {"body": b"\xff\xd8\xff\xe0"}),
    ("ftp://img.example/c.jpg", {"body": b"\xff\xd8\xff\xe0"}),
])
def test_generate_cover_url_failure_is_not_an_error(env, lc, http, monkeypatch, url, route):
    monkeypatch.setattr("app.api_jobs.MAX_COVER_MB", 1)
    http.route("GET", url, **route)
    r = _gen(lc, YT, cover_url=url)
    assert r.status_code == 201, r.text
    inputs = r.json()["params"]["inputs"]
    assert "cover" not in inputs
    assert sorted(p.name for p in (env.data / inputs["dir"]).iterdir()) == []
    if url.startswith(("http://192.", "ftp:")):
        assert http.calls() == []


def test_link_song_is_not_labelled_import(env, lc):
    _own_song(env, lc, params={"language": "en", "source": "link"})
    item = lc.get("/api/songs").json()["items"][0]
    assert item["own"] is True and item["source"] is None
    assert lc.get(f"/api/songs/{item['song_id']}").json()["source"] is None


def test_imported_song_keeps_import_source(env, lc):
    _own_song(env, lc, params={"source": "usdb", "usdb_id": 5})
    assert lc.get("/api/songs").json()["items"][0]["source"] == "usdb"
