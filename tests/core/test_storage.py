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
from karaoke_core.db import OutputTarget, song_id_for
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
        self.fail = {}  # операция → исключение: open/read/write/replace/remove/scandir/...

    def _check(self, op):
        if op in self.fail:
            raise self.fail[op]

    def _p(self, unc: str) -> Path:
        assert unc.lower().startswith(self.prefix), unc
        rest = unc[len(self.prefix):].strip("\\")
        return self.root.joinpath(*[x for x in rest.split("\\") if x])

    def _wrap(self, fn, unc, *a):
        self._check(getattr(fn, "__name__", ""))
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
        return FakeSmbFile(self._wrap(open, path, self._p(path), mode), self)

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
        self._check("scandir")
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


class FakeSmbFile:
    """Файл с шары: ошибки посреди чтения/записи берутся из ``client.fail``."""

    def __init__(self, f, client):
        self._f, self._c = f, client

    def read(self, *a):
        self._c._check("read")
        return self._f.read(*a)

    def write(self, b):
        self._c._check("write")
        return self._f.write(b)

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


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

@pytest.mark.parametrize("target", [
    OutputTarget(kind="smb", host="h", share="s", path="p/q", user="u", password="pw"),
    OutputTarget(kind="smb", host="192.168.0.129", share="karaoke"),
    OutputTarget(kind="local", path="songs"),
    OutputTarget(kind="local"),
])
def test_make_storage_identity_comes_from_output_target(target):
    st = make_storage(target)
    assert isinstance(st, SmbStorage if target.kind == "smb" else LocalStorage)
    assert (st.target_id, st.label) == (target.target_id, target.label)
    assert song_id_for(st.target_id, "A/A - B") == song_id_for(target.target_id, "A/A - B")


def test_storages_built_directly_share_target_format():
    smb = SmbStorage("h", "s", "p/q", "u", "pw", client=FakeSmbClient(Path(".")))
    t = OutputTarget(kind="smb", host="h", share="s", path="p/q")
    assert (smb.target_id, smb.label) == (t.target_id, t.label) == ("smb://h/s/p/q", "//h/s/p/q")
    loc = LocalStorage("/output/songs")
    t = OutputTarget(kind="local", path="songs")
    assert (loc.target_id, loc.label) == (t.target_id, t.label) == ("local:/output/songs", "/output/songs")


def test_write_streams_into_part_before_final_name(env):
    st, root = env
    seen = []

    class Watching(io.RawIOBase):
        def __init__(self):
            self.chunks = [b"#TITLE:x\n", b": 0 1 1 a\n"]

        def readable(self):
            return True

        def read(self, n=-1):
            seen.append(((root / "A/x.txt.part").exists(), (root / "A/x.txt").exists()))
            return self.chunks.pop(0) if self.chunks else b""

    st.write_atomic("A/x.txt", Watching())
    assert seen[1] == (True, False)  # первый кусок уже в .part, готового .txt ещё нет
    assert (root / "A/x.txt").read_bytes() == b"#TITLE:x\n: 0 1 1 a\n"
    assert not (root / "A/x.txt.part").exists()


def test_read_song_single_folder(env):
    st, root = env
    d = "Исполнитель/Исполнитель - Песня"
    put(root, f"{d}/Исполнитель - Песня.lyrics.txt", LYRICS)
    put(root, f"{d}/Исполнитель - Песня.txt", SOLO)
    s = st.read_song(d)
    assert (s.rel_dir, s.txt_name, s.artist, s.title) == (d, "Исполнитель - Песня.txt",
                                                           "Исполнитель", "Песня")
    put(root, "Пусто/x.lyrics.txt", LYRICS)
    assert st.read_song("Пусто") is None


def test_stat_file(env):
    st, root = env
    put(root, "A/f.mp3", b"12345")
    assert st.stat("A/f.mp3").size == 5 and st.stat("A/f.mp3").is_dir is False
    assert st.stat("A").is_dir is True
    assert st.stat("A/none") is None


def test_delete_last_song_removes_empty_artist_dir(env, tmp_path):
    st, root = env
    put(root, "A/A - B/A - B.txt", SOLO)
    put(root, "A/A - C/A - C.txt", SOLO)
    put(root, "Solo/Solo.txt", SOLO)
    st.delete_dir("A/A - B")
    assert (root / "A").is_dir() and not (root / "A/A - B").exists()
    st.delete_dir("A/A - C")
    assert not (root / "A").exists()
    st.delete_dir("Solo")  # родитель — корень, его не трогаем
    assert root.is_dir() and list(root.iterdir()) == []


