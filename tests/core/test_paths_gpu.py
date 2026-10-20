"""Раскладка тома data (§3), статус GPU в settings, enqueue_with, публичные decode/number."""

import pytest

from karaoke_core import ultrastar
from karaoke_core.db import Jobs, Settings, connect
from karaoke_core.paths import DataPaths


def test_layout_follows_spec(tmp_path):
    p = DataPaths(tmp_path)
    assert p.db == tmp_path / "karaoke.sqlite"
    assert p.log(7) == tmp_path / "logs" / "7.log"
    assert p.song("Bros.", "Hi?") == tmp_path / "songs" / "Bros" / "Bros - Hi_"
    rel = "Кино/Кино - Группа крови"
    assert p.source(rel) == tmp_path / "songs" / "Кино" / "Кино - Группа крови" / "source"
    assert p.job_in(rel, 5) == tmp_path / "songs" / "Кино" / "Кино - Группа крови" / "jobs" / "5" / "in"
    assert p.rel(p.job_in(rel, 5) / "input.mp3") == "songs/Кино/Кино - Группа крови/jobs/5/in/input.mp3"
    assert DataPaths(env={"DATA_DIR": "/x"}).root.as_posix() == "/x"
    with pytest.raises(ValueError):
        p.song_at("../etc")


def test_gpu_status_roundtrip(tmp_path):
    s = Settings(connect(tmp_path / "db.sqlite"))
    assert s.get_gpu_status() is None
    s.set_gpu_status({"ok": False, "name": None, "vram_mb": None, "error": "нет GPU"})
    got = s.get_gpu_status()
    assert got["ok"] is False and got["error"] == "нет GPU" and got["checked_at"]


def test_enqueue_with_passes_id_and_rolls_back_on_error(tmp_path):
    jobs = Jobs(connect(tmp_path / "db.sqlite"))
    job = jobs.enqueue_with("generate", {"artist": "A", "title": "T"}, lambda i: {"dir": f"jobs/{i}/in"})
    assert job.params == {"dir": f"jobs/{job.id}/in"} and job.state == "queued"

    def boom(_):
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        jobs.enqueue_with("generate", {"artist": "B", "title": "T"}, boom)
    assert [j.artist for j in jobs.list()] == ["A"]


def test_public_decode_and_number():
    assert ultrastar.decode("Привет".encode("cp1251")) == ("Привет", "cp1251", False)
    assert ultrastar.decode(b"\xef\xbb\xbfhi") == ("hi", "utf-8", True)
    assert ultrastar.number("300,5", None) == 300.5
    assert ultrastar.number(" ", None) is None
