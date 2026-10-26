"""Шов 3: задание «Переименование» (rename) — файлы, заголовки, корзина, индекс, своя песня, теги."""

from karaoke_core import naming
from karaoke_core.db import Settings, Tags, Target, now

ARTIST, TITLE = "Группа", "Старая"
NEW_ARTIST, NEW_TITLE = "Группа", "Новая песня"
REL, BASE = naming.song_dir(ARTIST, TITLE), naming.base_name(ARTIST, TITLE)
NEW_REL, NEW_BASE = naming.song_dir(NEW_ARTIST, NEW_TITLE), naming.base_name(NEW_ARTIST, NEW_TITLE)
MP3 = b"ID3 mp3"


def _txt(base=BASE, artist=ARTIST, title=TITLE, nl="\r\n"):
    return nl.join([
        f"#TITLE:{title}", f"#ARTIST:{artist}", f"#MP3:{base}.mp3", f"#COVER:{base} [CO].jpg",
        f"#VIDEO:{base}.mp4", f"#INSTRUMENTAL:{base.upper()} [Instrumental].mp3", "#BACKGROUND:фон.jpg",
        "#BPM:300", "#GAP:1000", ": 0 4 5 Ёл", ": 4 4 5 ка", "E", ""])


def _song_in(world, root=None, *, rel=REL, base=BASE, data: bytes | None = None, target_id="local",
             own_song_id=None):
    root = root or world.out
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{base}.txt").write_bytes(data if data is not None else _txt(base).encode("cp1251"))
    for suffix, content in ((".mp3", MP3), (" [Instrumental].mp3", b"inst"), (" [CO].jpg", b"jpg"),
                            (".mp4", b"video")):
        (d / f"{base}{suffix}").write_bytes(content)
    (d / "фон.jpg").write_bytes(b"bg")
    storage = world.ctx.storage(target_id)
    entry = storage.read_song(rel)
    world.ctx.library.upsert(entry.to_library_item(target_id, own_song_id=own_song_id, scanned_at=now()))
    return d


def _rename(world, *, target_id="local", rel=REL, base=BASE, artist=NEW_ARTIST, title=NEW_TITLE,
            old=(ARTIST, TITLE)):
    params = {"rel_dir": rel, "txt_name": f"{base}.txt", "target_id": target_id, "artist": artist,
              "title": title, "new_rel_dir": naming.song_dir(artist, title),
              "new_txt_name": naming.song_file(artist, title, naming.SUFFIX_TXT), "wait": True}
    return world.jobs.enqueue("rename", {"artist": old[0], "title": old[1]}, params)


def _other(world, name="ПК"):
    return Settings(world.conn).save_target(Target(name=name, kind="local", path="/host/pc"))


