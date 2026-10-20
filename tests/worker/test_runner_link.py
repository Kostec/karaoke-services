"""Шов 3: generate по ссылке на музыку (inputs.audio_url) — yt-dlp и Яндекс Музыка фейковые."""

import json
import sys
import time
from pathlib import Path

import pytest
from karaoke_core import musiclink, naming
from karaoke_core.db import Jobs, Settings, connect
from karaoke_core.paths import INPUT_LYRICS

FIX = Path(__file__).resolve().parent / "fixtures"
ARTIST, TITLE = "Тестовая Группа", "Песня Ёлки"
DIR = "Тестовая Группа/Тестовая Группа - Песня Ёлки"
BASE = "Тестовая Группа - Песня Ёлки"
YT = "https://www.youtube.com/watch?v=abcdefghijk"
YM = "https://music.yandex.ru/album/40620828/track/148124289"
YM_KEY = "ym-secret-0123456789abcdef"
JPG = b"\xff\xd8\xff\xe0OWN-COVER"


@pytest.fixture(autouse=True)
def _fakes(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_CMD", f"{sys.executable} {FIX / 'fake_ytdlp.py'}")
    monkeypatch.setenv("MUSICLINK_CMD", f"{sys.executable} {FIX / 'fake_musiclink.py'}")
    monkeypatch.setenv("FAKE_MUSICLINK_TRACE", str(tmp_path / "musiclink.json"))
    for key in ("FAKE_YTDLP_MODE", "FAKE_MUSICLINK_MODE", "YANDEX_MUSIC_TOKEN"):
        monkeypatch.delenv(key, raising=False)


def enqueue_link(world, url: str, *, cover: bool = False):
    rel_dir = naming.song_dir(ARTIST, TITLE)
    params = {"whisper_model": "large-v2", "language": "ru", "compute_type": "int8", "batch_size": 4,
              "align_model": "jonatasgrosman/wav2vec2-large-xlsr-53-russian", "vad_onset": None, "vad_offset": None, "demucs_model": "htdemucs",
              "keep_debug": False, "rel_dir": rel_dir, "replace": False, "replace_rel_dir": None,
              "target_id": world.storage.target_id, "source": "link"}

    def make(job_id: int) -> dict:
        d = world.paths.job_in(rel_dir, job_id)
        d.mkdir(parents=True)
        (d / INPUT_LYRICS).write_text("Ёлка\nпесня", "utf-8")
        inputs = {"dir": world.paths.rel(d), "lyrics": world.paths.rel(d / INPUT_LYRICS), "audio_url": url}
        if cover:
            (d / "cover.jpg").write_bytes(JPG)
            inputs["cover"] = world.paths.rel(d / "cover.jpg")
        return {**params, "inputs": inputs}

    return world.jobs.enqueue_with("generate", {"artist": ARTIST, "title": TITLE}, make)


def restart(world, failed):
    return world.jobs.enqueue(failed.type, failed, failed.params, parent_id=failed.id)  # как web restart


def _wait(cond, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _alive(name: bytes) -> bool:
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if name in cmdline.read_bytes():
                return True
        except OSError:
            pass
    return False


# ---------------------------------------------------------------------------- yt-dlp

def test_generate_from_ytdlp_link_with_thumbnail(world):
    job = enqueue_link(world, YT)
    world.run()

    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    assert b"YT-THUMB" in (world.out / DIR / f"{BASE} [CO].jpg").read_bytes()
    source = world.paths.source(DIR)
    assert b"YT-AUDIO " + YT.encode() in (source / "input.mp3").read_bytes()
    assert b"YT-THUMB" in (source / "cover.jpg").read_bytes()
    log = world.log(job.id)
    ytdlp = [ln for ln in log.splitlines() if ln.startswith("$ ") and "fake_ytdlp.py" in ln]
    assert len(ytdlp) == 1 and " -4 " in ytdlp[0] and "--write-thumbnail" in ytdlp[0]
    assert not world.paths.job(DIR, job.id).exists()


def test_ytdlp_link_with_own_cover_skips_thumbnail(world):
    job = enqueue_link(world, YT, cover=True)
    world.run()

    assert world.jobs.get(job.id).state == "done"
    assert b"OWN-COVER" in (world.out / DIR / f"{BASE} [CO].jpg").read_bytes()
    assert "--write-thumbnail" not in world.log(job.id)


def test_ytdlp_link_failure_message(world, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")
    job = enqueue_link(world, YT)
    world.run()

    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error.startswith("Не удалось скачать звук по ссылке: [youtube] abcdefghijk: Video unavailable")
    assert "Последние строки лога:" in failed.error
    assert not (world.out / DIR).exists()
    assert not (world.paths.job(DIR, job.id) / "in" / "input.mp3").exists()


def test_restart_after_download_does_not_download_again(world, monkeypatch):
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "fail")  # звук скачан, упало на подготовке
    job = enqueue_link(world, YT)
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    in_dir = world.paths.job(DIR, job.id) / "in"
    assert (in_dir / "input.mp3").is_file() and (in_dir / "cover.jpg").is_file()

    monkeypatch.setenv("FAKE_FFMPEG_MODE", "")
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")  # повторная загрузка уронила бы задание
    again = restart(world, failed)
    world.run()
    assert (world.jobs.get(again.id).state, world.jobs.get(again.id).error) == ("done", None)
    assert "fake_ytdlp.py" not in world.log(again.id)
    assert b"YT-THUMB" in (world.out / DIR / f"{BASE} [CO].jpg").read_bytes()


def test_vk_audio_link_is_rejected(world):
    job = enqueue_link(world, "https://vk.com/audio-2001_123")
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error == musiclink.MSG_VK_AUDIO


# ---------------------------------------------------------------------------- Яндекс Музыка

def test_generate_from_yandex_link_passes_key_only_in_env(world, tmp_path):
    Settings(world.conn).set_yandex(YM_KEY)
    job = enqueue_link(world, YM)
    world.run()

    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    assert b"YM-AUDIO " in (world.paths.source(DIR) / "input.mp3").read_bytes()
    trace = json.loads((tmp_path / "musiclink.json").read_text("utf-8"))
    assert trace["has_key"] and trace["key"] == YM_KEY
    assert trace["argv"][:2] == ["download", musiclink.classify(YM).url]
    assert trace["argv"][2].endswith("/input.mp3")
    assert YM_KEY not in " ".join(trace["argv"])
    log = world.log(job.id)
    assert YM_KEY not in log
    assert "fake_musiclink.py download" in log


def test_key_printed_by_downloader_is_masked_in_log(world, monkeypatch):
    monkeypatch.setenv("FAKE_MUSICLINK_MODE", "echo")
    Settings(world.conn).set_yandex(YM_KEY)
    job = enqueue_link(world, YM)
    world.run()

    assert world.jobs.get(job.id).state == "done"
    log = world.log(job.id)
    assert YM_KEY not in log and "debug key ***" in log


def test_yandex_without_key_fails_without_subprocess(world, tmp_path):
    job = enqueue_link(world, YM)
    world.run()

    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error == "Впишите токен Яндекс Музыки в Настройках"
    assert not (tmp_path / "musiclink.json").exists()


def test_yandex_download_failure_shows_last_stderr_line(world, monkeypatch):
    monkeypatch.setenv("FAKE_MUSICLINK_MODE", "fail")
    Settings(world.conn).set_yandex(YM_KEY)
    job = enqueue_link(world, YM)
    world.run()

    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error.startswith(
        "Яндекс Музыка не отдала трек: нужна подписка Плюс (и, возможно, российский IP)\n\n")
    assert YM_KEY not in failed.error
    assert not (world.paths.job(DIR, job.id) / "in" / "input.mp3").exists()
    assert not (world.out / DIR).exists()


def test_cancel_during_yandex_download_kills_it_and_keeps_input(world, monkeypatch):
    monkeypatch.setenv("FAKE_MUSICLINK_MODE", "hang")
    Settings(world.conn).set_yandex(YM_KEY)
    job = enqueue_link(world, YM)
    web = Jobs(connect(world.paths.db))
    t = world.run_in_thread()
    assert _wait(lambda: web.get(job.id).stage == "Загрузка звука"), "нет этапа «Загрузка звука»"
    assert _wait(lambda: _alive(b"fake_musiclink.py")), "загрузчик не запущен"
    web.request_cancel(job.id)
    assert _wait(lambda: web.get(job.id).state == "cancelled"), "не отменено за 15 с"
    t.join(15)
    assert sorted(p.name for p in world.paths.job(DIR, job.id).iterdir()) == ["in"]
    assert _wait(lambda: not _alive(b"fake_musiclink.py"), timeout=2), "загрузчик жив после отмены"
