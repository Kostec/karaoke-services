"""Задания: создание с валидацией, отмена, перезапуск, повторная выкладка, лог."""

import json

from karaoke_core.db import STAGE_PUBLISH, Jobs, connect

MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


def _gen(client, artist="Кино", title="Группа крови", audio=MP3, **form):
    files = {"audio": ("song.mp3", audio, "audio/mpeg")} if audio is not None else {}
    files.update(form.pop("files", {}))
    data = {"artist": artist, "title": title, **form}
    return client.post("/api/jobs/generate", data=data, files=files or None)


def _jobs(env):
    return Jobs(connect(env.data / "karaoke.sqlite"))


def test_generate_creates_queued_job_with_defaults_and_inputs(env, client):
    r = _gen(client, artist="  Кино ", title=" Группа крови ", lyrics="Тёплое место\nНо улицы ждут",
             params=json.dumps({"batch_size": 2}),
             files={"cover": ("c.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20, "image/png")})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["type"] == "generate" and job["state"] == "queued"
    assert (job["artist"], job["title"]) == ("Кино", "Группа крови")
    p = job["params"]
    assert p["whisper_model"] == "large-v2" and p["language"] == "ru" and p["compute_type"] == "int8"
    assert p["batch_size"] == 2
    assert p["align_model"] == "jonatasgrosman/wav2vec2-large-xlsr-53-russian"
    assert p["rel_dir"] == "Кино/Кино - Группа крови"
    assert p["inputs"]["dir"] == f"songs/Кино/Кино - Группа крови/jobs/{job['id']}/in"
    assert p["inputs"]["audio"] == p["inputs"]["dir"] + "/input.mp3"
    assert (env.data / p["inputs"]["audio"]).read_bytes() == MP3
    assert (env.data / p["inputs"]["lyrics"]).read_text("utf-8") == "Тёплое место\nНо улицы ждут"
    assert p["inputs"]["cover"] == p["inputs"]["dir"] + "/cover.png"
    assert not (env.data / "uploads").exists()
    assert client.get("/api/jobs").json()[0]["id"] == job["id"]


def test_generate_lyrics_file_in_cp1251(env, client):
    r = _gen(client, files={"lyrics_file": ("t.txt", "Привет, мир".encode("cp1251"), "text/plain")})
    assert r.status_code == 201
    assert (env.data / r.json()["params"]["inputs"]["lyrics"]).read_text("utf-8") == "Привет, мир"


def _lrc(text: str) -> dict:
    """LRC уходит файловой частью multipart (как из generateForm): лимит — 413, а не 400 Starlette."""
    return {"lyrics_lrc": ("lyrics.lrc", text.encode("utf-8"), "text/plain")}


LRC = "[00:01.00]Тёплое место\n[00:03.00]Но улицы ждут\n"


def test_generate_keeps_lrc_next_to_lyrics(env, client):
    assert client.get("/api/defaults").json()["defaults"]["lrc_timing"] is False
    r = _gen(client, lyrics="Тёплое место\nНо улицы ждут", files=_lrc(LRC),
             params=json.dumps({"lrc_timing": True}))
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["lrc_timing"] is True
    assert p["inputs"]["lrc"] == p["inputs"]["dir"] + "/lyrics.lrc"
    assert (env.data / p["inputs"]["lrc"]).read_bytes() == LRC.encode("utf-8")

    plain = _gen(client, title="Звезда", lyrics="текст").json()["params"]
    assert plain["lrc_timing"] is False and "lrc" not in plain["inputs"]


def test_generate_lrc_size_limit(client):
    r = _gen(client, lyrics="текст", files=_lrc("[00:01.00]" + "a" * (1024 * 1024)))
    assert r.status_code == 413 and r.json()["field"] == "lyrics_lrc"
    assert client.get("/api/jobs").json() == []


def test_restart_and_regen_take_lrc_from_previous_input(env, client):
    job = _gen(client, lyrics="Тёплое место\nНо улицы ждут", files=_lrc(LRC),
               params=json.dumps({"lrc_timing": True})).json()
    client.post(f"/api/jobs/{job['id']}/cancel")
    new = client.post(f"/api/jobs/{job['id']}/restart").json()
    assert (env.data / new["params"]["inputs"]["lrc"]).read_text("utf-8") == LRC
    client.post(f"/api/jobs/{new['id']}/cancel")

    # своя песня: вход лежит в source/ (воркер перенёс после успеха)
    from karaoke_core.db import Songs
    env.put_song("Кино/Кино - Группа крови", env.SONG_TXT, "Кино - Группа крови")
    Songs(connect(env.data / "karaoke.sqlite")).upsert(
        artist="Кино", title="Группа крови", rel_dir="Кино/Кино - Группа крови", params={"lrc_timing": True})
    src = env.data / "songs" / "Кино" / "Кино - Группа крови" / "source"
    src.mkdir(parents=True)
    (src / "input.mp3").write_bytes(MP3)
    (src / "lyrics.lrc").write_text(LRC, "utf-8")
    client.post("/api/songs/rescan")
    sid = client.get("/api/songs").json()["items"][0]["song_id"]
    regen = _gen(client, audio=None, lyrics="Тёплое место\nНо улицы ждут", song_id=sid,
                 params=json.dumps({"lrc_timing": True})).json()
    assert (env.data / regen["params"]["inputs"]["lrc"]).read_text("utf-8") == LRC
    client.post(f"/api/jobs/{regen['id']}/cancel")
    other = "[00:05.00]Другая\n"
    regen = _gen(client, audio=None, lyrics="Другая", files=_lrc(other), song_id=sid).json()
    assert (env.data / regen["params"]["inputs"]["lrc"]).read_text("utf-8") == other


def test_regen_empty_lrc_part_drops_saved_lrc_absent_part_keeps_it(env, client):
    from karaoke_core.db import Songs
    env.put_song("Кино/Кино - Группа крови", env.SONG_TXT, "Кино - Группа крови")
    Songs(connect(env.data / "karaoke.sqlite")).upsert(
        artist="Кино", title="Группа крови", rel_dir="Кино/Кино - Группа крови", params={})
    src = env.data / "songs" / "Кино" / "Кино - Группа крови" / "source"
    src.mkdir(parents=True)
    (src / "input.mp3").write_bytes(MP3)
    (src / "lyrics.lrc").write_text(LRC, "utf-8")
    client.post("/api/songs/rescan")
    sid = client.get("/api/songs").json()["items"][0]["song_id"]
    text = "Тёплое место\nНо улицы ждут"
    dropped = _gen(client, audio=None, lyrics=text, files=_lrc(""), song_id=sid).json()
    assert "lrc" not in dropped["params"]["inputs"]
    client.post(f"/api/jobs/{dropped['id']}/cancel")
    kept = _gen(client, audio=None, lyrics=text, song_id=sid).json()
    assert (env.data / kept["params"]["inputs"]["lrc"]).read_text("utf-8") == LRC


def test_generate_validation_errors(env, client):
    r = _gen(client, artist=" ")
    assert r.status_code == 400 and r.json()["detail"] == "Укажите исполнителя и название"
    r = _gen(client, audio=b"<html>not mp3</html>")
    assert r.status_code == 400 and r.json()["detail"] == "Это не mp3-файл"
    r = _gen(client, audio=None)
    assert r.status_code == 400 and r.json()["detail"] == "Загрузите mp3-файл"
    r = _gen(client, audio=MP3 + b"\x00" * (1024 * 1024 + 1))
    assert r.status_code == 413 and r.json()["detail"] == "Файл больше 1 МБ"
    r = _gen(client, params=json.dumps({"compute_type": "float16"}))
    assert r.status_code == 400 and "int8" in r.json()["detail"]
    r = _gen(client, params="{oops")
    assert r.status_code == 400 and r.json()["detail"] == "Параметры должны быть JSON-объектом"
    r = _gen(client, files={"cover": ("c.gif", b"GIF89a....", "image/gif")})
    assert r.status_code == 400 and r.json()["detail"] == "Обложка должна быть в формате jpg, png или webp"
    r = _gen(client, files={"lyrics_file": ("t.txt", b"a" * (1024 * 1024 + 1), "text/plain")})
    assert r.status_code == 413 and r.json()["detail"] == "Файл больше 1 МБ"
    assert client.get("/api/jobs").json() == []
    # неудачные попытки не оставляют загрузок в томе
    leftovers = [p for p in (env.data / "songs").rglob("*") if p.is_file()] if (env.data / "songs").exists() else []
    assert leftovers == []


def test_validation_errors_name_the_field(client):
    """Ошибка проверки поля несёт машиночитаемое имя поля формы — клиент подсвечивает его."""
    cases = [
        (dict(artist=" "), "artist"),
        (dict(title=""), "title"),
        (dict(audio=b"<html>not mp3</html>"), "audio"),
        (dict(audio=None), "audio"),
        (dict(audio=MP3 + b"\x00" * (1024 * 1024 + 1)), "audio"),
        (dict(files={"cover": ("c.gif", b"GIF89a....", "image/gif")}), "cover"),
        (dict(files={"lyrics_file": ("t.txt", b"a" * (1024 * 1024 + 1), "text/plain")}), "lyrics"),
        (dict(params=json.dumps({"compute_type": "float16"})), "compute_type"),
        (dict(params=json.dumps({"batch_size": 0})), "batch_size"),
        (dict(params=json.dumps({"vad_onset": 5})), "vad_onset"),
        (dict(params=json.dumps({"whisper_model": "huge"})), "whisper_model"),
        (dict(params=json.dumps({"demucs_model": "x"})), "demucs_model"),
        (dict(params=json.dumps({"language": ""})), "language"),
    ]
    for form, field in cases:
        r = _gen(client, **form)
        assert r.status_code in (400, 413), form
        assert r.json().get("field") == field, (form, r.json())


def test_duplicate_in_queue_is_rejected(client):
    assert _gen(client, artist="Кино", title="Группа крови").status_code == 201
    r = _gen(client, artist="КИНО", title="группа крови ")
    assert r.status_code == 409 and r.json()["detail"] == "Эта песня уже в очереди"


def test_existing_song_needs_replace(env, client, song):
    r = _gen(client, artist="artist", title="SONG")
    assert r.status_code == 409
    assert r.json() == {"detail": "Такая песня уже есть в папке результата", "song_id": song["song_id"]}
    r = _gen(client, artist="Artist", title="Song", replace="true")
    assert r.status_code == 201
    assert r.json()["params"]["replace_rel_dir"] == "Artist/Artist - Song"


def test_regenerate_foreign_song_needs_lyrics_and_takes_audio_from_folder(env, client, song):
    r = _gen(client, artist="Artist", title="Song", audio=None, song_id=song["song_id"])
    assert r.status_code == 400 and r.json()["detail"] == "Для чужой песни нужен текст"
    r = _gen(client, artist="Artist", title="Song", audio=None, song_id=song["song_id"], lyrics="При вет")
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["song_id"] == song["song_id"]
    assert (env.data / job["params"]["inputs"]["audio"]).read_bytes() == MP3
    assert job["params"]["replace_rel_dir"] == "Artist/Artist - Song"


def test_instrumental(client, song):
    r = client.post("/api/jobs/instrumental", json={"song_id": song["song_id"]})
    assert r.status_code == 201
    job = r.json()
    assert job["type"] == "instrumental" and job["params"]["audio"] == "Artist - Song.mp3"
    assert job["params"]["rel_dir"] == "Artist/Artist - Song"
    r = client.post("/api/jobs/instrumental", json={"song_id": song["song_id"]})
    assert r.status_code == 409 and r.json()["detail"] == "Эта песня уже в очереди"
    r = client.post("/api/jobs/instrumental", json={"song_id": "nope"})
    assert r.status_code == 404 and r.json()["detail"] == "Песня не найдена"


def test_cancel_restart(env, client):
    job = _gen(client, lyrics="текст").json()
    r = client.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 409 and r.json()["detail"] == "Перезапустить можно только завершённое задание"
    r = client.post(f"/api/jobs/{job['id']}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    r = client.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 201
    new = r.json()
    assert new["id"] != job["id"] and new["state"] == "queued" and new["parent_id"] == job["id"]
    strip = lambda p: {k: v for k, v in p.items() if k != "inputs"}  # noqa: E731
    assert strip(new["params"]) == strip(job["params"])
    assert new["params"]["inputs"]["dir"] == f"songs/Кино/Кино - Группа крови/jobs/{new['id']}/in"
    assert (env.data / new["params"]["inputs"]["audio"]).read_bytes() == MP3
    assert (env.data / new["params"]["inputs"]["lyrics"]).read_text("utf-8") == "текст"
    assert client.post("/api/jobs/999/cancel").json()["detail"] == "Задание не найдено"


def test_restart_falls_back_to_source_then_fails(env, client):
    import shutil
    job = _gen(client).json()
    _jobs(env).update(job["id"], state="done")
    song = env.data / "songs" / "Кино" / "Кино - Группа крови"
    (song / "source").mkdir(parents=True)
    shutil.move(str(song / "jobs" / str(job["id"]) / "in" / "input.mp3"), str(song / "source" / "input.mp3"))
    shutil.rmtree(song / "jobs" / str(job["id"]))  # воркер убрал рабочую папку после успеха
    r = client.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 201 and (env.data / r.json()["params"]["inputs"]["audio"]).read_bytes() == MP3
    client.post(f"/api/jobs/{r.json()['id']}/cancel")
    shutil.rmtree(song)
    r = client.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 409 and r.json()["detail"] == "Исходники задания не сохранились — создайте задание заново"


def test_republish_only_after_publish_failure(env, client):
    job = _gen(client).json()
    jobs = _jobs(env)
    jobs.update(job["id"], state="failed", stage="render", error="упало")
    r = client.post(f"/api/jobs/{job['id']}/republish")
    assert r.status_code == 409 and r.json()["detail"] == "Повторная выкладка возможна только после ошибки выкладки"
    jobs.update(job["id"], stage=STAGE_PUBLISH, error="ошибка выкладки: шара недоступна")
    r = client.post(f"/api/jobs/{job['id']}/republish")
    assert r.status_code == 201
    new = r.json()
    assert new["type"] == "publish" and new["params"]["source_job_id"] == job["id"]
    assert new["params"]["rel_dir"] == job["params"]["rel_dir"]


def test_log_chunks_and_sse(env, client):
    job = _gen(client).json()
    logs = env.data / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{job['id']}.log").write_text("строка 1\nстрока 2\n", "utf-8")
    r = client.get(f"/api/jobs/{job['id']}/log")
    assert r.text == "строка 1\nстрока 2\n"
    off = int(r.headers["x-log-offset"])
    assert client.get(f"/api/jobs/{job['id']}/log", params={"from": off}).text == ""
    assert client.get(f"/api/jobs/{job['id']}/log", params={"tail": 1}).text == "строка 2\n"
    _jobs(env).update(job["id"], state="done")
    with client.stream("GET", f"/api/jobs/{job['id']}/log/stream") as s:
        assert s.headers["content-type"].startswith("text/event-stream")
        body = "".join(s.iter_text())
    assert "data: строка 1\n" in body and "data: строка 2\n" in body
    assert "event: end\ndata: done\n" in body
    assert client.get("/api/jobs/999/log").status_code == 404


def test_sse_start_event_gives_byte_offset_of_first_line_crlf(env, client):
    """Первое событие SSE — `event: start` со смещением начала первой показанной строки:
    клиент догружает всё до него через ?from=0, на CRLF-логе ничего не обрезается."""
    job = _gen(client).json()
    logs = env.data / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    lines = [f"строка {i}" for i in range(1, 503)]  # 502 строки, в хвосте SSE — последние 500
    (logs / f"{job['id']}.log").write_bytes("".join(f"{x}\r\n" for x in lines).encode("utf-8"))
    _jobs(env).update(job["id"], state="done")
    with client.stream("GET", f"/api/jobs/{job['id']}/log/stream") as s:
        body = "".join(s.iter_text())
    first = body.split("\n\n")[0]
    assert first.startswith("event: start\ndata: ")
    start = int(first.split("data: ")[1])
    head = "строка 1\r\nстрока 2\r\n".encode("utf-8")  # две строки до хвоста, посчитано вручную
    assert start == len(head)
    assert "data: строка 3\n" in body and "data: строка 2\n" not in body