def test_artist_dir_with_other_files_is_kept(env):
    st, root = env
    put(root, "A/A - B/A - B.txt", SOLO)
    put(root, "A/folder.jpg", b"x")
    st.delete_dir("A/A - B")
    assert (root / "A/folder.jpg").exists()


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


def _resp(cls, status):
    from smbprotocol.header import SMB2HeaderResponse
    h = SMB2HeaderResponse()
    h["status"] = status
    return cls(h)


def _file_op_errors():
    from smbprotocol.exceptions import AccessDenied, SMBConnectionClosed
    return {
        "closed": (SMBConnectionClosed(f"connection closed {PW}"), "прервано"),
        "reset": (ConnectionResetError(104, "Connection reset by peer"), "недоступен"),
        "denied": (SMBOSError(NtStatus.STATUS_ACCESS_DENIED, r"\\pi\karaoke\x " + PW), "Нет доступа"),
        "denied_resp": (_resp(AccessDenied, NtStatus.STATUS_ACCESS_DENIED), "Нет доступа"),
        "timeout": (TimeoutError("timed out"), "недоступен"),
        "other": (RuntimeError(f"weird {PW}"), "Ошибка Samba"),
    }


def _smb_with_song(share):
    fake = FakeSmbClient(share)
    put(share, "A/A - B/A - B.txt", SOLO)
    put(share, "A/A - B/A - B.mp3", b"m" * 100)
    return SmbStorage("pi", "karaoke", "", "user", PW, client=fake), fake


FILE_OPS = {
    "read_txt": ("read", lambda st, src, tmp: st.read("A/A - B/A - B.txt")),
    "open_read": ("read", lambda st, src, tmp: st.open_read("A/A - B/A - B.mp3").read()),
    "download": ("read", lambda st, src, tmp: st.download_dir("A/A - B", tmp / "dl")),
    "list": ("read", lambda st, src, tmp: st.list_songs()),
    "write": ("write", lambda st, src, tmp: st.write_atomic("A/new.txt", b"abc")),
    "open_write": ("open", lambda st, src, tmp: st.write_atomic("A/new.txt", b"abc")),
    "rename": ("replace", lambda st, src, tmp: st.write_atomic("A/new.txt", b"abc")),
    "remove": ("remove", lambda st, src, tmp: st.delete_dir("A/A - B")),
    "rmdir": ("rmdir", lambda st, src, tmp: st.delete_dir("A/A - B")),
    "scandir": ("scandir", lambda st, src, tmp: st.sizes("A/A - B")),
    "stat": ("stat", lambda st, src, tmp: st.exists("A/A - B")),
    "upload": ("makedirs", lambda st, src, tmp: st.upload_dir(src, "Z/Z - Z")),
}


@pytest.mark.parametrize("case", ["closed", "reset", "denied", "denied_resp", "timeout", "other"])
@pytest.mark.parametrize("op", sorted(FILE_OPS))
def test_smb_file_operation_errors_are_storage_errors(case, op, tmp_path, caplog):
    exc, expected = _file_op_errors()[case]
    fail_op, action = FILE_OPS[op]
    st, fake = _smb_with_song(tmp_path / "share")
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.mp3").write_bytes(b"1")
    fake.fail[fail_op] = exc
    caplog.set_level("DEBUG")
    with pytest.raises(StorageError) as e:
        action(st, src, tmp_path)
    assert expected in str(e.value)
    assert PW not in str(e.value) and PW not in caplog.text
    assert not list((tmp_path / "share").rglob("*.part"))


def test_probe_raises_when_write_is_denied(tmp_path):
    st, fake = _smb_with_song(tmp_path)
    fake.fail["open"] = SMBOSError(NtStatus.STATUS_ACCESS_DENIED, r"\\pi\karaoke\probe")
    with pytest.raises(StorageError) as e:
        st.probe()
    assert "Нет доступа" in str(e.value)


def test_probe_reports_first_error_not_cleanup_error(tmp_path):
    from smbprotocol.exceptions import SMBConnectionClosed
    st, fake = _smb_with_song(tmp_path)
    fake.fail["read"] = SMBOSError(NtStatus.STATUS_ACCESS_DENIED, r"\\pi\karaoke\probe")
    fake.fail["remove"] = SMBConnectionClosed("closed")
    with pytest.raises(StorageError) as e:
        st.probe()
    assert "Нет доступа" in str(e.value)


def test_probe_reports_cleanup_error_when_rest_succeeded(tmp_path):
    st, fake = _smb_with_song(tmp_path)
    fake.fail["remove"] = SMBOSError(NtStatus.STATUS_ACCESS_DENIED, r"\\pi\karaoke\probe")
    with pytest.raises(StorageError) as e:
        st.probe()
    assert "Нет доступа" in str(e.value)


