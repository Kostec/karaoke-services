"""Шов 3: задание «Импорт» (истории 15, 18–23) — yt-dlp и ffmpeg фейковые, без сети и GPU."""

import json
import sys
import time
from pathlib import Path

import pytest
from karaoke_core.db import STAGE_PUBLISH, Jobs, connect, song_id_for

FIX = Path(__file__).resolve().parent / "fixtures"
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 64

GPU_OFF = {"ok": False, "name": None, "vram_mb": None, "error": "нет GPU (тест)"}
ARTIST, TITLE = "Группа", "Песня"
REL_DIR = "Группа/Группа - Песня"
BASE = "Группа - Песня"
YT = "https://www.youtube.com/watch?v=abcdefghijk"
ALT1 = "https://www.youtube.com/watch?v=alternativ1"
ALT2 = "https://youtu.be/alternativ2"

SONG_TXT = (
    "#TITLE:Песня (оригинал)\r\n#ARTIST:Группа\r\n#MP3:orig.mp3\r\n#AUDIO:orig.mp3\r\n"
    "#VIDEO:orig.mp4\r\n#BACKGROUND:bg.jpg\r\n#COVER:orig.jpg\r\n#BPM:300\r\n#GAP:1000\r\n"
    ": 0 4 5 Ёл\r\n: 4 4 5 ка\r\n- 10\r\n: 12 4 5 пес\r\nE\r\n"
).encode("utf-8")
JPG = b"\xff\xd8\xff\xe0OWN-COVER"


@pytest.fixture(autouse=True)
def _ytdlp(monkeypatch):
    monkeypatch.setenv("YTDLP_CMD", f"{sys.executable} {FIX / 'fake_ytdlp.py'}")
    for key in ("FAKE_YTDLP_MODE", "FAKE_YTDLP_DEAD", "FAKE_YTDLP_SEARCH"):
        monkeypatch.delenv(key, raising=False)


def read_json(path):
    return json.loads(Path(path).read_text("utf-8"))


def enqueue_import(world, *, source="files", audio: tuple[str, bytes] | None = ("input.mp3", MP3),
                   cover: bool = True, youtube_url=None, instrumental=False, txt: bytes = SONG_TXT,
                   video_file: tuple[str, bytes] | None = None, **extra):
    params = {"source": source, "youtube_url": youtube_url, "instrumental": instrumental,
              "rel_dir": REL_DIR, "replace": False, "replace_rel_dir": None,
              "target_id": world.storage.target_id, **extra}

    def make(job_id: int) -> dict:
        d = world.paths.job_in(REL_DIR, job_id)
        d.mkdir(parents=True)
        (d / "song.txt").write_bytes(txt)
        inputs = {"dir": world.paths.rel(d), "txt": world.paths.rel(d / "song.txt")}
        if audio is not None:
            (d / audio[0]).write_bytes(audio[1])
            inputs["audio"] = world.paths.rel(d / audio[0])
        if cover:
            (d / "cover.jpg").write_bytes(JPG)
            inputs["cover"] = world.paths.rel(d / "cover.jpg")
        if video_file is not None:
            (d / video_file[0]).write_bytes(video_file[1])
            inputs["video"] = world.paths.rel(d / video_file[0])
        return {**params, "inputs": inputs}

    return world.jobs.enqueue_with("import", {"artist": ARTIST, "title": TITLE}, make)


def headers(txt: bytes) -> dict[str, str]:
    out = {}
    for line in txt.decode("utf-8").splitlines():
        if line.startswith("#") and ":" in line:
            k, _, v = line[1:].partition(":")
            out[k] = v
    return out


def song_files(world) -> set[str]:
    d = world.out / REL_DIR
    return {p.name for p in d.iterdir()} if d.is_dir() else set()


