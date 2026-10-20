"""Интеграция с настоящей Samba-шарой. Пропускается без ``TEST_SMB_*``.

Запуск (значения — из своего окружения, не из кода):
``docker --context desktop-linux compose --profile test run --rm -e TEST_SMB_HOST -e TEST_SMB_SHARE
-e TEST_SMB_USER -e TEST_SMB_PASSWORD [-e TEST_SMB_PATH] tests pytest -q tests/core/test_storage_smb_integration.py``

Работает только внутри собственной временной подпапки и удаляет её в конце.
"""

import os
import secrets

import pytest

from karaoke_core.storage import SmbStorage, StorageError

ENV = {k: os.environ.get(f"TEST_SMB_{k}") for k in ("HOST", "SHARE", "USER", "PASSWORD", "PATH")}

pytestmark = pytest.mark.skipif(
    not (ENV["HOST"] and ENV["SHARE"]), reason="нет TEST_SMB_HOST/TEST_SMB_SHARE")

TXT = "#TITLE:Probe\n#ARTIST:Probe\n#MP3:Probe - Probe.mp3\n#BPM:300\n: 0 4 1 a\nE\n".encode()


@pytest.fixture
def st():
    sub = f"{ENV['PATH'] or ''}/_karaoke_it_{secrets.token_hex(4)}".strip("/")
    root = SmbStorage(ENV["HOST"], ENV["SHARE"], ENV["PATH"] or "", ENV["USER"] or "",
                      ENV["PASSWORD"])
    root.write_atomic(f"{sub.split('/')[-1]}/.keep", b"")
    s = SmbStorage(ENV["HOST"], ENV["SHARE"], sub, ENV["USER"] or "", ENV["PASSWORD"])
    yield s
    root.delete_dir(sub.split("/")[-1])
    s.close()
    root.close()


def test_real_share_roundtrip(st, tmp_path):
    st.probe()
    src = tmp_path / "Probe - Probe"
    src.mkdir()
    (src / "Probe - Probe.txt").write_bytes(TXT)
    (src / "Probe - Probe.mp3").write_bytes(b"m" * 70_000)
    st.upload_dir(src, "Probe/Probe - Probe")
    [song] = st.list_songs()
    assert (song.rel_dir, song.audio) == ("Probe/Probe - Probe", "Probe - Probe.mp3")
    st.download_dir("Probe/Probe - Probe", tmp_path / "dl")
    assert (tmp_path / "dl" / "Probe - Probe.mp3").stat().st_size == 70_000
    st.delete_dir("Probe/Probe - Probe")
    assert not st.exists("Probe/Probe - Probe")


def test_real_share_wrong_password_is_clear():
    bad = "wrong-" + secrets.token_hex(6)
    s = SmbStorage(ENV["HOST"], ENV["SHARE"], ENV["PATH"] or "", ENV["USER"] or "nobody", bad)
    with pytest.raises(StorageError) as e:
        s.probe()
    assert bad not in str(e.value)
