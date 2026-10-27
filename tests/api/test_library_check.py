"""Шов 2: проверка библиотеки — запуск и отчёт, исправление кодировки, задание «Звук по ссылке»."""

from __future__ import annotations

import json
from pathlib import Path

from karaoke_core import ultrastar
from karaoke_core.db import Settings, Target, connect

FIX = Path(__file__).resolve().parents[1] / "core" / "fixtures"
REL = "Artist/Artist - Song"
YT_ID = "abcdefghijk"


def _songs(client) -> list[dict]:
    assert client.post("/api/songs/rescan").status_code == 202
    return client.get("/api/songs").json()["items"]


def _put(env, client, txt: bytes, *, audio=True) -> dict:
    d = env.put_song(REL, txt, "Artist - Song")
    if not audio:
        (d / "Artist - Song.mp3").unlink()
    return next(i for i in _songs(client) if i["rel_dir"] == REL)


# ------------------------------------------------------------------ запуск и отчёт

def test_report_before_first_check(client):
    assert client.get("/api/library/check").json() == {"findings": None, "job": None}


def test_check_queues_one_job_and_second_is_409(client):
    r = client.post("/api/library/check", json={})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["type"] == "libcheck" and job["state"] == "queued" and job["params"]["target_ids"] is None
    r2 = client.post("/api/library/check", json={"target_ids": ["local"]})
    assert r2.status_code == 409 and r2.json()["detail"] == "Проверка уже идёт"
    got = client.get("/api/library/check").json()
    assert got["findings"] is None and got["job"]["id"] == job["id"]
    # перезапуск при идущей проверке — тоже 409
    client.app.state.ctx.jobs.update(job["id"], state="failed")
    assert client.post("/api/library/check").status_code == 201
    assert client.post(f"/api/jobs/{job['id']}/restart").status_code == 409


def test_check_selected_targets_and_unknown_is_400(env, client):
    pc = Settings(connect(env.data / "karaoke.sqlite")).save_target(Target(name="ПК", kind="local", path="/host/pc"))
    r = client.post("/api/library/check", json={"target_ids": ["nope"]})
    assert r.status_code == 400 and r.json()["field"] == "target_ids"
    r = client.post("/api/library/check", json={"target_ids": [pc.id]})
    assert r.status_code == 201 and r.json()["params"]["target_ids"] == [pc.id]
    assert "ПК" in r.json()["title"]


def test_report_is_served_with_dates(env, client):
    report = {"started_at": "2026-10-27T10:00:00Z", "finished_at": "2026-10-27T10:01:00Z", "job_id": 7,
              "target_ids": ["local"], "skipped": [], "findings": []}
    path = env.data / "reports" / "libcheck.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report), "utf-8")
    assert client.get("/api/library/check").json() == {**report, "job": None}


# ------------------------------------------------------------------ кодировка

def test_fix_encoding_writes_utf8_and_keeps_version_in_trash(env, client):
    koi8 = (FIX / "enc_koi8r.txt").read_bytes()
    song = _put(env, client, koi8)
    r = client.post(f"/api/songs/{song['song_id']}/encoding")
    assert r.status_code == 200, r.text
    written = (env.out / REL / "Artist - Song.txt").read_bytes()
    assert written == (FIX / "enc_utf8.txt").read_bytes()  # UTF-8 без BOM, те же строки
    assert r.json()["title"] == "Утренняя песня" and r.json()["artist"] == "Речной Трамвай"
    trash = client.get("/api/trash").json()
    assert len(trash) == 1 and trash[0]["kind"] == "version"
    again = client.post(f"/api/songs/{song['song_id']}/encoding")
    assert again.status_code == 409 and again.json()["detail"] == "Кодировка в порядке"


def test_fix_encoding_ok_file_is_409(env, client, song):
    r = client.post(f"/api/songs/{song['song_id']}/encoding")
    assert r.status_code == 409 and r.json()["detail"] == "Кодировка в порядке"
    assert client.get("/api/trash").json() == []


def test_fix_encoding_not_guessed_is_409_and_file_untouched(env, client):
    data = (FIX / "enc_replacement.txt").read_bytes()
    song = _put(env, client, data)
    r = client.post(f"/api/songs/{song['song_id']}/encoding")
    assert r.status_code == 409 and r.json()["detail"] == "Не удалось угадать кодировку"
    assert (env.out / REL / "Artist - Song.txt").read_bytes() == data
    assert client.get("/api/trash").json() == []


# ------------------------------------------------------------------ звук по ссылке #VIDEO

def _with_video(env, header: str) -> bytes:
    return ultrastar.set_header_line(env.SONG_TXT, "VIDEO", header)


def test_audio_job_from_youtube_link(env, client):
    song = _put(env, client, _with_video(env, f"v={YT_ID},co=cover.jpg"), audio=False)
    r = client.post("/api/jobs/audio", json={"song_id": song["song_id"]})
    assert r.status_code == 201, r.text
    job = r.json()
    p = job["params"]
    assert job["type"] == "audio" and job["song_id"] == song["song_id"]
    assert p["url"] == f"https://www.youtube.com/watch?v={YT_ID}"
    assert (p["rel_dir"], p["txt_name"], p["target_id"]) == (REL, "Artist - Song.txt", "local")
    assert p["inputs"]["dir"].endswith(f"/jobs/{job['id']}/in") and (env.data / p["inputs"]["dir"]).is_dir()
    dup = client.post("/api/jobs/audio", json={"song_id": song["song_id"]})
    assert dup.status_code == 409 and dup.json()["detail"] == "Эта песня уже в очереди"


def test_audio_job_without_youtube_link_is_409(env, client):
    song = _put(env, client, _with_video(env, "Artist - Song.mp4"), audio=False)
    r = client.post("/api/jobs/audio", json={"song_id": song["song_id"]})
    assert r.status_code == 409 and r.json()["detail"] == "В песне нет ссылки на видео YouTube"
    assert client.get("/api/jobs").json() == []


def test_audio_job_when_song_has_audio_is_409(env, client):
    song = _put(env, client, _with_video(env, f"https://youtu.be/{YT_ID}"))
    r = client.post("/api/jobs/audio", json={"song_id": song["song_id"]})
    assert r.status_code == 409 and r.json()["detail"] == "У песни уже есть звук"


def test_audio_restart_reuses_inputs(env, client):
    song = _put(env, client, _with_video(env, f"https://youtu.be/{YT_ID}"), audio=False)
    job = client.post("/api/jobs/audio", json={"song_id": song["song_id"]}).json()
    client.app.state.ctx.jobs.update(job["id"], state="failed")
    r = client.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 201, r.text
    assert r.json()["params"]["inputs"]["dir"] == job["params"]["inputs"]["dir"]