def test_import_from_mp3_file_without_gpu(world):
    job = enqueue_import(world, source="usdb", usdb_id=12345)
    world.run(gpu=GPU_OFF)

    done = world.jobs.get(job.id)
    assert (done.state, done.error, done.percent) == ("done", None, 100)
    assert song_files(world) == {f"{BASE}.txt", f"{BASE}.mp3", f"{BASE} [CO].jpg"}
    h = headers((world.out / REL_DIR / f"{BASE}.txt").read_bytes())
    assert h["AUDIO"] == h["MP3"] == f"{BASE}.mp3"
    assert h["COVER"] == f"{BASE} [CO].jpg"
    assert (h["ARTIST"], h["TITLE"]) == (ARTIST, TITLE)
    assert "VIDEO" not in h and "BACKGROUND" not in h
    assert (world.out / REL_DIR / f"{BASE}.mp3").read_bytes() == b"AUDIO-ONLY " + MP3  # один аудиопоток
    assert (world.out / REL_DIR / f"{BASE} [CO].jpg").read_bytes() == JPG
    # source/ — исходный .txt, input.mp3, обложка и params.json с источником (история 23)
    source = world.paths.source(REL_DIR)
    assert (source / "song.txt").read_bytes() == SONG_TXT
    assert (source / "input.mp3").read_bytes() == MP3
    assert (source / "cover.jpg").read_bytes() == JPG
    params = read_json(source / "params.json")
    assert (params["source"], params["usdb_id"], params["artist"]) == ("usdb", 12345, ARTIST)
    assert world.jobs.list(10) == [world.jobs.get(job.id)]  # минусовка не заказана
    assert not world.paths.job(REL_DIR, job.id).exists()


