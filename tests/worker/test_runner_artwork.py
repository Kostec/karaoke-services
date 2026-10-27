"""Шов 3: задание artwork (истории 12–18, 20) — обложка и фон песни USDB в cp1251/CRLF, без GPU."""

from __future__ import annotations

from pathlib import Path

CORE_FIX = Path(__file__).resolve().parents[1] / "core" / "fixtures"
MP3 = b"ID3" + bytes(7) + bytes([0xFF, 0xFB, 0x90, 0x00]) * 64
NO_GPU = {"ok": False, "name": None, "vram_mb": None, "error": "нет GPU (тест)"}

DIR = "USDB/Исполнитель USDB - Зимняя вишня"
STEM = "Исполнитель USDB - Зимняя вишня"
TXT = f"{STEM}.txt"
PNG = b"\x89PNG\r\n\x1a\nNEW-PNG"
JPG = b"\xff\xd8\xff\xe0NEW-JPG"


def _song(world, extra_header: str = "") -> bytes:
    d = world.out / DIR
    d.mkdir(parents=True)
    original = (CORE_FIX / "usdb_cp1251.txt").read_bytes()  # #COVER:<…> [CO].jpg, без #BACKGROUND
    if extra_header:
        original = original.replace(b"#BPM:", extra_header.encode("cp1251") + b"\r\n#BPM:", 1)
    (d / TXT).write_bytes(original)
    (d / f"{STEM}.mp3").write_bytes(MP3)
    (d / f"{STEM} [CO].jpg").write_bytes(b"\xff\xd8\xff\xe0OLD-CO")
    return original


def _enqueue(world, kind: str, *, image: tuple[str, bytes] | None = None, **extra):
    params = {"rel_dir": DIR, "txt_name": TXT, "target_id": world.storage.target_id, "kind": kind, **extra}

    def make(job_id: int) -> dict:
        d = world.paths.job_in(DIR, job_id)
        d.mkdir(parents=True)
        inputs = {"dir": world.paths.rel(d)}
        if image is not None:
            name, data = image
            (d / name).write_bytes(data)
            inputs["image"] = world.paths.rel(d / name)
        return {**params, "inputs": inputs}

    ref = {"artist": "Исполнитель USDB", "title": "Зимняя вишня", "song_id": "sid"}
    return world.jobs.enqueue_with("artwork", ref, make)


def _lines(data: bytes) -> list[bytes]:
    return data.split(b"\r\n")


def test_background_without_gpu_adds_file_and_exactly_one_line(world):
    original = _song(world)
    job = _enqueue(world, "background", image=("image.png", PNG))
    world.run(gpu=NO_GPU)

    done = world.jobs.get(job.id)
    assert (done.state, done.error, done.percent) == ("done", None, 100)
    assert (world.out / DIR / f"{STEM} [BG].png").read_bytes() == PNG
    new = (world.out / DIR / TXT).read_bytes()
    bg = f"#BACKGROUND:{STEM} [BG].png".encode("cp1251")
    assert [x for x in _lines(new) if x not in _lines(original)] == [bg]
    assert new.replace(bg + b"\r\n", b"", 1) == original  # прочие байты не тронуты
    assert [i.rel_file for i in world.trash.list() if i.kind == "version"] == [f"{DIR}/{TXT}"]
    assert not world.paths.job(DIR, job.id).exists()


def test_cover_replaces_old_file_of_other_name(world):
    original = _song(world)
    job = _enqueue(world, "cover", image=("image.png", PNG))
    world.run(gpu=NO_GPU)

    assert (world.jobs.get(job.id).state, world.jobs.get(job.id).error) == ("done", None)
    assert (world.out / DIR / f"{STEM} [CO].png").read_bytes() == PNG
    assert not (world.out / DIR / f"{STEM} [CO].jpg").exists()
    new = (world.out / DIR / TXT).read_bytes()
    assert new == original.replace(f"{STEM} [CO].jpg".encode("cp1251"), f"{STEM} [CO].png".encode("cp1251"))
    assert [i.rel_file for i in world.trash.list()] == [f"{DIR}/{TXT}"]  # картинка в корзину не идёт
    item = world.ctx.library.get(world.storage.target_id, DIR)
    assert item is not None and item.cover == f"{STEM} [CO].png"


def test_same_name_overwrites_without_touching_txt(world):
    original = _song(world)
    job = _enqueue(world, "cover", image=("image.jpg", JPG))
    world.run(gpu=NO_GPU)

    assert world.jobs.get(job.id).state == "done"
    assert (world.out / DIR / f"{STEM} [CO].jpg").read_bytes() == JPG
    assert (world.out / DIR / TXT).read_bytes() == original
    assert world.trash.list() == []


def test_remove_background_drops_line_and_file_byte_for_byte(world):
    original = _song(world, f"#BACKGROUND:{STEM} [BG].jpg")
    (world.out / DIR / f"{STEM} [BG].jpg").write_bytes(b"OLD-BG")
    job = _enqueue(world, "background", remove=True)
    world.run(gpu=NO_GPU)

    assert (world.jobs.get(job.id).state, world.jobs.get(job.id).error) == ("done", None)
    assert not (world.out / DIR / f"{STEM} [BG].jpg").exists()
    expected = original.replace(f"#BACKGROUND:{STEM} [BG].jpg\r\n".encode("cp1251"), b"", 1)
    assert expected != original
    assert (world.out / DIR / TXT).read_bytes() == expected
    assert (world.out / DIR / f"{STEM} [CO].jpg").exists()


def test_publish_failure_then_restart_and_republish(world):
    _song(world)
    world.storage_ok = False
    job = _enqueue(world, "background", image=("image.png", PNG))
    world.run(gpu=NO_GPU)
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and failed.stage == "publish"
    assert "ошибка выкладки" in failed.error or "недоступн" in failed.error

    world.storage_ok = True
    pub = world.jobs.enqueue("publish", failed, {"source_job_id": failed.id}, parent_id=failed.id)
    world.run(gpu=NO_GPU)
    assert (world.jobs.get(pub.id).state, world.jobs.get(pub.id).error) == ("done", None)
    assert (world.out / DIR / f"{STEM} [BG].png").read_bytes() == PNG


def test_restart_takes_parent_image(world):
    _song(world)
    world.storage_ok = False
    job = _enqueue(world, "cover", image=("image.png", PNG))
    world.run(gpu=NO_GPU)
    failed = world.jobs.get(job.id)
    assert failed.state == "failed"

    world.storage_ok = True
    again = world.jobs.enqueue("artwork", failed, failed.params, parent_id=failed.id)  # как web restart
    world.run(gpu=NO_GPU)
    assert (world.jobs.get(again.id).state, world.jobs.get(again.id).error) == ("done", None)
    assert (world.out / DIR / f"{STEM} [CO].png").read_bytes() == PNG


def test_missing_image_fails_with_russian_text(world):
    original = _song(world)
    job = _enqueue(world, "background")
    world.run(gpu=NO_GPU)
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and "Картинка" in failed.error
    assert (world.out / DIR / TXT).read_bytes() == original
