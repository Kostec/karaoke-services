"""Шов 3: generate выравнивает границы строк по тексту пользователя (если строки не заданы LRC)."""

from karaoke_core import ultrastar

DIR = "Тестовая Группа/Тестовая Группа - Песня Ёлки"
TXT = f"{DIR}/Тестовая Группа - Песня Ёлки.txt"
# фикстура UltraSinger: «Ла ла слоги тест / Вторая строчка / Конец»
LYRICS = "Ла ла слоги\nтест Вторая строчка\n\nКонец"
LRC = "[00:01.00]Ла ла слоги\n[00:02.00]тест Вторая строчка\n[00:03.00]Конец\n"


def _lines(world) -> list[str]:
    return ultrastar.extract_lyrics(ultrastar.parse((world.out / TXT).read_bytes())).split("\n")


def _run(world, **kw):
    job = world.enqueue_generate(**kw)
    world.run()
    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    return world.log(job.id)


def test_generate_aligns_lines_to_lyrics(world):
    log = _run(world, lyrics=LYRICS)
    assert _lines(world) == ["Ла ла слоги", "тест Вторая строчка", "Конец"]
    assert "Строки выровнены по тексту: 3 из 3" in log


def test_generate_partial_alignment_is_reported(world):
    log = _run(world, lyrics="Ла ла слоги\nтест Вторая строчка\nЭтого нет\nКонец")
    assert _lines(world) == ["Ла ла слоги", "тест Вторая строчка", "Конец"]
    assert "Строки выровнены по тексту: 3 из 4" in log


def test_generate_unmatched_text_keeps_lines(world):
    log = _run(world, lyrics="Совсем\nдругое")
    assert _lines(world) == ["Ла ла слоги тест", "Вторая строчка", "Конец"]
    assert "Строки не выровнены по тексту" in log


def test_lrc_timing_lines_are_not_touched(world):
    log = _run(world, lyrics=LYRICS, lrc=LRC, lrc_timing=True)
    assert "Тайминги строк — из LRC" in log
    assert _lines(world) == ["Ла ла слоги тест", "Вторая строчка", "Конец"]
    assert "Строки выровнены" not in log and "Строки не выровнены" not in log
