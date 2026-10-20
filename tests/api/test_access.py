"""Авторизация (§10), статус, значения по умолчанию, статика, OpenAPI, корзина по расписанию."""

import base64
from datetime import datetime, timedelta, timezone

from karaoke_core.db import Settings, connect
from karaoke_core.storage import LocalStorage
from karaoke_core.trash import Trash


def _basic(pw: str, user: str = "любой") -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def test_password_protects_every_path(env):
    with env.client(password="s3cret") as c:
        for path in ("/", "/index.html", "/api/status", "/api/jobs", "/api/docs",
                     "/api/jobs/1/log/stream"):
            r = c.get(path)
            assert r.status_code == 401, path
            assert r.headers["www-authenticate"].startswith("Basic")
            assert r.json()["detail"] == "Нужен пароль"
        assert c.get("/api/status", headers=_basic("wrong")).status_code == 401
        assert c.get("/api/status", headers=_basic("s3cret")).status_code == 200
        assert c.get("/", headers=_basic("s3cret", user="")).status_code == 200


def test_empty_password_means_open(client):
    assert client.get("/api/status").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/api/docs").status_code == 200


def test_status_without_worker_report(client):
    s = client.get("/api/status").json()
    assert s["gpu"]["ok"] is None
    assert s["gpu"]["error"] == "Воркер ещё не сообщил статус GPU"
    assert s["output"]["ok"] is True
    assert s["version"]


def test_status_reads_gpu_report_from_db(env, client):
    Settings(connect(env.data / "karaoke.sqlite")).set_gpu_status(
        {"ok": True, "name": "NVIDIA GeForce GTX 1080", "vram_mb": 8192, "error": None, "torch": "2.8.0"})
    gpu = client.get("/api/status").json()["gpu"]
    assert gpu == {"ok": True, "name": "NVIDIA GeForce GTX 1080", "vram_mb": 8192, "error": None}


def test_status_reports_unavailable_output(env, client):
    r = client.put("/api/settings/output", json={"kind": "local", "path": "missing"})
    assert r.status_code == 400
    # цель недоступна после сохранения — подменяем корень
    (env.out).rename(env.tmp / "gone")
    out = client.get("/api/status").json()["output"]
    assert out["ok"] is False and out["error"]


def test_defaults(client):
    d = client.get("/api/defaults").json()
    assert d["whisper_models"] == ["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3"]
    assert d["compute_types"] == ["int8", "float32"]
    assert d["defaults"]["whisper_model"] == "large-v2"
    assert d["defaults"]["language"] == "ru"
    assert d["defaults"]["compute_type"] == "int8"
    assert d["defaults"]["batch_size"] == 4
    assert d["align_models"]["ru"] == "jonatasgrosman/wav2vec2-large-xlsr-53-russian"
    assert any(lang["code"] == "ru" for lang in d["languages"])
    assert d["max_upload_mb"] == 1


def test_unknown_api_path_is_russian_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["detail"] == "Не найдено"


def test_trash_purged_on_start(env):
    old = datetime.now(timezone.utc) - timedelta(days=40)
    env.put_song("A/A - B", b"#TITLE:B\n#ARTIST:A\n: 0 1 1 a\nE\n", "A - B")
    Trash(env.data / "trash", clock=lambda: old).move_to_trash(LocalStorage(env.out), "A/A - B")
    assert Trash(env.data / "trash").list()
    with env.client():
        pass
    assert Trash(env.data / "trash").list() == []
