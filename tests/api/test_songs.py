"""Песни: индекс, exists, карточка, текст, ноты, аудио/обложка, удаление, корзина."""

from pathlib import Path

import pytest

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


def test_exists_ignores_case_and_yo(env, client):
    txt = "#TITLE:Ёжик в тумане\n#ARTIST:Ёлка\n#MP3:Ёлка - Ёжик в тумане.mp3\n#BPM:300\n#GAP:0\n: 0 4 5 Да\nE\n"
    env.put_song("Ёлка/Ёлка - Ёжик в тумане", txt.encode("utf-8"), "Ёлка - Ёжик в тумане")
    client.post("/api/songs/rescan")
    r = client.get("/api/songs/exists", params={"artist": "ЕЛКА", "title": "ежик в тумане"}).json()
    assert r["exists"] is True
    assert client.get("/api/songs/exists", params={"artist": "Елка", "title": "Ежик"}).json() == {"exists": False}


def test_exists_keeps_spaces_and_punctuation(env, client):
    txt = "#TITLE:Ма-ма\n#ARTIST:А Б\n#MP3:А Б - Ма-ма.mp3\n#BPM:300\n#GAP:0\n: 0 4 5 Да\nE\n"
    env.put_song("А Б/А Б - Ма-ма", txt.encode("utf-8"), "А Б - Ма-ма")
    client.post("/api/songs/rescan")

    def exists(a, t):
        return client.get("/api/songs/exists", params={"artist": a, "title": t}).json()["exists"]

    assert exists("а б", "МА-МА") is True
    assert exists("А Б", "Мама") is False
    assert exists("АБ", "Ма-ма") is False


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


def test_notes_duet_is_editable_with_players_and_singers(env, client):
    env.put_song("Pair/Pair - Duet", env.DUET_TXT, "Pair - Duet")
    client.post("/api/songs/rescan")
    duet = next(i for i in client.get("/api/songs").json()["items"] if i["is_duet"])
    n = client.get(f"/api/songs/{duet['song_id']}/notes").json()
    assert (n["editable"], n["duet"], n["singers"]) == (True, True, {"p1": "", "p2": ""})
    assert "reason" not in n
    assert [(ln["player"], ln["break_beat"], [x["text"] for x in ln["notes"]]) for ln in n["lines"]] == [
        (1, 6, ["Раз"]), (2, None, ["Два"])]


def test_notes_solo_is_not_duet(client, song):
    n = client.get(f"/api/songs/{song['song_id']}/notes").json()
    assert (n["duet"], n["singers"]) == (False, {"p1": "", "p2": ""})
    assert all("player" not in ln for ln in n["lines"])


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


def test_song_source_from_import_params(env, client):
    """Метки «импорт»/«из usdb»: API песни отдаёт source из params.json (null — у прочих)."""
    env.put_song("Artist/Artist - Song", env.SONG_TXT, "Artist - Song")
    env.put_song("Pair/Pair - Duet", env.DUET_TXT, "Pair - Duet", cover=None)
    env.put_song("Gen/Gen - Own", env.SONG_TXT, "Gen - Own")
    songs = Songs(connect(env.data / "karaoke.sqlite"))
    songs.upsert(artist="Artist", title="Song", rel_dir="Artist/Artist - Song",
                 params={"source": "usdb", "usdb_id": 7})
    songs.upsert(artist="Pair", title="Duet", rel_dir="Pair/Pair - Duet", params={"source": "files"})
    songs.upsert(artist="Gen", title="Own", rel_dir="Gen/Gen - Own", params={"language": "ru"})
    client.post("/api/songs/rescan")
    items = {i["rel_dir"]: i for i in client.get("/api/songs").json()["items"]}
    assert {d: i["source"] for d, i in items.items()} == {
        "Artist/Artist - Song": "usdb", "Pair/Pair - Duet": "files", "Gen/Gen - Own": None}
    sid = items["Artist/Artist - Song"]["song_id"]
    assert client.get(f"/api/songs/{sid}").json()["source"] == "usdb"


def test_foreign_song_has_no_source(env, client, song):
    assert client.get(f"/api/songs/{song['song_id']}").json()["source"] is None
    assert client.get("/api/songs").json()["items"][0]["source"] is None


# --------------------------------------------------------------------------- редактор нот

def _add_song(env, client, artist: str, title: str, txt: bytes) -> str:
    base = f"{artist} - {title}"
    env.put_song(f"{artist}/{base}", txt, base)
    assert client.post("/api/songs/rescan").status_code == 202
    return next(i["song_id"] for i in client.get("/api/songs").json()["items"] if i["title"] == title)


