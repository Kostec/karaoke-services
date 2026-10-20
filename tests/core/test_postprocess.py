import shutil
from pathlib import Path

import pytest

from karaoke_core import postprocess, ultrastar

FIX = Path(__file__).parent / "fixtures"
MB_BASE = "Тестовая Группа - Песня Ёлки"


@pytest.fixture
def out_dir(tmp_path):
    """Копия выхода UltraSinger (MusicBrainz нашёл «Тестовая Группа»)."""
    dst = tmp_path / "job" / "ultrasinger" / MB_BASE
    shutil.copytree(FIX / "ultrasinger_out" / MB_BASE, dst)
    return dst


def _txt(result, base):
    raw = (result.dir / f"{base}.txt").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    return ultrastar.parse(raw)


def test_matching_artist_keeps_musicbrainz_data_and_renames_files(out_dir):
    res = postprocess.finalize(out_dir, "тестовая группа", "Песня ёлки!", None)
    base = "тестовая группа - Песня ёлки!"
    assert res.mb_dropped is False
    assert res.zero_fixed == 3
    assert sorted(res.files) == sorted([
        f"{base}.txt", f"{base}.mp3", f"{base} [Instrumental].mp3",
        f"{base} [Vocals].mp3", f"{base} [CO].jpg", f"{base}.mid",
    ])
    assert sorted(p.name for p in res.dir.iterdir()) == sorted(res.files)
    song = _txt(res, base)
    assert song.header("ARTIST") == "тестовая группа"
    assert song.header("TITLE") == "Песня ёлки!"
    assert song.header("MP3") == f"{base}.mp3"
    assert song.header("AUDIO") == f"{base}.mp3"
    assert song.header("VOCALS") == f"{base} [Vocals].mp3"
    assert song.header("INSTRUMENTAL") == f"{base} [Instrumental].mp3"
    assert song.header("COVER") == f"{base} [CO].jpg"
    assert song.header("YEAR") == "2001"
    assert song.header("GENRE") == "Pop"
    # Содержимое файлов — исходное, под новыми именами.
    assert (res.dir / f"{base}.mp3").read_bytes() == b"ID3-original-audio"
    assert (res.dir / f"{base} [Instrumental].mp3").read_bytes() == b"ID3-instrumental"
    assert (res.dir / f"{base} [Vocals].mp3").read_bytes() == b"ID3-vocals"
    assert (res.dir / f"{base} [CO].jpg").read_bytes() == b"\xff\xd8musicbrainz-cover"
    assert all(n.length > 0 for n in song.notes())


def test_mismatching_artist_drops_cover_year_genre(out_dir):
    res = postprocess.finalize(out_dir, "Другая группа", "Песня Ёлки", None)
    base = "Другая группа - Песня Ёлки"
    assert res.mb_dropped is True
    assert not any("[CO]" in f for f in res.files)
    song = _txt(res, base)
    assert song.header("ARTIST") == "Другая группа"
    assert song.header("COVER") is None
    assert song.header("YEAR") is None
    assert song.header("GENRE") is None
    assert song.header("LANGUAGE") == "Russian"


def test_form_cover_is_used_as_CO(out_dir):
    res = postprocess.finalize(out_dir, "Другая группа", "Песня", FIX / "form_cover.png")
    base = "Другая группа - Песня"
    assert f"{base} [CO].png" in res.files
    assert (res.dir / f"{base} [CO].png").read_bytes() == b"\x89PNG-form-cover"
    assert not (res.dir / f"{base} [CO].jpg").exists()
    assert _txt(res, base).header("COVER") == f"{base} [CO].png"


def test_cache_and_extra_files_do_not_reach_result(out_dir):
    (out_dir / "lyrics_debug.json").write_text("{}")
    (out_dir / f"{MB_BASE}.lyrics.txt").write_text("текст")
    res = postprocess.finalize(out_dir, "Тестовая Группа", "Песня Ёлки", None)
    names = [p.name for p in res.dir.rglob("*")]
    assert "cache" not in names
    assert not any(n.endswith(".lyrics.txt") or n.endswith(".json") for n in names)
    assert f"{MB_BASE}.mp3" in names


def test_unsafe_form_names_are_sanitized(out_dir):
    res = postprocess.finalize(out_dir, "AC/DC", "Что? Где?.", None)
    base = "AC_DC - Что_ Где_"
    assert f"{base}.mp3" in res.files
    song = _txt(res, base)
    # В заголовке — строго значение из формы, в имени файла — безопасное имя.
    assert song.header("ARTIST") == "AC/DC"
    assert song.header("TITLE") == "Что? Где?."
    assert song.header("MP3") == f"{base}.mp3"


def test_output_parent_folder_is_accepted(out_dir):
    res = postprocess.finalize(out_dir.parent, "Тестовая Группа", "Песня Ёлки", None)
    assert f"{MB_BASE}.txt" in res.files


def test_missing_audio_is_an_error(out_dir):
    (out_dir / f"{MB_BASE}.mp3").unlink()
    with pytest.raises(postprocess.FinalizeError):
        postprocess.finalize(out_dir, "Тестовая Группа", "Песня Ёлки", None)
