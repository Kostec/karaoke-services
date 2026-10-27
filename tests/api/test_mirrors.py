"""REST зеркал хранилищ (истории 44–48)."""

from karaoke_core.db import Settings, Target, connect


def _target(env, name="Pi") -> Target:
    return Settings(connect(env.data / "karaoke.sqlite")).save_target(
        Target(name=name, kind="local", path=f"/host/{name.lower()}"))


def _create(client, src, dst, **kw):
    return client.post("/api/mirrors", json={"from_target": src, "to_target": dst, **kw})


def test_create_list_update_delete(env, client):
    pi = _target(env)
    r = _create(client, "local", pi.id)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["id"].startswith("m_") and m["enabled"] is True
    assert (m["from_name"], m["to_name"]) == ("Локальное хранилище", "Pi")
    assert m["job"] is None and m["waiting"] is None and m["missing"] is False

    listed = client.get("/api/mirrors").json()["mirrors"]
    assert [x["id"] for x in listed] == [m["id"]]

    r = client.put(f"/api/mirrors/{m['id']}", json={"enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False and r.json()["to_target"] == pi.id

    assert client.delete(f"/api/mirrors/{m['id']}").json() == {"ok": True}
    assert client.get("/api/mirrors").json()["mirrors"] == []
    assert client.delete(f"/api/mirrors/{m['id']}").status_code == 404
    assert client.put(f"/api/mirrors/{m['id']}", json={"enabled": True}).status_code == 404


def test_mirror_onto_itself_is_rejected(env, client):
    r = _create(client, "local", "local")
    assert r.status_code == 400
    assert r.json() == {"detail": "Хранилище не может быть зеркалом самого себя", "field": "to_target"}


def test_reverse_and_duplicate_mirror_are_rejected(env, client):
    pi = _target(env)
    assert _create(client, "local", pi.id).status_code == 201
    r = _create(client, pi.id, "local")
    assert r.status_code == 400
    assert r.json() == {"detail": "Обратное зеркало уже есть", "field": "to_target"}
    r = _create(client, "local", pi.id)
    assert r.status_code == 400 and r.json()["detail"] == "Такое зеркало уже есть"


def test_reverse_check_ignores_the_mirror_itself_on_update(env, client):
    pi, pc = _target(env), _target(env, "ПК")
    m = _create(client, "local", pi.id).json()
    r = client.put(f"/api/mirrors/{m['id']}", json={"from_target": pi.id, "to_target": "local"})
    assert r.status_code == 200, r.text  # развернуть своё зеркало можно
    other = _create(client, "local", pc.id).json()
    r = client.put(f"/api/mirrors/{other['id']}", json={"from_target": "local", "to_target": pi.id})
    assert r.status_code == 400 and r.json()["detail"] == "Обратное зеркало уже есть"


def test_unknown_storage_is_rejected(env, client):
    r = _create(client, "local", "t_nothere")
    assert r.status_code == 400 and r.json()["field"] == "to_target"
    r = _create(client, "t_nothere", "local")
    assert r.status_code == 400 and r.json()["field"] == "from_target"


def test_run_queues_job_and_second_run_conflicts(env, client):
    pi = _target(env)
    m = _create(client, "local", pi.id).json()
    r = client.post(f"/api/mirrors/{m['id']}/run")
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["type"] == "mirror" and job["params"] == {"mirror_id": m["id"]}
    assert (job["artist"], job["title"]) == ("Локальное хранилище", "Pi")

    r = client.post(f"/api/mirrors/{m['id']}/run")
    assert r.status_code == 409 and r.json()["detail"] == "Зеркало уже синхронизируется"
    assert client.get("/api/mirrors").json()["mirrors"][0]["job"]["id"] == job["id"]
    assert client.post("/api/mirrors/m_nothere/run").status_code == 404


def test_restart_of_mirror_job_conflicts_while_active(env, client):
    pi = _target(env)
    m = _create(client, "local", pi.id).json()
    job = client.post(f"/api/mirrors/{m['id']}/run").json()
    jobs = client.app.state.ctx.jobs
    jobs.update(job["id"], state="failed", params={"mirror_id": m["id"], "retry_at": "x"})
    r = client.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 201, r.text
    assert r.json()["params"] == {"mirror_id": m["id"]}
    jobs.update(job["id"], state="failed")
    assert client.post(f"/api/jobs/{job['id']}/restart").status_code == 409


def test_waiting_storage_is_shown(env, client):
    pi = _target(env)
    m = _create(client, "local", pi.id).json()
    job = client.post(f"/api/mirrors/{m['id']}/run").json()
    client.app.state.ctx.jobs.update(job["id"], stage="Ждёт хранилище «Pi»")
    assert client.get("/api/mirrors").json()["mirrors"][0]["waiting"] == "Ждёт хранилище «Pi»"

    client.app.state.ctx.jobs.update(job["id"], state="done", stage="")
    jobs = client.app.state.ctx.jobs
    copy = jobs.enqueue_copy({"artist": "A", "title": "B"}, rel_dir="A/A - B", txt_name="A - B.txt",
                             from_target="local", to_target=pi.id, wait=True)
    jobs.update(copy.id, stage="Ждёт хранилище «Pi»")
    got = client.get("/api/mirrors").json()["mirrors"][0]
    assert got["job"] is None and got["waiting"] == "Ждёт хранилище «Pi»"


def test_deleted_storage_disables_mirror_and_blocks_run(env, client):
    pi = _target(env)
    m = _create(client, "local", pi.id).json()
    assert client.delete(f"/api/targets/{pi.id}").status_code == 200
    got = client.get("/api/mirrors").json()["mirrors"][0]
    assert got["enabled"] is False and got["missing"] is True
    r = client.post(f"/api/mirrors/{m['id']}/run")
    assert r.status_code == 409 and r.json()["detail"] == "Хранилище зеркала удалено из настроек"
