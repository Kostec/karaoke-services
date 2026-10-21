"""POST /api/jobs/video — видео к песне из папки результата (истории 14–21) и умолчания блока «Видео»."""

from __future__ import annotations


def test_defaults_video_limits(env):
    with env.client(extra_env={"MAX_VIDEO_MB": "7"}) as c:
        d = c.get("/api/defaults").json()
    assert d["max_video_mb"] == 7
    assert d["video_heights"] == [360, 480, 720, 1080, 0]
    assert d["default_video_height"] == 720
    with env.client(extra_env={"MAX_VIDEO_MB": ""}) as c:
        assert c.get("/api/defaults").json()["max_video_mb"] == 2000


URL = "https://www.youtube.com/watch?v=abc123"


def post_video(client, song_id, *, file=None, **fields):
    data = {"song_id": song_id, **{k: str(v) for k, v in fields.items()}}
    files = {"video": file} if file else None
    return client.post("/api/jobs/video", data=data, files=files)


def test_video_by_url_queues_job(client, song):
    r = post_video(client, song["song_id"], video_url=URL + "&list=PL1", video_height=1080, videogap="-1,5")
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["type"] == "video" and job["song_id"] == song["song_id"]
    assert (job["artist"], job["title"]) == ("Artist", "Song")
    p = job["params"]
    assert p["rel_dir"] == "Artist/Artist - Song" and p["txt_name"] == "Artist - Song.txt"
    assert p["video_url"] == URL and p["video_height"] == 1080 and p["videogap"] == -1.5
    assert p["target_id"] == song["target_id"]
    assert p["inputs"]["dir"].endswith(f"/jobs/{job['id']}/in") and "video" not in p["inputs"]
    assert not p.get("remove")
    # второе задание видео той же песни, пока первое в очереди, — 409
    r = post_video(client, song["song_id"], video_url=URL)
    assert r.status_code == 409 and r.json()["detail"] == "Эта песня уже в очереди"


def test_video_defaults_height_and_keeps_gap(client, song):
    p = post_video(client, song["song_id"], video_url=URL).json()["params"]
    assert p["video_height"] == 720 and p["videogap"] is None


def test_video_file_is_staged_as_is(env, client, song):
    r = post_video(client, song["song_id"], file=("Клип.MKV", b"\x1aE\xdf\xa3mkv", "video/x-matroska"),
                   videogap="0")
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["inputs"]["video"].endswith("/in/video.mkv")
    assert (env.data / p["inputs"]["video"]).read_bytes() == b"\x1aE\xdf\xa3mkv"
    assert p["videogap"] == 0 and "video_url" not in p


def _err(r, status, field=None):
    assert r.status_code == status, r.text
    if field:
        assert r.json().get("field") == field, r.json()
    return r.json()["detail"]


def test_video_rejects_bad_input(client, song):
    sid = song["song_id"]
    assert "Яндекс" in _err(post_video(client, sid, video_url="https://music.yandex.ru/album/1/track/2"),
                            400, "video_url")
    _err(post_video(client, sid, video_url="http://192.168.1.10/clip.mp4"), 400, "video_url")
    _err(post_video(client, sid, video_url="ftp://example.com/x"), 400, "video_url")
    _err(post_video(client, sid, file=("clip.mp3", b"ID3", "audio/mpeg")), 400, "video")
    _err(post_video(client, sid), 400, "video")
    _err(post_video(client, sid, video_url=URL, file=("clip.mp4", b"x", "video/mp4")), 400, "video")
    _err(post_video(client, sid, video_url=URL, video_height=999), 400, "video_height")
    _err(post_video(client, sid, video_url=URL, videogap="abc"), 400, "videogap")
    assert _err(post_video(client, "nope", video_url=URL), 404) == "Песня не найдена"
    assert client.get("/api/jobs").json() == []  # ничего не поставлено


def test_video_file_over_limit_413(env, song):
    with env.client(extra_env={"MAX_VIDEO_MB": "1"}) as c:
        r = post_video(c, song["song_id"], file=("big.mp4", b"\0" * (1024 * 1024 + 1), "video/mp4"))
        assert _err(r, 413, "video") == "Файл больше 1 МБ"
        assert c.get("/api/jobs").json() == []
    leftovers = [p for p in env.data.rglob("*") if p.is_file() and p.name.startswith("video")]
    assert leftovers == []


def test_video_remove(env, client, song):
    assert _err(post_video(client, song["song_id"], remove="true"), 409) == "У песни нет видео"
    d = env.out / "Artist" / "Artist - Song"
    (d / "Artist - Song.mp4").write_bytes(b"mp4")
    txt = env.SONG_TXT.replace(b"#BPM:300\n", b"#VIDEO:Artist - Song.mp4\n#BPM:300\n")
    (d / "Artist - Song.txt").write_bytes(txt)
    client.post("/api/songs/rescan")
    item = next(i for i in client.get("/api/songs").json()["items"] if i["title"] == "Song")
    assert item["video"] == "Artist - Song.mp4"
    _err(post_video(client, item["song_id"], remove="true", video_url=URL), 400, "video")
    r = post_video(client, item["song_id"], remove="true")
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["remove"] is True and "video_url" not in p and "video" not in p["inputs"]


def test_video_restart_reuses_inputs(client, song):
    job = post_video(client, song["song_id"], video_url=URL).json()
    r = client.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 409  # ещё в очереди
    client.post(f"/api/jobs/{job['id']}/cancel")
    r = client.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 201, r.text
    again = r.json()
    assert again["type"] == "video" and again["parent_id"] == job["id"]
    assert again["params"]["inputs"]["dir"] == job["params"]["inputs"]["dir"]  # скачанное не качается заново
    assert again["params"]["video_url"] == URL
    r = client.post(f"/api/jobs/{job['id']}/restart")
    assert r.status_code == 409 and r.json()["detail"] == "Эта песня уже в очереди"
