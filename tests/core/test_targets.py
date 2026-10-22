"""Несколько хранилищ в ``settings``: модель, основная цель, миграция со старой «папки результата».

Шов — публичный API ``karaoke_core.db.Settings`` и ``Trash.retarget``, ``make_storage``.
"""

import json
import re

import pytest

from karaoke_core import db
from karaoke_core.storage import LocalStorage, SmbStorage, StorageError, make_storage
from karaoke_core.trash import Trash

PW = "smb-pass-1"
ENV_LOCAL = {"OUTPUT_KIND": "local"}
ENV_SMB = {"OUTPUT_KIND": "smb", "OUTPUT_SMB_HOST": "10.0.0.5", "OUTPUT_SMB_SHARE": "karaoke",
           "OUTPUT_SMB_PATH": "songs", "OUTPUT_SMB_USER": "pi", "OUTPUT_SMB_PASSWORD": "env-pass"}


@pytest.fixture
def path(tmp_path):
    return tmp_path / "karaoke.sqlite"


def _put(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))


def _lib_row(conn, target_id, rel_dir="A/A - B"):
    conn.execute("INSERT INTO library (target_id, rel_dir, txt_name) VALUES (?, ?, 'A - B.txt')",
                 (target_id, rel_dir))


def _lib_ids(conn):
    return sorted(r[0] for r in conn.execute("SELECT target_id FROM library"))


# --------------------------------------------------------------------------- модель

def test_builtin_local_always_first_and_default(path):
    s = db.Settings(db.connect(path), ENV_LOCAL)
    [local] = s.get_targets()
    assert (local.id, local.kind, local.path) == ("local", "local", "/output")
    assert local.name == "Локальное хранилище" and db.LOCAL_TARGET_ID == "local"
    assert s.get_default_target_id() == "local"
    assert s.get_target("local") == local and s.get_target("t_nope") is None


def test_save_target_assigns_stable_id_and_keeps_secret(path):
    s = db.Settings(db.connect(path), ENV_LOCAL)
    t = s.save_target(db.Target(id="", name="Шара", kind="smb", host="10.0.0.9", share="k",
                                user="pi", secret=PW))
    assert re.fullmatch(r"t_[0-9a-f]{8}", t.id)
    edited = s.save_target(db.Target(id=t.id, name="Шара 2", kind="smb", host="10.0.0.10",
                                     share="k", user="pi", secret=None))
    again = db.Settings(db.connect(path), ENV_LOCAL).get_target(t.id)
    assert edited.id == t.id and (again.name, again.host, again.secret) == ("Шара 2", "10.0.0.10", PW)
    assert [x.id for x in s.get_targets()] == ["local", t.id]


def test_save_target_keeps_token_and_public_hides_both(path):
    s = db.Settings(db.connect(path), ENV_LOCAL)
    t = s.save_target(db.Target(id="", name="Диск", kind="gdrive", client_id="cid",
                                secret="cs-1", token="rt-1", path="Караоке"))
    s.save_target(db.Target(id=t.id, name="Диск", kind="gdrive", client_id="cid", path="Другое"))
    got = s.get_target(t.id)
    assert (got.secret, got.token, got.path) == ("cs-1", "rt-1", "Другое")
    pub = got.public()
    assert "cs-1" not in json.dumps(pub) and "rt-1" not in json.dumps(pub)
    assert pub["has_password"] is True and pub["connected"] is True
    assert (pub["id"], pub["kind"], pub["name"]) == (t.id, "gdrive", "Диск")
    assert "cs-1" not in repr(got) and "rt-1" not in repr(got)


def test_default_switch_does_not_touch_targets(path):
    s = db.Settings(db.connect(path), ENV_LOCAL)
    t = s.save_target(db.Target(id="", name="Шара", kind="smb", host="h", share="k", user="u", secret=PW))
    for target_id in (t.id, "local", t.id, "local"):
        s.set_default_target_id(target_id)
        assert s.get_default_target_id() == target_id
    assert s.get_target(t.id).secret == PW and s.get_target(t.id).host == "h"
    with pytest.raises(ValueError):
        s.set_default_target_id("t_nope")


def test_delete_target_rules(path):
    conn = db.connect(path)
    s = db.Settings(conn, ENV_LOCAL)
    t = s.save_target(db.Target(id="", name="Шара", kind="smb", host="h", share="k"))
    s.set_default_target_id(t.id)
    with pytest.raises(ValueError, match="Сначала выберите другую основную цель"):
        s.delete_target(t.id)
    with pytest.raises(ValueError):
        s.delete_target("local")
    s.set_default_target_id("local")
    _lib_row(conn, t.id)
    _lib_row(conn, "local")
    s.delete_target(t.id)
    assert s.get_target(t.id) is None and _lib_ids(conn) == ["local"]


# --------------------------------------------------------------------------- миграция