def test_rename_in_local_renames_files_and_headers_keeping_bytes(world):
    own = world.ctx.songs.upsert(artist=ARTIST, title=TITLE, rel_dir=REL, params={"artist": ARTIST})
    src = world.paths.source(REL)
    src.mkdir(parents=True)
    (src / "input.mp3").write_bytes(MP3)
    tags = Tags(world.conn)
    tag = tags.create("Любимые")
    tags.set_for_song(naming.song_tag_key(ARTIST, TITLE), [tag.id])
    old_txt = _txt().encode("cp1251")
    _song_in(world, data=old_txt, own_song_id=own.id)

    job = _rename(world)
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    d = world.out / NEW_REL
    assert sorted(f.name for f in d.iterdir()) == sorted([
        f"{NEW_BASE}.txt", f"{NEW_BASE}.mp3", f"{NEW_BASE} [Instrumental].mp3", f"{NEW_BASE} [CO].jpg",
        f"{NEW_BASE}.mp4", "фон.jpg"])
    want = (old_txt.replace(f"#TITLE:{TITLE}".encode("cp1251"), f"#TITLE:{NEW_TITLE}".encode("cp1251"))
            .replace(f"{BASE}.mp3".encode("cp1251"), f"{NEW_BASE}.mp3".encode("cp1251"))
            .replace(f"{BASE} [CO]".encode("cp1251"), f"{NEW_BASE} [CO]".encode("cp1251"))
            .replace(f"{BASE}.mp4".encode("cp1251"), f"{NEW_BASE}.mp4".encode("cp1251"))
            .replace(f"{BASE.upper()} [Instrumental]".encode("cp1251"),
                     f"{NEW_BASE} [Instrumental]".encode("cp1251")))
    assert (d / f"{NEW_BASE}.txt").read_bytes() == want  # cp1251 и CRLF, прочее — байт в байт
    assert (d / f"{NEW_BASE}.mp4").read_bytes() == b"video"
    assert not (world.out / REL).exists()
    [trashed] = world.trash.list()
    assert (trashed.rel_dir, trashed.reason, trashed.target_id) == (REL, "переименована", "local")
    assert world.ctx.library.get("local", REL) is None
    item = world.ctx.library.get("local", NEW_REL)
    assert (item.artist, item.title, item.own_song_id) == (NEW_ARTIST, NEW_TITLE, own.id)
    moved = world.ctx.songs.get(own.id)
    assert (moved.rel_dir, moved.title) == (NEW_REL, NEW_TITLE)
    assert (world.paths.source(NEW_REL) / "input.mp3").read_bytes() == MP3
    assert not world.paths.song_at(REL).exists()  # пустые папки тома data убраны
    assert tags.for_songs([naming.song_tag_key(NEW_ARTIST, NEW_TITLE)]) == {
        naming.song_tag_key(NEW_ARTIST, NEW_TITLE): [tag.id]}
    assert not world.paths.job(REL, job.id).exists()


def test_rename_keeps_utf8_bom_and_lf(world):
    old_txt = b"\xef\xbb\xbf" + _txt(nl="\n").encode("utf-8")
    _song_in(world, data=old_txt)
    job = _rename(world, artist="Другая", title="Песня")
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    data = (world.out / "Другая/Другая - Песня/Другая - Песня.txt").read_bytes()
    assert data.startswith(b"\xef\xbb\xbf#TITLE:\xd0") and b"\r\n" not in data
    assert "#ARTIST:Другая\n#MP3:Другая - Песня.mp3\n".encode() in data
    assert world.ctx.library.get("local", "Другая/Другая - Песня") is not None
    assert not (world.out / ARTIST).exists()  # папка исполнителя опустела — удалена


def test_rename_conflict_fails_and_changes_nothing(world):
    _song_in(world)
    _song_in(world, rel=NEW_REL, base=NEW_BASE)
    job = _rename(world)
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and "Песня «Группа — Новая песня» уже есть в «" in failed.error
    assert (world.out / REL / f"{BASE}.txt").is_file()
    assert world.trash.list() == []
    assert world.ctx.library.get("local", REL) is not None


def test_rename_name_not_encodable_in_txt_fails(world):
    _song_in(world)
    job = _rename(world, title="日本")
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and "нельзя записать в кодировке" in failed.error
    assert (world.out / REL / f"{BASE}.txt").is_file() and world.trash.list() == []


def test_rename_case_only_trashes_first_then_uploads(world):
    _song_in(world)
    job = _rename(world, artist=ARTIST, title=TITLE.upper())
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    new_rel = naming.song_dir(ARTIST, TITLE.upper())
    new_base = naming.base_name(ARTIST, TITLE.upper())
    assert (world.out / new_rel / f"{new_base}.mp3").read_bytes() == MP3
    assert not (world.out / REL).exists()
    log = world.log(job.id)
    assert log.index("перенесена в корзину") < log.index("Выложено в «")
    assert world.ctx.library.get("local", REL) is None and world.ctx.library.get("local", new_rel) is not None


