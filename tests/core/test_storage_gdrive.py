"""GDriveStorage (Google Диск, Drive REST v3) на FakeHttp-эмуляции Drive и OAuth.

Общий контракт ``Storage`` — из ``test_storage.py`` (тесты с фикстурой ``env`` этого модуля);
Drive — ``fakes_http.FakeDrive`` поверх временной папки «Мой диск».
"""

import importlib.util
import json
import time
from pathlib import Path

import pytest

from fakes_http import FakeDrive, FakeHttp, response
from karaoke_core.db import Target
from karaoke_core.http import HttpError
from karaoke_core.storage import GDriveStorage, StorageError, StorageNotFound, make_storage

_spec = importlib.util.spec_from_file_location("_storage_contract_gd",
                                               Path(__file__).with_name("test_storage.py"))
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)

# Контракт целиком, кроме «первый кусок уже в .part»: загрузка уходит целиком при закрытии.
for _name in ("test_write_atomic_then_read_and_exists", "test_read_missing_raises_not_found",
              "test_paths_outside_root_are_rejected", "test_write_failure_leaves_no_file_and_no_part",
              "test_list_songs_depths_filters_encoding_duet", "test_list_songs_reports_existing_media",
              "test_upload_dir_writes_txt_last_via_part", "test_upload_interrupted_on_txt_leaves_no_ready_txt",
              "test_download_and_delete_dir", "test_delete_root_is_refused",
              "test_probe_writes_and_removes_file", "test_read_song_single_folder", "test_stat_file",
              "test_delete_last_song_removes_empty_artist_dir", "test_artist_dir_with_other_files_is_kept"):
    globals()[_name] = getattr(_contract, _name)

SOLO, put = _contract.SOLO, _contract.put
REVOKED = "Google Диск: доступ отозван — подключите заново в «Настройках»"


def oauth(drive: FakeDrive, *, access=None, expiry=None) -> str:
    return json.dumps({"access_token": access or drive.access, "refresh_token": drive.refresh,
                       "expiry": expiry if expiry is not None else time.time() + 3000})


@pytest.fixture
def drive(tmp_path):
    http = FakeHttp()
    disk = tmp_path / "mydrive"
    (disk / "Karaoke" / "Песни").mkdir(parents=True)
    return http, FakeDrive(http, disk, page_size=2), disk / "Karaoke" / "Песни"


def storage(drive, **kw) -> GDriveStorage:
    http, d, _ = drive
    return GDriveStorage("cid", "ckey", kw.pop("oauth", None) or oauth(d), kw.pop("path", "Karaoke/Песни"),
                         http=http, target_id="t_gd", label="Google", **kw)


@pytest.fixture
def env(drive):
    return storage(drive), drive[2]


def test_make_storage_builds_gdrive(drive):
    http, d, root = drive
    t = Target(id="t_0000000a", kind="gdrive", name="Гугл", client_id="cid", secret="ckey",
               token=oauth(d), path="Karaoke/Песни")
    st = make_storage(t, http=http)
    assert isinstance(st, GDriveStorage)
    assert (st.target_id, st.label) == (t.id, t.label)
    put(root, "A/A - B/A - B.txt", SOLO)
    assert [s.rel_dir for s in st.list_songs()] == ["A/A - B"]
    assert "ckey" not in repr(st) and d.refresh not in repr(st)


def test_expired_access_is_refreshed_on_401(drive):
    http, d, root = drive
    st = storage(drive)
    put(root, "A/f.txt", b"hello")
    d.expire()  # access-токен в st больше не годится
    assert st.read("A/f.txt") == b"hello"
    assert len(http.calls(FakeDrive.TOKEN)) == 1
    tok = http.calls(FakeDrive.TOKEN)[0].data
    assert tok["grant_type"] == "refresh_token" and tok["refresh_token"] == d.refresh
    st.write_atomic("A/g.txt", b"x")
    assert len(http.calls(FakeDrive.TOKEN)) == 1  # новый токен запомнен


def test_access_refreshed_before_expiry(drive):
    http, d, root = drive
    st = storage(drive, oauth=oauth(d, access="stale", expiry=time.time() - 10))
    put(root, "A/f.txt", b"1")
    assert st.read("A/f.txt") == b"1"
    assert len(http.calls(FakeDrive.TOKEN)) == 1
    assert not [r for r in http.requests if r.headers.get("Authorization") == "Bearer stale"]


def test_revoked_refresh_is_reported(drive):
    _, d, _ = drive
    st = storage(drive)
    d.revoked = True
    d.expire()
    with pytest.raises(StorageError) as e:
        st.probe()
    assert str(e.value) == REVOKED
    assert d.refresh not in str(e.value)


@pytest.mark.parametrize("status, cls", [(404, StorageNotFound), (403, StorageError), (500, StorageError)])
def test_http_errors_are_russian(drive, status, cls):
    http, d, root = drive
    st = storage(drive)
    put(root, "A/f.txt", b"1")
    st.stat("A/f.txt")
    http.route("GET", FakeDrive.API + "/", status=status)  # длиннее префикс — перехватывает файлы
    with pytest.raises(cls) as e:
        st.read("A/f.txt")
    assert d.access not in str(e.value)


