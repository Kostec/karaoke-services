"""Действия над несколькими песнями сразу (истории 25–33): теги, zip, удаление, минусовка."""

from __future__ import annotations

import io
import shutil
import zipfile
from urllib.parse import quote

from karaoke_core import naming
from karaoke_core.db import Settings, Target, connect

REL = "Artist/Artist - Song"


def _txt(artist: str, title: str, *, audio: bool = True, instrumental: bool = False) -> bytes:
    base = f"{artist} - {title}"
    lines = [f"#TITLE:{title}", f"#ARTIST:{artist}"]
    if audio:
        lines.append(f"#MP3:{base}.mp3")
    if instrumental:
        lines.append(f"#INSTRUMENTAL:{base} [Instrumental].mp3")
    lines += ["#BPM:300", "#GAP:0", ": 0 4 5 Раз", "E", ""]
    return "\n".join(lines).encode("utf-8")


def _put(env, artist: str, title: str, *, audio: bool = True, instrumental: bool = False, root=None):
    base = f"{artist} - {title}"
    d = (root or env.out) / artist / base
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{base}.txt").write_bytes(_txt(artist, title, audio=audio, instrumental=instrumental))
    (d / f"{base}.mp3").write_bytes(env.MP3)
    if instrumental:
        (d / f"{base} [Instrumental].mp3").write_bytes(env.MP3)
    return d


def _ids(client, target: str | None = None) -> dict[str, str]:
    """``{название: song_id}`` песен хранилища после пересканирования."""
    q = f"?target={target}" if target else ""
    assert client.post(f"/api/songs/rescan{q}").status_code == 202
    return {i["title"]: i["song_id"] for i in client.get(f"/api/songs{q}").json()["items"]}


def _pc(env, client) -> Target:
    """Хранилище «ПК» (``/host/pc`` → ``tmp/host/pc``)."""
    target = Settings(connect(env.data / "karaoke.sqlite")).save_target(
        Target(name="ПК", kind="local", path="/host/pc"))
    (env.tmp / "host" / "pc").mkdir(parents=True, exist_ok=True)
    return target


