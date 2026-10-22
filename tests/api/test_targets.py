"""REST хранилищ /api/targets: список, создание с проверкой, правка без пароля, основная цель,
удаление, обзор папок ПК, вход в Google Диск. Секреты и токены в ответах не появляются."""

from __future__ import annotations

import urllib.parse

import pytest

from fakes_http import FakeDrive, FakeHttp
from karaoke_core.http import HttpError
from karaoke_core.db import Settings, Target, connect
from karaoke_core.storage import LocalStorage

SMB_PASS = "smb-pass-for-test"
DAV_PASS = "dav-pass-for-test"
G_SECRET = "g-client-secret-for-test"
G_REFRESH = "g-refresh-for-test"
SECRETS = (SMB_PASS, DAV_PASS, G_SECRET, G_REFRESH)


def _no_secrets(r):
    for s in SECRETS:
        assert s not in r.text, r.text


class Net:
    """Фабрика хранилищ: сетевые типы — во временную папку ``net/<kind>``, запоминает цели."""

    def __init__(self, env, fail: set[str] | None = None):
        self.env, self.fail, self.seen = env, fail or set(), []

    def __call__(self, target: Target):
        self.seen.append(target)
        if target.kind == "local":
            return self.env.factory(target)
        root = self.env.tmp / "net" / target.kind
        if target.kind not in self.fail:
            root.mkdir(parents=True, exist_ok=True)
        return LocalStorage(root, target_id=target.id, label=target.label)


@pytest.fixture
def net(env):
    return Net(env)


@pytest.fixture
def api(env, net):
    with env.client(storage_factory=net, http=FakeHttp()) as c:
        yield c


def _settings(env) -> Settings:
    return Settings(connect(env.data / "karaoke.sqlite"))


SMB = {"kind": "smb", "name": "Пи", "host": "10.0.0.9", "share": "karaoke", "path": "songs", "user": "pi"}


def test_list_has_builtin_local_first(api):
    r = api.get("/api/targets")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_id"] == "local"
    assert body["targets"][0]["id"] == "local" and body["targets"][0]["builtin"] is True
    assert body["roots"]["output"] is True and isinstance(body["roots"]["host"], bool)


def test_create_smb_local_webdav_verified(env, api, net):
    r = api.post("/api/targets", json={**SMB, "password": SMB_PASS})
    assert r.status_code == 200, r.text
    _no_secrets(r)
    smb = r.json()
    assert smb["id"].startswith("t_") and smb["kind"] == "smb" and smb["has_password"] is True
    assert smb["label"] == "//10.0.0.9/karaoke/songs" and net.seen[-1].password == SMB_PASS

    (env.tmp / "host" / "Music").mkdir(parents=True)
    r = api.post("/api/targets", json={"kind": "local", "name": "Музыка", "path": "/host/Music"})
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "/host/Music"

    r = api.post("/api/targets", json={"kind": "webdav", "url": "https://dav.example/remote.php",
                                       "user": "me", "password": DAV_PASS, "path": "Karaoke"})
    assert r.status_code == 200, r.text
    _no_secrets(r)
    r = api.post("/api/targets", json={"kind": "yandex", "user": "me@yandex.ru", "password": DAV_PASS,
                                       "path": "Караоке"})
    assert r.status_code == 200, r.text
    ya = r.json()
    assert ya["kind"] == "webdav" and ya["preset"] == "yandex" and ya["url"] == "https://webdav.yandex.ru"
    assert ya["name"] == "Яндекс Диск"

    listing = api.get("/api/targets")
    _no_secrets(listing)
    assert [t["kind"] for t in listing.json()["targets"]] == ["local", "smb", "local", "webdav", "webdav"]
    assert _settings(env).get_target(smb["id"]).secret == SMB_PASS


