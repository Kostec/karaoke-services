"""Шов 3: задание video (истории 14–23) — песня USDB в cp1251, yt-dlp фейковый, без GPU."""

import json
import sys
import time
from pathlib import Path

import pytest
from karaoke_core import naming, ultrastar
from karaoke_core.paths import INPUT_PARAMS

FIX = Path(__file__).resolve().parent / "fixtures"
CORE_FIX = Path(__file__).resolve().parents[1] / "core" / "fixtures"
MP3 = b"ID3" + bytes(7) + bytes([0xFF, 0xFB, 0x90, 0x00]) * 64
NO_GPU = {"ok": False, "name": None, "vram_mb": None, "error": "нет GPU (тест)"}

DIR = "USDB/Исполнитель USDB - Зимняя вишня"
STEM = "Исполнитель USDB - Зимняя вишня"
TXT = f"{STEM}.txt"
YT = "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    monkeypatch.setenv("YTDLP_CMD", f"{sys.executable} {FIX / 'fake_ytdlp.py'}")
    monkeypatch.delenv("FAKE_YTDLP_MODE", raising=False)


def _song(world, extra_header: str = "") -> bytes:
    d = world.out / DIR
    d.mkdir(parents=True)
    original = (CORE_FIX / "usdb_cp1251.txt").read_bytes()
    if extra_header:
        original = original.replace(b"#BPM:", extra_header.encode("cp1251") + b"\r\n#BPM:", 1)
    (d / TXT).write_bytes(original)
    (d / f"{STEM}.mp3").write_bytes(MP3)
    return original


def _enqueue(world, *, video_file: tuple[str, bytes] | None = None, **extra):
    params = {"rel_dir": DIR, "txt_name": TXT, "target_id": world.storage.target_id, **extra}

    def make(job_id: int) -> dict:
        d = world.paths.job_in(DIR, job_id)
        d.mkdir(parents=True)
        inputs = {"dir": world.paths.rel(d)}
        if video_file is not None:
            name, data = video_file
            (d / name).write_bytes(data)
            inputs["video"] = world.paths.rel(d / name)
        return {**params, "inputs": inputs}

    return world.jobs.enqueue_with("video", {"artist": "Исполнитель USDB", "title": "Зимняя вишня"}, make)


def _added(original: bytes, new: bytes) -> list[bytes]:
    old = original.split(b"\r\n")
    return [line for line in new.split(b"\r\n") if line not in old]


def test_video_file_without_gpu_adds_file_and_exactly_video_lines(world):
    original = _song(world)
    job = _enqueue(world, video_file=("video.MKV", b"MKV-DATA"), videogap=-1.5)
    world.run(gpu=NO_GPU)

    done = world.jobs.get(job.id)
    assert (done.state, done.error, done.percent) == ("done", None, 100)
    assert (world.out / DIR / f"{STEM}.mkv").read_bytes() == b"MKV-DATA"
    new = (world.out / DIR / TXT).read_bytes()
    mkv, avi = (f"#VIDEO:{STEM}{ext}".encode("cp1251") for ext in (".mkv", ".avi"))
    assert _added(original, new) == [mkv, b"#VIDEOGAP:-1.5"]  # в фикстуре был #VIDEO:<…>.avi
    # прочие байты не тронуты
    assert new.replace(b"#VIDEOGAP:-1.5\r\n", b"", 1).replace(mkv, avi, 1) == original
    assert [i.rel_file for i in world.trash.list() if i.kind == "version"] == [f"{DIR}/{TXT}"]
    item = world.ctx.library.get(world.storage.target_id, DIR)
    assert item is not None and item.video == f"{STEM}.mkv"
    assert not world.paths.job(DIR, job.id).exists()


@pytest.mark.parametrize("height, res", [(720, "res:720,"), (0, None)])
def test_video_link_downloads_mp4_with_quality(world, height, res):
    _song(world)
    job = _enqueue(world, video_url=YT, video_height=height)
    world.run(gpu=NO_GPU)

    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    data = (world.out / DIR / f"{STEM}.mp4").read_bytes()
    assert data.startswith(b"FAKE-MP4 ") and YT.encode() in data
    assert b"vcodec:h264,ext:mp4" in data
    assert (res is None and b"res:" not in data) or (res is not None and res.encode() in data)
    new = (world.out / DIR / TXT).read_bytes()
    assert f"#VIDEO:{STEM}.mp4".encode("cp1251") in new
    assert b"#VIDEOGAP" not in new


def test_replacing_video_deletes_old_file_without_trashing_it(world):
    original = _song(world)  # в фикстуре #VIDEO:<…>.avi
    (world.out / DIR / f"{STEM}.avi").write_bytes(b"OLD-AVI")
    job = _enqueue(world, video_file=("video.mp4", b"NEW-MP4"))
    world.run(gpu=NO_GPU)

    assert world.jobs.get(job.id).state == "done"
    assert not (world.out / DIR / f"{STEM}.avi").exists()
    assert (world.out / DIR / f"{STEM}.mp4").read_bytes() == b"NEW-MP4"
    new = (world.out / DIR / TXT).read_bytes()
    assert new == original.replace(f"{STEM}.avi".encode("cp1251"), f"{STEM}.mp4".encode("cp1251"))
    assert [i.rel_file for i in world.trash.list()] == [f"{DIR}/{TXT}"]  # видео в корзину не идёт


