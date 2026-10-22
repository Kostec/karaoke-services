"""Песня в неосновном хранилище: карточка, ноты, удаление и корзина работают с её копией."""

from karaoke_core.db import Settings, Target, connect

REL = "Artist/Artist - Song"


def _other_target(env, client):
    """Хранилище «Папка ПК» в ``/host/pc`` (во временной ``tmp/host/pc``) с одной песней."""
    target = Settings(connect(env.data / "karaoke.sqlite")).save_target(
        Target(name="ПК", kind="local", path="/host/pc"))
    root = env.tmp / "host" / "pc"
    d = root / "Artist" / "Artist - Song"
    d.mkdir(parents=True)
    (d / "Artist - Song.txt").write_bytes(env.SONG_TXT)
    (d / "Artist - Song.mp3").write_bytes(env.MP3)
    item = client.app.state.ctx.refresh_song(REL, target.id)
    assert item is not None and item.target_id == target.id
    return target, d, item.song_id


def test_song_in_other_storage_notes_delete_restore(env, client):
    target, d, song_id = _other_target(env, client)
    assert client.get("/api/songs").json()["items"] == []  # основная цель — пустая «local»
    assert client.get(f"/api/songs/{song_id}").json()["target_id"] == target.id
    notes = client.get(f"/api/songs/{song_id}/notes")
    assert notes.status_code == 200, notes.text
    body = notes.json()
    put = {"gap": 2000, "lines": [{"break_beat": ln["break_beat"], "notes": ln["notes"]}
                                  for ln in body["lines"]]}
    r = client.put(f"/api/songs/{song_id}/notes", json=put)
    assert r.status_code == 200, r.text
    assert b"#GAP:2000\n" in (d / "Artist - Song.txt").read_bytes()

    r = client.delete(f"/api/songs/{song_id}")
    assert r.status_code == 200, r.text
    assert not d.exists()
    trash_id = r.json()["id"]
    assert r.json()["target_id"] == target.id
    r = client.post(f"/api/trash/{trash_id}/restore")
    assert r.status_code == 200, r.text
    assert (d / "Artist - Song.txt").is_file() and not (env.out / "Artist").exists()
    assert client.get(f"/api/songs/{song_id}").status_code == 200


def test_restore_into_removed_storage_is_409(env, client):
    target, d, song_id = _other_target(env, client)
    trash_id = client.delete(f"/api/songs/{song_id}").json()["id"]
    Settings(connect(env.data / "karaoke.sqlite")).delete_target(target.id)
    r = client.post(f"/api/trash/{trash_id}/restore")
    assert r.status_code == 409
    assert r.json()["detail"] == "Хранилище «/host/pc» удалено из настроек"
    assert not d.exists()
