"""Шов 3: выкладка «локально + основная цель» и задание «Копирование» (истории 18–22, 34–37)."""

from karaoke_core import naming
from karaoke_core.db import Jobs, Settings, Target, now
from karaoke_core.storage import LocalStorage, StorageError

ARTIST, TITLE = "Тестовая Группа", "Песня Ёлки"
REL = naming.song_dir(ARTIST, TITLE)


def _other(world, *, default=True, name="ПК"):
    settings = Settings(world.conn)
    other = settings.save_target(Target(name=name, kind="local", path="/host/pc"))
    if default:
        settings.set_default_target_id(other.id)
    return other


def _down(world, *ids):
    """Хранилища ``ids`` недоступны, пока их не убрать из возвращённого множества."""
    down, orig = set(ids), world.ctx.storage_factory

    def factory(target):
        if target.id in down:
            raise StorageError("нет связи (тест)")
        return orig(target)

    world.ctx.storage_factory = factory
    return down


def _copies(world):
    return [j for j in world.jobs.list(1000) if j.type == "copy"]


# ---------------------------------------------------------------------- выкладка

def test_new_song_is_published_to_local_and_default_target(world):
    other = _other(world)
    job = world.enqueue_generate()
    world.run()

    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert (world.out / REL).is_dir() and (world.tmp / other.id / REL).is_dir()
    assert world.ctx.library.get("local", REL) is not None
    assert world.ctx.library.get(other.id, REL) is not None
    assert world.log(job.id).count("Выложено в «") == 2


def test_default_local_means_single_publish(world):
    job = world.enqueue_generate()
    world.run()
    assert world.jobs.get(job.id).state == "done"
    assert world.log(job.id).count("Выложено в «") == 1
    assert _copies(world) == []


def test_default_target_down_keeps_song_locally_and_copies_later(world, monkeypatch):
    from karaoke_worker import handlers

    monkeypatch.setattr(handlers, "COPY_RETRY_S", 0)
    other = _other(world)
    down = _down(world, other.id)
    job = world.enqueue_generate()

    def waiting() -> bool:
        cs = _copies(world)
        return bool(cs) and cs[0].state == "queued" and (cs[0].stage or "").startswith("Ждёт хранилище")

    world.run(until=waiting)
    done = world.jobs.get(job.id)
    assert done.state == "done", world.log(job.id)
    log = world.log(job.id)
    assert "Основная цель «ПК» недоступна: " in log
    assert "песня сохранена в локальном хранилище и докопируется, когда цель станет доступна" in log
    assert (world.out / REL).is_dir() and not (world.tmp / other.id / REL).exists()
    copy = _copies(world)[0]
    assert copy.params["wait"] is True and copy.params["to_target"] == other.id
    assert copy.params["from_target"] == "local" and copy.params["rel_dir"] == REL
    assert copy.stage == "Ждёт хранилище «ПК»"

    down.clear()  # цель «появилась»
    world.run()
    assert world.jobs.get(copy.id).state == "done", world.log(copy.id)
    assert (world.tmp / other.id / REL).is_dir()
    assert world.ctx.library.get(other.id, REL) is not None


def test_local_storage_down_fails_publish(world):
    other = _other(world)
    _down(world, "local", other.id)
    job = world.enqueue_generate()
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and failed.stage == "publish"
    assert _copies(world) == []


# ---------------------------------------------------------------------- задание copy

def _song_in(root, rel=REL, text=b"#TITLE:x\n#ARTIST:y\n#BPM:100\n: 0 1 0 a\nE\n"):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "song.txt").write_bytes(text)
    (d / "song.mp3").write_bytes(b"ID3 mp3")
    return d


def _copy(world, to, *, replace=False, wait=False, frm="local"):
    params = {"rel_dir": REL, "txt_name": "song.txt", "from_target": frm, "to_target": to,
              "replace": replace, "wait": wait}
    return world.jobs.enqueue("copy", {"artist": ARTIST, "title": TITLE}, params)


def test_copy_moves_song_files_and_indexes_target(world):
    other = _other(world, default=False)
    _song_in(world.out)
    job = _copy(world, other.id)
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert (world.tmp / other.id / REL / "song.mp3").read_bytes() == b"ID3 mp3"
    assert world.ctx.library.get(other.id, REL) is not None
    assert not world.paths.job(REL, job.id).exists()