def test_remove_video_drops_headers_and_file_byte_for_byte(world):
    original = _song(world, "#VIDEOGAP:2,5")
    (world.out / DIR / f"{STEM}.avi").write_bytes(b"OLD-AVI")
    job = _enqueue(world, remove=True)
    world.run(gpu=NO_GPU)

    assert world.jobs.get(job.id).state == "done"
    assert not (world.out / DIR / f"{STEM}.avi").exists()
    expected = original.replace(f"#VIDEO:{STEM}.avi\r\n".encode("cp1251"), b"", 1)
    expected = expected.replace(b"#VIDEOGAP:2,5\r\n", b"", 1)
    assert expected != original
    assert (world.out / DIR / TXT).read_bytes() == expected
    assert world.ctx.library.get(world.storage.target_id, DIR).video is None


@pytest.mark.parametrize("mode, url, text", [
    ("novideo", YT, "По ссылке нет видео"),
    ("forbidden", YT, "HTTP 403"),
    ("network", YT, "Нет связи с сайтом видео"),
    ("", "https://music.yandex.ru/album/1/track/2", "Яндекс Музыка отдаёт только звук"),
])
def test_video_link_errors_are_russian_and_song_untouched(world, monkeypatch, mode, url, text):
    original = _song(world)
    monkeypatch.setenv("FAKE_YTDLP_MODE", mode)
    job = _enqueue(world, video_url=url, video_height=720)
    world.run(gpu=NO_GPU)

    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and text in failed.error
    assert (world.out / DIR / TXT).read_bytes() == original


def test_publish_failure_then_republish_and_restart_without_redownload(world, monkeypatch):
    _song(world)
    world.storage_ok = False
    job = _enqueue(world, video_url=YT, video_height=480)
    world.run(gpu=NO_GPU)
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and failed.stage == "publish"

    world.storage_ok = True
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")  # повторная загрузка упала бы
    again = world.jobs.enqueue("video", failed, failed.params, parent_id=failed.id)  # как web restart
    world.run(gpu=NO_GPU)
    assert (world.jobs.get(again.id).state, world.jobs.get(again.id).error) == ("done", None)
    assert b"res:480," in (world.out / DIR / f"{STEM}.mp4").read_bytes()


def test_republish_of_video_job(world):
    _song(world)
    world.storage_ok = False
    job = _enqueue(world, video_file=("video.webm", b"WEBM"))
    world.run(gpu=NO_GPU)
    failed = world.jobs.get(job.id)
    assert failed.state == "failed"

    world.storage_ok = True
    pub = world.jobs.enqueue("publish", failed, {"source_job_id": failed.id}, parent_id=failed.id)
    world.run(gpu=NO_GPU)
    assert world.jobs.get(pub.id).state == "done"
    assert (world.out / DIR / f"{STEM}.webm").read_bytes() == b"WEBM"


def test_cancel_during_video_download(world, monkeypatch):
    original = _song(world)
    monkeypatch.setenv("FAKE_YTDLP_MODE", "hang")
    job = _enqueue(world, video_url=YT)
    t = world.run_in_thread(gpu=NO_GPU, timeout=30)
    deadline = time.monotonic() + 15
    while world.jobs.get(job.id).stage != "Загрузка видео" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert world.jobs.get(job.id).stage == "Загрузка видео"
    world.jobs.request_cancel(job.id)
    t.join(20)
    assert world.jobs.get(job.id).state == "cancelled"
    assert (world.out / DIR / TXT).read_bytes() == original


def test_regenerate_carries_old_video(world):
    artist, title = "Тестовая Группа", "Песня Ёлки"
    rel_dir, base = naming.song_dir(artist, title), naming.base_name(artist, title)
    old = world.out / rel_dir
    old.mkdir(parents=True)
    (old / "old.txt").write_text(f"#TITLE:{title}\n#ARTIST:{artist}\n#MP3:{base}.mp3\n#VIDEO:clip.mkv\n"
                                 "#VIDEOGAP:1,5\n#BPM:300\n#GAP:0\n: 0 4 1 Ля\nE\n", "utf-8")
    (old / f"{base}.mp3").write_bytes(MP3)
    (old / "clip.mkv").write_bytes(b"OLD-CLIP")
    job = world.enqueue_generate(artist, title, replace=True, replace_rel_dir=rel_dir)  # без своего видео
    world.run()

    assert (world.jobs.get(job.id).state, world.jobs.get(job.id).error) == ("done", None)
    assert (world.out / rel_dir / f"{base}.mkv").read_bytes() == b"OLD-CLIP"
    assert not (world.out / rel_dir / "clip.mkv").exists()
    song = ultrastar.parse((world.out / rel_dir / f"{base}.txt").read_bytes())
    assert (song.header("VIDEO"), song.header("VIDEOGAP")) == (f"{base}.mkv", "1.5")