def _tag(client, name: str) -> str:
    r = client.post("/api/tags", json={"name": name, "color": "blue"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- теги


def test_bulk_tags_add_and_remove_keep_other_tags(env, client):
    _put(env, "Artist", "One")
    _put(env, "Artist", "Two")
    ids = _ids(client)
    keep, old, new = _tag(client, "Оставить"), _tag(client, "Снять"), _tag(client, "Добавить")
    for sid in ids.values():
        assert client.put(f"/api/songs/{sid}/tags", json={"tag_ids": [keep, old]}).status_code == 200
    r = client.post("/api/songs/tags", json={"song_ids": list(ids.values()), "add": [new], "remove": [old]})
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 2, "errors": []}
    for sid in ids.values():
        assert sorted(client.get(f"/api/songs/{sid}").json()["tags"]) == sorted([keep, new])


def test_bulk_tags_copies_share_one_key_without_duplicates(env, client):
    pc = _pc(env, client)
    _put(env, "Artist", "One")
    _put(env, "Artist", "One", root=env.tmp / "host" / "pc")
    local, other = _ids(client)["One"], _ids(client, pc.id)["One"]
    tag = _tag(client, "Общий")
    r = client.post("/api/songs/tags", json={"song_ids": [local, other], "add": [tag], "remove": []})
    assert r.status_code == 200 and r.json()["errors"] == []
    links = client.app.state.ctx.tags.for_songs([naming.song_tag_key("Artist", "One")])
    assert list(links.values()) == [[tag]]
    assert client.get(f"/api/songs/{other}").json()["tags"] == [tag]


def test_bulk_tags_unknown_song_is_error_and_others_done(env, client):
    _put(env, "Artist", "One")
    sid = _ids(client)["One"]
    tag = _tag(client, "Т")
    r = client.post("/api/songs/tags", json={"song_ids": [sid, "nope"], "add": [tag]})
    assert r.status_code == 200
    assert r.json() == {"updated": 1, "errors": [{"song_id": "nope", "detail": "Песня не найдена"}]}
    assert client.get(f"/api/songs/{sid}").json()["tags"] == [tag]


def test_bulk_tags_unknown_tag_is_400_and_changes_nothing(env, client):
    _put(env, "Artist", "One")
    sid = _ids(client)["One"]
    tag = _tag(client, "Т")
    r = client.post("/api/songs/tags", json={"song_ids": [sid], "add": [tag, "t_nope"], "remove": []})
    assert r.status_code == 400 and r.json()["field"] == "add"
    r = client.post("/api/songs/tags", json={"song_ids": [sid], "add": [tag], "remove": ["t_nope"]})
    assert r.status_code == 400 and r.json()["field"] == "remove"
    assert client.get(f"/api/songs/{sid}").json()["tags"] == []


# --------------------------------------------------------------------------- лимиты


def test_bulk_limits_are_400_song_ids(env, client):
    many = [f"s{i}" for i in range(1001)]
    for url, body in [("/api/songs/tags", {"song_ids": many, "add": []}),
                      ("/api/songs/delete", {"song_ids": many}),
                      ("/api/jobs/instrumental/bulk", {"song_ids": many})]:
        r = client.post(url, json=body)
        assert r.status_code == 400 and r.json()["field"] == "song_ids", (url, r.text)
    r = client.post("/api/songs/zip", data={"song_ids": ",".join(many[:501])})
    assert r.status_code == 400 and r.json()["field"] == "song_ids"
    r = client.post("/api/songs/zip", data={"song_ids": ""})
    assert r.status_code == 400 and r.json()["field"] == "song_ids"


# --------------------------------------------------------------------------- zip


def test_bulk_zip_streams_song_folders_and_not_included_list(env, client):
    _put(env, "Artist", "One")
    _put(env, "Band", "Two")
    ids = _ids(client)
    r = client.post("/api/songs/zip", data={"song_ids": f"{ids['One']},nope,{ids['Two']}"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert quote("Песни (3).zip") in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert {"Artist/Artist - One/Artist - One.txt", "Artist/Artist - One/Artist - One.mp3",
            "Band/Band - Two/Band - Two.txt", "Band/Band - Two/Band - Two.mp3"} <= names
    assert zf.read("Band/Band - Two/Band - Two.mp3") == env.MP3
    skipped = zf.read("НЕ ВОШЛО.txt").decode("utf-8")
    assert "nope" in skipped and "Песня не найдена" in skipped


def test_bulk_zip_unavailable_storage_goes_to_not_included(env, client):
    pc = _pc(env, client)
    _put(env, "Artist", "One")
    _put(env, "Band", "Two", root=env.tmp / "host" / "pc")
    local, other = _ids(client)["One"], _ids(client, pc.id)["Two"]
    shutil.rmtree(env.tmp / "host" / "pc")
    r = client.post("/api/songs/zip", data={"song_ids": f"{local},{other}"})
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "Artist/Artist - One/Artist - One.txt" in zf.namelist()
    assert not any(n.startswith("Band/") for n in zf.namelist())
    assert "Band — Two" in zf.read("НЕ ВОШЛО.txt").decode("utf-8")


# --------------------------------------------------------------------------- удаление


def test_bulk_delete_moves_to_trash_and_reports_errors(env, client):
    _put(env, "Artist", "One")
    _put(env, "Band", "Two")
    ids = _ids(client)
    r = client.post("/api/songs/delete", json={"song_ids": [ids["One"], "nope", ids["Two"]]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["removed"] == [ids["One"], ids["Two"]]
    assert body["errors"] == [{"song_id": "nope", "detail": "Песня не найдена"}]
    assert not (env.out / "Artist" / "Artist - One").exists()
    assert client.get("/api/songs").json()["items"] == []
    trash = client.get("/api/trash").json()
    assert len(trash) == 2  # ничего не удалено навсегда — всё в корзине
    assert client.post(f"/api/trash/{trash[0]['id']}/restore").status_code == 200


def test_bulk_delete_unavailable_storage_is_error_others_removed(env, client):
    pc = _pc(env, client)
    _put(env, "Artist", "One")
    _put(env, "Band", "Two", root=env.tmp / "host" / "pc")
    _put(env, "Band", "Three", root=env.tmp / "host" / "pc")
    local = _ids(client)["One"]
    others = _ids(client, pc.id)
    shutil.rmtree(env.tmp / "host" / "pc")
    r = client.post("/api/songs/delete", json={"song_ids": [others["Two"], local, others["Three"]]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["removed"] == [local]
    assert [e["song_id"] for e in body["errors"]] == [others["Two"], others["Three"]]
    assert all(e["detail"] for e in body["errors"])
    assert len(client.get("/api/trash").json()) == 1


# --------------------------------------------------------------------------- минусовка


def test_bulk_instrumental_queues_and_skips_with_reasons(env, client):
    _put(env, "Artist", "Plain")
    _put(env, "Artist", "Has", instrumental=True)
    _put(env, "Artist", "Mute", audio=False)
    ids = _ids(client)
    body = {"song_ids": [ids["Plain"], ids["Has"], ids["Mute"], "nope"]}
    r = client.post("/api/jobs/instrumental/bulk", json=body)
    assert r.status_code == 201, r.text
    res = r.json()
    assert len(res["queued"]) == 1
    job = client.get(f"/api/jobs/{res['queued'][0]}").json()
    assert job["type"] == "instrumental" and job["song_id"] == ids["Plain"]
    assert res["skipped"] == [{"song_id": ids["Has"], "reason": "уже есть минусовка"},
                              {"song_id": ids["Mute"], "reason": "нет звука"}]
    assert res["errors"] == [{"song_id": "nope", "detail": "Песня не найдена"}]
    again = client.post("/api/jobs/instrumental/bulk", json={"song_ids": [ids["Plain"], ids["Plain"]]}).json()
    assert again["queued"] == []
    assert again["skipped"] == [{"song_id": ids["Plain"], "reason": "уже в очереди"}]  # повтор id — один раз


def test_bulk_instrumental_replace_recreates_existing(env, client):
    _put(env, "Artist", "Has", instrumental=True)
    sid = _ids(client)["Has"]
    r = client.post("/api/jobs/instrumental/bulk", json={"song_ids": [sid], "replace": True})
    assert r.status_code == 201
    res = r.json()
    assert len(res["queued"]) == 1 and res["skipped"] == [] and res["errors"] == []