def test_copy_skips_existing_song_without_replace(world):
    other = _other(world, default=False)
    _song_in(world.out)
    _song_in(world.tmp / other.id, text=b"#TITLE:old\n#BPM:1\n: 0 1 0 a\nE\n")
    job = _copy(world, other.id)
    world.run()
    assert world.jobs.get(job.id).state == "done"
    assert f"Уже есть в «ПК» — пропущено" in world.log(job.id)
    assert (world.tmp / other.id / REL / "song.txt").read_bytes().startswith(b"#TITLE:old")
    assert world.trash.list() == []


def test_copy_with_replace_moves_previous_version_to_target_trash(world):
    other = _other(world, default=False)
    _song_in(world.out)
    _song_in(world.tmp / other.id, text=b"#TITLE:old\n#BPM:1\n: 0 1 0 a\nE\n")
    job = _copy(world, other.id, replace=True)
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert (world.tmp / other.id / REL / "song.txt").read_bytes().startswith(b"#TITLE:x")
    trashed = world.trash.list()
    assert len(trashed) == 1 and trashed[0].target_id == other.id


def test_copy_restart_does_not_download_again(world):
    other = _other(world, default=False)
    src = _song_in(world.out)
    down = _down(world, other.id)
    job = _copy(world, other.id)
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and "«ПК» недоступно" in failed.error
    (src / "song.mp3").unlink()  # источник изменился — перезапуск берёт уже скачанное
    down.clear()
    again = world.jobs.enqueue("copy", failed, failed.params, parent_id=job.id)  # как «Перезапустить»
    world.run()
    assert world.jobs.get(again.id).state == "done", world.log(again.id)
    assert (world.tmp / other.id / REL / "song.mp3").read_bytes() == b"ID3 mp3"


def test_copy_missing_source_song_fails_in_russian(world):
    other = _other(world, default=False)
    job = _copy(world, other.id)
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and f"Песни «{REL}» нет в «" in failed.error


def test_waiting_copy_can_be_cancelled(world, monkeypatch):
    from karaoke_worker import handlers

    monkeypatch.setattr(handlers, "COPY_RETRY_S", 0)
    other = _other(world, default=False)
    _song_in(world.out)
    _down(world, other.id)
    job = _copy(world, other.id, wait=True)
    world.run(until=lambda: (world.jobs.get(job.id).stage or "").startswith("Ждёт"))
    assert world.jobs.get(job.id).state == "queued"
    world.jobs.request_cancel(job.id)
    world.run()
    assert world.jobs.get(job.id).state == "cancelled"
    assert world.log(job.id).count("недоступно") == 1  # повторы — не чаще раза в 10 минут


def test_claim_next_skips_job_waiting_for_retry(world):
    jobs = Jobs(world.conn)
    waiting = jobs.enqueue("copy", {"artist": "a", "title": "b"}, {"retry_at": "2999-01-01T00:00:00+00:00"})
    ready = jobs.enqueue("copy", {"artist": "a", "title": "c"}, {"retry_at": now()})
    assert jobs.claim_next().id == ready.id
    assert jobs.claim_next() is None
    assert jobs.get(waiting.id).state == "queued"


def test_failed_target_is_reset_but_other_storage_stays_open(world):
    """Сбой выкладки в неосновное хранилище закрывает только его; открытое локальное — в кэше."""
    other = _other(world, default=False)
    _song_in(world.out)
    made, closed, orig = [], [], world.ctx.storage_factory

    class Broken(LocalStorage):
        def upload_dir(self, local, rel_dir):
            raise StorageError("обрыв (тест)")

        def close(self):
            closed.append(self.target_id)

    def factory(target):
        made.append(target.id)
        if target.id == other.id:
            return Broken(world.tmp / other.id, target_id=other.id, label=target.label)
        return orig(target)

    world.ctx.storage_factory = factory
    local = world.ctx.storage("local")
    job = _copy(world, other.id)
    seen = {}

    def finished() -> bool:
        if world.jobs.get(job.id).state != "failed":
            return False
        seen["local"] = world.ctx.storage("local") is local  # до закрытия всех в finally
        return True

    world.run(until=finished)
    assert seen["local"] is True
    assert made.count("local") == 1 and closed == [other.id]


