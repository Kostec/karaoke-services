"""Резервная копия настроек (истории 66–68): выгрузка без секретов, план загрузки, применение.

Шов — ``karaoke_core.backup``: ``export_settings``, ``read_backup``, ``plan_import``, ``apply_import``.
"""

import json

import pytest

from karaoke_core import backup, db
from karaoke_core.naming import song_tag_key

SMB_PW = "smb-pass-Secret1"
DAV_PW = "dav-pass-Secret2"
G_SECRET = "google-client-Secret3"
G_OAUTH = '{"refresh_token": "g-refresh-Secret4"}'
USDB_PW = "usdb-pass-Secret5"
YM = "ym-oauth-Secret6"
BOT = "123456:AAH-bot-Secret7"
SECRETS = [SMB_PW, DAV_PW, G_SECRET, "g-refresh-Secret4", USDB_PW, YM, BOT]


def _open(path):
    conn = db.connect(path)
    return db.Settings(conn, env={"OUTPUT_KIND": "local"}), db.Tags(conn)


@pytest.fixture
def home(tmp_path):
    return _open(tmp_path / "home.sqlite")


@pytest.fixture
def other(tmp_path):
    return _open(tmp_path / "other.sqlite")


def _fill(settings: db.Settings, tags: db.Tags) -> dict:
    """Установка со всеми видами настроек и всеми секретами."""
    pi = settings.save_target(db.Target(name="Pi", kind="smb", host="10.0.0.5", share="karaoke",
                                        path="songs", user="pi", secret=SMB_PW))
    disk = settings.save_target(db.Target(name="Диск", kind="webdav", url="https://webdav.yandex.ru",
                                          preset="yandex", path="Караоке", user="me", secret=DAV_PW))
    gd = settings.save_target(db.Target(name="Гугл", kind="gdrive", path="Karaoke", client_id="cid",
                                        secret=G_SECRET, token=G_OAUTH))
    pc = settings.save_target(db.Target(name="Папка", kind="local", path="/host/karaoke"))
    settings.set_default_target_id(pi.id)
    settings.set_usdb(db.UsdbAccount("singer", USDB_PW))
    settings.set_yandex(YM)
    settings.set_telegram(db.TelegramSettings(BOT, "248019337", True, False, True))
    mirror = settings.save_mirror(db.Mirror(from_target="local", to_target=pi.id, enabled=False))
    fav = tags.create("Любимое", "pink")
    duo = tags.create("Дуэты", "teal")
    k1, k2 = song_tag_key("Звери", "Районы"), song_tag_key("Би-2", "Полковник")
    tags.set_for_song(k1, [fav.id, duo.id])
    tags.set_for_song(k2, [fav.id])
    return {"pi": pi, "disk": disk, "gd": gd, "pc": pc, "mirror": mirror, "fav": fav, "duo": duo,
            "k1": k1, "k2": k2}


def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)


def test_export_has_settings_and_no_secrets(home):
    settings, tags = home
    s = _fill(settings, tags)
    data = backup.export_settings(settings, tags)
    text = json.dumps(data, ensure_ascii=False)

    for value in SECRETS:
        assert value not in text
    for key in _keys(data):
        assert not any(bad in key.lower() for bad in ("secret", "token", "password")), key

    assert data["format"] == "karaoke-services-settings" and data["version"] == 1
    assert data["created_at"]
    assert data["default_target_id"] == s["pi"].id
    assert [t["id"] for t in data["targets"]] == [s["pi"].id, s["disk"].id, s["gd"].id, s["pc"].id]
    assert data["targets"][0] == {"id": s["pi"].id, "name": "Pi", "kind": "smb", "path": "songs",
                                  "host": "10.0.0.5", "share": "karaoke", "user": "pi", "url": "",
                                  "preset": "", "client_id": ""}
    assert data["targets"][2]["client_id"] == "cid"
    by_name = {t["name"]: t for t in data["tags"]}
    assert by_name["Любимое"] == {"name": "Любимое", "color": "pink", "songs": sorted([s["k1"], s["k2"]])}
    assert by_name["Дуэты"]["songs"] == [s["k1"]]
    assert data["usdb"] == {"user": "singer"}
    assert data["telegram"] == {"chat_id": "248019337", "on_done": True, "on_failed": False,
                                "on_queue_empty": True}
    assert data["mirrors"] == [{"from_target": "local", "to_target": s["pi"].id, "enabled": False}]


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"[1, 2]", b'{"format": "other"}',
    b'{"format": "karaoke-services-settings", "version": 99}',
    b'{"format": "karaoke-services-settings", "version": 1, "targets": "x"}',
    b'{"format": "karaoke-services-settings", "version": 1, "tags": [{"name": 5}]}',
    b'{"format": "karaoke-services-settings", "version": 1, "targets": [{"id": "t_1", "kind": "ftp"}]}',
    "\xff\xfe".encode("latin-1"),
])
def test_foreign_or_broken_file_is_rejected(raw, home):
    settings, tags = home
    with pytest.raises(backup.BackupError) as e:
        backup.plan_import(backup.read_backup(raw), settings, tags)
    assert str(e.value) == "Это не файл настроек karaoke-services"


