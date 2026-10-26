"""Свои теги (REST), теги в списке песен, сведения страницы песни и отдача любого файла папки."""

from __future__ import annotations

from urllib.parse import quote

from karaoke_core.db import Settings, Songs, Target, connect

REL = "Artist/Artist - Song"


def _tag(client, name, color=None):
    body = {"name": name} if color is None else {"name": name, "color": color}
    r = client.post("/api/tags", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _other_target(env, client, *, txt=None):
    """Второе хранилище «ПК» (``/host/pc``) с той же песней."""
    target = Settings(connect(env.data / "karaoke.sqlite")).save_target(
        Target(name="ПК", kind="local", path="/host/pc"))
    d = env.tmp / "host" / "pc" / "Artist" / "Artist - Song"
    d.mkdir(parents=True)
    (d / "Artist - Song.txt").write_bytes(txt or env.SONG_TXT)
    (d / "Artist - Song.mp3").write_bytes(env.MP3)
    item = client.app.state.ctx.refresh_song(REL, target.id)
    return target, item.song_id


# ------------------------------------------------------------------ REST тегов

def test_tags_crud_and_errors(client):
    r = client.get("/api/tags")
    assert r.json() == {"tags": [], "colors": ["blue", "violet", "pink", "orange", "yellow", "teal",
                                               "gray", "red"], "default_color": "blue"}
    t = _tag(client, " Рок ")
    assert t == {"id": t["id"], "name": "Рок", "color": "blue", "count": 0}
    p = _tag(client, "Акустика", "teal")

    for body, field, text in [({"name": ""}, "name", "Введите название тега"),
                              ({"name": "x" * 41}, "name", "Не длиннее 40 символов"),
                              ({"name": "рок"}, "name", "Такой тег уже есть"),
                              ({"name": "Новый", "color": "green"}, "color", "Неизвестный цвет")]:
        r = client.post("/api/tags", json=body)
        assert r.status_code == 400, body
        assert r.json() == {"detail": text, "field": field}

    r = client.put(f"/api/tags/{t['id']}", json={"color": "red"})
    assert r.status_code == 200 and r.json() == {"id": t["id"], "name": "Рок", "color": "red", "count": 0}
    r = client.put(f"/api/tags/{t['id']}", json={"name": "Ёж"})
    assert r.json()["name"] == "Ёж"
    r = client.put(f"/api/tags/{p['id']}", json={"name": "еж"})
    assert r.status_code == 400 and r.json()["field"] == "name"
    assert client.put("/api/tags/nope", json={"name": "x"}).status_code == 404

    names = [x["name"] for x in client.get("/api/tags").json()["tags"]]
    assert names == ["Акустика", "Ёж"]

    assert client.delete("/api/tags/nope").status_code == 404
    r = client.delete(f"/api/tags/{p['id']}")
    assert r.status_code == 200 and r.json() == {"ok": True, "removed": 0}


def test_song_tags_set_list_count_and_delete(client, song):
    a = _tag(client, "Б-тег")
    b = _tag(client, "А-тег", "pink")
    sid = song["song_id"]
    assert song["tags"] == []

    r = client.put(f"/api/songs/{sid}/tags", json={"tag_ids": [a["id"], b["id"]]})
    assert r.status_code == 200 and r.json() == {"tags": [b["id"], a["id"]]}
    assert client.get("/api/songs").json()["items"][0]["tags"] == [b["id"], a["id"]]
    assert client.get(f"/api/songs/{sid}").json()["tags"] == [b["id"], a["id"]]
    counts = {x["id"]: x["count"] for x in client.get("/api/tags").json()["tags"]}
    assert counts == {a["id"]: 1, b["id"]: 1}
    assert client.put(f"/api/tags/{a['id']}", json={"color": "red"}).json()["count"] == 1

    r = client.put(f"/api/songs/{sid}/tags", json={"tag_ids": [a["id"], "nope"]})
    assert r.status_code == 400 and r.json()["field"] == "tag_ids"
    assert client.put("/api/songs/0000000000000000/tags", json={"tag_ids": []}).status_code == 404

    r = client.delete(f"/api/tags/{a['id']}")
    assert r.json() == {"ok": True, "removed": 1}
    assert client.get(f"/api/songs/{sid}").json()["tags"] == [b["id"]]


def test_list_reads_tags_in_one_query(env, client, monkeypatch):
    for n in range(3):
        env.put_song(f"A{n}/A{n} - S", f"#TITLE:S\n#ARTIST:A{n}\n#BPM:300\n: 0 1 1 a\nE\n".encode(), f"A{n} - S")
    client.post("/api/songs/rescan")
    from karaoke_core import db

    calls = []
    orig = db.Tags.for_songs
    monkeypatch.setattr(db.Tags, "for_songs", lambda self, keys: calls.append(list(keys)) or orig(self, keys))
    items = client.get("/api/songs").json()["items"]
    assert len(items) == 3 and all(i["tags"] == [] for i in items)
    assert len(calls) == 1 and len(calls[0]) == 3


def test_tag_shared_by_copy_in_other_storage(env, client, song):
    t = _tag(client, "Общий")
    client.put(f"/api/songs/{song['song_id']}/tags", json={"tag_ids": [t["id"]]})
    target, other_id = _other_target(env, client)
    assert other_id != song["song_id"]
    items = client.get(f"/api/songs?target={target.id}").json()["items"]
    assert items[0]["tags"] == [t["id"]]
    assert client.get(f"/api/songs/{other_id}").json()["tags"] == [t["id"]]


def test_tags_survive_trash_and_restore(env, client, song):
    t = _tag(client, "Живучий")
    client.put(f"/api/songs/{song['song_id']}/tags", json={"tag_ids": [t["id"]]})
    r = client.delete(f"/api/songs/{song['song_id']}")
    assert r.status_code == 200
    assert client.post(f"/api/trash/{r.json()['id']}/restore").status_code == 200
    assert client.get(f"/api/songs/{song['song_id']}").json()["tags"] == [t["id"]]


# ------------------------------------------------------------------ сведения песни

def test_details_full(env, client):
    txt = ("#TITLE:Song\n#ARTIST:Artist\n#AUTHOR:Композитор\n#MP3:Artist - Song.mp3\n"
           "#COVER:Artist - Song [CO].jpg\n#BACKGROUND:artist - song [bg].JPG\n"
           "#INSTRUMENTAL:Artist - Song [Instrumental].mp3\n#VIDEO:Artist - Song.mp4\n#VIDEOGAP:1.5\n"
           "#BPM:300\n#GAP:1000\n#LANGUAGE:Russian\n#YEAR:\n#GENRE:Rock\n#CREATOR:me\n"
           ": 0 4 5 При\nE\n").encode("utf-8")
    d = env.put_song(REL, txt, "Artist - Song")
    (d / "Artist - Song [Instrumental].mp3").write_bytes(b"i" * 10)
    (d / "Artist - Song [Vocals].mp3").write_bytes(b"v" * 7)
    (d / "Artist - Song.mp4").write_bytes(b"m" * 5)
    (d / "Artist - Song [BG].jpg").write_bytes(b"b" * 3)
    (d / "b.mid").write_bytes(b"x")
    (d / "a.mid").write_bytes(b"x")
    (d / "sub").mkdir()
    (d / "sub" / "deep.txt").write_bytes(b"x")
    Songs(connect(env.data / "karaoke.sqlite")).upsert(
        artist="Artist", title="Song", rel_dir=REL, params={"source": "usdb", "usdb_id": 123})
    client.post("/api/songs/rescan")
    sid = client.get("/api/songs").json()["items"][0]["song_id"]

    r = client.get(f"/api/songs/{sid}/details")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["song"] == client.get(f"/api/songs/{sid}").json()
    assert body["headers"] == {"author": "Композитор", "bpm": "300", "gap": "1000", "language": "Russian",
                               "genre": "Rock", "creator": "me", "videogap": "1.5"}
    assert body["singers"] is None
    assert body["media"] == {"audio": "Artist - Song.mp3",
                             "instrumental": "Artist - Song [Instrumental].mp3",
                             "vocals": "Artist - Song [Vocals].mp3", "video": "Artist - Song.mp4",
                             "cover": "Artist - Song [CO].jpg", "background": "Artist - Song [BG].jpg",
                             "midi": "a.mid"}
    names = [f["name"] for f in body["files"]]
    assert names == sorted(names) and "sub" not in names and "deep.txt" not in names
    sizes = {f["name"]: f["size"] for f in body["files"]}
    assert sizes["Artist - Song [Vocals].mp3"] == 7 and sizes["Artist - Song [Instrumental].mp3"] == 10
    assert all(isinstance(f["mtime"], (int, float)) for f in body["files"])
    [copy] = body["copies"]
    assert copy["target_name"] and isinstance(copy["target_name"], str)
    assert copy == {"song_id": sid, "target_id": "local", "target_name": copy["target_name"], "current": True}
    assert body["usdb_url"] == "https://usdb.animux.de/index.php?link=detail&id=123"


def test_details_minimal_duet_copies_and_404(env, client):
    d = env.put_song("Pair/Pair - Duet", env.DUET_TXT.replace(b"#BPM", "#P1:Аня\n#P2:Боря\n#BACKGROUND:nope.jpg\n#BPM".encode()),
                     "Pair - Duet", cover=None)
    assert d.is_dir()
    client.post("/api/songs/rescan")
    sid = client.get("/api/songs").json()["items"][0]["song_id"]
    body = client.get(f"/api/songs/{sid}/details").json()
    assert body["singers"] == {"p1": "Аня", "p2": "Боря"}
    assert body["headers"] == {"bpm": "300", "gap": "0"}
    assert body["media"] == {"audio": "Pair - Duet.mp3", "instrumental": None, "vocals": None,
                             "video": None, "cover": None, "background": None, "midi": None}
    assert body["usdb_url"] is None
    assert client.get("/api/songs/0000000000000000/details").status_code == 404


def test_details_copies_across_storages(env, client, song):
    target, other_id = _other_target(env, client)
    body = client.get(f"/api/songs/{other_id}/details").json()
    copies = {c["target_id"]: c for c in body["copies"]}
    assert copies["local"] == {"song_id": song["song_id"], "target_id": "local",
                               "target_name": copies["local"]["target_name"], "current": False}
    assert copies[target.id] == {"song_id": other_id, "target_id": target.id, "target_name": "ПК",
                                 "current": True}
    assert len(body["copies"]) == 2
    assert copies["local"]["target_name"]


def _txt(artist, title):
    return f"#TITLE:{title}\n#ARTIST:{artist}\n#MP3:{artist} - {title}.mp3\n#BPM:300\n: 0 1 1 a\nE\n".encode()


def test_details_copies_match_key_ignores_case_and_yo(env, client):
    env.put_song("Ёлка/Ёлка - Прованс", _txt("Ёлка", "Прованс"), "Ёлка - Прованс")
    env.put_song("Other/Other - X", _txt("Other", "X"), "Other - X")
    client.post("/api/songs/rescan")
    sid = next(i["song_id"] for i in client.get("/api/songs").json()["items"] if i["artist"] == "Ёлка")
    target = Settings(connect(env.data / "karaoke.sqlite")).save_target(
        Target(name="ПК", kind="local", path="/host/pc"))
    d = env.tmp / "host" / "pc" / "Елка" / "Елка - прованс"
    d.mkdir(parents=True)
    (d / "Елка - прованс.txt").write_bytes(_txt("ЕЛКА", "прованс"))
    other = client.app.state.ctx.refresh_song("Елка/Елка - прованс", target.id)
    ids = {c["song_id"] for c in client.get(f"/api/songs/{sid}/details").json()["copies"]}
    assert ids == {sid, other.song_id}


# ------------------------------------------------------------------ любой файл папки

def test_file_range_download_and_bad_names(env, client, song):
    d = env.out / "Artist" / "Artist - Song"
    (d / "Artist - Song [Vocals].mp3").write_bytes(b"0123456789")
    (d / "sub").mkdir()
    (d / "sub" / "x.txt").write_bytes(b"x")
    url = f"/api/songs/{song['song_id']}/file"

    r = client.get(url, params={"name": "artist - song [vocals].MP3"}, headers={"Range": "bytes=2-5"})
    assert r.status_code == 206 and r.content == b"2345"
    assert r.headers["content-range"] == "bytes 2-5/10"
    assert "content-disposition" not in r.headers

    r = client.get(url, params={"name": "Artist - Song [Vocals].mp3", "download": "1"})
    assert r.status_code == 200 and r.content == b"0123456789"
    assert r.headers["content-disposition"] == (
        "attachment; filename*=UTF-8''" + quote("Artist - Song [Vocals].mp3"))

    for bad in ["nope.mp3", "sub", "sub/x.txt", "..", "../Artist - Song/Artist - Song.mp3",
                "sub\\x.txt", ""]:
        r = client.get(url, params={"name": bad})
        assert r.status_code == 404, bad
        assert r.json()["detail"] == "У песни нет такого файла"
    assert client.get("/api/songs/0000000000000000/file", params={"name": "x"}).status_code == 404


def test_file_inline_only_media_and_nosniff(env, client, song):
    """Чужой HTML/SVG папки песни не исполняется в адресе сервиса: отдаётся вложением."""
    d = env.out / "Artist" / "Artist - Song"
    (d / "evil.html").write_bytes(b"<script>alert(1)</script>")
    (d / "evil.svg").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    (d / "back.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (d / "clip.mp4").write_bytes(b"0000")
    url = f"/api/songs/{song['song_id']}/file"

    for name in ["evil.html", "evil.svg", "Artist - Song.txt"]:
        r = client.get(url, params={"name": name})
        assert r.status_code == 200, name
        assert r.headers["content-disposition"] == "attachment; filename*=UTF-8''" + quote(name), name
        assert r.headers["x-content-type-options"] == "nosniff", name

    for name in ["Artist - Song.mp3", "back.png", "clip.mp4"]:
        r = client.get(url, params={"name": name})
        assert r.status_code == 200, name
        assert "content-disposition" not in r.headers, name
        assert r.headers["x-content-type-options"] == "nosniff", name