def test_notes_have_ids_in_file_order(client, song):
    notes = client.get(f"/api/songs/{song['song_id']}/notes").json()
    assert [[n["id"] for n in ln["notes"]] for ln in notes["lines"]] == [[0, 1], [2, 3]]


def test_notes_without_bpm_are_read_only(env, client):
    sid = _add_song(env, client, "Solo", "NoBpm", "#TITLE:NoBpm\n#ARTIST:Solo\n#GAP:0\n: 0 4 5 Раз\nE\n".encode())
    n = client.get(f"/api/songs/{sid}/notes").json()
    assert n["editable"] is False and n["reason"] == "В песне нет #BPM — редактор только для просмотра"
    r = client.put(f"/api/songs/{sid}/notes", json=n)
    assert r.status_code == 409 and r.json()["detail"] == n["reason"]


RICH_TXT = b"\xef\xbb\xbf" + (
    "#TITLE:Rich\r\n#ARTIST:Band\r\n#MP3:Band - Rich.mp3\r\n#BPM:200,5\r\n#GAP:500.0\r\n"
    ":  0  4  5 Раз\r\n# комментарий\r\n: 4 4 5 два\r\n- 9\r\n: 10 2 3 три\r\nE\r\nхвост\r\n"
).encode("utf-8")


def _rich(env, client):
    sid = _add_song(env, client, "Band", "Rich", RICH_TXT)
    return sid, env.out / "Band" / "Band - Rich" / "Band - Rich.txt", client.get(f"/api/songs/{sid}/notes").json()


def test_notes_put_one_note_changes_only_its_line(env, client):
    sid, txt, notes = _rich(env, client)
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert txt.read_bytes() == RICH_TXT and client.get("/api/trash").json() == []

    notes["lines"][1]["notes"][0]["pitch"] = 4
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert txt.read_bytes() == RICH_TXT.replace(": 10 2 3 три".encode(), ": 10 2 4 три".encode())


def test_notes_put_raw_lines_follow_surviving_note(env, client):
    sid, txt, notes = _rich(env, client)
    del notes["lines"][0]["notes"][1]  # «два», перед ней стоял комментарий
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert txt.read_bytes() == b"\xef\xbb\xbf" + (
        "#TITLE:Rich\r\n#ARTIST:Band\r\n#MP3:Band - Rich.mp3\r\n#BPM:200,5\r\n#GAP:500.0\r\n"
        ":  0  4  5 Раз\r\n# комментарий\r\n- 9\r\n: 10 2 3 три\r\nE\r\nхвост\r\n").encode("utf-8")


def test_notes_put_timing_pitch_type_add_delete_and_lines(env, client, song):
    sid = song["song_id"]
    txt = env.out / "Artist" / "Artist - Song" / "Artist - Song.txt"
    notes = client.get(f"/api/songs/{sid}/notes").json()
    (pri, _vet), (mir, excl) = (ln["notes"] for ln in notes["lines"])
    pri.update(type="*", start=1, length=2, pitch=6)
    excl.update(type="F", start=20, length=3, pitch=9)
    new = {"id": None, "type": ":", "start": 4, "length": 3, "pitch": 8, "text": " нов"}
    notes["lines"] = [{"break_beat": 8, "notes": [pri, new]}, {"break_beat": None, "notes": [mir]},
                      {"break_beat": None, "notes": [excl]}]
    r = client.put(f"/api/songs/{sid}/notes", json=notes)
    assert r.status_code == 200, r.text
    head = env.SONG_TXT.decode("utf-8").split(": 0 4 5")[0]
    assert txt.read_text("utf-8") == head + "* 1 2 6 При\n: 4 3 8  нов\n- 8\n: 12 4 7 мир\n- 16\nF 20 3 9 !\nE\n"

    back = client.get(f"/api/songs/{sid}/notes").json()
    assert [[(n["id"], n["type"], n["start"], n["length"], n["pitch"], n["text"]) for n in ln["notes"]]
            for ln in back["lines"]] == [[(0, "*", 1, 2, 6, "При"), (1, ":", 4, 3, 8, " нов")],
                                         [(2, ":", 12, 4, 7, "мир")], [(3, "F", 20, 3, 9, "!")]]
    assert [ln["break_beat"] for ln in back["lines"]] == [8, 16, None]


def test_notes_put_gap(env, client, song):
    sid = song["song_id"]
    txt = env.out / "Artist" / "Artist - Song" / "Artist - Song.txt"
    notes = client.get(f"/api/songs/{sid}/notes").json()
    notes["gap"] = 1234.0
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert txt.read_bytes() == env.SONG_TXT.replace(b"#GAP:1000\n", b"#GAP:1234\n")
    notes["gap"] = 987.5
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert txt.read_bytes() == env.SONG_TXT.replace(b"#GAP:1000\n", b"#GAP:987.5\n")
    notes["gap"] = 1000.1 + 0.2  # 1000.3000000000001 после сдвига на клиенте
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert txt.read_bytes() == env.SONG_TXT.replace(b"#GAP:1000\n", b"#GAP:1000.3\n")


