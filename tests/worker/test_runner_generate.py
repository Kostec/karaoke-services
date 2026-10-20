"""Шов 3: generate от queued до done с фейковым UltraSinger (истории 12, 17–19, 30, 32)."""

import json

from karaoke_core.db import Settings, Songs

ARTIST, TITLE = "Тестовая Группа", "Песня Ёлки"
DIR = "Тестовая Группа/Тестовая Группа - Песня Ёлки"
BASE = "Тестовая Группа - Песня Ёлки"


def test_generate_goes_from_queued_to_done_and_lands_in_storage(world, tmp_path, monkeypatch):
    args_file = tmp_path / "args.json"
    monkeypatch.setenv("FAKE_US_ARGS", str(args_file))
    job = world.enqueue_generate(ARTIST, TITLE)
    assert job.state == "queued"

    world.run()

    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    assert done.percent == 100
    files = sorted(p.name for p in (world.out / DIR).iterdir())
    assert files == sorted([f"{BASE}.txt", f"{BASE}.mp3", f"{BASE} [Instrumental].mp3",
                            f"{BASE} [Vocals].mp3", f"{BASE}.mid", f"{BASE} [CO].jpg"])
    txt = (world.out / DIR / f"{BASE}.txt").read_text("utf-8")
    assert f"#ARTIST:{ARTIST}" in txt and f"#TITLE:{TITLE}" in txt

    # проверенная команда по умолчанию (история 12), без --interactive
    argv = json.loads(args_file.read_text("utf-8"))
    joined = " ".join(argv)
    assert ("--whisper large-v2 --whisper_compute_type int8 --whisper_batch_size 4 --language ru "
            "--whisper_align_model jonatasgrosman/wav2vec2-large-xlsr-53-russian") in joined
    assert "--interactive" not in argv
    assert argv[argv.index("-i") + 1].endswith(f"/{BASE}.mp3")
    assert argv[argv.index("--lyrics") + 1].endswith("lyrics.txt")
    assert argv[argv.index("--format_version") + 1] == "1.2.0"

    # лог без ANSI и без повторов tqdm
    log = world.log(job.id)
    assert "\x1b" not in log and "\r" not in log
    assert "Transcribing vocals.wav" in log
    separate = [line for line in log.splitlines() if line.startswith("separate:")]
    assert len(separate) == 1 and "100%|" in separate[0]

    # исходники и params в source/, рабочая папка задания удалена (Решения §3)
    source = world.paths.source(DIR)
    assert sorted(p.name for p in source.iterdir()) == ["input.mp3", "lyrics.txt", "params.json"]
    assert json.loads((source / "params.json").read_text("utf-8"))["whisper_model"] == "large-v2"
    assert not world.paths.job(DIR, job.id).exists()
    assert Songs(world.conn).by_rel_dir(DIR) is not None
    assert Settings(world.conn).get_gpu_status()["name"] == "Fake GPU"


def test_ultrasinger_without_output_folder_is_a_failure(world, monkeypatch):
    monkeypatch.setenv("FAKE_US_MODE", "noresult")
    job = world.enqueue_generate()
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert "не создал результат" in failed.error
    assert not (world.out / DIR).exists()


def test_known_errors_are_explained(world, monkeypatch):
    monkeypatch.setenv("FAKE_US_MODE", "oom")
    job = world.enqueue_generate()
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error.startswith("Не хватило видеопамяти — попробуйте batch size 2 или модель поменьше")
    assert failed.stage == "Загрузка модели"


def test_ultrasinger_hanging_after_uncaught_error_is_stopped(world, monkeypatch):
    monkeypatch.setenv("FAKE_US_MODE", "crash_hang")
    world.ctx.fatal_grace = 0.5
    job = world.enqueue_generate()
    world.run(timeout=30)
    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert "unexpected keyword argument 'fmin'" in failed.error


def test_traceback_of_child_with_output_after_it_does_not_kill_job(world, monkeypatch):
    monkeypatch.setenv("FAKE_US_MODE", "child_traceback")
    world.ctx.fatal_grace = 0.5  # тишина после трассировки короче — вывод идёт каждые 0.2 с
    job = world.enqueue_generate()
    world.run(timeout=30)
    assert world.jobs.get(job.id).state == "done"


def test_alignment_debug_is_kept_in_song_folder_of_data_volume(world):
    job = world.enqueue_generate(keep_debug=True)
    world.run()
    assert world.jobs.get(job.id).state == "done"
    assert (world.paths.song_at(DIR) / "debug" / "lyrics_debug.json").is_file()
    assert not list(world.out.rglob("lyrics_debug.json"))
