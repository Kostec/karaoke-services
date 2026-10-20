"""Шов 3: karaoke_worker.runner с фейковыми UltraSinger, demucs и ffmpeg (tests/worker/fixtures)."""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from karaoke_core.db import FINAL_STATES, Jobs, connect  # noqa: E402
from karaoke_core.paths import INPUT_AUDIO, INPUT_LYRICS, DataPaths  # noqa: E402
from karaoke_core.storage import LocalStorage  # noqa: E402
from karaoke_core.trash import Trash  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
CORE_FIX = ROOT / "tests" / "core" / "fixtures"
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 64
GPU_OK = {"ok": True, "name": "Fake GPU", "vram_mb": 8192, "error": None}

# Параметры, которые кладёт web (web/app/params.py: defaults из .env по умолчанию).
DEFAULT_PARAMS = {
    "whisper_model": "large-v2", "language": "ru", "compute_type": "int8", "batch_size": 4,
    "align_model": "jonatasgrosman/wav2vec2-large-xlsr-53-russian", "vad_onset": None,
    "vad_offset": None, "demucs_model": "htdemucs", "keep_debug": False,
}


class _FailingUpload(LocalStorage):
    """Первая выкладка папки обрывается (связь восстановилась к моменту отката)."""

    failed = False

    def upload_dir(self, local, rel_dir):
        from karaoke_core.storage import StorageError

        if not self.failed:
            self.failed = True
            raise StorageError("связь с папкой результата оборвалась (тест)")
        return super().upload_dir(local, rel_dir)


class World:
    def __init__(self, tmp_path: Path, monkeypatch):
        from karaoke_worker.runner import JobContext

        self.tmp = tmp_path
        self.paths = DataPaths(tmp_path / "data")
        self.paths.root.mkdir(parents=True)
        self.out = tmp_path / "out"
        self.out.mkdir()
        self.storage_ok = True
        self.fail_upload = False
        py = sys.executable
        monkeypatch.setenv("ULTRASINGER_CMD", f"{py} {FIX / 'fake_ultrasinger.py'}")
        monkeypatch.setenv("DEMUCS_CMD", f"{py} {FIX / 'fake_demucs.py'}")
        monkeypatch.setenv("FFMPEG_CMD", f"{py} {FIX / 'fake_ffmpeg.py'}")
        self.trash = Trash(self.paths.trash, days=30)
        self.ctx = JobContext(self.paths, storage_factory=self._storage, trash=self.trash)
        self.conn = connect(self.paths.db)  # «сторона web»
        self.jobs = Jobs(self.conn)

    def _storage(self, _target):
        from karaoke_core.storage import StorageError

        if not self.storage_ok:
            raise StorageError("Папка результата недоступна: нет связи (тест)")
        if self.fail_upload:
            return _FailingUpload(self.out)
        return LocalStorage(self.out)

    @property
    def storage(self) -> LocalStorage:
        return LocalStorage(self.out)

    def enqueue_generate(self, artist="Тестовая Группа", title="Песня Ёлки", *, lyrics="Ёлка\nпесня",
                         lrc: str | None = None, **extra):
        from karaoke_core import naming

        rel_dir = naming.song_dir(artist, title)
        params = {**DEFAULT_PARAMS, "rel_dir": rel_dir, "replace": False, "replace_rel_dir": None,
                  "target_id": self.storage.target_id, **extra}

        def make(job_id: int) -> dict:
            d = self.paths.job_in(rel_dir, job_id)
            d.mkdir(parents=True)
            (d / INPUT_AUDIO).write_bytes(MP3)
            inputs = {"dir": self.paths.rel(d), "audio": self.paths.rel(d / INPUT_AUDIO)}
            if lyrics:
                (d / INPUT_LYRICS).write_text(lyrics, "utf-8")
                inputs["lyrics"] = self.paths.rel(d / INPUT_LYRICS)
            if lrc is not None:
                (d / "lyrics.lrc").write_text(lrc, "utf-8")
                inputs["lrc"] = self.paths.rel(d / "lyrics.lrc")
            return {**params, "inputs": inputs}

        return self.jobs.enqueue_with("generate", {"artist": artist, "title": title}, make)

    def run(self, *, timeout: float = 60, gpu=GPU_OK, until=None):
        """Исполнять очередь, пока все задания не придут в конечное состояние."""
        from karaoke_worker import runner

        deadline = time.monotonic() + timeout

        def done() -> bool:
            if time.monotonic() > deadline:
                raise AssertionError("очередь не обработана за отведённое время")
            if until is not None:
                return until()
            return all(j.state in FINAL_STATES for j in self.jobs.list(1000))

        runner.run_forever(self.ctx, gpu_check=lambda: dict(gpu), poll=0.05, until=done)

    def run_in_thread(self, **kw) -> threading.Thread:
        t = threading.Thread(target=self.run, kwargs=kw, daemon=True)
        t.start()
        return t

    def log(self, job_id: int) -> str:
        return self.paths.log(job_id).read_text("utf-8")


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    yield w
    w.conn.close()


def read_json(path: Path):
    return json.loads(Path(path).read_text("utf-8"))
