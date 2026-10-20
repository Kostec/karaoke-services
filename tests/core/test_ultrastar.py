from pathlib import Path

import pytest

from karaoke_core import ultrastar

FIX = Path(__file__).parent / "fixtures"
ALL_FIXTURES = ["ultrasinger_utf8.txt", "bom_crlf.txt", "usdb_cp1251.txt", "duet.txt"]


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_parse_render_roundtrip_is_byte_exact(name):
    raw = (FIX / name).read_bytes()
    assert ultrastar.render(ultrastar.parse(raw)) == raw


def test_parse_reads_headers_in_order_and_notes():
    song = ultrastar.parse((FIX / "ultrasinger_utf8.txt").read_bytes())
    keys = [k for k, _ in song.header_items()]
    assert keys[:3] == ["VERSION", "ARTIST", "TITLE"]
    assert song.header("artist") == "Тестовая Группа"
    assert song.header("INSTRUMENTAL") == "Тестовая Группа - Песня Ёлки [Instrumental].mp3"
    texts = [n.text for n in song.notes()]
    assert texts[:4] == ["Ла ", "ла ", "сло", "ги "]
    assert song.notes()[2].length == 0


def test_parse_detects_cp1251_and_unknown_headers():
    song = ultrastar.parse((FIX / "usdb_cp1251.txt").read_bytes())
    assert song.encoding == "cp1251"
    assert song.header("EDITION") == "SingStar Россия"
    assert [n.type for n in song.notes()][:6] == [":", ":", ":", "*", "R", "G"]
    assert song.notes()[2].text == " я~"


def test_parse_detects_bom_and_crlf():
    song = ultrastar.parse((FIX / "bom_crlf.txt").read_bytes())
    assert song.bom is True
    assert song.newline == "\r\n"
    assert song.header("ARTIST") == "Ёжик"


def test_duet_players():
    song = ultrastar.parse((FIX / "duet.txt").read_bytes())
    assert song.is_duet is True
    assert [n.player for n in song.notes()] == [1, 1, 1, 2, 2, 2, 2, 2]
    assert ultrastar.parse((FIX / "bom_crlf.txt").read_bytes()).is_duet is False


def test_modified_model_is_rendered_from_fields():
    song = ultrastar.parse((FIX / "ultrasinger_utf8.txt").read_bytes())
    song.set_header("ARTIST", "Другой")
    song.notes()[0].pitch = 12
    out = ultrastar.render(song).decode("utf-8")
    assert "#ARTIST:Другой\n" in out
    assert "\n: 0 4 12 Ла \n" in out
    assert out.endswith("\nE")


# --- set_header_line -------------------------------------------------------

def test_set_header_line_inserts_instrumental_cp1251_crlf_without_touching_other_bytes():
    raw = (FIX / "usdb_cp1251.txt").read_bytes()
    out = ultrastar.set_header_line(raw, "INSTRUMENTAL", "Исполнитель USDB - Зимняя вишня [Instrumental].mp3")
    mp3_line = "#MP3:Исполнитель USDB - Зимняя вишня.mp3\r\n".encode("cp1251")
    inserted = "#INSTRUMENTAL:Исполнитель USDB - Зимняя вишня [Instrumental].mp3\r\n".encode("cp1251")
    # Ожидание собрано вручную: новая строка сразу после #MP3, всё остальное — как было.
    pos = raw.index(mp3_line) + len(mp3_line)
    assert out == raw[:pos] + inserted + raw[pos:]


def test_set_header_line_replaces_existing_value_only():
    raw = (FIX / "ultrasinger_utf8.txt").read_bytes()
    old = "#INSTRUMENTAL:Тестовая Группа - Песня Ёлки [Instrumental].mp3\n".encode()
    new = "#INSTRUMENTAL:минус.mp3\n".encode()
    assert ultrastar.set_header_line(raw, "instrumental", "минус.mp3") == raw.replace(old, new)


