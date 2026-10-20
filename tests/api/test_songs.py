"""Песни: индекс, exists, карточка, текст, ноты, аудио/обложка, удаление, корзина."""

from karaoke_core.db import Songs, connect


def test_list_rescan_and_search(env, client):
    r = client.get("/api/songs").json()
    assert r["items"] == [] and r["output"]["ok"] is True and r["output"]["label"]
    env.put_song("Artist/Artist - Song", env.SONG_TXT, "Artist - Song")
    env.put_song("Pair/Pair - Duet", env.DUET_TXT, "Pair - Duet", cover=None)
    assert client.post("/api/songs/rescan").status_code == 202
    r = client.get("/api/songs").json()
    assert r["scanned_at"]
    assert [(i["artist"], i["title"], i["is_duet"], i["own"]) for i in r["items"]] == [
        ("Artist", "Song", False, False), ("Pair", "Duet", True, False)]
    assert [i["title"] for i in client.get("/api/songs", params={"q": "дуэт"}).json()["items"]] == []
    assert [i["title"] for i in client.get("/api/songs", params={"q": "PAIR"}).json()["items"]] == ["Duet"]


def test_unavailable_output_keeps_last_index(env, client, song):
    env.out.rename(env.tmp / "gone")
    client.post("/api/songs/rescan")
    r = client.get("/api/songs").json()
    assert r["output"]["ok"] is False and r["output"]["error"]
    assert [i["title"] for i in r["items"]] == ["Song"]


def test_exists(client, song):
    r = client.get("/api/songs/exists", params={"artist": "artist ", "title": "song"}).json()
    assert r == {"exists": True, "song_id": song["song_id"]}
    assert client.get("/api/songs/exists", params={"artist": "X", "title": "Y"}).json() == {"exists": False}


def test_song_card_and_lyrics(env, client, song):
    r = client.get(f"/api/songs/{song['song_id']}").json()
    assert r["own"] is False and r["rel_dir"] == "Artist/Artist - Song" and r["audio"] == "Artist - Song.mp3"
    assert client.get(f"/api/songs/{song['song_id']}/lyrics").json() == {
        "text": "Привет\nмир!", "source": "extracted"}
    assert client.get("/api/songs/nope").json()["detail"] == "Песня не найдена"


def test_own_song_card_has_params_and_own_lyrics(env, client):
    env.put_song("Artist/Artist - Song", env.SONG_TXT, "Artist - Song")
    own = Songs(connect(env.data / "karaoke.sqlite")).upsert(
        artist="Artist", title="Song", rel_dir="Artist/Artist - Song", params={"language": "ru"})
    src = env.data / "songs" / "Artist" / "Artist - Song" / "source"
    src.mkdir(parents=True)
    (src / "lyrics.txt").write_text("[Куплет]\nПри вет мир", "utf-8")
    client.post("/api/songs/rescan")
    item = client.get("/api/songs").json()["items"][0]
    assert item["own"] is True and item["own_song_id"] == own.id
    card = client.get(f"/api/songs/{item['song_id']}").json()
    assert card["params"] == {"language": "ru"} and card["lyrics"] == "[Куплет]\nПри вет мир"
    assert client.get(f"/api/songs/{item['song_id']}/lyrics").json()["source"] == "own"


def test_notes_roundtrip_edit_and_version_in_trash(env, client, song):
    sid = song["song_id"]
    txt = env.out / "Artist" / "Artist - Song" / "Artist - Song.txt"
    notes = client.get(f"/api/songs/{sid}/notes").json()
    assert notes["editable"] is True and notes["bpm"] == 300 and notes["gap"] == 1000
    assert ["X-CUSTOM", "keep"] in notes["headers"]
    assert [[n["text"] for n in ln["notes"]] for ln in notes["lines"]] == [["При", "вет"], ["мир", "!"]]
    assert notes["lines"][0]["break_beat"] == 10

    r = client.put(f"/api/songs/{sid}/notes", json=notes)
    assert r.status_code == 200 and txt.read_bytes() == env.SONG_TXT
    assert client.get("/api/trash").json() == []

    notes["lines"][1]["notes"][0]["text"] = "мiр"
    r = client.put(f"/api/songs/{sid}/notes", json=notes)
    assert r.status_code == 200 and r.json()["rel_dir"] == "Artist/Artist - Song"
    assert txt.read_bytes() == env.SONG_TXT.replace(": 12 4 7 мир".encode(), ": 12 4 7 мiр".encode())
    trash = client.get("/api/trash").json()
    assert len(trash) == 1 and trash[0]["kind"] == "version"