def test_rename_waits_for_unavailable_storage_and_renames_every_copy(world, monkeypatch):
    from karaoke_core.storage import StorageError
    from karaoke_worker import handlers

    monkeypatch.setattr(handlers, "COPY_RETRY_S", 0)
    other = _other(world)
    own = world.ctx.songs.upsert(artist=ARTIST, title=TITLE, rel_dir=REL, params={})
    world.paths.source(REL).mkdir(parents=True)
    _song_in(world, own_song_id=own.id)
    _song_in(world, world.tmp / other.id, target_id=other.id, own_song_id=own.id)
    down, orig = {other.id}, world.ctx.storage_factory

    def factory(target):
        if target.id in down:
            raise StorageError("нет связи (тест)")
        return orig(target)

    world.ctx.reset_storage()
    world.ctx.storage_factory = factory
    local, remote = _rename(world), _rename(world, target_id=other.id)
    world.run(until=lambda: world.jobs.get(local.id).state == "done"
              and (world.jobs.get(remote.id).stage or "").startswith("Ждёт хранилище"))
    waiting = world.jobs.get(remote.id)
    assert waiting.state == "queued" and waiting.stage == "Ждёт хранилище «ПК»"
    assert waiting.params["retry_at"] and waiting.params["wait_logged_at"]
    down.clear()
    world.run()
    assert world.jobs.get(remote.id).state == "done", world.log(remote.id)
    assert (world.tmp / other.id / NEW_REL / f"{NEW_BASE}.txt").is_file()
    assert not (world.tmp / other.id / REL).exists()
    assert world.ctx.library.get(other.id, NEW_REL) is not None and world.ctx.library.get(other.id, REL) is None
    assert world.ctx.songs.get(own.id).rel_dir == NEW_REL and world.paths.source(NEW_REL).is_dir()
    assert "Исходники песни перенесены" not in world.log(remote.id)  # уже перенесены первой копией
    assert sorted(i.target_id for i in world.trash.list()) == sorted(["local", other.id])


# ---------------------------------------------------------------------- сбои и повторы

def _restart(world, job):
    """Как «Перезапустить» в вебе: те же params без ожидания, parent_id — прежнее задание."""
    p = {k: v for k, v in world.jobs.get(job.id).params.items() if k not in ("retry_at", "wait_logged_at")}
    return world.jobs.enqueue("rename", world.jobs.get(job.id), p, parent_id=job.id)


def test_case_only_restart_after_old_folder_already_in_trash(world):
    """Старая папка уже в корзине, вход ``in/`` скачан — выложить из него, корзину не трогать."""
    import shutil

    _song_in(world)
    title = TITLE.upper()
    first = _rename(world, artist=ARTIST, title=title)
    shutil.copytree(world.out / REL, world.paths.job_in(REL, first.id))
    world.trash.move_to_trash(world.storage, REL, reason="переименована")
    world.jobs.update(first.id, state="failed", error="прервано перезапуском")
    again = _restart(world, first)
    world.run()
    assert world.jobs.get(again.id).state == "done", world.log(again.id)
    new_rel, new_base = naming.song_dir(ARTIST, title), naming.base_name(ARTIST, title)
    assert (world.out / new_rel / f"{new_base}.mp3").read_bytes() == MP3
    assert len(world.trash.list()) == 1
    assert world.ctx.library.get("local", new_rel) is not None


def test_partial_upload_is_removed_and_retry_succeeds(world, monkeypatch):
    from karaoke_core.storage import LocalStorage, StorageError
    from karaoke_worker import handlers

    monkeypatch.setattr(handlers, "COPY_RETRY_S", 0)
    _song_in(world)
    state = {"writes": 0, "failed": False}

    class Flaky(LocalStorage):
        def write_atomic(self, rel, data):
            if rel.startswith(NEW_REL) and not state["failed"]:
                state["writes"] += 1
                if state["writes"] == 2:
                    state["failed"] = True
                    raise StorageError("обрыв посреди выкладки (тест)")
            return super().write_atomic(rel, data)

    world.ctx.reset_storage()
    world.ctx.storage_factory = lambda t: Flaky(world.out, target_id=t.id, label=t.label)
    job = _rename(world)
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert state["failed"]
    assert len(list((world.out / NEW_REL).iterdir())) == 6
    assert not (world.out / REL).exists()


