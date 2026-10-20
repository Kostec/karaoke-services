"""Разбор сборника: распаковка zip, поиск песен, ссылки YouTube из #VIDEO."""

from __future__ import annotations

import stat
import zipfile

import pytest

from karaoke_core import songpack
from karaoke_core.songpack import PackError

WATCH = "https://www.youtube.com/watch?v="


# --------------------------------------------------------------------------- youtube_links

def test_youtube_links_usdb_form_audio_before_video_and_cover():
    urls, cover = songpack.youtube_links(
        "v=dQw4w9WgXcQ,co=https://images.example.org/c.jpg,a=https://youtu.be/abcdefghijk")
    assert urls == ["https://youtu.be/abcdefghijk", WATCH + "dQw4w9WgXcQ"]
    assert cover == "https://images.example.org/c.jpg"


def test_youtube_links_usdb_form_value_with_equals_and_unknown_keys():
    urls, cover = songpack.youtube_links(
        "v=https://www.youtube.com/watch?v=dQw4w9WgXcQ,v-gap=1.5,bg=back.jpg")
    assert urls == [WATCH + "dQw4w9WgXcQ"]
    assert cover is None


def test_youtube_links_cover_without_scheme_is_fanart_file():
    assert songpack.youtube_links("v=dQw4w9WgXcQ,co=artist-cover-123.jpg") == (
        [WATCH + "dQw4w9WgXcQ"], "https://images.fanart.tv/fanart/artist-cover-123.jpg")
    assert songpack.youtube_links("v=dQw4w9WgXcQ,co=nodot")[1] is None
    assert songpack.youtube_links("v=dQw4w9WgXcQ,co=../x.jpg")[1] is None


def test_youtube_links_bare_url_and_id():
    assert songpack.youtube_links("https://youtu.be/dQw4w9WgXcQ") == (
        ["https://youtu.be/dQw4w9WgXcQ"], None)
    assert songpack.youtube_links(" dQw4w9WgXcQ ") == ([WATCH + "dQw4w9WgXcQ"], None)


def test_youtube_links_ignores_local_video_file_and_empty():
    assert songpack.youtube_links("Artist - Title.mp4") == ([], None)
    assert songpack.youtube_links("") == ([], None)
    assert songpack.youtube_links(None) == ([], None)


def test_youtube_links_same_link_twice_listed_once():
    urls, _ = songpack.youtube_links("a=dQw4w9WgXcQ,v=dQw4w9WgXcQ")
    assert urls == [WATCH + "dQw4w9WgXcQ"]


# --------------------------------------------------------------------------- safe_extract

