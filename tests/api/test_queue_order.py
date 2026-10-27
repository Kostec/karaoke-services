"""Очередь: порядок и отложенный запуск (истории 56-58): move, schedule, schedule-all, GET /api/jobs."""

from datetime import datetime, timedelta, timezone

from karaoke_core.db import Jobs, connect

REF = {"artist": "Кино", "title": "Песня"}


def _jobs(env):
    return Jobs(connect(env.data / "karaoke.sqlite"))


def _queue(env, n=3):
    jobs = _jobs(env)
    return jobs, [jobs.enqueue("instrumental", {**REF, "title": f"П{i}"}, {}) for i in range(n)]


def _at(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")


def test_move_first_reorders_queue_and_list_shows_position(env, client):
    jobs, (a, b, c) = _queue(env)
    r = client.post(f"/api/jobs/{c.id}/move", json={"where": "first"})
    assert r.status_code == 200, r.text
    assert [j["id"] for j in r.json()["jobs"]] == [c.id, a.id, b.id]
    listed = {j["id"]: j for j in client.get("/api/jobs").json()}
    assert listed[c.id]["position"] < listed[a.id]["position"] < listed[b.id]["position"]
    assert listed[a.id]["start_at"] is None


def test_move_up_and_down(env, client):
    _, (a, b, c) = _queue(env)
    assert [j["id"] for j in client.post(f"/api/jobs/{c.id}/move", json={"where": "up"}).json()["jobs"]] == [a.id, c.id, b.id]
    assert [j["id"] for j in client.post(f"/api/jobs/{a.id}/move", json={"where": "down"}).json()["jobs"]] == [c.id, a.id, b.id]


def test_move_not_queued_is_409_unknown_is_404_bad_direction_400(env, client):
    jobs, (a, *_rest) = _queue(env)
    jobs.update(a.id, state="done")
    r = client.post(f"/api/jobs/{a.id}/move", json={"where": "up"})
    assert r.status_code == 409 and r.json()["detail"] == "Переставлять можно только ожидающие задания"
    assert client.post("/api/jobs/9999/move", json={"where": "up"}).status_code == 404
    assert client.post(f"/api/jobs/{_rest[0].id}/move", json={"where": "sideways"}).status_code == 400


def test_schedule_sets_and_clears_start_at(env, client):
    _, (a, *_r) = _queue(env)
    at = _at(5)
    r = client.post(f"/api/jobs/{a.id}/schedule", json={"start_at": at})
    assert r.status_code == 200, r.text
    assert r.json()["start_at"] == at
    assert client.get(f"/api/jobs/{a.id}").json()["start_at"] == at
    r = client.post(f"/api/jobs/{a.id}/schedule", json={"start_at": None})
    assert r.status_code == 200 and r.json()["start_at"] is None


def test_schedule_past_time_is_400_and_not_queued_is_409(env, client):
    jobs, (a, b, _c) = _queue(env)
    r = client.post(f"/api/jobs/{a.id}/schedule", json={"start_at": _at(-1)})
    assert r.status_code == 400 and r.json()["detail"] == "Время уже прошло" and r.json()["field"] == "start_at"
    assert client.post(f"/api/jobs/{a.id}/schedule", json={"start_at": "завтра"}).status_code == 400
    jobs.update(b.id, state="failed")
    r = client.post(f"/api/jobs/{b.id}/schedule", json={"start_at": _at(2)})
    assert r.status_code == 409
    assert client.post("/api/jobs/9999/schedule", json={"start_at": _at(2)}).status_code == 404


def test_schedule_all_counts_queued_without_time(env, client):
    jobs, (a, b, c) = _queue(env)
    client.post(f"/api/jobs/{a.id}/schedule", json={"start_at": _at(9)})
    jobs.update(c.id, state="done")
    r = client.post("/api/jobs/schedule", json={"start_at": _at(3)})
    assert r.status_code == 200, r.text
    assert r.json() == {"count": 1}
    assert client.get(f"/api/jobs/{b.id}").json()["start_at"] is not None
    assert client.post("/api/jobs/schedule", json={"start_at": _at(-1)}).status_code == 400
    assert client.post("/api/jobs/schedule", json={"start_at": None}).status_code == 400


def test_restart_drops_start_at(env, client):
    jobs, (a, *_r) = _queue(env)
    client.post(f"/api/jobs/{a.id}/schedule", json={"start_at": _at(4)})
    jobs.update(a.id, state="failed")
    r = client.post(f"/api/jobs/{a.id}/restart")
    assert r.status_code == 201, r.text
    assert r.json()["start_at"] is None


def test_time_without_zone_is_rejected(env, client):
    _, (a, *_r) = _queue(env)
    naive = (datetime.now() + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(f"/api/jobs/{a.id}/schedule", json={"start_at": naive})
    assert r.status_code == 400 and r.json() == {"detail": "Неверное время", "field": "start_at"}
    assert client.post("/api/jobs/schedule", json={"start_at": naive}).status_code == 400
