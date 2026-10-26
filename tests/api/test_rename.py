"""POST /api/jobs/rename: проверки, задания на все копии, новые song_id, restart."""

from karaoke_core.db import Jobs, Settings, Target, connect, song_id_for

REL = "Artist/Artist - Song"
NEW_REL = "Artist/Artist - New Name"


def _pc(env, client, *, rel=REL, txt=None, base="Artist - Song"):
    """Хранилище «ПК» (``/host/pc`` → ``tmp/host/pc``) с песней ``rel``."""
    target = Settings(connect(env.data / "karaoke.sqlite")).save_target(
        Target(name="ПК", kind="local", path="/host/pc"))
    d = env.tmp / "host" / "pc" / rel
    d.mkdir(parents=True)
    (d / f"{base}.txt").write_bytes(txt or env.SONG_TXT)
    assert client.app.state.ctx.refresh_song(rel, target.id) is not None
    return target


def _rename(client, song_id, artist="Artist", title="New Name"):
    return client.post("/api/jobs/rename", json={"song_id": song_id, "artist": artist, "title": title})


def test_rename_queues_job_per_copy_with_new_song_ids(env, client, song):
    pc = _pc(env, client)
    r = _rename(client, song["song_id"], " Artist ", " New Name ")
    assert r.status_code == 201, r.text
    jobs = r.json()["jobs"]
    assert [j["target_id"] for j in jobs] == ["local", pc.id]  # хранилище песни — первым
    assert [j["song_id"] for j in jobs] == [song_id_for("local", NEW_REL), song_id_for(pc.id, NEW_REL)]
    job = client.get(f"/api/jobs/{jobs[0]['job_id']}").json()
    assert job["type"] == "rename" and job["song_id"] == song["song_id"]
    assert (job["artist"], job["title"]) == ("Artist", "Song")
    assert job["params"] == {"rel_dir": REL, "txt_name": "Artist - Song.txt", "target_id": "local",
                             "artist": "Artist", "title": "New Name", "new_rel_dir": NEW_REL,
                             "new_txt_name": "Artist - New Name.txt", "wait": True}
    assert client.get(f"/api/jobs/{jobs[1]['job_id']}").json()["params"]["target_id"] == pc.id


def test_rename_validation(env, client, song):
    r = _rename(client, song["song_id"], " ", "x")
    assert r.status_code == 400 and r.json()["field"] == "artist"
    r = _rename(client, song["song_id"], "Artist", "")
    assert r.status_code == 400 and r.json()["field"] == "title"
    r = _rename(client, song["song_id"], " Artist", "Song ")
    assert r.status_code == 400 and r.json()["detail"] == "Имя не изменилось"
    r = _rename(client, song["song_id"], "Artist", "Song?")  # «?» → «_»: другая папка
    assert r.status_code == 201
    assert _rename(client, "nope").status_code == 404


def test_rename_case_only_is_allowed(env, client, song):
    r = _rename(client, song["song_id"], "ARTIST", "Song")
    assert r.status_code == 201, r.text
    assert r.json()["jobs"][0]["song_id"] == song_id_for("local", "ARTIST/ARTIST - Song")


def test_rename_refused_while_song_has_active_jobs(env, client, song):
    pc = _pc(env, client)
    jobs = Jobs(connect(env.data / "karaoke.sqlite"))
    other = song_id_for(pc.id, REL)
    job = jobs.enqueue("video", {"artist": "Artist", "title": "Song", "song_id": other}, {})
    r = _rename(client, song["song_id"])
    assert r.status_code == 409 and r.json()["detail"] == "У песни есть незавершённые задания — дождитесь их"
    jobs.update(job.id, state="done")
    first = _rename(client, song["song_id"])
    assert first.status_code == 201
    again = _rename(client, song["song_id"], title="Other")  # переименование уже в очереди
    assert again.status_code == 409


def test_rename_conflict_with_other_song_in_any_copy_storage(env, client, song):
    pc = _pc(env, client)
    other_txt = env.SONG_TXT.replace(b"#TITLE:Song", b"#TITLE:New Name")
    d = env.tmp / "host" / "pc" / "artist" / "artist - new name"
    d.mkdir(parents=True)
    (d / "artist - new name.txt").write_bytes(other_txt)
    assert client.app.state.ctx.refresh_song("artist/artist - new name", pc.id) is not None
    r = _rename(client, song["song_id"])
    assert r.status_code == 409 and r.json()["field"] == "title"
    assert r.json()["detail"] == "Песня «Artist — New Name» уже есть в «ПК»"
    assert [j for j in client.get("/api/jobs").json() if j["type"] == "rename"] == []


def test_restart_rename_drops_waiting_marks(env, client, song):
    job_id = _rename(client, song["song_id"]).json()["jobs"][0]["job_id"]
    jobs = Jobs(connect(env.data / "karaoke.sqlite"))
    p = {**jobs.get(job_id).params, "retry_at": "2999-01-01T00:00:00+00:00", "wait_logged_at": "x"}
    jobs.update(job_id, state="failed", params=p)
    r = client.post(f"/api/jobs/{job_id}/restart")
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["type"] == "rename" and new["parent_id"] == job_id
    assert "retry_at" not in new["params"] and "wait_logged_at" not in new["params"]
    assert client.post(f"/api/jobs/{job_id}/restart").status_code == 409  # уже в очереди


def test_rename_conflict_in_storage_without_copy(env, client, song):
    """Песня с новым именем в хранилище, где копии нет, — тоже конфликт."""
    _pc(env, client, rel=NEW_REL, base="Artist - New Name",
        txt=env.SONG_TXT.replace(b"#TITLE:Song", b"#TITLE:New Name"))
    r = _rename(client, song["song_id"])
    assert r.status_code == 409 and r.json()["field"] == "title"
    assert r.json()["detail"] == "Песня «Artist — New Name» уже есть в «ПК»"


def test_rename_conflict_with_own_song_in_data_volume(env, client, song):
    from karaoke_core.db import Songs

    Songs(connect(env.data / "karaoke.sqlite")).upsert(artist="Artist", title="New Name", rel_dir=NEW_REL)
    r = _rename(client, song["song_id"])
    assert r.status_code == 409 and r.json()["field"] == "title"


def test_rename_refused_while_other_copy_waits_under_new_name(env, client):
    """Одна копия ещё ждёт переименования в «New Name» — переименовать уже переименованную нельзя."""
    env.put_song(NEW_REL, env.SONG_TXT.replace(b"#TITLE:Song", b"#TITLE:New Name"), "Artist - New Name")
    assert client.post("/api/songs/rescan").status_code == 202
    item = next(i for i in client.get("/api/songs").json()["items"] if i["title"] == "New Name")
    Jobs(connect(env.data / "karaoke.sqlite")).enqueue(
        "rename", {"artist": "Artist", "title": "Song", "song_id": song_id_for("t_x", REL)},
        {"rel_dir": REL, "txt_name": "Artist - Song.txt", "target_id": "t_x", "artist": "Artist",
         "title": "New Name", "new_rel_dir": NEW_REL, "new_txt_name": "Artist - New Name.txt", "wait": True})
    r = _rename(client, item["song_id"], title="Third")
    assert r.status_code == 409, r.text