def _zip(path, entries):
    """entries: {имя: байты} или (ZipInfo, байты) — для симлинков и подделанных имён."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for item in entries:
            if isinstance(item, tuple):
                z.writestr(*item)
            else:
                z.writestr(item, entries[item] if isinstance(entries, dict) else b"x")
    return path


def _files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_safe_extract_keeps_only_song_files(tmp_path):
    z = _zip(tmp_path / "pack.zip", {
        "Pack/A - T/A - T.txt": b"#TITLE:T\n",
        "Pack/A - T/A - T.MP3": b"mp3",
        "Pack/A - T/A - T [CO].jpg": b"jpg",
        "Pack/A - T/A - T.mp4": b"video",
        "Pack/readme.html": b"<html>",
        "Pack/run.exe": b"MZ",
    })
    dest = tmp_path / "out"
    songpack.safe_extract(z, dest, 10 * 2**20)
    assert _files(dest) == ["Pack/A - T/A - T [CO].jpg", "Pack/A - T/A - T.MP3",
                            "Pack/A - T/A - T.txt"]
    assert (dest / "Pack/A - T/A - T.MP3").read_bytes() == b"mp3"


@pytest.mark.parametrize("name", ["../evil.txt", "a/../../evil.txt", "/etc/evil.txt",
                                  "..\\evil.txt","C:/evil.txt"])
def test_safe_extract_refuses_paths_outside_dest(tmp_path, name):
    z = _zip(tmp_path / "slip.zip", {"ok.txt": b"#TITLE:x\n", name: b"pwned"})
    dest = tmp_path / "a" / "out"
    with pytest.raises(PackError) as e:
        songpack.safe_extract(z, dest, 2**20)
    assert "недопустим" in e.value.message
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "a" / "evil.txt").exists()


def test_safe_extract_does_not_create_symlinks(tmp_path):
    link = zipfile.ZipInfo("song.mp3")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    z = _zip(tmp_path / "link.zip", [(link, "/etc/passwd"), ("song.txt", b"#TITLE:x\n")])
    dest = tmp_path / "out"
    songpack.safe_extract(z, dest, 2**20)
    assert _files(dest) == ["song.txt"]
    assert not (dest / "song.mp3").is_symlink()


def test_safe_extract_total_size_limit(tmp_path):
    z = _zip(tmp_path / "big.zip", {"a.mp3": b"\0" * 600_000, "b.mp3": b"\0" * 600_000})
    with pytest.raises(PackError) as e:
        songpack.safe_extract(z, tmp_path / "out", 2**20)
    assert e.value.message == "Архив больше 1 МБ после распаковки"


def test_safe_extract_forged_size_is_broken_archive_not_written_past_header(tmp_path):
    z = _zip(tmp_path / "bomb.zip", {"a.mp3": b"\0" * 3_000_000})
    data = bytearray(z.read_bytes())
    # Подделать объявленный размер (central directory) на 10 байт — zip-бомба врёт.
    cd = data.rfind(b"PK\x01\x02")
    data[cd + 24:cd + 28] = (10).to_bytes(4, "little")
    z.write_bytes(bytes(data))
    dest = tmp_path / "out"
    with pytest.raises(PackError) as e:
        songpack.safe_extract(z, dest, 2**20)
    assert e.value.message == "Архив повреждён"
    written = dest / "a.mp3"
    assert not written.exists() or written.stat().st_size <= 10


def test_safe_extract_broken_zip(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(PackError) as e:
        songpack.safe_extract(bad, tmp_path / "out", 2**20)
    assert e.value.message == "Архив повреждён"


# --------------------------------------------------------------------------- find_songs

NOTES = ": 0 4 1 Ла\n- 6\n: 8 4 2 ла\nE\n"


def _put(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _pack(root):
    # Песня 1: cp1251, #AUDIO другим регистром, обложка по суффиксу [CO], #VIDEO формы usdb.
    _put(root, "Пак/Кино - Группа крови/Кино - Группа крови.txt",
         ("#ARTIST:Кино\r\n#TITLE:Группа крови\r\n#LANGUAGE:Russian\r\n"
          "#AUDIO:кино - группа крови.MP3\r\n#VIDEO:v=dQw4w9WgXcQ,a=abcdefghijk\r\n"
          "#BPM:300\r\n" + NOTES.replace("\n", "\r\n")).encode("cp1251"))
    _put(root, "Пак/Кино - Группа крови/Кино - Группа крови.mp3", b"mp3")
    _put(root, "Пак/Кино - Группа крови/Кино - Группа крови [CO].JPG", b"jpg")
    _put(root, "Пак/Кино - Группа крови/Кино - Группа крови.lyrics.txt", b"#TITLE:x\n" + NOTES.encode())
    # Песня 2: UTF-8 с BOM, дуэт, #MP3 без файла, обложка по #COVER в подпапке.
    _put(root, "Пак/Duo/song.txt",
         ("﻿#TITLE: Дуэт \n#ARTIST: Он и Она \n#MP3:missing.mp3\n#COVER:img/Front.png\n"
          "#BPM:200\nP1\n: 0 4 1 При\nP2\n: 0 4 6 Здрав\nE\n").encode("utf-8"))
    _put(root, "Пак/Duo/IMG/front.PNG", b"png")
    # Не песни: без нот, без #TITLE, не .txt.
    _put(root, "Пак/readme.txt", "Сборник песен\nhttp://example.org\n".encode())
    _put(root, "Пак/notitle.txt", b"#ARTIST:x\n" + NOTES.encode())
    _put(root, "Пак/headers_only.txt", b"#TITLE:x\n#ARTIST:y\n")


def test_find_songs_two_songs_in_subfolders(tmp_path):
    _pack(tmp_path)
    songs = songpack.find_songs(tmp_path)
    assert [s.txt_rel for s in songs] == ["Пак/Duo/song.txt",
                                          "Пак/Кино - Группа крови/Кино - Группа крови.txt"]
    duo, kino = songs
    assert (kino.artist, kino.title, kino.language, kino.duet) == (
        "Кино", "Группа крови", "Russian", False)
    assert kino.audio_rel == "Пак/Кино - Группа крови/Кино - Группа крови.mp3"
    assert kino.cover_rel == "Пак/Кино - Группа крови/Кино - Группа крови [CO].JPG"
    assert kino.youtube == ["https://www.youtube.com/watch?v=abcdefghijk",
                            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    assert kino.cover_url is None

    assert (duo.artist, duo.title, duo.language, duo.duet) == ("Он и Она", "Дуэт", None, True)
    assert duo.audio_rel is None
    assert duo.cover_rel == "Пак/Duo/IMG/front.PNG"
    assert duo.youtube == []


def test_find_songs_cover_header_wins_over_co_suffix(tmp_path):
    _put(tmp_path, "s/a.txt", b"#TITLE:T\n#ARTIST:A\n#MP3:a.ogg\n#COVER:cover.webp\n" + NOTES.encode())
    _put(tmp_path, "s/a.ogg", b"ogg")
    _put(tmp_path, "s/cover.webp", b"webp")
    _put(tmp_path, "s/a [CO].jpg", b"jpg")
    [song] = songpack.find_songs(tmp_path)
    assert (song.audio_rel, song.cover_rel) == ("s/a.ogg", "s/cover.webp")


def test_find_songs_audio_header_pointing_to_non_audio_is_ignored(tmp_path):
    _put(tmp_path, "a.txt", b"#TITLE:T\n#MP3:a.txt\n" + NOTES.encode())
    [song] = songpack.find_songs(tmp_path)
    assert song.audio_rel is None and song.cover_rel is None


def test_find_songs_empty_dir_gives_empty_list(tmp_path):
    _put(tmp_path, "readme.txt", b"nothing here")
    assert songpack.find_songs(tmp_path) == []


def test_extract_then_find_from_zip(tmp_path):
    src = tmp_path / "src"
    _pack(src)
    z = _zip(tmp_path / "p.zip", {p.relative_to(src).as_posix(): p.read_bytes()
                                  for p in src.rglob("*") if p.is_file()})
    dest = tmp_path / "out"
    songpack.safe_extract(z, dest, 2**20)
    assert [s.title for s in songpack.find_songs(dest)] == ["Дуэт", "Группа крови"]


# --------------------------------------------------------------------------- DataPaths

def test_data_paths_import_dir(tmp_path):
    from karaoke_core.paths import DataPaths

    paths = DataPaths(tmp_path)
    assert paths.imports_root == tmp_path / "imports"
    assert paths.import_dir("0a1b2c") == tmp_path / "imports" / "0a1b2c"
    for bad in ("", "..", "a/b", "../x", "a\\b"):
        with pytest.raises(ValueError):
            paths.import_dir(bad)
