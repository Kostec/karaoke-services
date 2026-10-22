"""POST /api/jobs/copy и pending_copies у песни (истории 18–22, Решения §9)."""

from karaoke_core.db import Settings, Target, connect

REL = "Artist/Artist - Song"


def _pc(env, client, *, with_song=False):
    """Хранилище «ПК» (``/host/pc`` → ``tmp/host/pc``); по желанию — с той же песней."""
    target = Settings(connect(env.data / "karaoke.sqlite")).save_target(
        Target(name="ПК", kind="local", path="/host/pc"))
    (env.tmp / "host" / "pc").mkdir(parents=True, exist_ok=True)
    if with_song:
        d = env.tmp / "host" / "pc" / "Artist" / "Artist - Song"
        d.mkdir(parents=True)
        (d / "Artist - Song.txt").write_bytes(env.SONG_TXT)
        assert client.app.state.ctx.refresh_song(REL, target.id) is not None
    return target


def test_copy_queues_job_and_returns_existing_duplicate(env, client, song):
    pc = _pc(env, client)
    r = client.post("/api/jobs/copy", json={"song_ids": [song["song_id"]], "target_id": pc.id})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["skipped"] == 0 and body["errors"] == [] and len(body["queued"]) == 1
    job = client.get(f"/api/jobs/{body['queued'][0]}").json()
    assert job["type"] == "copy" and job["song_id"] == song["song_id"]
    assert job["params"] == {"rel_dir": REL, "txt_name": "Artist - Song.txt", "from_target": "local",
                             "to_target": pc.id, "replace": False, "wait": False}
    again = client.post("/api/jobs/copy", json={"song_ids": [song["song_id"]], "target_id": pc.id}).json()
    assert again["queued"] == body["queued"]


def test_copy_only_missing_skips_songs_already_in_target(env, client, song):
    pc = _pc(env, client, with_song=True)
    r = client.post("/api/jobs/copy", json={"song_ids": [song["song_id"]], "target_id": pc.id})
    assert r.json() == {"queued": [], "skipped": 1, "errors": []}
    r = client.post("/api/jobs/copy", json={"song_ids": [song["song_id"]], "target_id": pc.id,
                                            "only_missing": False, "replace": True})
    assert len(r.json()["queued"]) == 1
    job = client.get(f"/api/jobs/{r.json()['queued'][0]}").json()
    assert job["params"]["replace"] is True


def test_copy_into_own_storage_and_unknown_song_are_errors(env, client, song):
    r = client.post("/api/jobs/copy", json={"song_ids": [song["song_id"], "nope"], "target_id": "local"})
    assert r.status_code == 201
    body = r.json()
    assert body["queued"] == [] and body["skipped"] == 0
    assert [e["song_id"] for e in body["errors"]] == [song["song_id"], "nope"]
    assert body["errors"][0]["detail"] == "Песня уже в этом хранилище"
    assert body["errors"][1]["detail"] == "Песня не найдена"


def test_copy_unknown_target_and_limit(env, client, song):
    r = client.post("/api/jobs/copy", json={"song_ids": [song["song_id"]], "target_id": "t_nope"})
    assert r.status_code == 400 and r.json()["field"] == "target_id"
    r = client.post("/api/jobs/copy", json={"song_ids": ["x"] * 1001, "target_id": "local"})
    assert r.status_code == 400 and r.json()["field"] == "song_ids"


def test_song_shows_pending_copies(env, client, song):
    pc = _pc(env, client)
    assert client.get(f"/api/songs/{song['song_id']}").json()["pending_copies"] == []
    job_id = client.post("/api/jobs/copy", json={"song_ids": [song["song_id"]],
                                                 "target_id": pc.id}).json()["queued"][0]
    want = [{"target_id": pc.id, "name": "ПК", "job_id": job_id}]
    assert client.get(f"/api/songs/{song['song_id']}").json()["pending_copies"] == want
    item = next(i for i in client.get("/api/songs").json()["items"] if i["song_id"] == song["song_id"])
    assert item["pending_copies"] == want
    client.post(f"/api/jobs/{job_id}/cancel")
    assert client.get(f"/api/songs/{song['song_id']}").json()["pending_copies"] == []


def test_restart_copy_returns_active_duplicate(env, client, song):
    """«Перезапустить» копирование при уже активной такой же копии — та же копия, не новая."""
    pc = _pc(env, client)
    body = {"song_ids": [song["song_id"]], "target_id": pc.id}
    first = client.post("/api/jobs/copy", json=body).json()["queued"][0]
    jobs = client.app.state.ctx.jobs
    jobs.update(first, state="failed", params={**jobs.get(first).params, "retry_at": "2000-01-01T00:00:00+00:00"})
    active = client.post("/api/jobs/copy", json=body).json()["queued"][0]
    assert active != first
    r = client.post(f"/api/jobs/{first}/restart")
    assert r.status_code == 201, r.text
    assert r.json()["id"] == active
    assert [j.id for j in jobs.active("copy")] == [active]
    jobs.update(active, state="cancelled")
    again = client.post(f"/api/jobs/{first}/restart").json()
    assert again["id"] not in (first, active) and again["parent_id"] == first
    assert "retry_at" not in again["params"] and again["params"]["to_target"] == pc.id