def test_restart_after_crash_between_upload_and_trash_finishes_steps(world, monkeypatch):
    own = world.ctx.songs.upsert(artist=ARTIST, title=TITLE, rel_dir=REL, params={})
    world.paths.source(REL).mkdir(parents=True)
    _song_in(world, own_song_id=own.id)
    real = world.trash.move_to_trash

    def crash(*a, **kw):
        raise RuntimeError("воркер упал (тест)")

    monkeypatch.setattr(world.trash, "move_to_trash", crash)
    first = _rename(world)
    world.run()
    assert world.jobs.get(first.id).state == "failed"
    assert (world.out / NEW_REL).is_dir() and (world.out / REL).is_dir()
    monkeypatch.setattr(world.trash, "move_to_trash", real)
    again = _restart(world, first)
    world.run()
    assert world.jobs.get(again.id).state == "done", world.log(again.id)
    assert not (world.out / REL).exists()
    assert [i.rel_dir for i in world.trash.list()] == [REL]
    assert world.ctx.library.get("local", REL) is None
    assert world.ctx.library.get("local", NEW_REL).own_song_id == own.id
    assert world.ctx.songs.get(own.id).rel_dir == NEW_REL


def test_foreign_data_folder_under_new_name_is_never_removed(world):
    own = world.ctx.songs.upsert(artist=ARTIST, title=TITLE, rel_dir=REL, params={})
    world.paths.source(REL).mkdir(parents=True)
    (world.paths.source(REL) / "input.mp3").write_bytes(MP3)
    foreign = world.paths.source(NEW_REL)
    foreign.mkdir(parents=True)
    (foreign / "input.mp3").write_bytes(b"other")
    _song_in(world, own_song_id=own.id)
    job = _rename(world)
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert (foreign / "input.mp3").read_bytes() == b"other"
    assert (world.paths.source(REL) / "input.mp3").read_bytes() == MP3
    assert "Предупреждение: исходники" in world.log(job.id)


def test_tags_stay_on_old_name_until_last_copy_is_renamed(world, monkeypatch):
    from karaoke_core.storage import StorageError
    from karaoke_worker import handlers

    monkeypatch.setattr(handlers, "COPY_RETRY_S", 0)
    other = _other(world)
    _song_in(world)
    _song_in(world, world.tmp / other.id, target_id=other.id)
    tags = Tags(world.conn)
    tag = tags.create("Любимые")
    old_key, new_key = naming.song_tag_key(ARTIST, TITLE), naming.song_tag_key(NEW_ARTIST, NEW_TITLE)
    tags.set_for_song(old_key, [tag.id])
    down, orig = {other.id}, world.ctx.storage_factory

    def factory(target):
        if target.id in down:
            raise StorageError("нет связи (тест)")
        return orig(target)

    world.ctx.reset_storage()
    world.ctx.storage_factory = factory
    local, remote = _rename(world), _rename(world, target_id=other.id)
    world.run(until=lambda: world.jobs.get(local.id).state == "done"
              and (world.jobs.get(remote.id).stage or "").startswith("Ждёт"))
    assert tags.for_songs([old_key, new_key]) == {old_key: [tag.id], new_key: [tag.id]}
    down.clear()
    world.run()
    assert world.jobs.get(remote.id).state == "done", world.log(remote.id)
    assert tags.for_songs([old_key, new_key]) == {new_key: [tag.id]}


def test_txt_named_song_txt_from_pack(world):
    """``song.txt`` (zip/GitHub): имя .txt — по тому же правилу, что и прочие файлы."""
    d = world.out / REL
    d.mkdir(parents=True)
    (d / "song.txt").write_bytes("#TITLE:Старая\n#ARTIST:Группа\n#MP3:song.mp3\n#BPM:300\n: 0 4 5 a\nE\n".encode())
    (d / "song.mp3").write_bytes(MP3)
    world.ctx.library.upsert(world.ctx.storage("local").read_song(REL).to_library_item("local", scanned_at=now()))
    job = _rename(world, base="song")
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    out = world.out / NEW_REL
    assert sorted(f.name for f in out.iterdir()) == [f"{NEW_BASE}.mp3", f"{NEW_BASE}.txt"]
    assert f"#MP3:{NEW_BASE}.mp3\n".encode() in (out / f"{NEW_BASE}.txt").read_bytes()


