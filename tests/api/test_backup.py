"""REST резервной копии настроек (истории 66–68): скачивание без секретов, предпросмотр и применение."""

import json
import re

from karaoke_core.db import Settings, Tags, Target, TelegramSettings, UsdbAccount, connect

SMB_PW = "smb-pass-Secret1"
USDB_PW = "usdb-pass-Secret5"
BOT = "123456:AAH-bot-Secret7"
NOT_SETTINGS = "Это не файл настроек karaoke-services"


def _db(env):
    conn = connect(env.data / "karaoke.sqlite")
    return Settings(conn), Tags(conn)


def _upload(client, raw: bytes, apply: int):
    return client.post(f"/api/settings/backup?apply={apply}",
                       files={"file": ("karaoke-settings.json", raw, "application/json")})


def test_download_is_attachment_without_secrets(env, client):
    settings, tags = _db(env)
    pi = settings.save_target(Target(name="Pi", kind="smb", host="10.0.0.5", share="k", user="pi",
                                     secret=SMB_PW))
    settings.set_usdb(UsdbAccount("singer", USDB_PW))
    settings.set_telegram(TelegramSettings(BOT, "42"))
    tags.create("Любимое")

    r = client.get("/api/settings/backup")
    assert r.status_code == 200, r.text
    assert re.fullmatch(r'attachment; filename="karaoke-settings-\d{4}-\d{2}-\d{2}\.json"',
                        r.headers["content-disposition"])
    for value in (SMB_PW, USDB_PW, BOT):
        assert value not in r.text
    assert not re.search(r'"[^"]*(secret|token|password)[^"]*"\s*:', r.text, re.I)
    data = r.json()
    assert data["format"] == "karaoke-services-settings"
    assert [t["id"] for t in data["targets"]] == [pi.id]
    assert data["usdb"] == {"user": "singer"} and data["telegram"]["chat_id"] == "42"


def test_preview_then_apply_then_repeat_adds_nothing(env, client):
    settings, tags = _db(env)
    pi = settings.save_target(Target(name="Pi", kind="smb", host="10.0.0.5", share="k", user="pi",
                                     secret=SMB_PW))
    tags.create("Любимое", "pink")
    raw = client.get("/api/settings/backup").content
    # «другая установка»: файл с новым хранилищем и тегом, которых здесь нет
    data = json.loads(raw)
    data["targets"].append({"id": "t_0badc0de", "name": "Диск", "kind": "webdav",
                            "url": "https://webdav.yandex.ru", "preset": "yandex", "user": "me", "path": "K"})
    data["tags"].append({"name": "Дуэты", "color": "teal", "songs": ["пара\nдуэт"]})
    data["mirrors"] = [{"from_target": "local", "to_target": "t_0badc0de", "enabled": True}]
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")

    r = _upload(client, raw, 0)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert (plan["targets_added"], plan["targets_updated"], plan["tags_added"], plan["tag_links_added"],
            plan["mirrors_added"]) == (1, 0, 1, 1, 1)
    assert plan["needs_password"] == ["Диск"] and plan["needs_google"] == []
    assert plan["yandex_needs_token"] is True
    assert settings.get_target("t_0badc0de") is None and len(tags.list()) == 1  # предпросмотр

    r = _upload(client, raw, 1)
    assert r.status_code == 200, r.text
    assert r.json()["targets_added"] == 1
    assert settings.get_target("t_0badc0de").name == "Диск"
    assert settings.get_target(pi.id).secret == SMB_PW
    assert {t.name for t in tags.list()} == {"Любимое", "Дуэты"}
    assert client.get("/api/targets").json()["targets"][-1]["id"] == "t_0badc0de"

    again = _upload(client, raw, 1).json()
    assert sum(again[k] for k in ("targets_added", "targets_updated", "tags_added", "tag_links_added",
                                  "mirrors_added")) == 0


def test_foreign_or_broken_file_is_400(client):
    for raw in (b"{oops", b'{"format": "something-else", "version": 1}', b"[]"):
        r = _upload(client, raw, 0)
        assert r.status_code == 400, raw
        assert r.json()["detail"] == NOT_SETTINGS
    r = client.post("/api/settings/backup?apply=0")
    assert r.status_code == 400 and r.json()["detail"] == NOT_SETTINGS
