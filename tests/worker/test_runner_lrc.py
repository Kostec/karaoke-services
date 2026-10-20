"""Шов 3: тайминги строк из LRC (G06.2, G06.3) — флаг --lyrics_timing только при совпадении строк."""

import json

import pytest

DIR = "Тестовая Группа/Тестовая Группа - Песня Ёлки"
NOT_USED = "Тайминги LRC не использованы: текст отличается"

LYRICS = "В лесу родилась ёлочка,\n\nВ лесу она росла!\nЗимой и летом стройная"
# метаданные, пауза, [Chorus], другой регистр/пунктуация/ё, строка с двумя метками
LRC = ("[ar:Народная]\n[offset:+0]\n[00:01.00]В лесу родилась елочка\n[00:03.50]\n"
       "[00:04.00]Припев\n" "[00:06.20][00:02.00]в лесу она — росла\n[00:08.000]Зимой и летом стройная\n")
LRC_LINES = ("[00:01.00]В лесу родилась ёлочка\n[00:04.00]В лесу она росла\n"
             "[00:06.20]Зимой и летом стройная\n")


def run(world, tmp_path, monkeypatch, **kw):
    args_file = tmp_path / "args.json"
    monkeypatch.setenv("FAKE_US_ARGS", str(args_file))
    job = world.enqueue_generate(**kw)
    world.run()
    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    return json.loads(args_file.read_text("utf-8")), world.log(job.id)


def test_matching_lines_pass_lyrics_timing(world, tmp_path, monkeypatch):
    lyrics = "В лесу родилась ёлочка,\nВ лесу она росла!\nЗимой и летом стройная"
    argv, log = run(world, tmp_path, monkeypatch, lyrics=lyrics, lrc=LRC_LINES, lrc_timing=True)
    assert argv[argv.index("--lyrics_timing") + 1].endswith("/in/lyrics.lrc")
    assert NOT_USED not in log
    source = world.paths.song_at(DIR) / "source"
    assert (source / "lyrics.lrc").read_text("utf-8") == LRC_LINES


def test_multi_tag_line_is_expanded_by_time(world, tmp_path, monkeypatch):
    # «в лесу она росла» стоит в 00:02 и 00:06 → две строки, по порядку времени
    lyrics = ("В лесу родилась ёлочка\nВ лесу она росла\n[Припев]\nПрипев\n"
              "В лесу она росла\nЗимой и летом стройная")
    argv, log = run(world, tmp_path, monkeypatch, lyrics=lyrics, lrc=LRC, lrc_timing=True)
    assert "--lyrics_timing" in argv
    assert NOT_USED not in log


@pytest.mark.parametrize("lyrics", [
    LYRICS,  # строка с двумя метками не развёрнута в тексте
    "В лесу родилась ёлочка\nВ лесу она росла\nПрипев\nВ лесу она росла\nЗимой и летом стройна",
])
def test_differing_text_runs_without_flag_and_logs(world, tmp_path, monkeypatch, lyrics):
    argv, log = run(world, tmp_path, monkeypatch, lyrics=lyrics, lrc=LRC, lrc_timing=True)
    assert "--lyrics_timing" not in argv
    assert NOT_USED in log


def test_lrc_timing_off_ignores_lrc(world, tmp_path, monkeypatch):
    lyrics = "В лесу родилась ёлочка\nВ лесу она росла\nЗимой и летом стройная"
    argv, log = run(world, tmp_path, monkeypatch, lyrics=lyrics, lrc=LRC_LINES, lrc_timing=False)
    assert "--lyrics_timing" not in argv
    assert NOT_USED not in log


def test_unreadable_lrc_logs_real_cause(world, tmp_path, monkeypatch):
    lyrics = "В лесу родилась ёлочка\nВ лесу она росла\nЗимой и летом стройная"
    monkeypatch.setenv("FAKE_US_ARGS", str(tmp_path / "args.json"))
    job = world.enqueue_generate(lyrics=lyrics, lrc=LRC_LINES, lrc_timing=True)
    world.paths.abs(world.jobs.get(job.id).params["inputs"]["lrc"]).write_bytes(b"[00:01.00]\xff\xfe\x80")
    world.run()
    log = world.log(job.id)
    assert world.jobs.get(job.id).state == "done"
    assert NOT_USED not in log and "lyrics.lrc" in log and "UnicodeDecodeError" in log