def test_migrates_saved_smb_output(path, tmp_path):
    conn = db.connect(path)
    _put(conn, "output", {"kind": "smb", "host": "10.0.0.9", "share": "karaoke", "path": "",
                          "user": "pi", "password": PW})
    _lib_row(conn, "smb://10.0.0.9/karaoke")
    _lib_row(conn, "local:/output", "C/C - D")
    trash = tmp_path / "trash"
    (trash / "e1").mkdir(parents=True)
    (trash / "e1" / "meta.json").write_text(json.dumps(
        {"id": "e1", "deleted_at": "2026-10-01T00:00:00+00:00", "kind": "song", "rel_dir": "A/A - B",
         "target_id": "smb://10.0.0.9/karaoke", "target_label": "//10.0.0.9/karaoke"}), "utf-8")

    s = db.Settings(conn, ENV_LOCAL)
    local, smb = s.get_targets()
    assert re.fullmatch(r"t_[0-9a-f]{8}", smb.id)
    assert (smb.kind, smb.host, smb.share, smb.user, smb.secret) == ("smb", "10.0.0.9", "karaoke", "pi", PW)
    assert s.get_default_target_id() == smb.id
    assert _lib_ids(conn) == sorted(["local", smb.id])
    assert Trash(trash).retarget(s.resolve_target_id) == 1
    assert Trash(trash).list()[0].target_id == smb.id

    # повторный запуск ничего не меняет
    s2 = db.Settings(db.connect(path), ENV_LOCAL)
    assert [t.id for t in s2.get_targets()] == ["local", smb.id]
    assert _lib_ids(conn) == sorted(["local", smb.id])
    assert Trash(trash).retarget(s2.resolve_target_id) == 0


def test_migrates_local_subfolder_output(path):
    conn = db.connect(path)
    _put(conn, "output", {"kind": "local", "host": "", "share": "", "path": "Песни/Новые",
                          "user": "", "password": ""})
    _lib_row(conn, "local:/output/Песни/Новые")
    s = db.Settings(conn, ENV_LOCAL)
    local, sub = s.get_targets()
    assert (sub.kind, sub.path) == ("local", "/output/Песни/Новые")
    assert s.get_default_target_id() == sub.id and _lib_ids(conn) == [sub.id]


def test_migrates_local_root_output_to_builtin(path):
    conn = db.connect(path)
    _put(conn, "output", {"kind": "local", "path": ""})
    _lib_row(conn, "local:/output")
    s = db.Settings(conn, ENV_LOCAL)
    assert [t.id for t in s.get_targets()] == ["local"]
    assert s.get_default_target_id() == "local" and _lib_ids(conn) == ["local"]


def test_migrates_from_env_when_nothing_saved(path):
    conn = db.connect(path)
    _lib_row(conn, "smb://10.0.0.5/karaoke/songs")
    s = db.Settings(conn, ENV_SMB)
    local, smb = s.get_targets()
    assert (smb.host, smb.share, smb.path, smb.user, smb.secret) == (
        "10.0.0.5", "karaoke", "songs", "pi", "env-pass")
    assert s.get_default_target_id() == smb.id and _lib_ids(conn) == [smb.id]


def test_resolve_legacy_job_target_ids(path):
    conn = db.connect(path)
    _put(conn, "output", {"kind": "smb", "host": "10.0.0.9", "share": "karaoke", "path": "a/b",
                          "user": "pi", "password": PW})
    s = db.Settings(conn, ENV_LOCAL)
    smb = s.get_targets()[1]
    assert s.resolve_target_id("smb://10.0.0.9/karaoke/a/b") == smb.id
    assert s.resolve_target_id("local:/output") == "local"
    assert s.resolve_target_id(smb.id) == smb.id and s.resolve_target_id("local") == "local"
    assert s.resolve_target_id("smb://10.6.6.6/x") is None and s.resolve_target_id("t_gone0000") is None
    # адрес хранилища поменяли — старые задания всё равно находят его
    s.save_target(db.Target(**{**smb.__dict__, "host": "10.0.0.10", "secret": None}))
    assert s.resolve_target_id("smb://10.0.0.9/karaoke/a/b") == smb.id


# --------------------------------------------------------------------------- make_storage

def test_make_storage_by_target(tmp_path):
    loc = make_storage(db.Target(id="t_00000001", name="ПК", kind="local", path=str(tmp_path)))
    assert isinstance(loc, LocalStorage) and loc.target_id == "t_00000001"
    smb = make_storage(db.Target(id="t_00000002", name="Шара", kind="smb", host="h", share="s",
                                 path="p", user="u", secret=PW))
    assert isinstance(smb, SmbStorage) and smb.target_id == "t_00000002" and smb.label == "//h/s/p"
    with pytest.raises(StorageError, match="Неизвестный тип хранилища"):
        make_storage(db.Target(id="t_00000003", name="Я", kind="ftp"))


def test_migration_leaves_no_rows_with_legacy_id_on_collision(path):
    """Та же песня проиндексирована и под старым, и под новым id: сирот со старым не остаётся."""
    conn = db.connect(path)
    _put(conn, "output", {"kind": "local", "path": ""})
    _lib_row(conn, "local:/output")
    _lib_row(conn, "local")  # коллизия по (target_id, rel_dir) после переписывания
    _lib_row(conn, "local:/output", "C/C - D")
    db.Settings(conn, ENV_LOCAL).get_targets()
    rows = sorted(tuple(r) for r in conn.execute("SELECT target_id, rel_dir FROM library"))
    assert rows == [("local", "A/A - B"), ("local", "C/C - D")]