def _first(n):
    return n["lines"][0]["notes"][0]


@pytest.mark.parametrize("change, detail", [
    (lambda n: n.update(lines=[]), "В песне должна остаться хотя бы одна нота"),
    (lambda n: _first(n).update(type="X"), "Неизвестный тип ноты «X»: строка 1, слог «При»"),
    (lambda n: _first(n).update(start=-1), "Начало ноты раньше бита 0: строка 1, слог «При»"),
    (lambda n: _first(n).update(length=0), "Длина ноты — не меньше 1 бита: строка 1, слог «При»"),
    (lambda n: _first(n).update(pitch=101), "Высота ноты — от −40 до 100: строка 1, слог «При»"),
    (lambda n: _first(n).update(pitch=-41), "Высота ноты — от −40 до 100: строка 1, слог «При»"),
    (lambda n: _first(n).update(text="При\nвет"), "В слоге не может быть перевода строки: строка 1"),
    (lambda n: _first(n).update(length=5), "Ноты перекрываются: строка 1, слог «вет»"),
    (lambda n: n["lines"][1]["notes"][0].update(start=6), "Ноты перекрываются: строка 2, слог «мир»"),
    (lambda n: n["lines"][0].update(break_beat=7),
     "Разрыв строки 1 должен стоять между концом её последней ноты и началом строки 2"),
    (lambda n: n["lines"][0].update(break_beat=13),
     "Разрыв строки 1 должен стоять между концом её последней ноты и началом строки 2"),
    (lambda n: _first(n).update(id=9), "Нота с id 9 не найдена в файле"),
    (lambda n: _first(n).update(id=1), "Нота с id 1 встречается дважды"),
    (lambda n: n.update(gap=-1), "Раньше начала трека сдвигать некуда: #GAP не может быть меньше 0"),
])
def test_notes_put_validation(env, client, song, change, detail):
    sid = song["song_id"]
    txt = env.out / "Artist" / "Artist - Song" / "Artist - Song.txt"
    notes = client.get(f"/api/songs/{sid}/notes").json()
    change(notes)
    r = client.put(f"/api/songs/{sid}/notes", json=notes)
    assert (r.status_code, r.json()["detail"]) == (400, detail)
    assert txt.read_bytes() == env.SONG_TXT and client.get("/api/trash").json() == []


def test_notes_put_allows_empty_syllable_and_touching_notes(env, client, song):
    sid = song["song_id"]
    txt = env.out / "Artist" / "Artist - Song" / "Artist - Song.txt"
    notes = client.get(f"/api/songs/{sid}/notes").json()
    _first(notes).update(text="")
    notes["lines"][0]["break_beat"] = 12  # ровно на начале следующей строки — допустимо
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert "\n: 0 4 5 \n: 4 4 5 вет\n- 12\n".encode() in txt.read_bytes()


# --------------------------------------------------------------------------- дуэты

# Фикстура дуэта ядра; её нота длины 0 (для fix_zero_length) PUT не пропустит — здесь длина 1.
DUET_FIX_TXT = ((Path(__file__).resolve().parents[1] / "core" / "fixtures" / "duet.txt").read_bytes()
                .replace(": 20 0 8 ".encode(), ": 20 1 8 ".encode()))


def _duet(env, client, txt: bytes):
    env.put_song("Pair/Pair - Duet", txt, "Pair - Duet")
    assert client.post("/api/songs/rescan").status_code == 202
    sid = next(i["song_id"] for i in client.get("/api/songs").json()["items"]
               if i["rel_dir"] == "Pair/Pair - Duet")
    return sid, env.out / "Pair" / "Pair - Duet" / "Pair - Duet.txt", client.get(f"/api/songs/{sid}/notes").json()


@pytest.mark.parametrize("fixture", ["duet.txt", "DUET_TXT"])  # без «- N» перед P2 и с ним
def test_notes_put_duet_unchanged_is_byte_exact(env, client, fixture):
    txt = DUET_FIX_TXT if fixture == "duet.txt" else env.DUET_TXT
    sid, path, notes = _duet(env, client, txt)
    r = client.put(f"/api/songs/{sid}/notes", json=notes)
    assert r.status_code == 200, r.text
    assert path.read_bytes() == txt and client.get("/api/trash").json() == []


