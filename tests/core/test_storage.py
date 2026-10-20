"""Контракт ``Storage``: один набор тестов для LocalStorage и SmbStorage.

SmbStorage здесь работает через подменённый клиент ``smbclient``, который
отображает ``\\\\host\\share\\...`` во временную папку и ведёт себя как
настоящий (ошибки — ``SMBOSError`` с NTSTATUS). Реальная шара проверяется
в ``test_storage_smb_integration.py`` и только при заданных ``TEST_SMB_*``.
"""

import io
import os
import shutil
from pathlib import Path

import pytest
from smbprotocol.exceptions import SMBOSError
from smbprotocol.header import NtStatus

from karaoke_core import naming
from karaoke_core.db import OutputTarget
from karaoke_core.storage import (LocalStorage, SmbStorage, StorageError, StorageNotFound,
                                  make_storage)

FIX = Path(__file__).parent / "fixtures"

SOLO = ("#TITLE:Песня\n#ARTIST:Исполнитель\n#MP3:Исполнитель - Песня.mp3\n"
        "#COVER:Исполнитель - Песня [CO].jpg\n#INSTRUMENTAL:Исполнитель - Песня [Instrumental].mp3\n"
        "#BPM:300\n#GAP:0\n: 0 4 1 Ля\n- 6\n: 8 4 2 ля\nE\n").encode("utf-8")
NO_NOTES = b"#TITLE:Only header\n#ARTIST:X\n#BPM:300\nE\n"
LYRICS = b"Just some lyrics\nwithout headers\n"


# --------------------------------------------------------------------------- fake smbclient

class FakeSmbClient:
    """Минимальная копия API ``smbclient`` поверх локальной папки."""

    def __init__(self, root: Path, host: str = "pi", share: str = "karaoke"):
        self.root = root
        self.prefix = f"\\\\{host}\\{share}".lower()
        self.sessions = []
        self.register_error = None

    def _p(self, unc: str) -> Path:
        assert unc.lower().startswith(self.prefix), unc
        rest = unc[len(self.prefix):].strip("\\")
        return self.root.joinpath(*[x for x in rest.split("\\") if x])

    def _wrap(self, fn, unc, *a):
        try:
            return fn(*a)
        except FileNotFoundError:
            raise SMBOSError(NtStatus.STATUS_OBJECT_NAME_NOT_FOUND, unc)
        except FileExistsError:
            raise SMBOSError(NtStatus.STATUS_OBJECT_NAME_COLLISION, unc)

    def register_session(self, server, username=None, password=None, port=445, **kw):
        if self.register_error is not None:
            raise self.register_error
        self.sessions.append((server, username, port))

    def open_file(self, path, mode="r", **kw):
        return self._wrap(open, path, self._p(path), mode)

    class _Entry:
        def __init__(self, p: Path):
            self.name, self.path, self._p = p.name, str(p), p

        def is_dir(self):
            return self._p.is_dir()

        def is_file(self):
            return self._p.is_file()

        def stat(self):
            return self._p.stat()

    def scandir(self, path, **kw):
        p = self._p(path)
        if not p.is_dir():
            raise SMBOSError(NtStatus.STATUS_OBJECT_NAME_NOT_FOUND, path)
        return iter([self._Entry(c) for c in sorted(p.iterdir())])

    def stat(self, path, **kw):
        return self._wrap(os.stat, path, self._p(path))

    def makedirs(self, path, exist_ok=False, **kw):
        return self._wrap(os.makedirs, path, self._p(path), 0o777, exist_ok)

    def replace(self, src, dst, **kw):
        return self._wrap(os.replace, src, self._p(src), self._p(dst))

    def remove(self, path, **kw):
        return self._wrap(os.remove, path, self._p(path))

    def rmdir(self, path, **kw):
        return self._wrap(os.rmdir, path, self._p(path))


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(params=["local", "smb"])
def env(request, tmp_path):
    """(storage, root) — хранилище и папка, в которой физически лежат его файлы."""
    root = tmp_path / "out"
    root.mkdir()
    if request.param == "local":
        return LocalStorage(str(root)), root
    share = tmp_path / "share"
    (share / "Karaoke" / "Songs").mkdir(parents=True)
    fake = FakeSmbClient(share)
    st = SmbStorage("pi", "karaoke", "Karaoke/Songs", "user", "s3cret-pw", client=fake)
    return st, share / "Karaoke" / "Songs"


def put(root: Path, rel: str, data: bytes):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


# --------------------------------------------------------------------------- read / write

def test_write_atomic_then_read_and_exists(env):
    st, root = env
    st.write_atomic("A/A - B/A - B.txt", SOLO)
    st.write_atomic("A/A - B/A - B.mp3", io.BytesIO(b"x" * 300_000))
    assert (root / "A/A - B/A - B.txt").read_bytes() == SOLO
    assert st.read("A/A - B/A - B.txt") == SOLO
    with st.open_read("A/A - B/A - B.mp3") as f:
        assert f.read() == b"x" * 300_000
    assert st.exists("A/A - B/A - B.txt") and st.exists("A/A - B")
    assert not st.exists("A/A - C")
    assert not [p for p in root.rglob("*.part")]


