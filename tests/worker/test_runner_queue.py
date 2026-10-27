"""Шов 3: очередь — отмена, одно задание за раз, ошибка выкладки и «Выложить повторно»,
замена с корзиной, без GPU (истории 20–24, 31, 43)."""

import os
import time
from pathlib import Path

from karaoke_core.db import STAGE_PUBLISH, Jobs, connect

DIR = "Тестовая Группа/Тестовая Группа - Песня Ёлки"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    return not (stat.exists() and stat.read_text().split(") ")[-1].startswith("Z"))  # зомби = мёртв


def _wait(cond, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_cancel_running_job_kills_process_group_within_15s(world, tmp_path, monkeypatch):
    child_pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("FAKE_US_MODE", "slow")
    monkeypatch.setenv("FAKE_US_CHILD_PID", str(child_pid_file))
    job = world.enqueue_generate()
    t = world.run_in_thread(timeout=60)
    assert _wait(child_pid_file.exists), "фейковый UltraSinger не запустил дочерний процесс"
    child = int(child_pid_file.read_text())
    assert world.jobs.get(job.id).state == "running"

    web = Jobs(connect(world.paths.db))
    started = time.monotonic()
    web.request_cancel(job.id)
    assert _wait(lambda: web.get(job.id).state == "cancelled", timeout=15), "не отменено за 15 с"
    assert time.monotonic() - started <= 15
    assert _wait(lambda: not _alive(child), timeout=2), "дочерний процесс UltraSinger жив"
    job_dir = world.paths.job(DIR, job.id)
    assert sorted(p.name for p in job_dir.iterdir()) == ["in"]  # вход нужен «Перезапустить»
    inputs = web.get(job.id).params["inputs"]
    assert all(world.paths.abs(inputs[k]).is_file() for k in ("audio", "lyrics"))
    t.join(5)


def test_two_queued_jobs_never_run_at_the_same_time(world, tmp_path, monkeypatch):
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv("FAKE_US_TRACE", str(trace))
    a = world.enqueue_generate("Группа А", "Первая")
    b = world.enqueue_generate("Группа Б", "Вторая")
    world.run()
    assert [world.jobs.get(j.id).state for j in (a, b)] == ["done", "done"]
    events = [line.split() for line in trace.read_text().splitlines()]
    assert [e[0] for e in events] == ["start", "end", "start", "end"]
    assert float(events[1][1]) <= float(events[2][1])


def test_publish_failure_keeps_result_and_republish_uploads_it(world):
    world.storage_ok = False
    job = world.enqueue_generate()
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and failed.stage == STAGE_PUBLISH
    assert failed.error.startswith("ошибка выкладки: ")
    assert (world.paths.job(DIR, job.id) / "result").is_dir()
    assert not (world.out / DIR).exists()

    world.storage_ok = True
    params = {**failed.params, "source_job_id": failed.id}  # так ставит web (republish)
    again = world.jobs.enqueue("publish", failed, params, parent_id=failed.id)
    world.run()
    assert world.jobs.get(again.id).state == "done"
    assert (world.out / DIR / "Тестовая Группа - Песня Ёлки.txt").is_file()
    assert not world.paths.job(DIR, job.id).exists()
    assert (world.paths.source(DIR) / "input.mp3").is_file()


def test_replace_moves_old_folder_to_trash_only_after_success(world, monkeypatch):
    old_dir = "Старая Группа/Старая Группа - Песня"
    (world.out / old_dir).mkdir(parents=True)
    (world.out / old_dir / "Старая Группа - Песня.txt").write_text(
        "#TITLE:Песня\n#ARTIST:Старая Группа\n#BPM:100\n: 0 1 0 ля\nE\n", "utf-8")

    monkeypatch.setenv("FAKE_US_MODE", "oom")
    failed = world.enqueue_generate(replace=True, replace_rel_dir=old_dir)
    world.run()
    assert world.jobs.get(failed.id).state == "failed"
    assert (world.out / old_dir).is_dir() and world.trash.list() == []

    monkeypatch.setenv("FAKE_US_MODE", "ok")
    ok = world.enqueue_generate(replace=True, replace_rel_dir=old_dir)
    world.run()
    assert world.jobs.get(ok.id).state == "done"
    assert not (world.out / old_dir).exists()
    assert [i.rel_dir for i in world.trash.list()] == [old_dir]
    assert (world.out / DIR).is_dir()


def test_without_gpu_generate_is_not_taken_and_status_is_written(world):
    from karaoke_core.db import Settings

    job = world.enqueue_generate()
    polls = []
    world.run(gpu={"ok": False, "name": None, "vram_mb": None, "error": "нет GPU"},
              until=lambda: polls.append(1) or len(polls) > 5)
    assert world.jobs.get(job.id).state == "queued"
    assert Settings(world.conn).get_gpu_status()["error"] == "нет GPU"


def test_startup_marks_interrupted_job_failed(world):
    job = world.enqueue_generate()
    world.jobs.claim_next()
    world.run(until=lambda: True)
    got = world.jobs.get(job.id)
    assert (got.state, got.error) == ("failed", "прервано перезапуском")


def _old_song(world, rel_dir, base):
    (world.out / rel_dir).mkdir(parents=True)
    txt = f"#TITLE:старая\n#ARTIST:старая\n#MP3:{base}.mp3\n#BPM:100\n: 0 1 0 ля\nE\n".encode()
    (world.out / rel_dir / f"{base}.txt").write_bytes(txt)
    (world.out / rel_dir / f"{base}.mp3").write_bytes(b"ID3 old")
    return txt


def test_failed_upload_after_trash_step_restores_previous_version(world):
    base = "Тестовая Группа - Песня Ёлки"
    old = _old_song(world, DIR, base)
    world.fail_upload = True
    job = world.enqueue_generate(replace=True, replace_rel_dir=DIR)
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and failed.error.startswith("ошибка выкладки: ")
    assert (world.out / DIR / f"{base}.txt").read_bytes() == old
    assert sorted(p.name for p in (world.out / DIR).iterdir()) == [f"{base}.mp3", f"{base}.txt"]


def test_renamed_replacement_uploads_new_before_trashing_old(world):
    old_dir = "Старая Группа/Старая Группа - Песня"
    _old_song(world, old_dir, "Старая Группа - Песня")
    world.fail_upload = True
    job = world.enqueue_generate(replace=True, replace_rel_dir=old_dir)
    world.run()
    assert world.jobs.get(job.id).state == "failed"
    assert (world.out / old_dir).is_dir() and world.trash.list() == []


def test_without_gpu_publish_behind_generate_is_taken(world):
    world.storage_ok = False
    failed = world.enqueue_generate()
    world.run()
    world.storage_ok = True
    gen = world.enqueue_generate("Группа Б", "Вторая")
    pub = world.jobs.enqueue("publish", world.jobs.get(failed.id),
                             {**world.jobs.get(failed.id).params, "source_job_id": failed.id})
    world.run(gpu={"ok": False, "name": None, "vram_mb": None, "error": "нет GPU"},
              until=lambda: world.jobs.get(pub.id).state in ("done", "failed"))
    assert world.jobs.get(pub.id).state == "done"
    assert world.jobs.get(gen.id).state == "queued"


def _future(seconds):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def test_postponed_job_waits_and_others_go_first(world):
    later = world.enqueue_generate("Группа А", "Отложена")
    now_job = world.enqueue_generate("Группа Б", "Сразу")
    world.jobs.schedule(later.id, _future(3600))
    world.run(until=lambda: world.jobs.get(now_job.id).state == "done")
    assert world.jobs.get(later.id).state == "queued"
    # «Запустить сейчас» — и воркер берёт задание
    world.jobs.schedule(later.id, None)
    world.run(until=lambda: world.jobs.get(later.id).state == "done")


def test_moved_first_job_runs_before_earlier_ones(world):
    a = world.enqueue_generate("Группа А", "Первая")
    b = world.enqueue_generate("Группа Б", "Вторая")
    c = world.enqueue_generate("Группа В", "Третья")
    world.jobs.move(c.id, "first")
    world.run(until=lambda: world.jobs.get(c.id).state == "done")
    assert [world.jobs.get(j.id).state for j in (a, b)] == ["queued", "queued"]
    world.jobs.move(b.id, "first")
    world.run(until=lambda: world.jobs.get(b.id).state == "done")
    assert world.jobs.get(a.id).state == "queued"
