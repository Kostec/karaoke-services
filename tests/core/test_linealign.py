"""Границы строк по исходному тексту: ``linealign.align_line_starts`` и ``align_song``."""

from karaoke_core import ultrastar
from karaoke_core.linealign import LineAlign, align_line_starts, align_song, line_starts

LYRICS = "Тяни лотерейный билет\nЧто б тамбур прокуренным был\nУ нас с тобой выигравших нет\n"
NOTES = ["Тя", "ни ", "ло", "те", "рей", "ный ", "би", "лет ",          # 0..7
         "Что ", "б ", "там", "бур ", "про", "ку", "рен", "ным ", "был ",  # 8..16
         "У ", "нас ", "с ", "то", "бой ", "вы", "иг", "рав", "ших ", "нет "]  # 17..26


def test_full_match_gives_exactly_lyrics_lines():
    r = align_line_starts(NOTES, LYRICS, existing_starts=[0, 8, 9, 16, 17])
    assert r == LineAlign(starts=[0, 8, 17], unmatched=0, total=3)


def test_starts_always_begin_with_zero_and_ignore_blank_lines():
    r = align_line_starts(NOTES, "\n\n" + LYRICS.replace("\n", "\n\n"))
    assert r.starts == [0, 8, 17] and r.total == 3


def test_leading_trailing_spaces_and_tilde():
    notes = ["Ла", "~", " ла", "~ ", "сло", " ~", "ги ", "тест", " ~ ", "Вто", "ра", "я ", "~", "строч", "ка "]
    # слова: «Лала»? нет — « ла» с пробелом в начале — новое слово; «~» тянет предыдущее
    r = align_line_starts(notes, "Ла ла слоги\nтест\nВторая строчка")
    assert r.starts == [0, 7, 9] and r.unmatched == 0


def test_space_after_tilde_ends_word():
    notes = ["Ра", "~ ", "два ", "три "]
    assert align_line_starts(notes, "Ра два\nтри").starts == [0, 3]


def test_word_dropped_by_ultrasinger():
    notes = [n for i, n in enumerate(NOTES) if i != 9]  # «б» не расслышано
    r = align_line_starts(notes, LYRICS, existing_starts=[0, 8, 15, 16])
    assert r.starts == [0, 8, 16] and r.unmatched == 0


def test_first_word_of_line_misheard_goes_to_its_line():
    notes = list(NOTES)
    notes[8] = "Шо "  # «Что» → «Шо»: слово не совпало, но стоит перед строкой 2
    r = align_line_starts(notes, LYRICS, existing_starts=[0, 9])
    assert r.starts == [0, 8, 17]


def test_line_missing_in_notes_is_unmatched_and_keeps_existing_starts():
    lyrics = "Тяни лотерейный билет\nЭтой строки нет в нотах\nУ нас с тобой выигравших нет"
    # в нотах на месте второй строки — нераспознанное «Что б…» с прежними разрывами
    r = align_line_starts(NOTES, lyrics, existing_starts=[0, 8, 12, 17])
    assert r.unmatched == 1 and r.total == 3
    assert r.starts == [0, 8, 12, 17]


def test_extra_notes_between_adjacent_lines_do_not_keep_old_breaks():
    r = align_line_starts(NOTES, "Тяни лотерейный билет\nУ нас с тобой выигравших нет",
                          existing_starts=[0, 4, 8, 12, 17])
    assert r.starts == [0, 17] and r.unmatched == 0


def test_nothing_matched_returns_existing():
    r = align_line_starts(NOTES, "совсем\nдругой текст", existing_starts=[17, 8, 0, 99])
    assert r == LineAlign(starts=[0, 8, 17], unmatched=2, total=2, unmatched_lines=[0, 1])


def test_case_yo_punctuation_brackets():
    notes = ["Ёл", "ка, ", "ёл", "ка! ", "при", "пев ", "(эй) "]
    r = align_line_starts(notes, "ЕЛКА —\n«Елка!»\n[Припев] (Эй)")
    assert r == LineAlign(starts=[0, 2, 4], unmatched=0, total=3)


def test_punctuation_only_lines_are_not_counted():
    r = align_line_starts(NOTES, "...\n" + LYRICS + "—\n")
    assert r.total == 3 and r.starts == [0, 8, 17]


def test_empty_notes():
    assert align_line_starts([], LYRICS) == LineAlign(starts=[0], unmatched=3, total=3,
                                                      unmatched_lines=[0, 1, 2])


def test_align_song_rewrites_breaks():
    body = "".join(f": {i * 2} 2 5 {t}\n" + ("- " + str(i * 2 + 2) + "\n" if i in (7, 8, 15) else "")
                   for i, t in enumerate(NOTES))
    raw = f"#TITLE:T\n#ARTIST:A\n#BPM:300\n#GAP:0\n{body}E\n".encode()
    song = ultrastar.parse(raw)
    assert line_starts(song) == [0, 8, 9, 16]
    r = align_song(song, LYRICS)
    assert r.starts == [0, 8, 17]
    assert line_starts(song) == [0, 8, 17]
    out = ultrastar.render(song).decode()
    assert "\n- 16\n: 16 2 5 Что \n" in out and "\n- 34\n: 34 2 5 У \n" in out
    assert out.count("\n- ") == 2


def test_unmatched_lines_are_text_line_numbers_without_blank_lines():
    lyrics = "".join([chr(10), "Тяни лотерейный билет", chr(10) * 2, "Этой строки нет в нотах", chr(10),
                      "У нас с тобой выигравших нет", chr(10), "И этой тоже нет"])
    r = align_line_starts(NOTES, lyrics, existing_starts=[0, 8, 17])
    # нумерация — по строкам со словами: 0 «Тяни…», 1 «Этой…», 2 «У нас…», 3 «И этой…»
    assert r.unmatched_lines == [1, 3]
    assert r.unmatched == len(r.unmatched_lines) == 2


def test_no_unmatched_lines_when_all_found():
    assert align_line_starts(NOTES, LYRICS).unmatched_lines == []