def test_read_missing_raises_not_found(env):
    st, _ = env
    with pytest.raises(StorageNotFound):
        st.read("nope/x.txt")


def test_paths_outside_root_are_rejected(env):
    st, _ = env
    for bad in ("../x.txt", "A/../../x.txt", "/etc/passwd"):
        with pytest.raises(StorageError):
            st.write_atomic(bad, b"1")


def test_write_failure_leaves_no_file_and_no_part(env):
    st, root = env

    class Broken(io.RawIOBase):
        def __init__(self):
            self.n = 0

        def readable(self):
            return True

        def readinto(self, b):
            self.n += 1
            if self.n > 1:
                raise OSError("обрыв")
            b[:4] = b"abcd"
            return 4

    with pytest.raises(Exception):
        st.write_atomic("A/A - B/A - B.txt", Broken())
    assert not (root / "A/A - B/A - B.txt").exists()
    assert not list(root.rglob("*.part"))


# --------------------------------------------------------------------------- list_songs

def test_list_songs_depths_filters_encoding_duet(env):
    st, root = env
    put(root, "d1/Song1.txt", SOLO)
    put(root, "d1/d2/Song2.txt", SOLO)
    put(root, "d1/d2/d3/Song3.txt", SOLO)
    put(root, "a/b/d3/d4/Song4.txt", SOLO)
    put(root, "a/b/c/d/e/Song5.txt", SOLO)  # глубина 5 — не ищем
    put(root, "USDB/Зимняя вишня/song.txt", (FIX / "usdb_cp1251.txt").read_bytes())
    put(root, "Duo/Duo - Duet/Duo - Duet.txt", (FIX / "duet.txt").read_bytes())
    put(root, "Duo/Duo - Duet/Duo - Duet.lyrics.txt", LYRICS)
    put(root, "Junk/readme.txt", NO_NOTES)
    put(root, "Junk/notes.txt", LYRICS)

    songs = {s.rel_dir: s for s in st.list_songs()}
    assert set(songs) == {"d1", "d1/d2", "d1/d2/d3", "a/b/d3/d4",
                          "USDB/Зимняя вишня", "Duo/Duo - Duet"}

    usdb = songs["USDB/Зимняя вишня"]
    assert (usdb.artist, usdb.title, usdb.txt_name) == ("Исполнитель USDB", "Зимняя вишня", "song.txt")
    assert usdb.is_duet is False

    duet = songs["Duo/Duo - Duet"]
    assert duet.is_duet is True and duet.txt_name == "Duo - Duet.txt"
    assert (duet.artist, duet.title) == ("Он и Она", "Дуэт")

    s1 = songs["d1"]
    assert s1.audio is None  # #MP3 указывает на файл, которого нет
    assert s1.mtime and s1.mtime > 0


def test_list_songs_reports_existing_media(env):
    st, root = env
    d = "Исполнитель/Исполнитель - Песня"
    put(root, f"{d}/Исполнитель - Песня.txt", SOLO)
    put(root, f"{d}/Исполнитель - Песня.mp3", b"a")
    put(root, f"{d}/Исполнитель - Песня [CO].jpg", b"c")
    [s] = st.list_songs()
    assert s.audio == "Исполнитель - Песня.mp3"
    assert s.cover == "Исполнитель - Песня [CO].jpg"
    assert s.instrumental is None  # в заголовке есть, файла нет
    item = s.to_library_item("t1", scanned_at="now")
    assert (item.target_id, item.rel_dir, item.artist) == ("t1", d, "Исполнитель")


# --------------------------------------------------------------------------- upload / download / delete

def _song_src(tmp_path) -> Path:
    src = tmp_path / "src" / "A - B"
    src.mkdir(parents=True)
    (src / "A - B.txt").write_bytes(SOLO)
    (src / "A - B.mp3").write_bytes(b"m" * 1000)
    (src / "A - B [Instrumental].mp3").write_bytes(b"i" * 500)
    (src / "A - B [CO].jpg").write_bytes(b"c" * 10)
    return src


def test_upload_dir_writes_txt_last_via_part(env, tmp_path):
    st, root = env
    order = []
    orig = st.write_atomic

    def spy(rel, data):
        order.append(rel)
        return orig(rel, data)

    st.write_atomic = spy
    st.upload_dir(_song_src(tmp_path), "A/A - B")
    assert order[-1] == "A/A - B/A - B.txt"
    assert len(order) == 4
    assert sorted(p.name for p in (root / "A/A - B").iterdir()) == sorted(
        p.name for p in _song_src(tmp_path / "again").iterdir())
    assert st.sizes("A/A - B") == {"A - B.txt": len(SOLO), "A - B.mp3": 1000,
                                   "A - B [Instrumental].mp3": 500, "A - B [CO].jpg": 10}