def test_txt_with_tail_keeps_tail(world):
    """``A - T (duet).txt`` → ``B - U (duet).txt``: хвост после прежней основы сохраняется."""
    d = world.out / REL
    d.mkdir(parents=True)
    (d / f"{BASE} (duet).txt").write_bytes(
        f"#TITLE:{TITLE}\n#ARTIST:{ARTIST}\n#MP3:{BASE}.mp3\n#BPM:300\n: 0 4 5 a\nE\n".encode())
    (d / f"{BASE}.mp3").write_bytes(MP3)
    world.ctx.library.upsert(world.ctx.storage("local").read_song(REL).to_library_item("local", scanned_at=now()))
    job = _rename(world, base=f"{BASE} (duet)")
    world.run()
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    out = world.out / NEW_REL
    assert sorted(f.name for f in out.iterdir()) == [f"{NEW_BASE} (duet).txt", f"{NEW_BASE}.mp3"]
    item = world.ctx.library.get("local", NEW_REL)
    assert item.txt_name == f"{NEW_BASE} (duet).txt"


def _upload_breaks(world, *, fail_delete: bool):
    """Хранилище, у которого связь рвётся на 2-й записи в новую папку; удаление недописанной
    папки (``fail_delete``) в тот раз тоже не проходит."""
    from karaoke_core.storage import LocalStorage, StorageError

    state = {"writes": 0, "broken": False, "deletes": 0}

    class Flaky(LocalStorage):
        def write_atomic(self, rel, data):
            if rel.startswith(NEW_REL) and not state["broken"]:
                state["writes"] += 1
                if state["writes"] == 2:
                    state["broken"] = True
                    raise StorageError("обрыв посреди выкладки (тест)")
            return super().write_atomic(rel, data)

        def delete_dir(self, rel_dir):
            if fail_delete and rel_dir == NEW_REL and state["deletes"] == 0:
                state["deletes"] += 1
                raise StorageError("связи всё ещё нет (тест)")
            return super().delete_dir(rel_dir)

    world.ctx.reset_storage()
    world.ctx.storage_factory = lambda t: Flaky(world.out, target_id=t.id, label=t.label)
    return state


def test_partial_upload_that_could_not_be_removed_waits_and_is_redone(world, monkeypatch):
    from karaoke_worker import handlers

    monkeypatch.setattr(handlers, "COPY_RETRY_S", 0)
    _song_in(world)
    state = _upload_breaks(world, fail_delete=True)
    job = _rename(world)
    world.run()
    assert state["broken"] and state["deletes"] == 1
    assert world.jobs.get(job.id).state == "done", world.log(job.id)
    assert len(list((world.out / NEW_REL).iterdir())) == 6 and not (world.out / REL).exists()


def test_restart_removes_partial_upload_of_parent_job(world):
    _song_in(world)
    _upload_breaks(world, fail_delete=True)
    first = world.jobs.enqueue("rename", {"artist": ARTIST, "title": TITLE},
                               {**_rename(world).params, "wait": False})
    world.jobs.request_cancel(first.id - 1)  # лишнее задание из _rename — не нужно
    world.run()
    failed = world.jobs.get(first.id)
    assert failed.state == "failed" and (world.out / NEW_REL).is_dir()
    assert failed.params.get("upload_started") == NEW_REL
    again = _restart(world, first)
    world.run()
    assert world.jobs.get(again.id).state == "done", world.log(again.id)
    assert len(list((world.out / NEW_REL).iterdir())) == 6 and not (world.out / REL).exists()


def test_foreign_folder_without_song_is_conflict_when_upload_not_started_by_us(world):
    _song_in(world)
    (world.out / NEW_REL).mkdir(parents=True)
    (world.out / NEW_REL / "чужое.mp3").write_bytes(b"x")
    job = _rename(world)
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and "уже есть" in failed.error
    assert (world.out / NEW_REL / "чужое.mp3").is_file()


def test_two_files_mapping_to_one_name_fail_before_writing(world):
    d = _song_in(world)
    (d / f"{BASE.upper()}.mp3").write_bytes(b"other mp3")  # то же имя без учёта регистра
    job = _rename(world)
    world.run()
    failed = world.jobs.get(job.id)
    assert failed.state == "failed" and "одно имя" in failed.error, failed.error
    assert not (world.out / NEW_REL).exists() and world.trash.list() == []
