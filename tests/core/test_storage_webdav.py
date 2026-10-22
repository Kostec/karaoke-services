"""WebDavStorage (Яндекс Диск и любой WebDAV) на FakeHttp-эмуляции сервера.

Общий контракт ``Storage`` берётся из ``test_storage.py`` (те же тесты с фикстурой ``env``
этого модуля); сервер — ``fakes_http.FakeWebDav`` поверх временной папки.
"""

import importlib.util
from pathlib import Path

import pytest

from fakes_http import FakeHttp, FakeWebDav
from karaoke_core.db import Target
from karaoke_core.http import HttpError
from karaoke_core.storage import StorageError, StorageNotFound, WebDavStorage, make_storage

_spec = importlib.util.spec_from_file_location("_storage_contract",
                                               Path(__file__).with_name("test_storage.py"))
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)

# Контракт целиком, кроме «первый кусок уже в .part»: WebDAV пишет во временный файл
# и отправляет PUT целиком при закрытии (так решено в спецификации).
for _name in ("test_write_atomic_then_read_and_exists", "test_read_missing_raises_not_found",
              "test_paths_outside_root_are_rejected", "test_write_failure_leaves_no_file_and_no_part",
              "test_list_songs_depths_filters_encoding_duet", "test_list_songs_reports_existing_media",
              "test_upload_dir_writes_txt_last_via_part", "test_upload_interrupted_on_txt_leaves_no_ready_txt",
              "test_download_and_delete_dir", "test_delete_root_is_refused",
              "test_probe_writes_and_removes_file", "test_read_song_single_folder", "test_stat_file",
              "test_delete_last_song_removes_empty_artist_dir", "test_artist_dir_with_other_files_is_kept"):
    globals()[_name] = getattr(_contract, _name)

SOLO, put = _contract.SOLO, _contract.put
URL = "https://webdav.example.org/remote.php/dav"
PW = "app-pw-SECRET-123"


@pytest.fixture
def server(tmp_path):
    http = FakeHttp()
    disk = tmp_path / "disk"
    (disk / "Karaoke" / "Мои песни").mkdir(parents=True)
    return http, FakeWebDav(http, URL, disk, "user", PW), disk / "Karaoke" / "Мои песни"


@pytest.fixture
def env(server):
    http, _, root = server
    return WebDavStorage(URL, "user", PW, "Karaoke/Мои песни", http=http, target_id="t_dav", label="Диск"), root


def test_make_storage_builds_webdav(server):
    http, _, root = server
    t = Target(id="t_00000009", kind="webdav", name="Яндекс", url=URL, user="user", secret=PW,
               path="Karaoke/Мои песни", preset="yandex")
    st = make_storage(t, http=http)
    assert isinstance(st, WebDavStorage)
    assert (st.target_id, st.label) == (t.id, t.label)
    put(root, "A/A - B/A - B.txt", SOLO)
    assert [s.rel_dir for s in st.list_songs()] == ["A/A - B"]
    assert PW not in repr(st)


@pytest.mark.parametrize("fail, cls, text", [
    (401, StorageError, "Неверный логин или пароль приложения"),
    (403, StorageError, "Неверный логин или пароль приложения"),
    (HttpError("Нет связи с сервером webdav.example.org"), StorageError, "Хранилище недоступно"),
])
def test_errors_are_russian_without_password(server, env, fail, cls, text):
    _, dav, _ = server
    st, _ = env
    dav.fail = fail
    for op in (lambda: st.read("A/x.txt"), lambda: st.write_atomic("A/x.txt", b"1"),
               st.list_songs, st.probe):
        with pytest.raises(cls) as e:
            op()
        assert text in str(e.value) and PW not in str(e.value)
        assert not isinstance(e.value, StorageNotFound)


def test_wrong_password_is_reported(server):
    http, _, _ = server
    st = WebDavStorage(URL, "user", "wrong", "Karaoke/Мои песни", http=http, target_id="t", label="Диск")
    with pytest.raises(StorageError) as e:
        st.probe()
    assert "Неверный логин или пароль приложения" in str(e.value)


def test_probe_creates_missing_folder(server):
    http, _, root = server
    st = WebDavStorage(URL, "user", PW, "Karaoke/Новая/Папка", http=http, target_id="t", label="Диск")
    st.probe()
    new = root.parent / "Новая" / "Папка"
    assert new.is_dir() and list(new.iterdir()) == []


def test_list_songs_lists_each_folder_once(server, env):
    http, _, root = server
    st, _ = env
    for a, t in (("A", "B"), ("A", "C"), ("D", "E")):
        put(root, f"{a}/{a} - {t}/{a} - {t}.txt", SOLO)
        put(root, f"{a}/{a} - {t}/{a} - {t}.mp3", b"m")
    http.requests.clear()
    assert len(st.list_songs()) == 3
    propfinds = [r.url for r in http.requests if r.method == "PROPFIND"]
    gets = [r.url for r in http.requests if r.method == "GET"]
    # корень + 2 исполнителя + 3 песни — по одному листингу на папку; .txt — по одному GET
    assert len(propfinds) == 6 and len(set(propfinds)) == 6
    assert len(gets) == 3
