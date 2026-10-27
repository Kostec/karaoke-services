"""Шов 3: задание audio — звук по ссылке YouTube из #VIDEO (история 39), yt-dlp фейковый, без GPU."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from karaoke_core import ultrastar
from karaoke_core.paths import INPUT_AUDIO

FIX = Path(__file__).resolve().parent / "fixtures"
CORE_FIX = Path(__file__).resolve().parents[1] / "core" / "fixtures"
NO_GPU = {"ok": False, "name": None, "vram_mb": None, "error": "нет GPU (тест)"}

DIR = "USDB/Исполнитель USDB - Зимняя вишня"
STEM = "Исполнитель USDB - Зимняя вишня"
TXT = f"{STEM}.txt"
YT = "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    monkeypatch.setenv("YTDLP_CMD", f"{sys.executable} {FIX / 'fake_ytdlp.py'}")
    monkeypatch.delenv("FAKE_YTDLP_MODE", raising=False)


def _song(world, original: bytes | None = None) -> bytes:
    """Песня usdb (cp1251, CRLF, #MP3 без #AUDIO) без звукового файла."""
    d = world.out / DIR
    d.mkdir(parents=True)
    original = original or (CORE_FIX / "usdb_cp1251.txt").read_bytes()
    (d / TXT).write_bytes(original)
    return original


def _enqueue(world, *, saved: bytes | None = None, url: str = YT):
    params = {"rel_dir": DIR, "txt_name": TXT, "target_id": world.storage.target_id, "url": url}

    def make(job_id: int) -> dict:
        d = world.paths.job_in(DIR, job_id)
        d.mkdir(parents=True)
        if saved is not None:
            (d / INPUT_AUDIO).write_bytes(saved)
        return {**params, "inputs": {"dir": world.paths.rel(d)}}

    return world.jobs.enqueue_with("audio", {"artist": "Исполнитель USDB", "title": "Зимняя вишня"}, make)


def test_audio_downloaded_and_headers_set_without_gpu(world):
    original = _song(world)
    job = _enqueue(world)
    world.run(gpu=NO_GPU)
    done = world.jobs.get(job.id)
    assert done.state == "done", done.error
    mp3 = world.out / DIR / f"{STEM}.mp3"
    assert mp3.read_bytes().startswith(b"AUDIO-ONLY ID3") and YT.encode() in mp3.read_bytes()
    new = (world.out / DIR / TXT).read_bytes()
    # меняется только строка #MP3 (имя то же — байты те же), #AUDIO не добавляется: он не был
    assert new == original
    assert ultrastar.parse(new).header("AUDIO") is None
    item = world.ctx.library.get("local", DIR)
    assert item is not None and item.audio == f"{STEM}.mp3"
    assert not world.paths.job(DIR, job.id).exists()


def test_audio_sets_both_headers_and_versions_txt(world):
    txt = ("#TITLE:Зимняя вишня\r\n#ARTIST:Исполнитель USDB\r\n#AUDIO:old.mp3\r\n#MP3:old.mp3\r\n"
           "#VIDEO:v=abcdefghijk\r\n#BPM:300\r\n: 0 3 60 Зим\r\nE\r\n").encode("cp1251")
    _song(world, txt)
    job = _enqueue(world)
    world.run(gpu=NO_GPU)
    assert world.jobs.get(job.id).state == "done"
    song = ultrastar.parse((world.out / DIR / TXT).read_bytes())
    assert song.header("AUDIO") == song.header("MP3") == f"{STEM}.mp3"
    assert song.encoding == "cp1251"
    assert any(e.kind == "version" for e in world.trash.list())


def test_audio_without_mp3_header_gets_mp3(world):
    txt = "#TITLE:T\n#ARTIST:A\n#BPM:300\n: 0 3 60 la\nE\n".encode("utf-8")
    _song(world, txt)
    _enqueue(world)
    world.run(gpu=NO_GPU)
    song = ultrastar.parse((world.out / DIR / TXT).read_bytes())
    assert song.header("MP3") == f"{STEM}.mp3" and song.header("AUDIO") is None


def test_restart_does_not_download_again(world, monkeypatch):
    _song(world)
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")  # скачивание упало бы
    job = _enqueue(world, saved=b"ID3SAVED-AUDIO")
    world.run(gpu=NO_GPU)
    assert world.jobs.get(job.id).state == "done", world.jobs.get(job.id).error
    assert (world.out / DIR / f"{STEM}.mp3").read_bytes() == b"ID3SAVED-AUDIO"
    assert "Звук уже скачан" in world.log(job.id)


def test_dead_link_fails_with_reason(world, monkeypatch):
    _song(world)
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")
    job = _enqueue(world)
    world.run(gpu=NO_GPU)
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and "YouTube не отдал звук" in failed.error
    assert not (world.out / DIR / f"{STEM}.mp3").exists()