def test_network_error_is_unavailable(drive):
    http, _, _ = drive
    st = storage(drive)
    http.route("GET", FakeDrive.API, HttpError("Нет связи с сервером www.googleapis.com"))
    with pytest.raises(StorageError) as e:
        st.list_songs()
    assert "Хранилище недоступно" in str(e.value) and not isinstance(e.value, StorageNotFound)


def test_probe_creates_missing_folder(drive):
    _, _, root = drive
    st = storage(drive, path="Karaoke/Новая/Папка")
    st.probe()
    new = root.parent / "Новая" / "Папка"
    assert new.is_dir() and list(new.iterdir()) == []


def test_replace_failure_keeps_old_file(drive):
    http, d, root = drive
    st = storage(drive)
    st.write_atomic("A/x.txt", b"old")

    def patch(req):
        if json.loads(req.data or b"{}").get("name") == "x.txt" and req.query.get("fields"):
            src = d._rel(d._file_id(req.url, FakeDrive.API))
            if src and src.endswith(".part"):
                return HttpError("Нет связи с сервером www.googleapis.com")
        return d._api(req)
    http.route("PATCH", FakeDrive.API, patch)
    with pytest.raises(StorageError):
        st.write_atomic("A/x.txt", b"new")
    assert (root / "A/x.txt").read_bytes() == b"old"
    assert storage(drive).read("A/x.txt") == b"old"
    assert sorted(p.name for p in (root / "A").iterdir()) == ["x.txt"]


@pytest.fixture
def sleeps(monkeypatch):
    from karaoke_core.storage import gdrive
    got = []
    monkeypatch.setattr(gdrive, "SLEEP", got.append)
    return got


@pytest.mark.parametrize("fail", [
    dict(status=429),
    dict(status=403, json={"error": {"errors": [{"reason": "rateLimitExceeded"}], "code": 403}}),
    dict(status=403, json={"error": {"errors": [{"reason": "userRateLimitExceeded"}], "code": 403}}),
])
def test_rate_limit_is_retried(drive, sleeps, fail):
    http, d, root = drive
    st = storage(drive)
    put(root, "A/f.txt", b"1")
    st.stat("A/f.txt")
    left = [2]

    def media(req):
        if left[0]:
            left[0] -= 1
            return response(**fail)
        return d._api(req)
    http.route("GET", FakeDrive.API + "/", media)
    assert st.read("A/f.txt") == b"1"
    assert sleeps == [1, 2]


def test_rate_limit_gives_up_after_three_retries(drive, sleeps):
    http, _, _ = drive
    st = storage(drive)
    http.route("GET", FakeDrive.API, status=429)
    with pytest.raises(StorageError) as e:
        st.list_songs()
    assert str(e.value) == "Google Диск: превышен лимит запросов, попробуйте позже"
    assert sleeps == [1, 2, 4]


def test_replace_overwrites_same_name_without_duplicates(env):
    st, root = env
    st.write_atomic("A/x.txt", b"one")
    st.write_atomic("A/x.txt", b"two")
    assert st.read("A/x.txt") == b"two"
    assert sorted(p.name for p in (root / "A").iterdir()) == ["x.txt"]


def test_list_songs_lists_each_folder_once(drive):
    http, _, root = drive
    st = storage(drive)
    for a, t in (("A", "B"), ("A", "C"), ("D", "E")):
        put(root, f"{a}/{a} - {t}/{a} - {t}.txt", SOLO)
        put(root, f"{a}/{a} - {t}/{a} - {t}.mp3", b"m")
    http.requests.clear()
    assert len(st.list_songs()) == 3
    listing = [r.query for r in http.requests if r.method == "GET" and r.url.startswith(FakeDrive.API + "?")]
    media = [r for r in http.requests if r.query.get("alt") == "media"]
    # каждая из 6 папок листается один раз (страницы по 2 — продолжения с pageToken не в счёт)
    folder_lists = [q["q"] for q in listing if "name=" not in q["q"] and not q.get("pageToken")]
    assert len(folder_lists) == 6 and len(set(folder_lists)) == 6
    assert len([q for q in listing if "name=" in q["q"]]) <= 2  # поиск базового пути «Karaoke/Песни»
    assert len(media) == 3


def test_exchange_code_returns_token_json(drive):
    http, d, root = drive
    d.codes["code-1"] = "refresh-new"
    raw = GDriveStorage.exchange_code(http, "cid", "ckey", "code-1", "http://localhost:8090/cb")
    tok = json.loads(raw)
    assert tok["refresh_token"] == "refresh-new" and tok["access_token"] == d.access
    assert tok["expiry"] > time.time() + 3000
    sent = http.calls(FakeDrive.TOKEN)[0].data
    assert sent["grant_type"] == "authorization_code" and sent["redirect_uri"] == "http://localhost:8090/cb"
    put(root, "A/A - B/A - B.txt", SOLO)
    st = GDriveStorage("cid", "ckey", raw, "Karaoke/Песни", http=http, target_id="t", label="G")
    assert len(st.list_songs()) == 1


def test_exchange_code_failure_is_russian(drive):
    http, _, _ = drive
    with pytest.raises(StorageError) as e:
        GDriveStorage.exchange_code(http, "cid", "ckey", "bad-code", "http://localhost/cb")
    assert str(e.value).startswith("Google не дал доступ")
