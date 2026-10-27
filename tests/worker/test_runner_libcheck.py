"""Шов 3: задание libcheck (истории 34–43) — без GPU, отчёт reports/libcheck.json, недоступное — пропущено."""

from __future__ import annotations

import json
from pathlib import Path

from karaoke_core.db import Target, song_id_for
from karaoke_core.storage import StorageError

CORE_FIX = Path(__file__).resolve().parents[1] / "core" / "fixtures"
NO_GPU = {"ok": False, "name": None, "vram_mb": None, "error": "нет GPU (тест)"}
MP3 = b"ID3" + bytes(7) + b"\xff\xfb\x90\x00" * 16


def _txt(artist: str, title: str, extra: str = "") -> bytes:
    base = f"{artist} - {title}"
    return (f"#TITLE:{title}\n#ARTIST:{artist}\n#MP3:{base}.mp3\n#COVER:{base} [CO].jpg\n{extra}"
            "#BPM:300\n#GAP:0\n: 0 4 5 Ла\n: 4 4 5 ла\nE\n").encode("utf-8")


def _put(root: Path, artist: str, title: str, *, txt: bytes | None = None, audio=True, cover=True,
         extra_files: dict | None = None, extra: str = "") -> str:
    base = f"{artist} - {title}"
    rel = f"{artist}/{base}"
    d = root / artist / base
    d.mkdir(parents=True)
    (d / f"{base}.txt").write_bytes(txt or _txt(artist, title, extra))
    if audio:
        (d / f"{base}.mp3").write_bytes(MP3)
    if cover:
        (d / f"{base} [CO].jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg")
    for name, data in (extra_files or {}).items():
        (d / name).write_bytes(data)
    return rel


def _report(world) -> dict:
    return json.loads(world.paths.libcheck_report().read_text("utf-8"))


def _enqueue(world, target_ids=None):
    return world.jobs.enqueue("libcheck", {"artist": "Хранилища", "title": "все"}, {"target_ids": target_ids})


def test_libcheck_finds_all_kinds_without_gpu(world):
    pi = world.ctx.settings.save_target(Target(name="Pi", kind="local", path="/host/pi"))
    pi_root = world.tmp / pi.id
    _put(world.out, "Чистая", "Песня")
    no_audio = _put(world.out, "Без", "Звука", audio=False, extra="#VIDEO:v=abcdefghijk\n")
    no_cover = _put(world.out, "Без", "Обложки", cover=False)
    video = _put(world.out, "Видео", "Нет", extra="#VIDEO:Видео - Нет.mp4\n")
    url_video = _put(world.out, "Видео", "Ссылка", extra="#VIDEO:https://youtu.be/abcdefghijk\n")
    enc = _put(world.out, "Кодировка", "Битая", txt=(CORE_FIX / "enc_koi8r.txt").read_bytes())
    dup_a = _put(world.out, "Кино", "Группа крови")
    dup_b = _put(world.out, "Kино", "Группа крови!")
    shared = _put(world.out, "Общая", "Песня", extra_files={"Общая - Песня [Instrumental].mp3": MP3})
    _put(pi_root, "Общая", "Песня")
    _put(pi_root, "Без", "Звука")  # копия со звуком — «Взять из копии»
    job = _enqueue(world)
    world.run(gpu=NO_GPU)
    done = world.jobs.get(job.id)
    assert done.state == "done", done.error
    report = _report(world)
    assert report["job_id"] == job.id and report["skipped"] == []
    assert set(report["target_ids"]) == {"local", pi.id}
    assert report["started_at"] and report["finished_at"]
    by = {(f["kind"], f["rel_dir"]) for f in report["findings"]}
    local = "local"
    assert ("no_audio", no_audio) in by and ("no_cover", no_cover) in by
    assert ("video_missing", video) in by
    assert not any(rel == url_video for _, rel in by)  # ссылка в #VIDEO — не находка
    assert ("encoding", enc) in by
    assert ("duplicate", dup_a) in by or ("duplicate", dup_b) in by
    assert ("diverged", shared) in by
    na = next(f for f in report["findings"] if f["kind"] == "no_audio" and f["target_id"] == local)
    assert [x["action"] for x in na["fixes"]] == ["copy_from", "audio_from_video", "trash"]
    assert na["fixes"][0]["from_target"] == pi.id
    assert na["song_id"] == song_id_for(local, no_audio)
    # индекс обновлён — id находок открываются как песни
    assert world.ctx.library.find(na["song_id"]) is not None
    assert "Проверка «Pi»" in world.log(job.id) or "Проверка «Локальное" in world.log(job.id)


def test_unavailable_target_is_skipped_others_checked(world):
    dead = world.ctx.settings.save_target(Target(name="Мёртвое", kind="local", path="/host/dead"))
    factory = world.ctx.storage_factory

    def storage(target):
        if target.id == dead.id:
            raise StorageError("нет связи (тест)")
        return factory(target)

    world.ctx.storage_factory = storage
    rel = _put(world.out, "Без", "Обложки", cover=False)
    job = _enqueue(world)
    world.run(gpu=NO_GPU)
    assert world.jobs.get(job.id).state == "done"
    report = _report(world)
    assert report["target_ids"] == ["local"]
    assert [(s["target_id"], s["name"]) for s in report["skipped"]] == [(dead.id, "Мёртвое")]
    assert "нет связи" in report["skipped"][0]["error"]
    assert [(f["kind"], f["rel_dir"]) for f in report["findings"]] == [("no_cover", rel)]
    assert "Хранилище «Мёртвое» недоступно — пропущено" in world.log(job.id)


def test_selected_targets_only_and_clean_library(world):
    pi = world.ctx.settings.save_target(Target(name="Pi", kind="local", path="/host/pi"))
    _put(world.out, "Без", "Обложки", cover=False)  # в local — не проверяется
    _put(world.tmp / pi.id, "Чистая", "Песня")
    job = _enqueue(world, [pi.id])
    world.run(gpu=NO_GPU)
    report = _report(world)
    assert report["target_ids"] == [pi.id] and report["findings"] == []
    assert "Проблем не найдено" in world.log(job.id)