def test_notes_put_duet_one_p2_note_changes_only_its_line(env, client):
    raw = DUET_FIX_TXT
    sid, path, notes = _duet(env, client, raw)
    p2 = [ln for ln in notes["lines"] if ln["player"] == 2]
    p2[1]["notes"][0]["pitch"] = 9
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert path.read_bytes() == raw.replace(": 12 4 8 Хо".encode(), ": 12 4 9 Хо".encode())


def _p2(notes):
    return [ln for ln in notes["lines"] if ln["player"] == 2]


@pytest.mark.parametrize("change, detail", [
    # ноты P2 с бита 0 не перекрываются с P1 — перекрытие только внутри партии
    (lambda n: _p2(n)[1]["notes"][0].update(start=6), "Певец 2, строка 2: ноты перекрываются, слог «Хо»"),
    (lambda n: _p2(n)[0].update(break_beat=13),
     "Певец 2, строка 1: разрыв должен стоять между концом её последней ноты и началом строки 2"),
    (lambda n: _p2(n)[1]["notes"][0].update(pitch=101), "Певец 2, строка 2: высота ноты — от −40 до 100, слог «Хо»"),
    (lambda n: n["lines"][2].pop("player"), "Строка 3: не указан певец (1 или 2)"),
    (lambda n: n["lines"][0].update(player=3), "Строка 1: певец — 1 или 2, а не 3"),
], ids=["overlap", "break", "pitch", "no-player", "bad-player"])
def test_notes_put_duet_validation_is_per_track(env, client, change, detail):
    sid, path, notes = _duet(env, client, DUET_FIX_TXT)
    change(notes)
    r = client.put(f"/api/songs/{sid}/notes", json=notes)
    assert (r.status_code, r.json()["detail"]) == (400, detail)
    assert path.read_bytes() == DUET_FIX_TXT


def test_notes_put_solo_to_duet_and_back(env, client, song):
    sid = song["song_id"]
    txt = env.out / "Artist" / "Artist - Song" / "Artist - Song.txt"
    head = env.SONG_TXT.decode("utf-8").split(": 0 4 5")[0]
    notes = client.get(f"/api/songs/{sid}/notes").json()
    a, b = notes["lines"]
    both = {**b, "player": 2, "notes": [{**x, "id": None} for x in b["notes"]]}  # «оба» — копия в P2
    notes["lines"] = [{**a, "player": 1}, {**b, "player": 1}, both]
    notes["singers"] = {"p1": "Аня", "p2": "Боря"}
    r = client.put(f"/api/songs/{sid}/notes", json=notes)
    assert r.status_code == 200, r.text
    assert r.json()["is_duet"] is True
    assert txt.read_text("utf-8") == head.replace("#X-CUSTOM:keep\n", "#X-CUSTOM:keep\n#P1:Аня\n#P2:Боря\n") + (
        "P1\n: 0 4 5 При\n: 4 4 5 вет\n- 10\n: 12 4 7 мир\n* 16 2 7 !\nP2\n: 12 4 7 мир\n* 16 2 7 !\nE\n")
    back = client.get(f"/api/songs/{sid}/notes").json()
    assert (back["duet"], back["singers"]) == (True, {"p1": "Аня", "p2": "Боря"})
    assert [ln["player"] for ln in back["lines"]] == [1, 1, 2]

    back["lines"] = [{**ln, "player": 1} for ln in back["lines"][:2]]  # «Сделать соло»
    r = client.put(f"/api/songs/{sid}/notes", json=back)
    assert r.status_code == 200 and r.json()["is_duet"] is False
    assert txt.read_bytes() == env.SONG_TXT


def test_notes_put_duet_singer_names_and_reused_marks(env, client):
    raw = ("#TITLE:Duet\n#ARTIST:Pair\n#DUETSINGERP1:A\n#BPM:300\n#GAP:0\n"
           "P 1\n: 0 4 5 Раз\nP 2\n: 8 4 5 Два\nE\n").encode()
    sid, path, notes = _duet(env, client, raw)
    assert notes["singers"] == {"p1": "A", "p2": ""}
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert path.read_bytes() == raw  # имена те же — #P1 не добавляется
    notes["singers"] = {"p1": "Аня", "p2": "Боря"}
    notes["lines"][1]["notes"][0]["pitch"] = 6
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert path.read_text("utf-8") == ("#TITLE:Duet\n#ARTIST:Pair\n#DUETSINGERP1:Аня\n#BPM:300\n#GAP:0\n"
                                       "#P1:Аня\n#P2:Боря\nP 1\n: 0 4 5 Раз\nP 2\n: 8 4 6 Два\nE\n")
    notes["singers"] = {"p1": "", "p2": "Боря"}
    assert client.put(f"/api/songs/{sid}/notes", json=notes).status_code == 200
    assert "P1:" not in path.read_text("utf-8") and "#P2:Боря\n" in path.read_text("utf-8")