def _wait(cond, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_import_ogg_is_converted_to_mp3(world):
    job = enqueue_import(world, audio=("audio.ogg", b"OggS-FAKE"), cover=False)
    world.run(gpu=GPU_OFF)

    assert world.jobs.get(job.id).state == "done"
    mp3 = (world.out / REL_DIR / f"{BASE}.mp3").read_bytes()
    assert mp3.startswith(b"ID3") and b"FAKE-MP3 OggS-FAKE" in mp3  # libmp3lame, не копия потока
    assert song_files(world) == {f"{BASE}.txt", f"{BASE}.mp3"}  # без обложки — не ошибка
    assert "COVER" not in headers((world.out / REL_DIR / f"{BASE}.txt").read_bytes())
    source = world.paths.source(REL_DIR)
    assert (source / "input.mp3").read_bytes() == mp3  # перегенерации нужен mp3
    assert read_json(source / "params.json")["source"] == "files"


def test_import_from_youtube_with_thumbnail_cover(world):
    job = enqueue_import(world, source="url", audio=None, cover=False, youtube_url=YT)
    world.run(gpu=GPU_OFF)

    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    assert song_files(world) == {f"{BASE}.txt", f"{BASE}.mp3", f"{BASE} [CO].jpg"}
    assert (world.out / REL_DIR / f"{BASE}.mp3").read_bytes().endswith(b"YT-AUDIO " + YT.encode())
    assert b"YT-THUMB" in (world.out / REL_DIR / f"{BASE} [CO].jpg").read_bytes()
    source = world.paths.source(REL_DIR)
    assert b"YT-AUDIO" in (source / "input.mp3").read_bytes()
    assert b"YT-THUMB" in (source / "cover.jpg").read_bytes()
    assert "--no-playlist" in world.log(job.id)


def test_youtube_failure_message_and_restart(world, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")
    monkeypatch.setenv("FAKE_YTDLP_SEARCH", json.dumps([{"id": "found000001", "title": "x", "duration": 10}]))
    # своя ссылка пользователя: ни запасных ссылок, ни поиска — только сообщение
    job = enqueue_import(world, source="url", audio=None, cover=False, youtube_url=YT,
                         youtube_from_user=True, youtube_alternatives=[ALT1])
    world.run(gpu=GPU_OFF)

    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error.startswith("YouTube не отдал звук: [youtube] abcdefghijk: Video unavailable")
    log = world.log(job.id)
    assert ALT1 not in log and "ytsearch" not in log and "недоступна" not in log
    assert "Последние строки лога:" in failed.error
    assert not (world.out / REL_DIR).exists()
    assert (world.paths.job(REL_DIR, job.id) / "in" / "song.txt").is_file()

    monkeypatch.setenv("FAKE_YTDLP_MODE", "")
    again = world.jobs.enqueue(failed.type, failed, failed.params, parent_id=failed.id)  # как web restart
    world.run(gpu=GPU_OFF)
    assert world.jobs.get(again.id).state == "done"
    assert (world.out / REL_DIR / f"{BASE}.mp3").is_file()


def test_cancel_during_download_kills_ytdlp_and_keeps_input(world, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "hang")
    job = enqueue_import(world, source="url", audio=None, youtube_url=YT)
    web = Jobs(connect(world.paths.db))
    t = world.run_in_thread(gpu=GPU_OFF)
    assert _wait(lambda: web.get(job.id).stage == "Загрузка звука"), "нет этапа «Загрузка звука»"
    web.request_cancel(job.id)
    assert _wait(lambda: web.get(job.id).state == "cancelled"), "не отменено за 15 с"
    t.join(15)
    assert sorted(p.name for p in world.paths.job(REL_DIR, job.id).iterdir()) == ["in"]
    assert _wait(lambda: not _ytdlp_alive(), timeout=2), "yt-dlp жив после отмены"


def _ytdlp_alive() -> bool:
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if b"fake_ytdlp.py" in cmdline.read_bytes():
                return True
        except OSError:
            pass
    return False


def test_replace_existing_song_moves_old_to_trash(world):
    old = world.out / REL_DIR
    old.mkdir(parents=True)
    (old / f"{BASE}.txt").write_bytes(b"#TITLE:old\n#ARTIST:old\n#MP3:old.mp3\n: 0 1 1 a\nE\n")
    (old / "old.mp3").write_bytes(MP3)
    job = enqueue_import(world, replace=True, replace_rel_dir=REL_DIR)
    world.run(gpu=GPU_OFF)

    assert world.jobs.get(job.id).state == "done"
    assert song_files(world) == {f"{BASE}.txt", f"{BASE}.mp3", f"{BASE} [CO].jpg"}
    assert [i.kind for i in world.trash.list()] == ["song"]


def test_instrumental_is_queued_after_publish_and_waits_for_gpu(world):
    job = enqueue_import(world, instrumental=True)
    world.run(gpu=GPU_OFF, until=lambda: world.jobs.get(job.id).state in ("done", "failed"))

    assert world.jobs.get(job.id).state == "done"
    inst = [j for j in world.jobs.list(10) if j.type == "instrumental"]
    assert len(inst) == 1
    assert (inst[0].state, inst[0].parent_id) == ("queued", job.id)
    assert inst[0].params == {"rel_dir": REL_DIR, "txt_name": f"{BASE}.txt", "audio": f"{BASE}.mp3",
                              "instrumental": None, "replace": False,
                              "target_id": world.storage.target_id}
    assert (inst[0].artist, inst[0].title) == (ARTIST, TITLE)
    assert inst[0].song_id == song_id_for(world.storage.target_id, REL_DIR)

    world.run()  # с GPU минусовка выполняется (фейковый demucs)
    assert world.jobs.get(inst[0].id).state == "done"
    assert (world.out / REL_DIR / f"{BASE} [Instrumental].mp3").is_file()


def test_publish_failure_then_republish_import(world):
    world.storage_ok = False
    job = enqueue_import(world, instrumental=True)
    world.run(gpu=GPU_OFF)
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and failed.stage == STAGE_PUBLISH
    assert [j.type for j in world.jobs.list(10)] == ["import"]  # минусовка не поставлена

    world.storage_ok = True
    params = {**failed.params, "source_job_id": failed.id}  # так ставит web (republish)
    again = world.jobs.enqueue("publish", failed, params, parent_id=failed.id)
    world.run(gpu=GPU_OFF, until=lambda: world.jobs.get(again.id).state in ("done", "failed"))
    assert world.jobs.get(again.id).state == "done"
    assert (world.out / REL_DIR / f"{BASE}.txt").is_file()
    assert read_json(world.paths.source(REL_DIR) / "params.json")["source"] == "files"
    assert [j.type for j in world.jobs.list(10)].count("instrumental") == 1


def test_worker_start_removes_stale_import_staging(world):
    import os

    from karaoke_worker import runner

    old, fresh = world.paths.import_dir("oldtoken"), world.paths.import_dir("freshtoken")
    for d in (old, fresh):
        d.mkdir(parents=True)
        (d / "meta.json").write_text("{}", "utf-8")
    two_hours_ago = time.time() - 2 * 3600
    os.utime(old, (two_hours_ago, two_hours_ago))
    runner.startup(world.ctx, gpu_check=lambda: dict(GPU_OFF))
    assert not old.exists()
    assert (fresh / "meta.json").is_file()


def test_restart_after_prepare_failure_reuses_downloaded_audio_and_thumbnail(world, monkeypatch):
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "fail")  # звук скачан, «Подготовка» падает
    job = enqueue_import(world, source="url", audio=None, cover=False, youtube_url=YT)
    world.run(gpu=GPU_OFF)
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and failed.stage == "Подготовка"
    in_dir = world.paths.job(REL_DIR, job.id) / "in"
    assert b"YT-AUDIO" in (in_dir / "input.mp3").read_bytes()

    monkeypatch.setenv("FAKE_FFMPEG_MODE", "")
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")  # повторная загрузка уронила бы задание
    again = world.jobs.enqueue(failed.type, failed, failed.params, parent_id=failed.id)  # как web restart
    world.run(gpu=GPU_OFF)
    assert (world.jobs.get(again.id).state, world.jobs.get(again.id).error) == ("done", None)
    assert "fake_ytdlp.py" not in world.log(again.id)
    assert (world.out / REL_DIR / f"{BASE}.mp3").read_bytes().endswith(b"YT-AUDIO " + YT.encode())
    assert b"YT-THUMB" in (world.out / REL_DIR / f"{BASE} [CO].jpg").read_bytes()


def test_youtube_with_own_cover_does_not_request_thumbnail(world):
    job = enqueue_import(world, source="url", audio=None, cover=True, youtube_url=YT)
    world.run(gpu=GPU_OFF)

    assert world.jobs.get(job.id).state == "done"
    log = world.log(job.id)
    assert "fake_ytdlp.py" in log and "--write-thumbnail" not in log
    assert (world.out / REL_DIR / f"{BASE} [CO].jpg").read_bytes() == JPG


# ------------------------------------------------------------ ролик песни удалён с YouTube

# конец последней ноты: GAP 1000 + 3980 бит × 60000 / (300 × 4) = 200 000 мс (3:20)
LONG_TXT = (
    "#TITLE:Песня\n#ARTIST:Группа\n#MP3:orig.mp3\n#BPM:300\n#GAP:1000\n"
    ": 0 4 5 Раз\n- 10\n: 3970 10 5 конец\nE\n"
).encode("utf-8")
CANDIDATES = [
    {"id": "short000001", "url": "https://www.youtube.com/watch?v=short000001", "title": "Короткий", "duration": 150},
    {"id": "live0000001", "url": "https://www.youtube.com/watch?v=live0000001", "title": "Эфир", "duration": None},
    {"id": "long0000001", "url": "https://www.youtube.com/watch?v=long0000001", "title": "Длинный", "duration": 260},
    {"id": "tiefirst001", "url": "https://www.youtube.com/watch?v=tiefirst001", "title": "Первый", "duration": 202},
    {"id": "tiesecond01", "title": "Второй", "duration": 198.0},  # ≥ конец нот − 2 с, та же разница, но второй
]


def test_dead_song_link_falls_back_to_next_song_link(world, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_DEAD", "abcdefghijk,alternativ1")
    job = enqueue_import(world, source="usdb", audio=None, cover=False, youtube_url=YT,
                         youtube_from_user=False, youtube_alternatives=[ALT1, ALT2])
    world.run(gpu=GPU_OFF)

    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    assert (world.out / REL_DIR / f"{BASE}.mp3").read_bytes().endswith(b"YT-AUDIO " + ALT2.encode())
    log = world.log(job.id)
    assert f"Ссылка из песни недоступна — беру {ALT1}" in log
    assert f"Ссылка из песни недоступна — беру {ALT2}" in log
    assert "ytsearch" not in log
    assert b"YT-THUMB" in (world.out / REL_DIR / f"{BASE} [CO].jpg").read_bytes()


def test_all_song_links_dead_search_picks_video_by_song_length(world, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_DEAD", "abcdefghijk,alternativ1")
    monkeypatch.setenv("FAKE_YTDLP_SEARCH", json.dumps(CANDIDATES))
    job = enqueue_import(world, source="usdb", audio=None, cover=False, youtube_url=YT, txt=LONG_TXT,
                         youtube_from_user=False, youtube_alternatives=[ALT1])
    world.run(gpu=GPU_OFF)

    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    mp3 = (world.out / REL_DIR / f"{BASE}.mp3").read_bytes()
    assert mp3.endswith(b"YT-AUDIO https://www.youtube.com/watch?v=tiefirst001")
    log = world.log(job.id)
    assert "ytsearch5:Группа - Песня" in log and "--flat-playlist" in log
    assert "Найден ролик «Первый» (3:22) — ноты сделаны под другую запись, слова могут разъехаться" in log
    assert '"entries"' not in log  # JSON поиска в лог не пишется
    assert (world.paths.source(REL_DIR) / "input.mp3").read_bytes().endswith(b"v=tiefirst001")


def test_search_skips_dead_best_candidate(world, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_DEAD", "abcdefghijk,tiefirst001")
    monkeypatch.setenv("FAKE_YTDLP_SEARCH", json.dumps(CANDIDATES))
    job = enqueue_import(world, source="usdb", audio=None, cover=False, youtube_url=YT, txt=LONG_TXT)
    world.run(gpu=GPU_OFF)

    assert world.jobs.get(job.id).state == "done"
    assert (world.out / REL_DIR / f"{BASE}.mp3").read_bytes().endswith(
        b"YT-AUDIO https://www.youtube.com/watch?v=tiesecond01")


@pytest.mark.parametrize("mode, reason", [("forbidden", "HTTP Error 403"),
                                          ("network", "Temporary failure in name resolution")])
def test_forbidden_or_network_error_is_not_a_reason_to_substitute(world, monkeypatch, mode, reason):
    monkeypatch.setenv("FAKE_YTDLP_MODE", mode)
    monkeypatch.setenv("FAKE_YTDLP_SEARCH", json.dumps(CANDIDATES))
    job = enqueue_import(world, source="usdb", audio=None, cover=False, youtube_url=YT, txt=LONG_TXT,
                         youtube_from_user=False, youtube_alternatives=[ALT1])
    world.run(gpu=GPU_OFF)

    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error.startswith("YouTube не отдал звук: ") and reason in failed.error
    log = world.log(job.id)
    assert ALT1 not in log and "ytsearch" not in log and "недоступна" not in log


def test_dead_link_and_nothing_found_message(world, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_DEAD", "abcdefghijk")
    monkeypatch.setenv("FAKE_YTDLP_SEARCH", json.dumps(CANDIDATES[:2]))  # короткий и без длительности
    job = enqueue_import(world, source="usdb", audio=None, cover=False, youtube_url=YT, txt=LONG_TXT)
    world.run(gpu=GPU_OFF)

    failed = world.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error == ("Ролик из песни удалён с YouTube, а поиск не нашёл подходящего — вставьте свою "
                            "ссылку или загрузите mp3 и перезапустите импорт")
    assert (world.paths.job(REL_DIR, job.id) / "in" / "song.txt").is_file()  # можно перезапустить


def test_rank_search_results_and_song_end():
    from karaoke_core import ultrastar
    from karaoke_worker.handlers import rank_search_results, song_end_ms

    assert song_end_ms(ultrastar.parse(LONG_TXT)) == 200000
    assert song_end_ms(ultrastar.parse(b"#BPM:300\n#RELATIVE:yes\n: 0 4 5 a\nE\n")) is None
    assert song_end_ms(ultrastar.parse(b"#TITLE:x\n: 0 4 5 a\nE\n")) is None  # нет #BPM
    ids = [e["id"] for e in rank_search_results(CANDIDATES, 200000)]
    assert ids == ["tiefirst001", "tiesecond01", "long0000001"]
    assert [e["id"] for e in rank_search_results(CANDIDATES, None)][0] == "short000001"
    assert rank_search_results([{"id": "x", "duration": True}, "мусор"], None) == []


# --------------------------------------------------------------------------- видео (истории 24–27)

def test_import_video_from_pack_replaces_old_video_headers(world):
    job = enqueue_import(world, video={"mode": "pack", "height": 720, "gap": -1.25},
                         video_file=("video.mkv", b"MKV-DATA"))
    world.run(gpu=GPU_OFF)
    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    assert song_files(world) == {f"{BASE}.txt", f"{BASE}.mp3", f"{BASE} [CO].jpg", f"{BASE}.mkv"}
    assert (world.out / REL_DIR / f"{BASE}.mkv").read_bytes() == b"MKV-DATA"
    h = headers((world.out / REL_DIR / f"{BASE}.txt").read_bytes())
    assert (h["VIDEO"], h["VIDEOGAP"]) == (f"{BASE}.mkv", "-1.25") and "BACKGROUND" not in h
    assert not list(world.paths.source(REL_DIR).glob("video.*"))  # в source/ видео не копируется


def test_import_video_by_link_after_audio(world):
    job = enqueue_import(world, video={"mode": "source", "url": YT, "height": 480})
    world.run(gpu=GPU_OFF)
    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    assert (world.out / REL_DIR / f"{BASE}.mp4").read_bytes().startswith(b"FAKE-MP4 " + YT.encode())
    h = headers((world.out / REL_DIR / f"{BASE}.txt").read_bytes())
    assert h["VIDEO"] == f"{BASE}.mp4" and "VIDEOGAP" not in h
    assert read_json(world.paths.source(REL_DIR) / "params.json")["video_url"] == YT


def test_import_video_failure_publishes_song_without_video(world, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "novideo")
    job = enqueue_import(world, video={"mode": "url", "url": YT, "height": 720})
    world.run(gpu=GPU_OFF)
    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    assert song_files(world) == {f"{BASE}.txt", f"{BASE}.mp3", f"{BASE} [CO].jpg"}
    assert "VIDEO" not in headers((world.out / REL_DIR / f"{BASE}.txt").read_bytes())
    log = world.log(job.id)
    assert "Видео не скачалось: " in log and ", песня выложена без видео" in log