def test_create_rejects_bad_input_and_unreachable(env, api, net):
    net.fail.add("webdav")
    r = api.post("/api/targets", json={"kind": "webdav", "url": "https://dav.example", "user": "me",
                                       "password": DAV_PASS})
    assert r.status_code == 400 and r.json()["detail"].startswith("Хранилище недоступно")
    r = api.post("/api/targets", json={"kind": "local", "path": "/host/../etc"})
    assert r.status_code == 400 and r.json()["field"] == "path"
    r = api.post("/api/targets", json={"kind": "local", "path": "/etc"})
    assert r.status_code == 400 and r.json()["field"] == "path"
    r = api.post("/api/targets", json={"kind": "smb", "share": "x"})
    assert r.status_code == 400 and r.json()["field"] == "host"
    r = api.post("/api/targets", json={"kind": "webdav", "url": "ftp://x"})
    assert r.status_code == 400 and r.json()["field"] == "url"
    r = api.post("/api/targets", json={"kind": "ftp"})
    assert r.status_code == 400 and r.json()["field"] == "kind"
    r = api.post("/api/targets", json={"kind": "gdrive", "client_id": "c", "password": G_SECRET})
    assert r.status_code == 400  # только через «Войти через Google»
    assert [t["id"] for t in api.get("/api/targets").json()["targets"]] == ["local"]


def test_pc_folder_cannot_be_output_root(api):
    for path in ("/output", "/output/"):
        r = api.post("/api/targets", json={"kind": "local", "path": path})
        assert r.status_code == 400 and r.json()["field"] == "path"
        assert r.json()["detail"] == "Это и есть «Локальное хранилище»"
    assert api.post("/api/targets", json={"kind": "local", "path": "/output/sub"}).status_code == 400  # нет папки
    assert [t["id"] for t in api.get("/api/targets").json()["targets"]] == ["local"]


def test_edit_without_password_keeps_secret_only_for_same_account(env, api, net):
    smb = api.post("/api/targets", json={**SMB, "password": SMB_PASS}).json()
    r = api.put(f"/api/targets/{smb['id']}", json={**SMB, "path": "other", "name": "Пи 2"})
    assert r.status_code == 200, r.text
    _no_secrets(r)
    assert r.json()["id"] == smb["id"] and r.json()["path"] == "other" and r.json()["has_password"] is True
    assert net.seen[-1].password == SMB_PASS
    assert _settings(env).get_target(smb["id"]).secret == SMB_PASS

    for change in ({"host": "10.6.6.6"}, {"share": "x"}, {"user": "admin"}):
        n = len(net.seen)
        r = api.put(f"/api/targets/{smb['id']}", json={**SMB, **change})
        assert r.status_code == 400 and r.json()["field"] == "password", r.text
        r = api.post("/api/targets/test", json={**SMB, **change, "id": smb["id"]})
        assert r.status_code == 400 and r.json()["field"] == "password"
        assert len(net.seen) == n  # прежний пароль на чужой адрес не ушёл

    r = api.post("/api/targets/test", json={**SMB, "id": smb["id"]})
    assert r.status_code == 200 and r.json()["ok"] is True and net.seen[-1].password == SMB_PASS
    assert api.put("/api/targets/local", json={"kind": "local", "path": "/output"}).status_code == 400
    assert api.put("/api/targets/t_missing", json=SMB).status_code == 404


def test_switch_default_keeps_storages_and_delete_rules(env, api):
    smb = api.post("/api/targets", json={**SMB, "password": SMB_PASS}).json()
    for target_id in (smb["id"], "local", smb["id"]):
        r = api.put("/api/targets/default", json={"id": target_id})
        assert r.status_code == 200, r.text
        assert r.json()["default_id"] == target_id
        _no_secrets(r)
    assert _settings(env).get_target(smb["id"]).secret == SMB_PASS  # SMB не потерялся

    r = api.delete(f"/api/targets/{smb['id']}")
    assert r.status_code == 409 and r.json()["detail"] == "Сначала выберите другую основную цель"
    assert api.delete("/api/targets/local").status_code == 400
    assert api.put("/api/targets/default", json={"id": "t_missing"}).status_code == 404

    api.put("/api/targets/default", json={"id": "local"})
    r = api.delete(f"/api/targets/{smb['id']}")
    assert r.status_code == 200, r.text
    assert [t["id"] for t in api.get("/api/targets").json()["targets"]] == ["local"]
    assert api.delete(f"/api/targets/{smb['id']}").status_code == 404