def test_plan_changes_nothing_then_apply_restores_on_new_install(home, other):
    s = _fill(*home)
    data = backup.read_backup(json.dumps(backup.export_settings(*home)).encode("utf-8"))
    settings, tags = other

    plan = backup.plan_import(data, settings, tags)
    assert plan.to_dict() == {
        "tags_added": 2, "tag_links_added": 3, "targets_added": 4, "targets_updated": 0,
        "mirrors_added": 1, "usdb_user_set": True, "needs_password": ["Pi", "Диск"],
        "needs_google": ["Гугл"], "default_target": "Pi", "telegram_set": True,
        "telegram_needs_token": True, "usdb_needs_password": True, "yandex_needs_token": True,
    }
    # предпросмотр ничего не записал
    assert [t.id for t in settings.get_targets()] == ["local"]
    assert tags.list() == [] and settings.get_mirrors() == []
    assert settings.get_usdb().user == "" and settings.get_telegram().chat_id == ""

    backup.apply_import(plan, settings, tags)
    assert [t.id for t in settings.get_targets()] == ["local", s["pi"].id, s["disk"].id, s["gd"].id,
                                                      s["pc"].id]
    pi = settings.get_target(s["pi"].id)
    assert (pi.name, pi.host, pi.share, pi.path, pi.user, pi.secret) == ("Pi", "10.0.0.5", "karaoke",
                                                                         "songs", "pi", None)
    assert settings.get_target(s["disk"].id).preset == "yandex"
    assert settings.get_default_target_id() == s["pi"].id
    assert {t.name: t.color for t in tags.list()} == {"Любимое": "pink", "Дуэты": "teal"}
    names = {t.id: t.name for t in tags.list()}
    got = {k: sorted(names[i] for i in ids) for k, ids in tags.for_songs([s["k1"], s["k2"]]).items()}
    assert got == {s["k1"]: ["Дуэты", "Любимое"], s["k2"]: ["Любимое"]}
    assert [(m.from_target, m.to_target, m.enabled) for m in settings.get_mirrors()] == \
        [("local", s["pi"].id, False)]
    assert settings.get_usdb() == db.UsdbAccount("singer", None)
    tg = settings.get_telegram()
    assert (tg.bot_token, tg.chat_id, tg.on_done, tg.on_failed, tg.on_queue_empty) == \
        (None, "248019337", True, False, True)

    # повторная загрузка того же файла ничего не добавляет
    again = backup.plan_import(data, settings, tags).to_dict()
    assert again["tags_added"] == again["tag_links_added"] == again["targets_added"] == 0
    assert again["targets_updated"] == again["mirrors_added"] == 0
    assert again["usdb_user_set"] is False and again["telegram_set"] is False
    assert again["default_target"] is None


def test_apply_keeps_secrets_and_deletes_nothing(home):
    settings, tags = home
    s = _fill(settings, tags)
    data = backup.export_settings(settings, tags)
    # в файле Pi переименовано, тег — другим регистром и другим цветом, в файле нет «Папки»
    data["targets"] = [dict(t, name="Малинка") if t["id"] == s["pi"].id else t
                       for t in data["targets"] if t["id"] != s["pc"].id]
    data["tags"] = [{"name": "любимое", "color": "red", "songs": [song_tag_key("Новый", "Хит")]}]
    data["mirrors"] = [{"from_target": s["pi"].id, "to_target": "local", "enabled": True}]  # обратное
    other_tag = tags.create("Своё")

    plan = backup.plan_import(data, settings, tags)
    d = plan.to_dict()
    assert (d["targets_added"], d["targets_updated"], d["tags_added"], d["tag_links_added"]) == (0, 1, 0, 1)
    assert d["mirrors_added"] == 0
    assert d["needs_password"] == [] and d["needs_google"] == []
    assert d["usdb_needs_password"] is False and d["yandex_needs_token"] is False
    assert d["telegram_needs_token"] is False
    backup.apply_import(plan, settings, tags)

    pi = settings.get_target(s["pi"].id)
    assert pi.name == "Малинка" and pi.secret == SMB_PW
    gd = settings.get_target(s["gd"].id)
    assert (gd.secret, gd.token) == (G_SECRET, G_OAUTH)
    assert settings.get_target(s["pc"].id) is not None  # не удалено
    assert settings.get_usdb().password == USDB_PW and settings.get_yandex() == YM
    assert settings.get_telegram().bot_token == BOT
    assert {t.name: t.color for t in tags.list()} == {"Любимое": "pink", "Дуэты": "teal", "Своё": "blue"}
    assert tags.get(other_tag.id) is not None
    assert tags.for_songs([s["k2"]])[s["k2"]] == [s["fav"].id]  # прежние связи на месте
    assert tags.for_songs([song_tag_key("Новый", "Хит")]) == {song_tag_key("Новый", "Хит"): [s["fav"].id]}
    assert len(settings.get_mirrors()) == 1


def test_other_usdb_login_is_not_overwritten(home):
    settings, tags = home
    settings.set_usdb(db.UsdbAccount("mine", USDB_PW))
    data = {"format": "karaoke-services-settings", "version": 1, "usdb": {"user": "theirs"}}
    plan = backup.plan_import(data, settings, tags)
    assert plan.to_dict()["usdb_user_set"] is False
    backup.apply_import(plan, settings, tags)
    assert settings.get_usdb() == db.UsdbAccount("mine", USDB_PW)


def test_mirror_to_unknown_target_and_local_target_are_skipped(home):
    settings, tags = home
    data = {"format": "karaoke-services-settings", "version": 1, "default_target_id": "t_gone0000",
            "targets": [{"id": "local", "name": "Чужое локальное", "kind": "local", "path": "/output"}],
            "mirrors": [{"from_target": "local", "to_target": "t_gone0000", "enabled": True}]}
    d = backup.plan_import(data, settings, tags).to_dict()
    assert (d["targets_added"], d["targets_updated"], d["mirrors_added"]) == (0, 0, 0)
    assert d["default_target"] is None