def test_notes_merge_split_delete(env, client, song):
    sid = song["song_id"]
    txt = env.out / "Artist" / "Artist - Song" / "Artist - Song.txt"
    notes = client.get(f"/api/songs/{sid}/notes").json()
    a, b = notes["lines"]
    # склеить строки, удалить «!», разбить перед «вет»
    merged = a["notes"] + b["notes"][:1]
    notes["lines"] = [{"break_beat": None, "notes": merged[:1]}, {"break_beat": None, "notes": merged[1:]}]
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert txt.read_text("utf-8").endswith(": 0 4 5 При\n- 4\n: 4 4 5 вет\n: 12 4 7 мир\nE\n")


def test_notes_reject_timing_change_and_duet(env, client, song):
    sid = song["song_id"]
    notes = client.get(f"/api/songs/{sid}/notes").json()
    notes["lines"][0]["notes"][0]["start"] = 1
    r = client.put(f"/api/songs/{sid}/notes", json=notes)
    assert r.status_code == 400 and r.json()["detail"] == "Тайминги и высоты нот менять нельзя — только текст"

    env.put_song("Pair/Pair - Duet", env.DUET_TXT, "Pair - Duet")
    client.post("/api/songs/rescan")
    duet = next(i for i in client.get("/api/songs").json()["items"] if i["is_duet"])
    n = client.get(f"/api/songs/{duet['song_id']}/notes").json()
    assert n["editable"] is False and n["reason"] == "Дуэты редактор пока не поддерживает — только просмотр"
    r = client.put(f"/api/songs/{duet['song_id']}/notes", json=n)
    assert r.status_code == 409 and r.json()["detail"] == n["reason"]


def test_audio_range_and_cover(env, client, song):
    sid = song["song_id"]
    full = client.get(f"/api/songs/{sid}/audio")
    assert full.status_code == 200 and full.content == env.MP3
    assert full.headers["accept-ranges"] == "bytes" and full.headers["content-type"] == "audio/mpeg"
    r = client.get(f"/api/songs/{sid}/audio", headers={"Range": "bytes=3-9"})
    assert r.status_code == 206 and r.content == env.MP3[3:10]
    assert r.headers["content-range"] == f"bytes 3-9/{len(env.MP3)}"
    r = client.get(f"/api/songs/{sid}/audio", headers={"Range": "bytes=5000-"})
    assert r.status_code == 416
    r = client.get(f"/api/songs/{sid}/audio", headers={"Range": "bytes=-5"})
    assert r.status_code == 206 and r.content == env.MP3[-5:]
    c = client.get(f"/api/songs/{sid}/cover")
    assert c.status_code == 200 and c.headers["content-type"] == "image/jpeg"


def test_missing_cover_is_404(env, client):
    env.put_song("Pair/Pair - Duet", env.DUET_TXT, "Pair - Duet", cover=None)
    client.post("/api/songs/rescan")
    sid = client.get("/api/songs").json()["items"][0]["song_id"]
    r = client.get(f"/api/songs/{sid}/cover")
    assert r.status_code == 404 and r.json()["detail"] == "У песни нет такого файла"


def test_unavailable_output_is_503_for_file_endpoints(env, client, song):
    sid = song["song_id"]
    notes = client.get(f"/api/songs/{sid}/notes").json()
    env.out.rename(env.tmp / "gone")
    for method, path, kw in (("GET", "notes", {}), ("PUT", "notes", {"json": notes}), ("GET", "audio", {}),
                             ("GET", "cover", {}), ("GET", "lyrics", {}), ("DELETE", "", {})):
        r = client.request(method, f"/api/songs/{sid}/{path}".rstrip("/"), **kw)
        assert r.status_code == 503, (method, path, r.text)
        assert r.json()["detail"].startswith("Папка результата недоступна")


def test_delete_trash_restore(env, client, song):
    sid = song["song_id"]
    r = client.delete(f"/api/songs/{sid}")
    assert r.status_code == 200 and r.json()["kind"] == "song" and r.json()["days_left"] == 30
    assert not (env.out / "Artist" / "Artist - Song").exists()
    assert client.get("/api/songs").json()["items"] == []
    tid = client.get("/api/trash").json()[0]["id"]
    r = client.post(f"/api/trash/{tid}/restore")
    assert r.status_code == 200
    assert [i["title"] for i in client.get("/api/songs").json()["items"]] == ["Song"]

    client.delete(f"/api/songs/{sid}")
    env.put_song("Artist/Artist - Song", env.SONG_TXT, "Artist - Song")
    tid = client.get("/api/trash").json()[0]["id"]
    r = client.post(f"/api/trash/{tid}/restore")
    assert r.status_code == 409 and "Сначала удалите или переименуйте" in r.json()["detail"]
    assert client.post("/api/trash/nope/restore").status_code == 404
