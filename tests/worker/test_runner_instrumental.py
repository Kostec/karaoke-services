"""Шов 3: минусовка для песни USDB в cp1251 (истории 45–47); demucs и ffmpeg — фейки."""

from pathlib import Path

from karaoke_core.storage import LocalStorage

CORE_FIX = Path(__file__).resolve().parents[1] / "core" / "fixtures"
MP3 = b"ID3" + bytes(7) + bytes([0xFF, 0xFB, 0x90, 0x00]) * 64

DIR = "USDB/Исполнитель USDB - Зимняя вишня"
TXT = "Исполнитель USDB - Зимняя вишня.txt"
AUDIO = "Исполнитель USDB - Зимняя вишня.mp3"
INST = "Исполнитель USDB - Зимняя вишня [Instrumental].mp3"


def _song(world, extra_header: bytes = b""):
    d = world.out / DIR
    d.mkdir(parents=True)
    original = (CORE_FIX / "usdb_cp1251.txt").read_bytes()
    if extra_header:
        original = original.replace(b"#BPM:", extra_header + b"\r\n#BPM:", 1)
    (d / TXT).write_bytes(original)
    (d / AUDIO).write_bytes(MP3)
    return original


def _enqueue(world, instrumental=None):
    entry = LocalStorage(world.out).read_song(DIR)
    params = {"rel_dir": DIR, "txt_name": TXT, "audio": entry.audio, "instrumental": instrumental,
              "replace": bool(instrumental), "target_id": world.storage.target_id}
    return world.jobs.enqueue("instrumental", {"artist": entry.artist, "title": entry.title}, params)


def test_instrumental_on_cp1251_song_adds_mp3_and_exactly_one_line(world):
    original = _song(world)
    job = _enqueue(world)
    world.run()

    done = world.jobs.get(job.id)
    assert (done.state, done.error, done.percent) == ("done", None, 100)
    mp3 = (world.out / DIR / INST).read_bytes()
    assert mp3.startswith(b"ID3") and b"FAKE-MP3" in mp3
    new = (world.out / DIR / TXT).read_bytes()
    old_lines, new_lines = original.split(b"\r\n"), new.split(b"\r\n")
    assert len(new_lines) == len(old_lines) + 1
    added = [line for line in new_lines if line not in old_lines]
    assert added == [f"#INSTRUMENTAL:{INST}".encode("cp1251")]
    assert new.replace(added[0] + b"\r\n", b"", 1) == original  # остальные байты не тронуты
    # прежняя версия .txt — в корзине
    versions = [i for i in world.trash.list() if i.kind == "version"]
    assert [i.rel_file for i in versions] == [f"{DIR}/{TXT}"]
    assert not world.paths.job(DIR, job.id).exists()


def test_existing_instrumental_goes_to_trash_before_overwrite(world):
    _song(world, f"#INSTRUMENTAL:{INST}".encode("cp1251"))
    (world.out / DIR / INST).write_bytes(b"old instrumental")
    before = (world.out / DIR / TXT).read_bytes()
    job = _enqueue(world, instrumental=INST)
    world.run()

    assert world.jobs.get(job.id).state == "done"
    assert (world.out / DIR / INST).read_bytes() != b"old instrumental"
    assert (world.out / DIR / TXT).read_bytes() == before  # строка уже была — .txt не меняется
    saved = [i for i in world.trash.list() if i.rel_file == f"{DIR}/{INST}"]
    assert len(saved) == 1


def test_instrumental_writes_into_song_storage_not_default(world):
    """Песня в неосновном хранилище: минусовка пишется в её копию (история 38)."""
    from karaoke_core.db import Settings, Target

    settings = Settings(world.conn)
    other = settings.save_target(Target(name="ПК", kind="local", path="/host/pc"))
    root = world.tmp / other.id  # фабрика World: не-local хранилище — tmp/<id>
    d = root / DIR
    d.mkdir(parents=True)
    (d / TXT).write_bytes((CORE_FIX / "usdb_cp1251.txt").read_bytes())
    (d / AUDIO).write_bytes(MP3)
    entry = LocalStorage(root).read_song(DIR)
    params = {"rel_dir": DIR, "txt_name": TXT, "audio": entry.audio, "instrumental": None,
              "replace": False, "target_id": other.id}
    job = world.jobs.enqueue("instrumental", {"artist": entry.artist, "title": entry.title}, params)
    world.run()

    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert (d / INST).is_file() and not (world.out / DIR).exists()
    assert world.ctx.library.get(other.id, DIR).instrumental == INST


def test_instrumental_with_legacy_target_id_finds_local_storage(world):
    """Задание старого формата (``local:/output``) сопоставляется со встроенным «local»."""
    _song(world)
    entry = LocalStorage(world.out).read_song(DIR)
    params = {"rel_dir": DIR, "txt_name": TXT, "audio": entry.audio, "instrumental": None,
              "replace": False, "target_id": "local:/output"}
    job = world.jobs.enqueue("instrumental", {"artist": entry.artist, "title": entry.title}, params)
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert (world.out / DIR / INST).is_file()
