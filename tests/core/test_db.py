import threading

import pytest

from karaoke_core import db


@pytest.fixture
def path(tmp_path):
    return tmp_path / "karaoke.sqlite"


@pytest.fixture
def jobs(path):
    return db.Jobs(db.connect(path))


REF = {"artist": "Кино", "title": "Группа крови"}


def test_connect_uses_wal(path):
    conn = db.connect(path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_enqueue_get_list(jobs):
    a = jobs.enqueue("generate", REF, {"whisper_model": "large-v2"})
    b = jobs.enqueue("instrumental", {"artist": "A", "title": "B", "song_id": "s1"}, {})
    assert a.state == "queued" and a.type == "generate"
    assert a.artist == "Кино" and a.title == "Группа крови"
    assert a.params == {"whisper_model": "large-v2"}
    assert jobs.get(a.id).params == {"whisper_model": "large-v2"}
    assert b.song_id == "s1"
    assert [j.id for j in jobs.list(10)] == [b.id, a.id]  # новые сверху
    assert jobs.get(999) is None


def test_claim_next_takes_oldest_queued_and_marks_running(jobs):
    a = jobs.enqueue("generate", REF, {})
    b = jobs.enqueue("generate", REF, {})
    got = jobs.claim_next()
    assert got.id == a.id and got.state == "running" and got.started_at
    assert jobs.claim_next().id == b.id
    assert jobs.claim_next() is None


def test_claim_next_never_gives_same_job_twice_across_connections(path):
    db.connect(path)  # схема
    setup = db.Jobs(db.connect(path))
    ids = {setup.enqueue("generate", REF, {}).id for _ in range(60)}
    taken: list[list[int]] = [[], []]
    barrier = threading.Barrier(2)

    def worker(n):
        q = db.Jobs(db.connect(path))
        barrier.wait()
        while (job := q.claim_next()) is not None:
            taken[n].append(job.id)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    all_taken = taken[0] + taken[1]
    assert len(all_taken) == len(set(all_taken))
    assert set(all_taken) == ids


def test_fail_interrupted(jobs):
    running = jobs.enqueue("generate", REF, {})
    publishing = jobs.enqueue("publish", REF, {})
    queued = jobs.enqueue("generate", REF, {})
    done = jobs.enqueue("generate", REF, {})
    for j in (running, publishing, done):
        jobs.claim_next()
    jobs.update(publishing.id, state="publishing", stage="publish")
    jobs.update(done.id, state="done")
    jobs.update(queued.id, state="queued")
    assert jobs.fail_interrupted() == 2
    for j in (running, publishing):
        got = jobs.get(j.id)
        assert got.state == "failed"
        assert got.error == "прервано перезапуском"
        assert got.finished_at
    assert jobs.get(queued.id).state == "queued"
    assert jobs.get(done.id).state == "done"


def test_request_cancel(jobs):
    q = jobs.enqueue("generate", REF, {})
    r = jobs.enqueue("generate", REF, {})
    jobs.claim_next()  # q → running
    assert jobs.request_cancel(r.id).state == "cancelled"  # из очереди — сразу
    got = jobs.request_cancel(q.id)
    assert got.state == "running" and got.cancel_requested is True


def test_update_sets_fields_and_finish_time(jobs):
    j = jobs.enqueue("generate", REF, {})
    jobs.update(j.id, stage="separation", percent=42.5)
    got = jobs.get(j.id)
    assert (got.stage, got.percent) == ("separation", 42.5)
    jobs.update(j.id, state="failed", error="Нет GPU")
    got = jobs.get(j.id)
    assert got.state == "failed" and got.error == "Нет GPU" and got.finished_at
    with pytest.raises(ValueError):
        jobs.update(j.id, nonexistent=1)


def test_settings_output_defaults_from_env_and_persists(path, monkeypatch):
    monkeypatch.setenv("OUTPUT_KIND", "smb")
    monkeypatch.setenv("OUTPUT_SMB_HOST", "192.168.0.129")
    monkeypatch.setenv("OUTPUT_SMB_SHARE", "karaoke")
    monkeypatch.setenv("OUTPUT_SMB_PATH", "")
    monkeypatch.setenv("OUTPUT_SMB_USER", "pi")
    monkeypatch.setenv("OUTPUT_SMB_PASSWORD", "env-secret")
    settings = db.Settings(db.connect(path))
    t = settings.get_output()
    assert (t.kind, t.host, t.share, t.path, t.user, t.password) == (
        "smb", "192.168.0.129", "karaoke", "", "pi", "env-secret")
    settings.set_output(db.OutputTarget(kind="local", path="Песни/Новые"))
    t2 = db.Settings(db.connect(path)).get_output()
    assert (t2.kind, t2.path) == ("local", "Песни/Новые")
    assert t2.target_id != t.target_id


def test_settings_empty_password_means_keep(path, monkeypatch):
    monkeypatch.setenv("OUTPUT_SMB_PASSWORD", "")
    settings = db.Settings(db.connect(path))
    settings.set_output(db.OutputTarget(kind="smb", host="h", share="s", user="u", password="p1"))
    settings.set_output(db.OutputTarget(kind="smb", host="h", share="s2", user="u", password=None))
    t = settings.get_output()
    assert (t.share, t.password) == ("s2", "p1")
    assert "p1" not in repr(t)
    assert t.public()["has_password"] is True and "password" not in t.public()


def _item(rel_dir, artist, title, **kw):
    return db.LibraryItem(target_id="t1", rel_dir=rel_dir, txt_name=f"{rel_dir.split('/')[-1]}.txt",
                          artist=artist, title=title, **kw)


def test_library_replace_upsert_remove_and_search(path):
    lib = db.Library(db.connect(path))
    lib.replace_all("t1", [
        _item("Кино/Кино - Группа крови", "Кино", "Группа крови", is_duet=False),
        _item("Ёлка/Ёлка - Прованс", "Ёлка", "Прованс", instrumental="x [Instrumental].mp3"),
    ])
    lib.replace_all("t2", [db.LibraryItem(target_id="t2", rel_dir="A/A - B", txt_name="A - B.txt",
                                          artist="A", title="B")])
    assert [i.artist for i in lib.list("t1")] == ["Ёлка", "Кино"]
    assert [i.title for i in lib.list("t1", "ГРУППА")] == ["Группа крови"]
    assert [i.title for i in lib.list("t1", "прованс")] == ["Прованс"]
    lib.upsert(_item("Кино/Кино - Кукушка", "Кино", "Кукушка"))
    assert len(lib.list("t1")) == 3
    lib.remove("t1", "Кино/Кино - Группа крови")
    assert [i.title for i in lib.list("t1", "кино")] == ["Кукушка"]
    item = lib.list("t1", "прованс")[0]
    assert item.instrumental == "x [Instrumental].mp3"
    assert item.song_id == db.song_id_for("t1", "Ёлка/Ёлка - Прованс")
    assert db.song_id_for("t1", "a") != db.song_id_for("t2", "a")
    lib.replace_all("t1", [])
    assert lib.list("t1") == [] and len(lib.list("t2")) == 1


def test_songs_upsert_and_lookup(path):
    songs = db.Songs(db.connect(path))
    s = songs.upsert(artist="Кино", title="Группа крови",
                     rel_dir="Кино/Кино - Группа крови", params={"language": "ru"})
    assert songs.get(s.id).params == {"language": "ru"}
    again = songs.upsert(artist="Кино", title="Группа крови",
                         rel_dir="Кино/Кино - Группа крови", params={"language": "en"})
    assert again.id == s.id and again.params == {"language": "en"}
    assert songs.by_rel_dir("Кино/Кино - Группа крови").id == s.id
    assert songs.by_rel_dir("нет") is None
    assert songs.get("нет") is None


def test_claim_next_with_types_takes_oldest_of_those_types_only(jobs):
    gen = jobs.enqueue("generate", REF, {})
    pub = jobs.enqueue("publish", REF, {})
    got = jobs.claim_next(types=["publish"])
    assert got.id == pub.id and got.state == "running"
    assert jobs.get(gen.id).state == "queued"
    assert jobs.claim_next(types=["publish"]) is None
    assert jobs.claim_next(types=[]) is None
    assert jobs.claim_next().id == gen.id


def test_settings_yandex_token_roundtrip_and_delete(path):
    settings = db.Settings(db.connect(path))
    assert settings.get_yandex() is None
    settings.set_yandex("  y0_AgAAAA-key  ")
    assert db.Settings(db.connect(path)).get_yandex() == "y0_AgAAAA-key"
    raw = settings.conn.execute("SELECT value FROM settings WHERE key=?", (db.YANDEX_KEY,)).fetchone()[0]
    assert raw == '{"token": "y0_AgAAAA-key"}' and db.YANDEX_KEY == "yandex_music"
    settings.set_yandex("")
    assert settings.get_yandex() is None
    assert settings.conn.execute("SELECT 1 FROM settings WHERE key=?", (db.YANDEX_KEY,)).fetchone() is None
    settings.set_yandex("k2")
    settings.set_yandex(None)
    assert settings.get_yandex() is None
    settings.set_yandex(None)  # удаление отсутствующего — не ошибка


def test_settings_yandex_tolerates_garbage(path):
    settings = db.Settings(db.connect(path))
    settings._set(db.YANDEX_KEY, "not json")
    assert settings.get_yandex() is None
    settings._set(db.YANDEX_KEY, '{"token": ""}')
    assert settings.get_yandex() is None


def test_library_keeps_video(path):
    lib = db.Library(db.connect(path))
    lib.upsert(db.LibraryItem(target_id="t1", rel_dir="A/A - B", txt_name="A - B.txt", video="A - B.mp4"))
    item = lib.get("t1", "A/A - B")
    assert item.video == "A - B.mp4"
    assert item.to_dict()["video"] == "A - B.mp4"


def test_old_v1_database_migrates_to_video_column(path):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript(db._SCHEMA_V1 + ";PRAGMA user_version = 1;")
    conn.execute("INSERT INTO library (target_id, rel_dir, txt_name) VALUES ('t1', 'A/A - B', 'A - B.txt')")
    conn.commit()
    conn.close()
    item = db.Library(db.connect(path)).get("t1", "A/A - B")
    assert (item.txt_name, item.video) == ("A - B.txt", None)


def test_v2_database_gets_song_id_column_and_find_uses_index(path):
    """V3: у существующих строк library появляется song_id, find ищет по индексу, а не перебором."""
    import hashlib
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript(db._SCHEMA_V1 + ";" + db._SCHEMA_V2 + ";PRAGMA user_version = 2;")
    conn.execute("INSERT INTO library (target_id, rel_dir, txt_name, artist) VALUES ('t1', 'A/A - B', 'A - B.txt', 'A')")
    conn.execute("INSERT INTO library (target_id, rel_dir, txt_name, artist) VALUES ('t2', 'A/A - B', 'A - B.txt', 'A2')")
    conn.commit()
    conn.close()
    want = hashlib.sha1("t2\nA/A - B".encode("utf-8")).hexdigest()[:16]
    c = db.connect(path)
    lib = db.Library(c)
    item = lib.find(want)
    assert (item.target_id, item.artist, item.song_id) == ("t2", "A2", want)
    assert lib.find("0" * 16) is None
    plan = " ".join(str(tuple(r)) for r in c.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM library WHERE song_id=?", (want,)))
    assert "USING INDEX" in plan
    lib.upsert(db.LibraryItem(target_id="t3", rel_dir="C/C - D", txt_name="C - D.txt"))
    new_id = hashlib.sha1("t3\nC/C - D".encode("utf-8")).hexdigest()[:16]
    assert lib.find(new_id).rel_dir == "C/C - D"
