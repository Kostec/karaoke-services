"""Проверка библиотеки (истории 34–39): находки по снимкам песен — ``karaoke_core.libcheck``."""

from pathlib import Path

from karaoke_core import ultrastar
from karaoke_core.db import song_id_for
from karaoke_core.libcheck import SongScan, audio_link, find_problems, finding_id, scan_song
from karaoke_core.storage import LocalStorage

FIX = Path(__file__).resolve().parent / "fixtures"
NAMES = {"local": "Локальное", "t_pi": "Pi"}
YT = "https://www.youtube.com/watch?v=abcdefghijk"


def song(target="local", rel="A/A - T", artist="A", title="T", *, audio="A - T.mp3", cover="A - T [CO].jpg",
         video_header="", video_file=None, files=None, encoding=None, audio_header=None, cover_header=None):
    base = rel.rsplit("/", 1)[-1]
    files = files if files is not None else {f"{base}.txt": 100, f"{base}.mp3": 5000}
    return SongScan(target_id=target, rel_dir=rel, txt_name=f"{base}.txt", artist=artist, title=title,
                    audio=audio, cover=cover, audio_header=audio_header if audio_header is not None else (audio or ""),
                    cover_header=cover_header if cover_header is not None else (cover or ""),
                    video_header=video_header, video_file=video_file, files=files, encoding=encoding)


def kinds(findings):
    return sorted(f["kind"] for f in findings)


def test_clean_library_has_no_findings():
    assert find_problems([song(), song("t_pi")], NAMES) == []


def test_no_audio_fixes_copy_video_link_and_trash():
    bad = song(audio=None, audio_header="A - T.mp3", video_header=f"v={YT[-11:]},co=x.jpg")
    other = song("t_pi")
    [f] = find_problems([bad, other], NAMES)
    assert f["kind"] == "no_audio" and f["song_id"] == song_id_for("local", "A/A - T")
    assert f["target_id"] == "local" and f["artist"] == "A" and f["title"] == "T"
    assert "A - T.mp3" in f["detail"]
    actions = [x["action"] for x in f["fixes"]]
    assert actions == ["copy_from", "audio_from_video", "trash"]
    assert f["fixes"][0] == {"action": "copy_from", "from_target": "t_pi",
                             "from_song_id": song_id_for("t_pi", "A/A - T")}
    assert f["fix"] == f["fixes"][0]
    assert f["id"] == finding_id("no_audio", f["song_id"]) and len(f["id"]) == 12


def test_no_audio_without_link_or_copy_only_trash():
    s = song(audio=None, audio_header="", video_header="A - T.mp4", video_file="A - T.mp4")
    [f] = find_problems([s], NAMES)
    assert f["detail"] == "В песне не указан звук (#AUDIO/#MP3)"
    assert [x["action"] for x in f["fixes"]] == ["trash"]


def test_no_cover_and_video_missing():
    s = song(cover=None, cover_header="", video_header="A - T.mp4", video_file=None)
    found = {f["kind"]: f for f in find_problems([s], NAMES)}
    assert set(found) == {"no_cover", "video_missing"}
    assert found["no_cover"]["fix"] == {"action": "cover_search"}
    assert found["video_missing"]["fix"] == {"action": "video_remove"}
    assert "A - T.mp4" in found["video_missing"]["detail"]


def test_video_url_is_not_a_finding():
    for header in (YT, f"v={YT[-11:]}", "a=abcdefghijk,v=abcdefghijk"):
        assert find_problems([song(video_header=header)], NAMES) == []
    assert find_problems([song(video_header="A - T.mp4", video_file="A - T.mp4")], NAMES) == []


def test_encoding_finding_has_before_after():
    fix = ultrastar.encoding_problem((FIX / "enc_koi8r.txt").read_bytes())
    [f] = find_problems([song(encoding=fix)], NAMES)
    assert f["kind"] == "encoding" and f["fix"] == {"action": "encoding"}
    assert f["before"] == fix.preview_before and f["after"] == "Речной Трамвай - Утренняя песня"
    assert "→" in f["detail"]