# --------------------------------------------------------------------------- занятый файл

def _smb_on(tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    fake = FakeSmbClient(share)
    return SmbStorage("pi", "karaoke", "", "user", "s3cret-pw", client=fake), fake, share


class _Flaky:
    """Replace, который первые ``n`` раз отвечает как Samba на файл, открытый другим клиентом."""

    def __init__(self, fake, n, status=NtStatus.STATUS_ACCESS_DENIED):
        self.fake, self.left, self.status, self.calls = fake, n, status, 0
        self.real = type(fake).replace

    def __call__(self, src, dst, **kw):
        self.calls += 1
        if self.left:
            self.left -= 1
            raise SMBOSError(self.status, dst)
        return self.real(self.fake, src, dst, **kw)


@pytest.mark.parametrize("status", [NtStatus.STATUS_ACCESS_DENIED, NtStatus.STATUS_SHARING_VIOLATION])
def test_write_atomic_waits_while_file_is_busy(tmp_path, monkeypatch, status):
    from karaoke_core.storage import base
    sleeps = []
    monkeypatch.setattr(base.time, "sleep", sleeps.append)
    st, fake, share = _smb_on(tmp_path)
    put(share, "A/A - B/A - B.txt", b"old")
    flaky = _Flaky(fake, 2, status)
    fake.replace = flaky
    st.write_atomic("A/A - B/A - B.txt", b"new")
    assert (share / "A/A - B/A - B.txt").read_bytes() == b"new"
    # занятый файл: прямая замена и переименование старого отклонены → пауза → вторая попытка прошла
    assert len(sleeps) == 1 and flaky.left == 0
    assert not (share / "A/A - B/A - B.txt.part").exists()


def test_write_atomic_gives_up_with_hint_and_keeps_old_file(tmp_path, monkeypatch):
    from karaoke_core.storage import StorageBusy, base
    sleeps = []
    monkeypatch.setattr(base.time, "sleep", sleeps.append)
    st, fake, share = _smb_on(tmp_path)
    put(share, "A/A - B/A - B.txt", b"old")
    flaky = _Flaky(fake, 999)
    fake.replace = flaky
    with pytest.raises(StorageBusy) as e:
        st.write_atomic("A/A - B/A - B.txt", b"new")
    assert "Нет доступа" in str(e.value) and "открыт на другом устройстве" in str(e.value)
    assert len(sleeps) == len(base.BUSY_RETRY_DELAYS)  # все паузы выждали, потом сдались
    assert (share / "A/A - B/A - B.txt").read_bytes() == b"old"
    assert not (share / "A/A - B/A - B.txt.part").exists()


class _NoReplaceOverExisting:
    """Replace как у Samba на exFAT/NTFS-диске: переименовать поверх существующего файла — «нет доступа»."""

    def __init__(self, fake):
        self.fake, self.real = fake, type(fake).replace
        self.denied = 0

    def __call__(self, src, dst, **kw):
        if self.fake._p(dst).exists():
            self.denied += 1
            raise SMBOSError(NtStatus.STATUS_ACCESS_DENIED, dst)
        return self.real(self.fake, src, dst, **kw)


def test_write_atomic_replaces_existing_file_on_share_without_rename_over(tmp_path):
    st, fake, share = _smb_on(tmp_path)
    put(share, "A/A - B/A - B.txt", b"old")
    guard = _NoReplaceOverExisting(fake)
    fake.replace = guard
    st.write_atomic("A/A - B/A - B.txt", b"new")
    assert (share / "A/A - B/A - B.txt").read_bytes() == b"new"
    assert guard.denied == 1
    assert sorted(p.name for p in (share / "A/A - B").iterdir()) == ["A - B.txt"]


def test_swap_puts_old_file_back_when_new_one_cannot_be_placed(tmp_path):
    st, fake, share = _smb_on(tmp_path)
    put(share, "A/A - B/A - B.txt", b"old")
    real = type(fake).replace

    def replace(src, dst, **kw):
        if src.endswith(".part"):
            raise SMBOSError(NtStatus.STATUS_ACCESS_DENIED, dst)
        return real(fake, src, dst, **kw)
    fake.replace = replace
    with pytest.raises(StorageError):
        st.write_atomic("A/A - B/A - B.txt", b"new")
    assert (share / "A/A - B/A - B.txt").read_bytes() == b"old"
    assert sorted(p.name for p in (share / "A/A - B").iterdir()) == ["A - B.txt"]
