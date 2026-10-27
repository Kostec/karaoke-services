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


def test_v3_database_gets_tags_tables_and_keeps_data(path):
    """V4: старая БД версии 3 получает tags/song_tags, строки library и songs целы."""
    import sqlite3

    conn = sqlite3.connect(path)
    conn.create_function("karaoke_song_id", 2, db.song_id_for, deterministic=True)
    conn.executescript(db._SCHEMA_V1 + ";" + db._SCHEMA_V2 + ";" + db._SCHEMA_V3
                       + ";PRAGMA user_version = 3;")
    conn.execute("INSERT INTO library (target_id, rel_dir, txt_name, artist, song_id)"
                 " VALUES ('t1', 'A/A - B', 'A - B.txt', 'A', 'x')")
    conn.execute("INSERT INTO songs (id, rel_dir, artist, title, params, created_at, updated_at)"
                 " VALUES ('s1', 'A/A - B', 'A', 'B', '{}', 'c', 'u')")
    conn.commit()
    conn.close()
    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(db._MIGRATIONS)
    assert db.Library(c).get("t1", "A/A - B").artist == "A"
    assert db.Songs(c).get("s1").title == "B"
    tags = db.Tags(c)
    t = tags.create("Любимое")
    assert tags.set_for_song("a\nb", [t.id]) == [t.id]
    assert {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {"tags", "song_tags"}


# --------------------------------------------------------------------------- V5

def _v4_database(path):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.create_function("karaoke_song_id", 2, db.song_id_for, deterministic=True)
    conn.executescript(";".join(db._MIGRATIONS[:4]) + ";PRAGMA user_version = 4;")
    return conn


def test_v4_database_migrates_to_v5_match_key_and_job_order(path):
    from karaoke_core import naming

    conn = _v4_database(path)
    conn.execute("INSERT INTO library (target_id, rel_dir, txt_name, artist, title, song_id)"
                 " VALUES ('t1', 'Ёлка/Ёлка - Прованс', 'x.txt', 'Ёлка', 'Прованс', 'x')")
    conn.execute("INSERT INTO jobs (type, created_at) VALUES ('generate', 'c')")
    conn.commit()
    conn.close()
    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 5
    row = c.execute("SELECT match_key FROM library").fetchone()
    assert row[0] == naming.song_tag_key("Ёлка", "Прованс") == "елка\nпрованс"
    indexes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "library_match_key" in indexes
    old = db.Jobs(c).get(1)
    assert (old.position, old.start_at) == (None, None)
    new = db.Jobs(c).enqueue("generate", REF, {})
    assert new.position == new.id
    assert db.Jobs(c).get(new.id).to_dict()["position"] == new.id
    other = db.Jobs(c).enqueue_with("generate", REF, lambda i: {"n": i})
    assert other.position == other.id and other.params == {"n": other.id}


def test_library_copies_by_indexed_match_key(path):
    c = db.connect(path)
    lib = db.Library(c)
    lib.upsert(db.LibraryItem(target_id="t1", rel_dir="Ёлка/Ёлка - Прованс", txt_name="a.txt",
                              artist="Ёлка", title="Прованс"))
    lib.upsert(db.LibraryItem(target_id="t2", rel_dir="елка/елка - прованс", txt_name="b.txt",
                              artist="елка", title="ПРОВАНС "))
    lib.upsert(db.LibraryItem(target_id="t2", rel_dir="Ёлка/Ёлка - Другая", txt_name="c.txt",
                              artist="Ёлка", title="Другая"))
    seen: list[str] = []
    c.set_trace_callback(seen.append)
    got = lib.copies(" ЕЛКА", "прованс")
    c.set_trace_callback(None)
    assert sorted((i.target_id, i.rel_dir) for i in got) == [
        ("t1", "Ёлка/Ёлка - Прованс"), ("t2", "елка/елка - прованс")]
    assert all(isinstance(i, db.LibraryItem) for i in got)
    selects = [s for s in seen if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1 and "match_key" in selects[0], selects
    sql = selects[0]
    args = ("x",) * sql.count("?")
    plan = " ".join(str(tuple(r)) for r in c.execute("EXPLAIN QUERY PLAN " + sql, args))
    assert "library_match_key" in plan, plan
    assert [i.title for i in lib.by_key("елка\nдругая")] == ["Другая"]
    assert lib.copies("Нет", "Такой") == []


def test_library_match_key_follows_rename_on_upsert(path):
    lib = db.Library(db.connect(path))
    lib.upsert(db.LibraryItem(target_id="t1", rel_dir="A/A - B", txt_name="a.txt", artist="A", title="B"))
    lib.upsert(db.LibraryItem(target_id="t1", rel_dir="A/A - B", txt_name="a.txt", artist="A", title="C"))
    assert lib.copies("A", "B") == [] and len(lib.copies("a", "c")) == 1
    lib.replace_all("t2", [db.LibraryItem(target_id="", rel_dir="A/A - C", txt_name="a.txt",
                                          artist="a", title="c")])
    assert sorted(i.target_id for i in lib.copies("A", "C")) == ["t1", "t2"]


def _ids(jobs_list):
    return [j.id for j in jobs_list]


def test_claim_next_skips_future_start_and_follows_position(jobs):
    a = jobs.enqueue("generate", REF, {})
    b = jobs.enqueue("generate", REF, {})
    c = jobs.enqueue("generate", REF, {})
    jobs.update(a.id, start_at=db.now(3600))
    jobs.update(b.id, position=c.id + 10)  # b — в конец
    assert jobs.claim_next().id == c.id
    assert jobs.claim_next().id == b.id
    assert jobs.claim_next() is None  # a — ещё рано
    jobs.update(a.id, start_at=db.now(-5))
    assert jobs.claim_next().id == a.id


def test_claim_next_old_jobs_without_position_use_id(path):
    conn = _v4_database(path)
    conn.execute("INSERT INTO jobs (type, created_at) VALUES ('generate', 'c')")
    conn.execute("INSERT INTO jobs (type, created_at) VALUES ('generate', 'c')")
    conn.commit()
    conn.close()
    jobs = db.Jobs(db.connect(path))
    new = jobs.enqueue("generate", REF, {})
    jobs.move(new.id, "first")
    assert [jobs.claim_next().id for _ in range(3)] == [new.id, 1, 2]


def test_move_up_down_first_only_among_queued(jobs):
    a, b, c, d = (jobs.enqueue("generate", REF, {}) for _ in range(4))
    jobs.claim_next()  # a → running
    assert _ids(jobs.move(d.id, "up")) == [b.id, d.id, c.id]
    assert _ids(jobs.move(b.id, "down")) == [d.id, b.id, c.id]
    assert _ids(jobs.move(c.id, "first")) == [c.id, d.id, b.id]
    assert _ids(jobs.move(c.id, "up")) == [c.id, d.id, b.id]  # уже первый
    assert _ids(jobs.move(b.id, "down")) == [c.id, d.id, b.id]  # уже последний
    e = jobs.enqueue("generate", REF, {})  # новое — в конец
    assert [jobs.claim_next().id for _ in range(4)] == [c.id, d.id, b.id, e.id]
    with pytest.raises(ValueError) as err:
        jobs.move(a.id, "up")
    assert str(err.value) == "Переставлять можно только ожидающие задания"
    f = jobs.enqueue("generate", REF, {})
    with pytest.raises(ValueError):
        jobs.move(f.id, "sideways")
    with pytest.raises(ValueError):
        jobs.move(999, "up")


def test_schedule_only_queued_and_not_in_past(jobs):
    from datetime import datetime, timedelta, timezone

    a = jobs.enqueue("generate", REF, {})
    b = jobs.enqueue("generate", REF, {})
    at = db.now(7200)
    got = jobs.schedule(a.id, at)
    assert got.start_at == at
    assert jobs.claim_next().id == b.id
    assert jobs.claim_next() is None
    # другой формат ISO (Z, микросекунды) приводится к формату db.now()
    later = datetime.now(timezone.utc) + timedelta(hours=3)
    got = jobs.schedule(a.id, later.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    assert got.start_at == later.isoformat(timespec="seconds")
    with pytest.raises(ValueError) as err:
        jobs.schedule(a.id, db.now(-60))
    assert str(err.value) == "Время уже прошло"
    assert jobs.get(a.id).start_at == got.start_at
    with pytest.raises(ValueError):
        jobs.schedule(a.id, "завтра")
    assert jobs.schedule(a.id, None).start_at is None  # «Запустить сейчас»
    assert jobs.claim_next().id == a.id
    with pytest.raises(ValueError) as err:
        jobs.schedule(a.id, db.now(60))  # уже running
    assert "ожидающ" in str(err.value)


def test_schedule_all_defers_queued_without_time(jobs):
    a, b, c, d = (jobs.enqueue("generate", REF, {}) for _ in range(4))
    jobs.claim_next()  # a running
    early = db.now(600)
    jobs.schedule(b.id, early)
    at = db.now(7200)
    assert jobs.schedule_all(at) == 2
    assert [jobs.get(i).start_at for i in (a.id, b.id, c.id, d.id)] == [None, early, at, at]
    with pytest.raises(ValueError) as err:
        jobs.schedule_all(db.now(-1))
    assert str(err.value) == "Время уже прошло"


# --------------------------------------------------------------------------- Telegram и зеркала

def test_settings_telegram_roundtrip_and_public(path):
    s = db.Settings(db.connect(path))
    t = s.get_telegram()
    assert (t.bot_token, t.chat_id) == (None, "")
    assert t.public() == {"has_token": False, "chat_id": "", "on_done": t.on_done,
                          "on_failed": t.on_failed, "on_queue_empty": t.on_queue_empty}
    s.set_telegram(db.TelegramSettings("123:abc", "42", True, False, True))
    got = db.Settings(db.connect(path)).get_telegram()
    assert (got.bot_token, got.chat_id, got.on_done, got.on_failed, got.on_queue_empty) == (
        "123:abc", "42", True, False, True)
    pub = got.public()
    assert pub == {"has_token": True, "chat_id": "42", "on_done": True, "on_failed": False,
                   "on_queue_empty": True}
    assert "123:abc" not in repr(got) and "123:abc" not in str(pub)
    # None — прежний токен, пустая строка — удалить
    s.set_telegram(db.TelegramSettings(None, "7", False, True, False))
    assert (s.get_telegram().bot_token, s.get_telegram().chat_id) == ("123:abc", "7")
    s.set_telegram(db.TelegramSettings("", "7", False, True, False))
    assert s.get_telegram().bot_token is None


def test_settings_mirrors_crud_and_result(path):
    s = db.Settings(db.connect(path))
    t1 = s.save_target(db.Target(name="ПК", kind="local", path="/host/pc"))
    t2 = s.save_target(db.Target(name="ПК2", kind="local", path="/host/pc2"))
    assert s.get_mirrors() == []
    m = s.save_mirror(db.Mirror(from_target="local", to_target=t1.id, enabled=True))
    assert m.id and (m.from_target, m.to_target, m.enabled) == ("local", t1.id, True)
    assert (m.last_run_at, m.last_result) == (None, None)
    m2 = s.save_mirror(db.Mirror(from_target=t1.id, to_target=t2.id, enabled=True))
    assert [x.id for x in db.Settings(db.connect(path)).get_mirrors()] == [m.id, m2.id]
    result = {"added": 2, "updated": 1, "only_in_target": [
        {"song_id": "s", "artist": "А", "title": "Б", "rel_dir": "А/А - Б"}]}
    s.set_mirror_result(m.id, result)
    got = s.get_mirrors()[0]
    assert got.last_result == result and got.last_run_at
    # правка не теряет итог прошлого прогона
    edited = s.save_mirror(db.Mirror(id=m.id, from_target="local", to_target=t2.id, enabled=False))
    assert (edited.to_target, edited.enabled, edited.last_result) == (t2.id, False, result)
    for bad in (db.Mirror(from_target=t1.id, to_target=t1.id),
                db.Mirror(from_target="local", to_target="t_nope"),
                db.Mirror(id="m_nope", from_target="local", to_target=t1.id)):
        with pytest.raises(ValueError):
            s.save_mirror(bad)
    s.delete_mirror(m.id)
    assert [x.id for x in s.get_mirrors()] == [m2.id]
    with pytest.raises(ValueError):
        s.delete_mirror(m.id)


def test_delete_target_disables_its_mirrors(path):
    s = db.Settings(db.connect(path))
    t1 = s.save_target(db.Target(name="ПК", kind="local", path="/host/pc"))
    t2 = s.save_target(db.Target(name="ПК2", kind="local", path="/host/pc2"))
    on_t1 = s.save_mirror(db.Mirror(from_target="local", to_target=t1.id, enabled=True))
    other = s.save_mirror(db.Mirror(from_target="local", to_target=t2.id, enabled=True))
    s.delete_target(t1.id)
    state = {x.id: x.enabled for x in s.get_mirrors()}
    assert state == {on_t1.id: False, other.id: True}


def test_libcheck_report_path(tmp_path):
    from karaoke_core.paths import DataPaths

    assert DataPaths(tmp_path).libcheck_report() == tmp_path / "reports" / "libcheck.json"