def test_encoding_not_guessed_is_disabled():
    fix = ultrastar.encoding_problem((FIX / "enc_replacement.txt").read_bytes())
    [f] = find_problems([song(encoding=fix)], NAMES)
    assert f["fix"]["action"] == "encoding" and f["fix"]["disabled"] == "Не удалось угадать кодировку"


def test_duplicates_in_one_target_by_rough_key():
    a = song(rel="Кино/Кино - Группа крови", artist="Кино", title="Группа крови")
    b = song(rel="Kино/Kино - Группа крови!", artist="Kино", title="Группа Крови!")
    elsewhere = song("t_pi", rel="Кино/Кино - Группа крови", artist="Кино", title="Группа крови")
    found = [f for f in find_problems([a, b, elsewhere], NAMES) if f["kind"] == "duplicate"]
    assert len(found) == 1  # пара — одна находка; копия в другом хранилище не дубль
    f = found[0]
    ids = {song_id_for("local", a.rel_dir), song_id_for("local", b.rel_dir)}
    assert {f["song_id"], f["other"]["song_id"]} == ids
    assert {(x["action"], x["song_id"], x["trash_song_id"]) for x in f["fixes"]} == {
        ("keep_this", i, (ids - {i}).pop()) for i in ids}


def test_different_songs_are_not_duplicates():
    a = song(rel="A/A - T", artist="A", title="T")
    b = song(rel="A/A - T2", artist="A", title="T2")
    assert find_problems([a, b], NAMES) == []


def test_diverged_copies_by_files_and_sizes():
    a = song(files={"A - T.txt": 100, "A - T.mp3": 5000, "A - T [Instrumental].mp3": 4000})
    b = song("t_pi", files={"A - T.txt": 120, "A - T.mp3": 5000})
    [f] = find_problems([a, b], NAMES)
    assert f["kind"] == "diverged"
    assert "A - T [Instrumental].mp3" in f["detail"] and "A - T.txt" in f["detail"]
    assert "Pi" in f["detail"] or "Локальное" in f["detail"]
    pairs = {(x["song_id"], x["from_target"], x["from_song_id"]) for x in f["fixes"]}
    sa, sb = song_id_for("local", a.rel_dir), song_id_for("t_pi", b.rel_dir)
    assert pairs == {(sa, "t_pi", sb), (sb, "local", sa)}
    assert all(x["action"] == "make_like" for x in f["fixes"])


def test_same_copies_differ_only_in_case_are_equal():
    a = song(files={"A - T.txt": 100, "A - T.mp3": 5000})
    b = song("t_pi", files={"a - t.TXT": 100, "a - t.mp3": 5000})
    assert find_problems([a, b], NAMES) == []


def test_finding_ids_are_stable():
    s = [song(cover=None, cover_header="")]
    assert [f["id"] for f in find_problems(s, NAMES)] == [f["id"] for f in find_problems(s, NAMES)]


def test_audio_link_only_youtube():
    assert audio_link(YT) == YT
    assert audio_link("a=abcdefghijk,v=bbbbbbbbbbb") == "https://www.youtube.com/watch?v=abcdefghijk"
    assert audio_link("https://vimeo.com/123") is None
    assert audio_link("A - T.mp4") is None
    assert audio_link("") is None


def test_scan_song_reads_headers_files_and_encoding(tmp_path):
    d = tmp_path / "A" / "A - T"
    d.mkdir(parents=True)
    (d / "A - T.txt").write_bytes((FIX / "enc_koi8r.txt").read_bytes())
    (d / "Речной Трамвай - Утренняя песня.mp3").write_bytes(b"x" * 10)
    storage = LocalStorage(tmp_path, target_id="local", label="/output")
    entry = storage.read_song("A/A - T")
    s = scan_song(storage, entry)
    assert s.song_id == song_id_for("local", "A/A - T")
    assert s.encoding is not None and s.encoding.kind == "latin1"
    assert s.files == {"A - T.txt": (d / "A - T.txt").stat().st_size, "Речной Трамвай - Утренняя песня.mp3": 10}
    assert s.cover is None and s.cover_header  # #COVER есть, файла нет