def test_regenerate_with_chosen_video_replaces_old_video(world):
    """История 30: выбранное в блоке «Видео» побеждает перенос старого видео."""
    artist, title = "Тестовая Группа", "Песня Ёлки"
    rel_dir, base = naming.song_dir(artist, title), naming.base_name(artist, title)
    old = world.out / rel_dir
    old.mkdir(parents=True)
    (old / "old.txt").write_text(f"#TITLE:{title}\n#ARTIST:{artist}\n#MP3:{base}.mp3\n#VIDEO:clip.mkv\n"
                                 "#VIDEOGAP:1,5\n#BPM:300\n#GAP:0\n: 0 4 1 Ля\nE\n", "utf-8")
    (old / f"{base}.mp3").write_bytes(MP3)
    (old / "clip.mkv").write_bytes(b"OLD-CLIP")
    job = world.enqueue_generate(artist, title, replace=True, replace_rel_dir=rel_dir,
                                 video={"mode": "url", "url": YT, "height": 720})
    world.run()

    assert (world.jobs.get(job.id).state, world.jobs.get(job.id).error) == ("done", None)
    files = {f.name for f in (world.out / rel_dir).iterdir()}
    assert f"{base}.mp4" in files and f"{base}.mkv" not in files and "clip.mkv" not in files
    assert (world.out / rel_dir / f"{base}.mp4").read_bytes().startswith(b"FAKE-MP4 " + YT.encode())
    song = ultrastar.parse((world.out / rel_dir / f"{base}.txt").read_bytes())
    assert (song.header("VIDEO"), song.header("VIDEOGAP")) == (f"{base}.mp4", None)


def test_sources_skip_input_video_and_keep_video_url(world):
    artist, title = "Тестовая Группа", "Песня Ёлки"
    rel_dir = naming.song_dir(artist, title)
    job = world.enqueue_generate(artist, title, video_url=YT)  # без params.video
    (world.paths.job_in(rel_dir, job.id) / "video.mp4").write_bytes(b"IN-VIDEO")
    world.run()

    assert (world.jobs.get(job.id).state, world.jobs.get(job.id).error) == ("done", None)
    source = world.paths.source(rel_dir)
    assert (source / "input.mp3").is_file()
    assert not (source / "video.mp4").exists()
    assert json.loads((source / INPUT_PARAMS).read_text("utf-8"))["video_url"] == YT


def test_video_of_other_case_only_is_not_deleted_after_upload(world, monkeypatch):
    """Хранилище без регистра: прежнее «X.MP4» и новое «X.mp4» — один файл, удалять нельзя."""
    from karaoke_core.storage import LocalStorage

    def delete_file(self, rel):
        parent, _, name = rel.rpartition("/")
        for f in self._abs(parent).iterdir():
            if f.name.casefold() == name.casefold():
                f.unlink()

    monkeypatch.setattr(LocalStorage, "delete_file", delete_file)
    original = _song(world).replace(f"{STEM}.avi".encode("cp1251"), f"{STEM}.MP4".encode("cp1251"))
    (world.out / DIR / TXT).write_bytes(original)
    (world.out / DIR / f"{STEM}.MP4").write_bytes(b"OLD-MP4")
    job = _enqueue(world, video_file=("video.mp4", b"NEW-MP4"))
    world.run(gpu=NO_GPU)

    assert world.jobs.get(job.id).state == "done", world.jobs.get(job.id).error
    assert (world.out / DIR / f"{STEM}.mp4").read_bytes() == b"NEW-MP4"


def test_remove_dangling_video_link_without_file(world):
    """Находка проверки «#VIDEO на несуществующий файл»: строки сняты, прочие файлы не тронуты."""
    original = _song(world, "#VIDEOGAP:2,5")
    assert not (world.out / DIR / f"{STEM}.avi").exists()
    job = _enqueue(world, remove=True)
    world.run(gpu=NO_GPU)

    assert world.jobs.get(job.id).state == "done", world.jobs.get(job.id).error
    expected = original.replace(f"#VIDEO:{STEM}.avi\r\n".encode("cp1251"), b"", 1)
    expected = expected.replace(b"#VIDEOGAP:2,5\r\n", b"", 1)
    assert expected != original
    assert (world.out / DIR / TXT).read_bytes() == expected
    assert (world.out / DIR / f"{STEM}.mp3").read_bytes() == MP3
    assert sorted(p.name for p in (world.out / DIR).iterdir()) == sorted([TXT, f"{STEM}.mp3"])
    assert [i.rel_file for i in world.trash.list()] == [f"{DIR}/{TXT}"]