def test_set_header_line_keeps_bom_and_crlf():
    raw = (FIX / "bom_crlf.txt").read_bytes()
    out = ultrastar.set_header_line(raw, "INSTRUMENTAL", "x [Instrumental].mp3")
    anchor = "#MP3:Ёжик - Утро.mp3\r\n".encode()
    pos = raw.index(anchor) + len(anchor)
    assert out == raw[:pos] + b"#INSTRUMENTAL:x [Instrumental].mp3\r\n" + raw[pos:]


def test_set_header_line_rejects_value_unencodable_in_file_encoding():
    raw = (FIX / "usdb_cp1251.txt").read_bytes()
    with pytest.raises(ValueError):
        ultrastar.set_header_line(raw, "INSTRUMENTAL", "日本 [Instrumental].mp3")


# --- fix_zero_length -------------------------------------------------------

def _notes(song):
    return [(n.start, n.length, n.text) for n in song.notes()]


def _breaks(song):
    return [b.beat for b in song.body if isinstance(b, ultrastar.LineBreak)]


def test_fix_zero_length_on_ultrasinger_output():
    song = ultrastar.parse((FIX / "ultrasinger_utf8.txt").read_bytes())
    assert ultrastar.fix_zero_length(song) == 3
    # Разобрано вручную по правилу §6.4.
    assert _notes(song) == [
        (0, 4, "Ла "), (5, 3, "ла "), (8, 1, "сло"), (9, 4, "ги "), (14, 6, "тест "),
        (24, 3, "Вто"), (27, 1, "ра"), (28, 2, "я "), (30, 5, "строч"), (35, 1, "ка "),
        (40, 4, "Ко"), (44, 6, "нец "),
    ]
    assert _breaks(song) == [20, 36]


def test_fix_zero_length_invariants():
    for name in ALL_FIXTURES:
        song = ultrastar.parse((FIX / name).read_bytes())
        texts_before = [n.text for n in song.notes()]
        ultrastar.fix_zero_length(song)
        assert [n.text for n in song.notes()] == texts_before
        assert all(n.length > 0 for n in song.notes())
        for line in song.lines():
            notes = line["notes"]
            for a, b in zip(notes, notes[1:]):
                assert b.start >= a.end, (name, a, b)
            if line["break"] is not None and notes:
                assert line["break"].beat >= notes[-1].end


def test_fix_zero_length_keeps_file_untouched_when_nothing_to_fix():
    raw = (FIX / "bom_crlf.txt").read_bytes()
    song = ultrastar.parse(raw)
    assert ultrastar.fix_zero_length(song) == 0
    assert ultrastar.render(song) == raw


def test_fix_zero_length_duet_tracks_are_independent():
    song = ultrastar.parse((FIX / "duet.txt").read_bytes())
    assert ultrastar.fix_zero_length(song) == 1
    p2 = [(n.start, n.length) for n in song.notes() if n.player == 2]
    assert p2 == [(0, 4), (4, 4), (12, 4), (16, 4), (20, 1)]


# --- время и текст ---------------------------------------------------------

def test_beat_to_ms():
    song = ultrastar.parse((FIX / "bom_crlf.txt").read_bytes())  # BPM 240, GAP 500
    assert ultrastar.beat_to_ms(song, 0) == 500
    assert ultrastar.beat_to_ms(song, 16) == 500 + 1000
    usdb = ultrastar.parse((FIX / "usdb_cp1251.txt").read_bytes())  # BPM 300,5 GAP 15230,5
    assert ultrastar.beat_to_ms(usdb, 0) == pytest.approx(15230.5)
    assert ultrastar.beat_to_ms(usdb, 1202) == pytest.approx(15230.5 + 60000)


def test_extract_lyrics():
    song = ultrastar.parse((FIX / "ultrasinger_utf8.txt").read_bytes())
    assert ultrastar.extract_lyrics(song) == "Ла ла слоги тест\nВторая строчка\nКонец"
    duet = ultrastar.parse((FIX / "duet.txt").read_bytes())
    assert ultrastar.extract_lyrics(duet) == "Привет\nКак\n\nЗдравствуй\nХорошо"
