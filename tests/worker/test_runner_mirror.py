"""Шов 3: задание «Зеркало» и его планировщик (истории 44–48)."""

from karaoke_core import naming
from karaoke_core.db import FINAL_STATES, Mirror, Settings, Target, now
from karaoke_core.storage import StorageError

MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 16


def _txt(artist: str, title: str, base: str, extra: str = "") -> bytes:
    return (f"#ARTIST:{artist}\n#TITLE:{title}\n#BPM:100\n#GAP:0\n#MP3:{base}.mp3\n"
            f": 0 4 0 Ля{extra}\nE\n").encode("utf-8")


def _put(root, artist: str, title: str, *, rel_dir: str | None = None, extra: str = "") -> str:
    rel = rel_dir or naming.song_dir(artist, title)
    base = rel.split("/")[-1]
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{base}.txt").write_bytes(_txt(artist, title, base, extra))
    (d / f"{base}.mp3").write_bytes(MP3)
    return rel


def _pi(world, name="Pi"):
    target = Settings(world.conn).save_target(Target(name=name, kind="local", path="/host/pi"))
    (world.tmp / target.id).mkdir(exist_ok=True)
    return target


def _mirror(world, to, *, enabled=True, last=None) -> Mirror:
    settings = Settings(world.conn)
    m = settings.save_mirror(Mirror(from_target="local", to_target=to.id, enabled=enabled))
    if last is not None:
        settings.set_mirror_result(m.id, last)
    return m


def _run_mirror(world, m, **kw):
    job = world.jobs.enqueue("mirror", {"artist": "Локальное", "title": "Pi"}, {"mirror_id": m.id})
    world.run(**kw)
    return world.jobs.get(job.id)


def _copies(world):
    return [j for j in world.jobs.list(1000) if j.type == "copy"]


def _stored(world, mirror_id):
    return next(m for m in Settings(world.conn).get_mirrors() if m.id == mirror_id)


def test_missing_song_is_copied_and_target_only_song_is_kept(world):
    pi = _pi(world)
    new = _put(world.out, "Группа", "Новая")
    only = _put(world.tmp / pi.id, "Звери", "Районы-кварталы")
    m = _mirror(world, pi)

    job = _run_mirror(world, m)

    assert job.state == "done", world.log(job.id)
    (copy,) = _copies(world)
    assert copy.params["rel_dir"] == new and copy.params["to_target"] == pi.id
    assert copy.params["replace"] is False and copy.params["wait"] is True
    assert copy.state == "done", world.log(copy.id)
    assert (world.tmp / pi.id / new).is_dir()
    assert (world.tmp / pi.id / only).is_dir()  # само ничего не удаляет
    res = _stored(world, m.id).last_result
    assert res["added"] == 1 and res["updated"] == 0
    assert [(s["artist"], s["title"], s["rel_dir"]) for s in res["only_in_target"]] == [
        ("Звери", "Районы-кварталы", only)]
    assert res["only_in_target"][0]["song_id"] == world.ctx.library.get(pi.id, only).song_id
    assert _stored(world, m.id).last_run_at


def test_changed_song_replaces_copy_and_old_goes_to_target_trash(world):
    pi = _pi(world)
    rel = _put(world.out, "Группа", "Песня")
    same = _put(world.out, "Группа", "Та же")
    _put(world.tmp / pi.id, "Группа", "Песня")
    _put(world.tmp / pi.id, "Группа", "Та же")
    m = _mirror(world, pi, last={"added": 0, "updated": 0, "only_in_target": [], "started_at": now(-3600)})
    _put(world.out, "Группа", "Песня", extra=" правка")  # изменилась после прошлого прогона

    job = _run_mirror(world, m)

    assert job.state == "done", world.log(job.id)
    (copy,) = _copies(world)  # «Та же» — размеры совпали, копии нет
    assert copy.params["rel_dir"] == rel and copy.params["replace"] is True and copy.params["wait"] is True
    assert "replace_rel_dir" not in copy.params
    assert copy.state == "done", world.log(copy.id)
    base = rel.split("/")[-1]
    assert b"\xd0\xbf\xd1\x80\xd0\xb0\xd0\xb2\xd0\xba\xd0\xb0" in (world.tmp / pi.id / rel / f"{base}.txt").read_bytes()
    assert any(e.rel_dir == rel for e in world.trash.list())  # прежняя — в корзине цели
    assert (world.tmp / pi.id / same).is_dir()
    assert _stored(world, m.id).last_result["updated"] == 1