def test_upload_interrupted_on_txt_leaves_no_ready_txt(env, tmp_path):
    st, root = env
    orig = st.write_atomic

    class Dying(io.RawIOBase):
        def readable(self):
            return True

        def readinto(self, b):
            raise OSError("сеть упала")

    def flaky(rel, data):
        if rel.endswith(".txt"):
            return orig(rel, Dying())
        return orig(rel, data)

    st.write_atomic = flaky
    with pytest.raises(Exception):
        st.upload_dir(_song_src(tmp_path), "A/A - B")
    assert not (root / "A/A - B/A - B.txt").exists()
    assert not list(root.rglob("*.part"))
    assert st.list_songs() == []


def test_download_and_delete_dir(env, tmp_path):
    st, root = env
    st.upload_dir(_song_src(tmp_path), "A/A - B")
    local = tmp_path / "dl"
    st.download_dir("A/A - B", local)
    assert (local / "A - B.txt").read_bytes() == SOLO
    assert (local / "A - B.mp3").stat().st_size == 1000
    st.delete_dir("A/A - B")
    assert not st.exists("A/A - B")
    assert not (root / "A/A - B").exists()


def test_delete_root_is_refused(env):
    st, _ = env
    with pytest.raises(StorageError):
        st.delete_dir("")


def test_probe_writes_and_removes_file(env):
    st, root = env
    before = set(root.iterdir())
    st.probe()
    assert set(root.iterdir()) == before


def test_probe_fails_for_missing_folder(tmp_path):
    with pytest.raises(StorageError) as e:
        LocalStorage(str(tmp_path / "nope")).probe()
    assert "не найдена" in str(e.value)


# --------------------------------------------------------------------------- make_storage

def test_make_storage_by_kind():
    st = make_storage(OutputTarget(kind="smb", host="h", share="s", path="p", user="u",
                                   password="pw"))
    assert isinstance(st, SmbStorage)
    assert st.target_id == "smb://h/s/p"
    loc = make_storage(OutputTarget(kind="local", path="songs"))
    assert isinstance(loc, LocalStorage) and loc.target_id == "local:/output/songs"


# --------------------------------------------------------------------------- ошибки SMB

PW = "s3cret-pw"


def _response_exc(cls, status):
    from smbprotocol.header import SMB2HeaderResponse
    h = SMB2HeaderResponse()
    h["status"] = status
    return cls(h)


def _smb_errors():
    from smbprotocol.exceptions import BadNetworkName, LogonFailure, SMBAuthenticationError
    return {
        "no_host": (ValueError(f"Failed to connect to 'pi:445': [Errno 113] No route to host"),
                    "недоступен"),
        "dns": (OSError(-2, "Name or service not known"), "недоступен"),
        "logon": (_response_exc(LogonFailure, NtStatus.STATUS_LOGON_FAILURE),
                  "Неверный логин или пароль"),
        "auth": (SMBAuthenticationError(f"Failed to authenticate with password {PW}"),
                 "Неверный логин или пароль"),
        "no_share": (_response_exc(BadNetworkName, NtStatus.STATUS_BAD_NETWORK_NAME),
                     "Шара «karaoke» не найдена"),
        "no_share_os": (SMBOSError(NtStatus.STATUS_BAD_NETWORK_NAME, r"\\pi\karaoke " + PW),
                        "Шара «karaoke» не найдена"),
        "other": (RuntimeError(f"unexpected failure for password={PW}"), "Ошибка Samba"),
    }


@pytest.mark.parametrize("case", ["no_host", "dns", "logon", "auth", "no_share", "no_share_os", "other"])
@pytest.mark.parametrize("op", ["probe", "list_songs", "write"])
def test_smb_errors_are_russian_and_hide_password(case, op, tmp_path, caplog):
    exc, expected = _smb_errors()[case]
    fake = FakeSmbClient(tmp_path)
    fake.register_error = exc
    st = SmbStorage("pi", "karaoke", "", "user", PW, client=fake)
    caplog.set_level("DEBUG")
    with pytest.raises(StorageError) as e:
        {"probe": st.probe, "list_songs": st.list_songs,
         "write": lambda: st.write_atomic("A/x.txt", b"1")}[op]()
    assert expected in str(e.value)
    assert PW not in str(e.value) and PW not in repr(e.value)
    assert e.value.__cause__ is None or PW not in str(e.value.__cause__)
    assert PW not in caplog.text
    assert PW not in repr(st)


def test_smb_missing_base_path_probe_message(tmp_path):
    st = SmbStorage("pi", "karaoke", "Нет/Такой", "user", PW, client=FakeSmbClient(tmp_path))
    with pytest.raises(StorageError) as e:
        st.probe()
    assert "Папка «Нет/Такой» не найдена на шаре //pi/karaoke" in str(e.value)


def test_smb_passes_credentials_to_session(tmp_path):
    fake = FakeSmbClient(tmp_path)
    st = SmbStorage("pi", "karaoke", "", "user", PW, client=fake)
    st.probe()
    assert fake.sessions == [("pi", "user", 445)]