def test_delete_clears_library_index_but_not_files(env, api):
    (env.tmp / "host" / "pc" / "A" / "A - S").mkdir(parents=True)
    song = env.tmp / "host" / "pc" / "A" / "A - S"
    (song / "A - S.txt").write_bytes(env.SONG_TXT.replace(b"Artist - Song", b"A - S"))
    (song / "A - S.mp3").write_bytes(env.MP3)
    pc = api.post("/api/targets", json={"kind": "local", "path": "/host/pc"}).json()
    assert api.app.state.ctx.refresh_song("A/A - S", pc["id"]) is not None
    assert api.delete(f"/api/targets/{pc['id']}").status_code == 200
    rows = connect(env.data / "karaoke.sqlite").execute(
        "SELECT COUNT(*) FROM library WHERE target_id=?", (pc["id"],)).fetchone()[0]
    assert rows == 0 and (song / "A - S.txt").is_file()


def test_browse_lists_dirs_only_inside_root(env, api, monkeypatch):
    import app.api_targets as api_targets

    host = env.tmp / "hostroot"
    (host / "Music" / "Rock").mkdir(parents=True)
    (host / "Video").mkdir()
    (host / ".hidden").mkdir()
    (host / "file.txt").write_text("x")
    monkeypatch.setitem(api_targets.BROWSE_ROOTS, "host", str(host))
    monkeypatch.setitem(api_targets.BROWSE_ROOTS, "output", str(env.out))

    assert api.get("/api/targets").json()["roots"] == {"host": True, "output": True}
    r = api.get("/api/targets/browse", params={"root": "host"})
    assert r.status_code == 200, r.text
    assert r.json()["dirs"] == ["Music", "Video"] and r.json()["parent"] is None
    assert r.json()["abs"] == "/host"
    r = api.get("/api/targets/browse", params={"root": "host", "path": "Music"})
    assert r.json()["dirs"] == ["Rock"] and r.json()["abs"] == "/host/Music" and r.json()["parent"] == ""
    for bad in ("..", "Music/../..", "../etc"):
        r = api.get("/api/targets/browse", params={"root": "host", "path": bad})
        assert r.status_code == 400 and r.json()["field"] == "path"
    assert api.get("/api/targets/browse", params={"root": "etc"}).status_code == 400
    assert api.get("/api/targets/browse", params={"root": "host", "path": "nope"}).status_code == 404
    assert api.get("/api/targets/browse", params={"root": "output"}).status_code == 200

    (host / "Music" / "out").symlink_to(env.tmp)  # симлинк наружу не показывается и не открывается
    assert api.get("/api/targets/browse", params={"root": "host", "path": "Music"}).json()["dirs"] == ["Rock"]
    assert api.get("/api/targets/browse", params={"root": "host", "path": "Music/out"}).status_code == 400


# ---------------------------------------------------------------------- Google Диск

GDRIVE = {"client_id": "cid.apps.googleusercontent.com", "password": G_SECRET, "path": "Karaoke"}


def _google(env, net):
    """Веб с FakeHttp, где token endpoint Google отвечает ``FakeDrive`` (настоящий обмен кода)."""
    http = FakeHttp()
    drive = FakeDrive(http, env.tmp / "drive", client_id=GDRIVE["client_id"], client_key=G_SECRET)
    return env.client(storage_factory=net, http=http), http, drive


def _start(api) -> str:
    draft = api.post("/api/targets/gdrive/draft", json=GDRIVE).json()["draft"]
    api.get("/api/targets/gdrive/auth", params={"draft": draft}, follow_redirects=False)
    return draft


