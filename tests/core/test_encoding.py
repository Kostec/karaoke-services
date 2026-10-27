"""Битая кодировка .txt (история 36): ``ultrastar.encoding_problem`` на фикстурах."""

from pathlib import Path

import pytest

from karaoke_core import ultrastar
from karaoke_core.ultrastar import EncodingFix, encoding_problem

FIX = Path(__file__).resolve().parent / "fixtures"
# Эталон: та же песня в UTF-8 (из него получены koi8-r, cp866, mojibake и U+FFFD — genfix в сборке).
GOOD = (FIX / "enc_utf8.txt").read_bytes().decode("utf-8")
GOOD_PREVIEW = "Речной Трамвай - Утренняя песня"


@pytest.mark.parametrize("name", ["enc_utf8.txt", "usdb_cp1251.txt", "bom_crlf.txt", "ultrasinger_utf8.txt",
                                  "duet.txt"])
def test_normal_files_have_no_problem(name):
    assert encoding_problem((FIX / name).read_bytes()) is None


def test_english_song_has_no_problem():
    data = b"#TITLE:Morning\r\n#ARTIST:River Tram\r\n#BPM:300\r\n: 0 3 5 Hello \r\n: 4 3 5 world\r\nE\r\n"
    assert encoding_problem(data) is None


def test_mojibake_utf8_read_as_cp1251_is_fixed():
    fix = encoding_problem((FIX / "enc_mojibake.txt").read_bytes())
    assert isinstance(fix, EncodingFix)
    assert fix.kind == "mojibake"
    assert fix.fixed_text == GOOD  # в том числе «И» (байт 0x98, которого нет в cp1251)
    assert fix.preview_before.startswith("Р\xa0РµС‡РЅРѕР№")  # «Р» + неразрывный пробел (0xA0)
    assert fix.preview_after == GOOD_PREVIEW


@pytest.mark.parametrize("name", ["enc_koi8r.txt", "enc_cp866.txt"])
def test_koi8r_and_cp866_disguised_as_cp1251(name):
    data = (FIX / name).read_bytes()
    assert ultrastar.decode(data)[1] == "cp1251"  # молча «проходит» как cp1251
    fix = encoding_problem(data)
    assert fix is not None and fix.kind == "latin1"
    assert fix.fixed_text == GOOD
    assert fix.preview_after == GOOD_PREVIEW
    assert fix.preview_before != GOOD_PREVIEW


def test_latin1_fallback_is_guessed():
    # cp866 с «Ш» (байт 0x98): ни utf-8, ни cp1251 — decode читает как latin-1
    text = GOOD.replace("Иду", "Шагаю")
    data = text.encode("cp866")
    assert ultrastar.decode(data)[1] == "latin-1"
    fix = encoding_problem(data)
    assert fix is not None and fix.kind == "latin1"
    assert fix.fixed_text == text


def test_replacement_char_is_found_but_not_guessed():
    fix = encoding_problem((FIX / "enc_replacement.txt").read_bytes())
    assert fix is not None and fix.kind == "replacement"
    assert fix.fixed_text == ""
    assert "�" in fix.preview_before


def test_unknown_bytes_are_not_guessed():
    # Сплошной мусор с байтом 0x98: ни одна кодировка не даёт правдоподобного текста
    data = b"#TITLE:" + bytes(range(0x80, 0xC0)) + b"\r\n#ARTIST:x\r\n: 0 1 1 a\r\nE\r\n"
    fix = encoding_problem(data)
    assert fix is not None and fix.kind == "latin1"
    assert fix.fixed_text == ""


def test_fixed_text_is_clean_and_encoding_header_follows():
    data = (FIX / "enc_koi8r.txt").read_bytes().replace(b"#BPM:", b"#ENCODING:CP1252\r\n#BPM:", 1)
    fix = encoding_problem(data)
    assert "#ENCODING:UTF8\r\n" in fix.fixed_text
    assert encoding_problem(fix.fixed_text.encode("utf-8")) is None


def test_preview_falls_back_to_first_changed_line():
    # заголовки латиницей, а слоги — mojibake: «было → станет» по первой отличающейся строке
    good = "#TITLE:Morning\r\n#ARTIST:River\r\n#BPM:300\r\n: 0 3 5 Привет \r\n: 4 3 5 мир, как дела\r\nE\r\n"
    raw = good.encode("utf-8")
    moji = "".join(bytes([b]).decode("cp1251") for b in raw).encode("utf-8")
    fix = encoding_problem(moji)
    assert fix is not None and fix.kind == "mojibake"
    assert fix.preview_after == ": 0 3 5 Привет"
