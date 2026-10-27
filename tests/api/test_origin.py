"""Защита от подделки запроса с чужой страницы: изменяющие запросы /api/ с чужим Origin — 403."""

from __future__ import annotations

import json

import pytest

from karaoke_core.db import Jobs, Settings, connect

MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
EVIL = {"Origin": "http://evil.example"}


def _backup(client) -> bytes:
    data = json.loads(client.get("/api/settings/backup").content)
    data["targets"].append({"id": "t_0badc0de", "name": "Диск", "kind": "webdav",
                            "url": "https://webdav.yandex.ru", "preset": "yandex", "user": "me", "path": "K"})
    data["mirrors"] = [{"from_target": "local", "to_target": "t_0badc0de", "enabled": True}]
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _apply(client, raw: bytes, headers: dict | None = None):
    return client.post("/api/settings/backup?apply=1", headers=headers,
                       files={"file": ("karaoke-settings.json", raw, "application/json")})


@pytest.mark.parametrize("headers", [EVIL, {"Origin": "null"}, {"Origin": "http://testserver:9999"},
                                     {"Sec-Fetch-Site": "cross-site"}])
def test_backup_apply_from_foreign_page_is_403_and_changes_nothing(env, client, headers):
    raw = _backup(client)
    r = _apply(client, raw, headers)
    assert r.status_code == 403, r.text
    assert "чуж" in r.json()["detail"]
    settings = Settings(connect(env.data / "karaoke.sqlite"))
    assert settings.get_target("t_0badc0de") is None
    assert settings.get_mirrors() == []


@pytest.mark.parametrize("headers", [None, {"Origin": "http://testserver"},
                                     {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}])
def test_backup_apply_same_origin_or_no_origin_passes(env, client, headers):
    r = _apply(client, _backup(client), headers)
    assert r.status_code == 200, r.text
    assert Settings(connect(env.data / "karaoke.sqlite")).get_target("t_0badc0de") is not None


def test_artwork_and_generate_from_foreign_page_are_403(env, client):
    env.put_song("Artist/Artist - Song", env.SONG_TXT, "Artist - Song")
    assert client.post("/api/songs/rescan").status_code == 202
    song = client.get("/api/songs").json()["items"][0]
    r = client.post("/api/jobs/artwork", headers=EVIL, data={"song_id": song["song_id"], "kind": "cover",
                                                              "remove": "1"})
    assert r.status_code == 403, r.text
    r = client.post("/api/jobs/generate", headers=EVIL, data={"artist": "A", "title": "T"},
                    files={"audio": ("a.mp3", MP3, "audio/mpeg")})
    assert r.status_code == 403, r.text
    for method in ("put", "delete", "patch"):
        assert getattr(client, method)("/api/tags/1", headers=EVIL).status_code == 403
    assert Jobs(connect(env.data / "karaoke.sqlite")).list() == []
    # чтение и запросы своей страницы — как раньше
    assert client.get("/api/songs", headers=EVIL).status_code == 200
    r = client.post("/api/jobs/artwork", headers={"Origin": "http://testserver"},
                    data={"song_id": song["song_id"], "kind": "cover", "remove": "1"})
    assert r.status_code == 201, r.text