def test_gdrive_oauth_flow_saves_connected_target(env, net):
    client, http, drive = _google(env, net)
    drive.codes["the-code"] = G_REFRESH
    with client as api:
        r = api.post("/api/targets/gdrive/draft", json=GDRIVE)
        assert r.status_code == 200, r.text
        draft = r.json()["draft"]
        assert api.get(f"/api/targets/gdrive/draft/{draft}").json() == {"state": "pending"}

        r = api.get("/api/targets/gdrive/auth", params={"draft": draft}, follow_redirects=False)
        assert r.status_code == 302
        loc = urllib.parse.urlsplit(r.headers["location"])
        assert f"{loc.scheme}://{loc.netloc}{loc.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
        q = dict(urllib.parse.parse_qsl(loc.query))
        assert q["client_id"] == GDRIVE["client_id"] and q["state"] == draft
        assert q["redirect_uri"] == "http://testserver/api/targets/gdrive/callback"
        assert q["scope"] == "https://www.googleapis.com/auth/drive"
        assert q["access_type"] == "offline" and q["prompt"] == "consent" and q["response_type"] == "code"
        assert G_SECRET not in r.headers["location"]

        r = api.get("/api/targets/gdrive/callback", params={"state": draft, "code": "the-code"})
        assert r.status_code == 200 and "Google Диск подключён" in r.text
        _no_secrets(r)
        sent = http.calls(FakeDrive.TOKEN)[-1]
        assert sent.data["code"] == "the-code" and sent.data["redirect_uri"] == q["redirect_uri"]

        r = api.get(f"/api/targets/gdrive/draft/{draft}")
        _no_secrets(r)
        body = r.json()
        assert body["state"] == "connected"
        t = body["target"]
        assert t["kind"] == "gdrive" and t["connected"] is True and t["has_password"] is True
        assert t["path"] == "Karaoke" and t["name"] == "Google Диск"
        assert net.seen[-1].kind == "gdrive" and G_REFRESH in (net.seen[-1].token or "")
        stored = _settings(env).get_target(t["id"])
        assert stored.secret == G_SECRET and G_REFRESH in stored.token
        _no_secrets(api.get("/api/targets"))

        # правка пути без секрета: токен и Client secret остаются
        r = api.put(f"/api/targets/{t['id']}", json={**GDRIVE, "kind": "gdrive", "password": "", "path": "Other"})
        assert r.status_code == 200, r.text
        assert r.json()["connected"] is True and _settings(env).get_target(t["id"]).token == stored.token
        r = api.put(f"/api/targets/{t['id']}", json={**GDRIVE, "kind": "gdrive", "client_id": "new-id"})
        assert r.status_code == 400 and r.json()["field"] == "client_id"


def test_gdrive_exchange_error_or_denied_is_not_saved(env, net):
    client, _, _ = _google(env, net)
    with client as api:
        draft = _start(api)
        r = api.get("/api/targets/gdrive/callback", params={"state": draft, "code": "bad"})
        assert r.status_code == 400 and "Google не дал доступ" in r.text
        _no_secrets(r)
        body = api.get(f"/api/targets/gdrive/draft/{draft}").json()
        assert body["state"] == "error" and body["error"].startswith("Google не дал доступ")
        assert "Google не дал доступ: Google не дал доступ" not in body["error"]

        draft = api.post("/api/targets/gdrive/draft", json=GDRIVE).json()["draft"]
        r = api.get("/api/targets/gdrive/callback", params={"state": draft, "error": "access_denied"})
        assert r.status_code == 400
        assert api.get(f"/api/targets/gdrive/draft/{draft}").json()["error"] ==             "Google не дал доступ: access_denied"
        assert [t["id"] for t in api.get("/api/targets").json()["targets"]] == ["local"]

        assert api.get("/api/targets/gdrive/draft/nope").status_code == 404
        assert api.get("/api/targets/gdrive/callback", params={"state": "nope", "code": "x"}).status_code == 404
        r = api.post("/api/targets/gdrive/draft", json={**GDRIVE, "password": ""})
        assert r.status_code == 400 and r.json()["field"] == "password"
        r = api.post("/api/targets/gdrive/draft", json={**GDRIVE, "client_id": ""})
        assert r.status_code == 400 and r.json()["field"] == "client_id"


@pytest.mark.parametrize("err", [
    RuntimeError(f"boom {G_SECRET}"),
    HttpError("HTTP 500", 500, body=f'{{"refresh_token": "{G_REFRESH}"}}'.encode()),
    HttpError(f"Сбой связи с ключом {G_SECRET}", None),
])
def test_gdrive_unknown_error_shows_generic_text_without_secrets(env, net, monkeypatch, err):
    from karaoke_core.storage.gdrive import GDriveStorage

    def boom(*a, **kw):
        raise err

    monkeypatch.setattr(GDriveStorage, "exchange_code", staticmethod(boom))
    client, _, _ = _google(env, net)
    with client as api:
        draft = _start(api)
        r = api.get("/api/targets/gdrive/callback", params={"state": draft, "code": "c"})
        assert r.status_code == 400 and "Google не дал доступ, попробуйте ещё раз" in r.text
        _no_secrets(r)
        state = api.get(f"/api/targets/gdrive/draft/{draft}")
        _no_secrets(state)
        assert state.json()["error"] == "Google не дал доступ, попробуйте ещё раз"
