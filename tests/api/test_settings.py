"""Настройки папки результата: пароль не возвращается, пустой = не менять, проверка цели."""

from karaoke_core.db import OutputTarget, Settings, connect

SECRET = "pi-pass-for-test"


def _store_smb(env):
    Settings(connect(env.data / "karaoke.sqlite")).set_output(OutputTarget(
        kind="smb", host="10.0.0.9", share="karaoke", path="", user="pi", password=SECRET))


def test_get_never_returns_password(env, client):
    _store_smb(env)
    r = client.get("/api/settings/output")
    assert r.status_code == 200 and SECRET not in r.text
    body = r.json()
    assert body["has_password"] is True and "password" not in body
    assert body["kind"] == "smb" and body["label"] == "//10.0.0.9/karaoke"


def test_put_local_verified_and_saved(env, client):
    (env.out / "songs").mkdir()
    r = client.put("/api/settings/output", json={"kind": "local", "path": "songs"})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "/output/songs" and r.json()["kind"] == "local"
    assert client.get("/api/settings/output").json()["path"] == "songs"
    assert list((env.out / "songs").iterdir()) == []  # пробный файл убран


def test_put_rejects_unreachable_target_and_keeps_old(env, client):
    r = client.put("/api/settings/output", json={"kind": "local", "path": "missing"})
    assert r.status_code == 400 and r.json()["detail"].startswith("Папка результата недоступна")
    assert client.get("/api/settings/output").json()["path"] == ""
    r = client.put("/api/settings/output", json={"kind": "local", "path": "../etc"})
    assert r.status_code == 400 and r.json()["detail"] == "Недопустимый путь"
    r = client.put("/api/settings/output", json={"kind": "smb", "host": "", "share": "x"})
    assert r.status_code == 400 and r.json()["detail"] == "Укажите адрес сервера и имя шары"
    r = client.put("/api/settings/output", json={"kind": "ftp"})
    assert r.status_code == 400


def test_put_without_password_keeps_previous(env):
    _store_smb(env)
    seen = []

    def fake_factory(target):
        seen.append(target.password)
        return env.factory(OutputTarget(kind="local"))

    with env.client(storage_factory=fake_factory) as client:
        r = client.put("/api/settings/output", json={"kind": "smb", "host": "10.0.0.9", "share": "karaoke",
                                                     "path": "songs", "user": "pi", "password": ""})
        assert r.status_code == 200 and SECRET not in r.text
        assert seen[-1] == SECRET
        assert Settings(connect(env.data / "karaoke.sqlite")).get_output().password == SECRET

        # другой сервер / логин — прежний пароль туда не уходит
        for change in ({"host": "10.6.6.6"}, {"share": "other"}, {"user": "admin"}):
            body = {"kind": "smb", "host": "10.0.0.9", "share": "karaoke", "user": "pi", **change}
            n = len(seen)
            r = client.put("/api/settings/output", json=body)
            assert r.status_code == 400 and r.json()["detail"] == "Введите пароль: сервер, шара или логин изменились"
            r = client.post("/api/settings/output/test", json=body)
            assert r.status_code == 400 and len(seen) == n


def test_output_test_endpoint(env, client):
    r = client.post("/api/settings/output/test", json={"kind": "local", "path": ""})
    assert r.status_code == 200 and r.json() == {"ok": True, "label": "/output"}
    r = client.post("/api/settings/output/test", json={"kind": "local", "path": "missing"})
    assert r.status_code == 400 and "недоступна" in r.json()["detail"]