def test_regenerate_with_replace_publishes_as_new_and_replaces_in_song_storage(world):
    """История 38: перегенерация песни из неосновного хранилища — локально + основная цель,
    а прежняя версия в хранилище песни заменяется (в корзину — там же)."""
    other = _other(world, default=False)
    _song_in(world.tmp / other.id, text=b"#TITLE:old\n#BPM:1\n: 0 1 0 a\nE\n")
    job = world.enqueue_generate(replace=True, replace_rel_dir=REL, target_id=other.id)
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert (world.out / REL).is_dir()
    assert not (world.tmp / other.id / REL / "song.txt").exists()  # заменена новой версией
    assert world.ctx.library.get(other.id, REL) is not None
    assert [i.target_id for i in world.trash.list()] == [other.id]


# ---------------------------------------------------------------------- минусовка и замена в каждом хранилище

IMP_REL, IMP_BASE = "Группа/Группа - Песня", "Группа - Песня"
IMP_TXT = ("#TITLE:Песня\r\n#ARTIST:Группа\r\n#MP3:orig.mp3\r\n#BPM:300\r\n#GAP:1000\r\n"
           ": 0 4 5 Ёл\r\n: 4 4 5 ка\r\nE\r\n").encode("utf-8")
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 64


def _import_with_instrumental(world):
    def make(job_id: int) -> dict:
        d = world.paths.job_in(IMP_REL, job_id)
        d.mkdir(parents=True)
        (d / "song.txt").write_bytes(IMP_TXT)
        (d / "input.mp3").write_bytes(MP3)
        return {"source": "files", "youtube_url": None, "instrumental": True, "rel_dir": IMP_REL,
                "replace": False, "replace_rel_dir": None, "target_id": "local",
                "inputs": {"dir": world.paths.rel(d), "txt": world.paths.rel(d / "song.txt"),
                           "audio": world.paths.rel(d / "input.mp3")}}

    return world.jobs.enqueue_with("import", {"artist": "Группа", "title": "Песня"}, make)


def _has_instrumental(root) -> bool:
    d = root / IMP_REL
    inst = f"{IMP_BASE} [Instrumental].mp3"
    return (d / inst).is_file() and f"#INSTRUMENTAL:{inst}".encode() in (d / f"{IMP_BASE}.txt").read_bytes()


def test_import_instrumental_lands_in_every_storage(world):
    other = _other(world)
    job = _import_with_instrumental(world)
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert all(j.state == "done" for j in world.jobs.list(100)), [(j.type, j.state, j.error) for j in world.jobs.list(100)]
    assert _has_instrumental(world.out) and _has_instrumental(world.tmp / other.id)
    assert [j.type for j in world.jobs.list(100)].count("instrumental") == 1  # demucs — один раз


def test_import_instrumental_reaches_target_copied_later(world, monkeypatch):
    from karaoke_worker import handlers

    monkeypatch.setattr(handlers, "COPY_RETRY_S", 0)
    other = _other(world)
    down = _down(world, other.id)
    job = _import_with_instrumental(world)

    def waiting() -> bool:
        inst = [j for j in world.jobs.list(100) if j.type == "instrumental"]
        cs = _copies(world)
        return bool(inst) and inst[0].state == "done" and bool(cs) and all(
            (c.stage or "").startswith("Ждёт хранилище") for c in cs)

    world.run(until=waiting)
    assert world.jobs.get(job.id).state == "done"
    assert "Основная цель «ПК» недоступна: " in world.log(job.id)
    down.clear()
    world.run()
    assert all(c.state == "done" for c in _copies(world)), [world.log(c.id) for c in _copies(world)]
    assert _has_instrumental(world.tmp / other.id)


def test_late_copy_moves_replaced_folder_to_target_trash(world, monkeypatch):
    """§8: замена с другой папкой — прежняя версия уходит в корзину и той цели, куда песня докопирована."""
    from karaoke_worker import handlers

    monkeypatch.setattr(handlers, "COPY_RETRY_S", 0)
    old_rel = "Тестовая Группа/Тестовая Группа - Старое имя"
    other = _other(world)
    _song_in(world.tmp / other.id, rel=old_rel)
    down = _down(world, other.id)
    job = world.enqueue_generate(replace=True, replace_rel_dir=old_rel, target_id=other.id)
    world.run(until=lambda: bool(_copies(world)) and (_copies(world)[0].stage or "").startswith("Ждёт"))
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    down.clear()
    world.run()
    copy = _copies(world)[0]
    assert world.jobs.get(copy.id).state == "done", world.log(copy.id)
    assert (world.tmp / other.id / REL).is_dir() and not (world.tmp / other.id / old_rel).exists()
    assert [(i.target_id, i.rel_dir) for i in world.trash.list()] == [(other.id, old_rel)]
    assert world.ctx.library.get(other.id, old_rel) is None