def test_changed_song_in_other_folder_replaces_that_folder(world):
    pi = _pi(world)
    rel = _put(world.out, "Группа", "Песня")
    old = _put(world.tmp / pi.id, "Группа", "Песня", rel_dir="Группа/Группа - Песня (старая)")
    m = _mirror(world, pi, last={"added": 0, "updated": 0, "only_in_target": [], "started_at": now(-3600)})
    _put(world.out, "Группа", "Песня", extra=" правка")

    job = _run_mirror(world, m)

    assert job.state == "done", world.log(job.id)
    (copy,) = _copies(world)
    assert copy.params["replace"] is True and copy.params["replace_rel_dir"] == old
    assert copy.state == "done", world.log(copy.id)
    assert (world.tmp / pi.id / rel).is_dir() and not (world.tmp / pi.id / old).exists()
    assert _stored(world, m.id).last_result["only_in_target"] == []


def test_unchanged_since_last_run_is_not_compared(world):
    pi = _pi(world)
    _put(world.out, "Группа", "Песня", extra=" правка")
    _put(world.tmp / pi.id, "Группа", "Песня")
    m = _mirror(world, pi, last={"added": 0, "updated": 0, "only_in_target": [], "started_at": now(3600)})

    job = _run_mirror(world, m)

    assert job.state == "done", world.log(job.id)
    assert _copies(world) == []


def test_first_run_only_adds_never_replaces(world):
    pi = _pi(world)
    _put(world.out, "Группа", "Песня", extra=" правка")
    _put(world.tmp / pi.id, "Группа", "Песня")
    m = _mirror(world, pi)

    job = _run_mirror(world, m)

    assert job.state == "done", world.log(job.id)
    assert _copies(world) == []
    assert _stored(world, m.id).last_result == {"added": 0, "updated": 0, "only_in_target": [],
                                                 "started_at": _stored(world, m.id).last_result["started_at"]}


def test_target_down_mirror_waits_for_storage(world):
    pi = _pi(world)
    _put(world.out, "Группа", "Песня")
    m = _mirror(world, pi)
    orig = world.ctx.storage_factory

    def factory(target):
        if target.id == pi.id:
            raise StorageError("нет связи (тест)")
        return orig(target)

    world.ctx.storage_factory = factory
    job = world.jobs.enqueue("mirror", {}, {"mirror_id": m.id})
    world.run(until=lambda: (world.jobs.get(job.id).stage or "").startswith("Ждёт"))

    waiting = world.jobs.get(job.id)
    assert waiting.state == "queued" and waiting.stage == "Ждёт хранилище «Pi»"
    assert _copies(world) == []
    assert _stored(world, m.id).last_run_at is None


def test_deleted_mirror_fails_job(world):
    job = world.jobs.enqueue("mirror", {}, {"mirror_id": "m_gone"})
    world.run()
    assert world.jobs.get(job.id).state == "failed"
    assert world.jobs.get(job.id).error.startswith("Зеркало удалено из настроек")


# ---------------------------------------------------------------------- планировщик

def _mirror_jobs(world):
    return [j for j in world.jobs.list(1000) if j.type == "mirror"]


def test_scheduler_queues_due_enabled_mirror_once(world):
    from karaoke_worker.mirror import schedule_mirrors

    pi = _pi(world)
    m = _mirror(world, pi)
    off = _mirror(world, _pi(world, "Выкл"), enabled=False)

    first = schedule_mirrors(world.ctx)
    again = schedule_mirrors(world.ctx)

    assert [j.params["mirror_id"] for j in first] == [m.id]
    assert again == []  # активное не дублируется
    assert [j.params["mirror_id"] for j in _mirror_jobs(world)] == [m.id]
    assert off.id not in {j.params["mirror_id"] for j in _mirror_jobs(world)}
    assert (first[0].artist, first[0].title) == ("Локальное хранилище", "Pi")


def test_scheduler_waits_30_minutes_after_last_run(world):
    from karaoke_worker.mirror import MIRROR_EVERY_S, schedule_mirrors

    assert MIRROR_EVERY_S == 1800
    pi = _pi(world)
    m = _mirror(world, pi, last={"added": 0, "updated": 0, "only_in_target": []})  # прогон «сейчас»
    assert schedule_mirrors(world.ctx) == []
    assert [j.params["mirror_id"] for j in schedule_mirrors(world.ctx, every_s=0)] == [m.id]


def test_scheduler_skips_mirror_of_deleted_storage(world):
    from karaoke_worker.mirror import schedule_mirrors

    pi = _pi(world)
    m = _mirror(world, pi)
    settings = Settings(world.conn)
    settings.delete_target(pi.id)  # зеркало выключается
    assert next(x for x in settings.get_mirrors() if x.id == m.id).enabled is False
    assert schedule_mirrors(world.ctx) == []


def test_worker_loop_runs_enabled_mirror(world):
    pi = _pi(world)
    rel = _put(world.out, "Группа", "Песня")
    m = _mirror(world, pi)

    def finished() -> bool:
        jobs = _mirror_jobs(world) + _copies(world)
        return len(jobs) == 2 and all(j.state in FINAL_STATES for j in jobs)

    world.run(until=finished)
    assert _mirror_jobs(world)[0].state == "done"
    assert (world.tmp / pi.id / rel).is_dir()
    assert _stored(world, m.id).last_result["added"] == 1
