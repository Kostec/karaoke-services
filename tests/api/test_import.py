"""Импорт готовой песни: POST /api/import/inspect и POST /api/jobs/import (сеть — только FakeHttp)."""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
from fakes_http import FakeHttp, response

MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
NO_SONGS = "В архиве нет песен UltraStar (.txt с #TITLE и нотами)"
NEED_AUDIO = "Нужен звук: загрузите mp3 или вставьте ссылку на YouTube"


def txt(artist: str, title: str, *, audio: str | None = None, cover: str | None = None,
        video: str | None = None, extra: str = "", eol: str = "\n") -> bytes:
    head = [f"#TITLE:{title}", f"#ARTIST:{artist}", "#LANGUAGE:Russian"]
    if audio:
        head.append(f"#MP3:{audio}")
    if cover:
        head.append(f"#COVER:{cover}")
    if video:
        head.append(f"#VIDEO:{video}")
    lines = head + ["#BPM:300", "#GAP:1000", ": 0 4 5 Раз", ": 4 4 5 два" + extra, "E"]
    return eol.join(lines).encode("utf-8") + eol.encode()


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


PACK = {
    "pack/Кино - Группа крови/Кино - Группа крови.txt":
        txt("Кино", "Группа крови", audio="Кино - Группа крови.mp3", cover="Кино - Группа крови [CO].jpg"),
    "pack/Кино - Группа крови/Кино - Группа крови.mp3": MP3,
    "pack/Кино - Группа крови/Кино - Группа крови [CO].jpg": JPG,
    "pack/Ария - Беспечный ангел/song.txt":
        txt("Ария", "Беспечный ангел", video="a=AbCdEfGhIj0,v=ZyXwVuTsRq9"),
    "pack/readme.md": b"not a song",
}


def inspect_files(client, files: list[tuple[str, bytes]]):
    return client.post("/api/import/inspect", data={"source": "files"},
                       files=[("files", (name, data)) for name, data in files])


def import_job(client, token: str, index: int, artist: str, title: str, **form):
    files = {}
    if "audio" in form:
        files["audio"] = ("my.mp3", form.pop("audio"))
    data = {"token": token, "index": str(index), "artist": artist, "title": title,
            **{k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in form.items()}}
    return client.post("/api/jobs/import", data=data, files=files or None)


@pytest.fixture
def http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture
def ic(env, http):
    with env.client(http=http) as c:
        yield c


# ------------------------------------------------------------------ inspect: files


def test_inspect_zip_pack_with_two_songs(env, ic):
    r = inspect_files(ic, [("pack.zip", make_zip(PACK))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "files" and body["token"]
    songs = sorted(body["songs"], key=lambda s: s["title"])
    assert [(s["artist"], s["title"]) for s in songs] == [("Ария", "Беспечный ангел"), ("Кино", "Группа крови")]
    aria, kino = songs
    assert kino["audio"] == "Кино - Группа крови.mp3" and kino["cover"] is True
    assert kino["language"] == "Russian" and kino["duet"] is False and kino["existing_song_id"] is None
    assert aria["audio"] is None and aria["cover"] is False
    assert aria["youtube"] == ["https://www.youtube.com/watch?v=AbCdEfGhIj0",
                               "https://www.youtube.com/watch?v=ZyXwVuTsRq9"]
    assert {s["index"] for s in songs} == {0, 1}
    assert isinstance(kino["warnings"], list)
    assert (env.data / "imports" / body["token"] / "meta.json").is_file()


def test_inspect_loose_files_and_has_instrumental(ic):
    song = txt("Ария", "Ангел", audio="a.mp3", extra="", eol="\n").replace(
        b"#BPM", b"#INSTRUMENTAL:A [Instrumental].MP3\n#BPM")
    r = inspect_files(ic, [("Ария - Ангел.txt", song), ("a.mp3", MP3), ("a [instrumental].mp3", MP3),
                           ("notes.doc", b"x")])
    assert r.status_code == 200, r.text
    (s,) = r.json()["songs"]
    assert s["audio"] == "a.mp3" and s["has_instrumental"] is True and s["warnings"] == []
    r = inspect_files(ic, [("pack.zip", make_zip(PACK))])
    assert all(x["has_instrumental"] is False for x in r.json()["songs"])


def test_inspect_without_songs_is_400(ic):
    r = inspect_files(ic, [("pack.zip", make_zip({"readme.txt": b"hello", "x.mp3": MP3}))])
    assert r.status_code == 400 and r.json()["detail"] == NO_SONGS
    r = inspect_files(ic, [("broken.zip", b"PK\x03\x04garbage")])
    assert r.status_code == 400 and r.json()["detail"] == "Архив повреждён"


def test_defaults_has_max_import_mb(ic):
    assert ic.get("/api/defaults").json()["max_import_mb"] == 500


# ------------------------------------------------------------------ jobs/import


def by_title(body: dict) -> dict:
    return {s["title"]: s for s in body["songs"]}


def test_import_job_from_pack_keeps_txt_bytes_and_params(env, ic):
    raw = b"\xef\xbb\xbf" + txt("Кино", "Группа крови", audio="Кино - Группа крови.mp3",
                                  cover="Кино - Группа крови [CO].jpg", eol="\r\n")
    body = inspect_files(ic, [("pack.zip", make_zip({**PACK, "pack/Кино - Группа крови/Кино - Группа крови.txt": raw}))]).json()
    kino = by_title(body)["Группа крови"]
    r = import_job(ic, body["token"], kino["index"], "Кино", "Группа крови", instrumental=True)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["type"] == "import" and job["state"] == "queued"
    assert (job["artist"], job["title"]) == ("Кино", "Группа крови")
    p = job["params"]
    d = f"songs/Кино/Кино - Группа крови/jobs/{job['id']}/in"
    assert p == {"source": "files", "instrumental": True, "rel_dir": "Кино/Кино - Группа крови",
                 "replace": False, "replace_rel_dir": None, "target_id": p["target_id"],
                 "inputs": {"dir": d, "txt": f"{d}/song.txt", "audio": f"{d}/audio.mp3",
                            "cover": f"{d}/cover.jpg"}}
    assert (env.data / p["inputs"]["txt"]).read_bytes() == raw
    assert (env.data / p["inputs"]["audio"]).read_bytes() == MP3
    assert (env.data / p["inputs"]["cover"]).read_bytes() == JPG


def test_import_job_audio_sources(env, ic, http):
    body = inspect_files(ic, [("pack.zip", make_zip(PACK))]).json()
    aria = by_title(body)["Беспечный ангел"]
    assert aria["warnings"] and aria["cover"] is False
    # ссылка из песни (#VIDEO a=) — когда своей нет
    r = import_job(ic, body["token"], aria["index"], "Ария", "Беспечный ангел")
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["youtube_url"] == "https://www.youtube.com/watch?v=AbCdEfGhIj0" and "audio" not in p["inputs"]
    ic.post(f"/api/jobs/{r.json()['id']}/cancel")
    # свой mp3 важнее ссылки; не mp3 — 400
    r = import_job(ic, body["token"], aria["index"], "Ария", "Беспечный ангел", audio=b"not mp3 at all")
    assert r.status_code == 400 and r.json()["field"] == "audio"
    r = import_job(ic, body["token"], aria["index"], "Ария", "Беспечный ангел 2", audio=MP3,
                   youtube_url="https://youtu.be/xxxxxxxxxxx")
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert "youtube_url" not in p and p["inputs"]["audio"].endswith("/in/input.mp3")
    # своя ссылка важнее ссылки из песни
    r = import_job(ic, body["token"], aria["index"], "Ария", "Беспечный ангел 3",
                   youtube_url="https://youtu.be/OwnLink0000")
    p = r.json()["params"]
    assert p["youtube_url"] == "https://youtu.be/OwnLink0000"
    assert (p["youtube_from_user"], p["youtube_alternatives"]) == (True, [])  # своя — без подмен


def test_import_job_without_any_audio_is_400(ic):
    pack = make_zip({"s/s.txt": txt("Нет", "Звука")})
    body = inspect_files(ic, [("p.zip", pack)]).json()
    assert body["songs"][0]["warnings"] == [NEED_AUDIO]
    r = import_job(ic, body["token"], 0, "Нет", "Звука")
    assert r.status_code == 400 and r.json() == {"detail": NEED_AUDIO, "field": "audio"}


def test_import_job_downloads_cover_url_from_video_co(env, ic, http):
    pack = make_zip({"s/s.txt": txt("Ко", "Обложка", video="a=AbCdEfGhIj0,co=https://img.example/c.png"),
                     "t/t.txt": txt("Ко", "Битая", video="a=AbCdEfGhIj0,co=https://img.example/bad.png")})
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    http.route("GET", "https://img.example/c.png", body=png)
    http.route("GET", "https://img.example/bad.png", status=404)
    body = inspect_files(ic, [("p.zip", pack)]).json()
    songs = by_title(body)
    assert songs["Обложка"]["cover"] is True
    r = import_job(ic, body["token"], songs["Обложка"]["index"], "Ко", "Обложка")
    inputs = r.json()["params"]["inputs"]
    assert inputs["cover"].endswith("/in/cover.png") and (env.data / inputs["cover"]).read_bytes() == png
    r = import_job(ic, body["token"], songs["Битая"]["index"], "Ко", "Битая")
    assert r.status_code == 201 and "cover" not in r.json()["params"]["inputs"]


# ------------------------------------------------------------------ usdb

USDB = "https://usdb.animux.de/"
USDB_FIX = Path(__file__).resolve().parent / "usdb_fixtures"


def usdb_page(name: str):
    return response(200, (USDB_FIX / name).read_bytes(), headers={"content-type": "text/html; charset=utf-8"})


def test_inspect_usdb_song_and_import_job(env, ic, http):
    http.route("POST", USDB, usdb_page("login_ok.html"))
    http.route("POST", USDB + "index.php?link=gettxt", usdb_page("gettxt.html"))
    http.route("GET", USDB + "index.php?link=detail", usdb_page("detail.html"))
    http.route("GET", "https://usdb.animux.de/data/cover/10101.jpg", body=JPG)
    assert ic.put("/api/settings/usdb", json={"user": "karaoke", "password": "pw-test"}).status_code == 200

    r = ic.post("/api/import/inspect", data={"source": "usdb", "usdb_id": "10101"})
    assert r.status_code == 200, r.text
    body = r.json()
    (s,) = body["songs"]
    assert body["source"] == "usdb" and (s["artist"], s["title"]) == ("Кино", "Звезда по имени Солнце")
    # #VIDEO v= первой, потом ссылки из комментариев, без повторов
    assert s["youtube"] == ["https://www.youtube.com/watch?v=AbCdEfGhIj0",
                            "https://www.youtube.com/watch?v=ZyXwVuTsRq9",
                            "https://www.youtube.com/watch?v=Qq_-1234567"]
    assert s["audio"] is None and s["cover"] is True and s["warnings"] == [
        "Ноты сделаны под конкретную запись — с другой версией слова могут разъехаться"]

    r = import_job(ic, body["token"], 0, "Кино", "Звезда по имени Солнце", instrumental=True)
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["source"] == "usdb" and p["usdb_id"] == 10101 and p["instrumental"] is True
    assert p["youtube_url"] == "https://www.youtube.com/watch?v=AbCdEfGhIj0"
    # запасные ссылки песни для воркера (ролик могли удалить) — без выбранной и повторов
    assert p["youtube_alternatives"] == ["https://www.youtube.com/watch?v=ZyXwVuTsRq9",
                                         "https://www.youtube.com/watch?v=Qq_-1234567"]
    assert p["youtube_from_user"] is False
    assert set(p["inputs"]) == {"dir", "txt", "cover"}
    assert (env.data / p["inputs"]["cover"]).read_bytes() == JPG
    assert (env.data / p["inputs"]["txt"]).read_bytes().decode("utf-8").startswith("#TITLE:Звезда по имени Солнце\n")


def test_inspect_usdb_needs_account(ic):
    r = ic.post("/api/import/inspect", data={"source": "usdb", "usdb_id": "1"})
    assert r.status_code == 400 and r.json()["code"] == "usdb_no_account"


# ------------------------------------------------------------------ url


def test_inspect_zip_by_url(ic, http):
    http.route("GET", "https://packs.example/ru.zip", body=make_zip(PACK))
    http.route("GET", "https://packs.example/page.html", body=b"<html>nope</html>")
    http.route("GET", "https://packs.example/missing.zip", status=404)
    r = ic.post("/api/import/inspect", data={"source": "url", "url": "https://packs.example/ru.zip"})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "url" and len(r.json()["songs"]) == 2
    assert http.calls("https://packs.example/ru.zip")[0].max_bytes == 500 * 2**20
    for url in ("https://packs.example/page.html", "https://packs.example/missing.zip", "ftp://x/y.zip"):
        r = ic.post("/api/import/inspect", data={"source": "url", "url": url})
        assert r.status_code == 400 and r.json()["field"] == "url", url


def test_inspect_url_too_big_is_413(ic, http):
    from karaoke_core.http import HttpError
    http.route("GET", "https://packs.example/big.zip",
               HttpError("Ответ сервера packs.example слишком большой (больше 1 байт)", too_large=True))
    r = ic.post("/api/import/inspect", data={"source": "url", "url": "https://packs.example/big.zip"})
    assert r.status_code == 413 and r.json()["field"] == "url"


GH_ZIP = make_zip({
    "UltraStarSongs-master/Russian/Кино - Группа крови/Кино - Группа крови.txt": PACK["pack/Кино - Группа крови/Кино - Группа крови.txt"],
    "UltraStarSongs-master/Russian/Кино - Группа крови/Кино - Группа крови.mp3": MP3,
    "UltraStarSongs-master/English/Song/song.txt": txt("Band", "Song", audio="x.mp3"),
})


def test_inspect_github_repo_default_branch(ic, http):
    http.route("GET", "https://api.github.com/repos/Vasil-Pahomov/UltraStarSongs", json={"default_branch": "master"})
    http.route("GET", "https://codeload.github.com/Vasil-Pahomov/UltraStarSongs/zip/refs/heads/master", body=GH_ZIP)
    r = ic.post("/api/import/inspect", data={"source": "url", "url": "https://github.com/Vasil-Pahomov/UltraStarSongs"})
    assert r.status_code == 200, r.text
    assert sorted(s["title"] for s in r.json()["songs"]) == ["Song", "Группа крови"]


def test_inspect_github_tree_folder_only(env, ic, http):
    http.route("GET", "https://codeload.github.com/Vasil-Pahomov/UltraStarSongs/zip/refs/heads/dev", body=GH_ZIP)
    r = ic.post("/api/import/inspect", data={
        "source": "url", "url": "https://github.com/Vasil-Pahomov/UltraStarSongs/tree/dev/Russian"})
    assert r.status_code == 200, r.text
    assert not http.calls("https://api.github.com/")
    (s,) = r.json()["songs"]
    assert s["title"] == "Группа крови" and s["audio"] == "Кино - Группа крови.mp3"
    job = import_job(ic, r.json()["token"], 0, "Кино", "Группа крови")
    assert job.status_code == 201, job.text
    assert (env.data / job.json()["params"]["inputs"]["audio"]).read_bytes() == MP3


# ------------------------------------------------------------------ токен и дубли


def test_stale_token_is_410_and_old_imports_are_purged(env, ic):
    body = inspect_files(ic, [("pack.zip", make_zip(PACK))]).json()
    work = env.data / "imports" / body["token"]
    old = time.time() - 3601
    os.utime(work / "meta.json", (old, old))
    r = import_job(ic, body["token"], 0, "Кино", "Группа крови")
    assert r.status_code == 410 and r.json()["detail"] == "Загрузка устарела, загрузите заново"
    assert import_job(ic, "no-such-token", 0, "A", "B").status_code == 410

    body = inspect_files(ic, [("pack.zip", make_zip(PACK))]).json()
    stale = env.data / "imports" / body["token"]
    os.utime(stale / "meta.json", (old, old))
    fresh = inspect_files(ic, [("pack.zip", make_zip(PACK))]).json()
    assert not stale.exists() and (env.data / "imports" / fresh["token"]).is_dir()


def test_duplicates(env, ic):
    env.put_song("Кино/Кино - Группа крови", env.SONG_TXT.replace(b"Artist", b"\xd0\x9a\xd0\xb8\xd0\xbd\xd0\xbe")
                 .replace(b"#TITLE:Song", "#TITLE:Группа крови".encode()), "Кино - Группа крови")
    assert ic.post("/api/songs/rescan").status_code == 202
    body = inspect_files(ic, [("pack.zip", make_zip(PACK))]).json()
    kino = by_title(body)["Группа крови"]
    assert kino["existing_song_id"]
    r = import_job(ic, body["token"], kino["index"], "Кино", "Группа крови")
    assert r.status_code == 409 and r.json()["song_id"] == kino["existing_song_id"]
    r = import_job(ic, body["token"], kino["index"], "Кино", "Группа крови", replace=True)
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["replace"] is True and p["replace_rel_dir"] == "Кино/Кино - Группа крови"
    # дубль в очереди — и с import, и с generate
    r = import_job(ic, body["token"], kino["index"], "Кино", "Группа крови", replace=True)
    assert r.status_code == 409 and r.json()["detail"] == "Эта песня уже в очереди"
    aria = by_title(body)["Беспечный ангел"]
    r = ic.post("/api/jobs/generate", data={"artist": "Ария", "title": "Беспечный ангел"},
                files={"audio": ("a.mp3", MP3)})
    assert r.status_code == 201, r.text
    r = import_job(ic, body["token"], aria["index"], "Ария", "Беспечный ангел")
    assert r.status_code == 409 and r.json()["detail"] == "Эта песня уже в очереди"


@pytest.mark.parametrize("folder", ["../..", "%2e%2e", "%2E%2E/%2e%2e/etc", "ok/../../x", "C:/Windows",
                                    "..%2f..", "a/%5c..%5c.."])
def test_github_folder_escaping_import_dir_is_400_before_download(env, ic, http, folder):
    http.route("GET", "https://codeload.github.com/", body=GH_ZIP)
    r = ic.post("/api/import/inspect", data={
        "source": "url", "url": f"https://github.com/Vasil-Pahomov/UltraStarSongs/tree/main/{folder}"})
    assert r.status_code == 400 and r.json()["field"] == "url", r.text
    assert not http.requests
    assert not any((env.data / "imports").iterdir())


@pytest.mark.parametrize("key,value", [("txt_rel", "files/../../../../secret.txt"),
                                       ("audio_rel", "files/../../../../secret.txt"),
                                       ("cover_rel", "files/../meta.json")])
def test_import_job_rejects_paths_outside_files(env, ic, key, value):
    body = inspect_files(ic, [("pack.zip", make_zip(PACK))]).json()
    meta_path = env.data / "imports" / body["token"] / "meta.json"
    (env.tmp / "secret.txt").write_bytes(b"secret")
    meta = json.loads(meta_path.read_text("utf-8"))
    kino = next(s for s in meta["songs"] if s["title"] == "Группа крови")
    assert kino["txt_rel"] and kino["audio_rel"] and kino["cover_rel"]  # все три пути копируются
    kino[key] = value
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    r = import_job(ic, body["token"], kino["index"], "Кино", "Группа крови")
    assert r.status_code == 400 and r.json()["detail"] == "Недопустимый путь в загрузке"
    assert not ic.get("/api/jobs").json()
    assert not any(p.is_file() for p in (env.data / "songs").rglob("*"))


# ------------------------------------------------------------------ россыпь и размер


def test_loose_files_with_same_name_are_400(ic):
    song = txt("Ария", "Ангел", audio="a.mp3")
    r = inspect_files(ic, [("Ария - Ангел.txt", song), ("ария - ангел.TXT", song), ("a.mp3", MP3)])
    assert r.status_code == 400 and r.json()["field"] == "files"
    assert "Ария - Ангел.txt" in r.json()["detail"] or "ария - ангел.TXT" in r.json()["detail"]
    r = inspect_files(ic, [("one/Ария - Ангел.txt", song), ("One/ария - ангел.txt", song), ("a.mp3", MP3)])
    assert r.status_code == 400 and r.json()["field"] == "files"


# ------------------------------------------------------------------ папка с относительными путями


def test_folder_upload_keeps_relative_paths(env, ic):
    """Папка из браузера: одинаковые имена в разных подпапках — разные песни, пути сохраняются."""
    kino = txt("Кино", "Группа крови", audio="song.mp3", cover="cover.jpg")
    aria = txt("Ария", "Ангел", audio="song.mp3")
    r = inspect_files(ic, [("Музыка/Кино - Группа крови/song.txt", kino),
                           ("Музыка/Кино - Группа крови/song.mp3", MP3),
                           ("Музыка/Кино - Группа крови/cover.jpg", JPG),
                           ("Музыка/Ария - Ангел/song.txt", aria),
                           ("Музыка/Ария - Ангел/song.mp3", MP3 + b"!"),
                           ("Музыка/Сплин - Романс.mp3", MP3),
                           ("Музыка/.hidden/x.txt", b"#TITLE:x"),
                           ("Музыка/readme.md", b"x")])
    assert r.status_code == 200, r.text
    body = r.json()
    songs = by_title(body)
    assert set(songs) == {"Группа крови", "Ангел"}
    assert songs["Группа крови"]["audio"] == "song.mp3" and songs["Группа крови"]["cover"] is True
    files = env.data / "imports" / body["token"] / "files"
    assert (files / "Музыка/Ария - Ангел/song.mp3").read_bytes() == MP3 + b"!"
    assert (files / "Музыка/Сплин - Романс.mp3").is_file()
    assert not (files / "Музыка/.hidden").exists() and not (files / "Музыка/readme.md").exists()
    meta = json.loads((env.data / "imports" / body["token"] / "meta.json").read_text("utf-8"))
    aria_meta = next(s for s in meta["songs"] if s["title"] == "Ангел")
    r = import_job(ic, body["token"], aria_meta["index"], "Ария", "Ангел")
    assert r.status_code == 201, r.text
    job = r.json()
    audio = env.data / job["params"]["inputs"]["audio"]
    assert audio.read_bytes() == MP3 + b"!"


@pytest.mark.parametrize("name", ["../x/song.txt", "a/../../song.txt", "/etc/song.txt", "C:/Music/song.txt",
                                  "a/C:/song.txt", "a\\..\\..\\song.txt"])
def test_folder_upload_rejects_bad_paths(env, ic, name):
    r = inspect_files(ic, [(name, txt("Ария", "Ангел", audio="a.mp3")), ("a.mp3", MP3)])
    assert r.status_code == 400 and r.json()["field"] == "files", r.text
    assert r.json()["detail"] == "Недопустимый путь в загрузке"
    assert not any((env.data / "imports").iterdir())


def test_loose_files_size_error_speaks_of_files(ic):
    ic.app.state.ctx.env["MAX_IMPORT_MB"] = "1"
    song = txt("Ария", "Ангел", audio="a.mp3")
    r = inspect_files(ic, [("Ария - Ангел.txt", song), ("a.mp3", MP3 + bytes(1024 * 1024))])
    assert r.status_code == 413 and r.json()["field"] == "files"
    assert "Архив" not in r.json()["detail"] and "Файлы" in r.json()["detail"]


def test_url_download_over_limit_is_413_via_fake_download(ic, http):
    ic.app.state.ctx.env["MAX_IMPORT_MB"] = "1"
    http.route("GET", "https://packs.example/huge.zip", body=b"PK\x03\x04" + bytes(1024 * 1024))
    r = ic.post("/api/import/inspect", data={"source": "url", "url": "https://packs.example/huge.zip"})
    assert r.status_code == 413 and r.json()["field"] == "url"


@pytest.mark.parametrize("names", [["a/x.txt", "a/x.txt/song.txt"], ["a/X.TXT/song.txt", "a/x.txt"],
                                   ["a/" + "я" * 200 + ".txt"], ["a/" + "d" * 300 + "/song.txt"]])
def test_folder_upload_unwritable_paths_are_400(env, ic, names):
    """Файл и папка с одним именем или слишком длинное имя — 400, ничего не записано."""
    song = txt("Ария", "Ангел", audio="a.mp3")
    r = inspect_files(ic, [(n, song) for n in names] + [("a/a.mp3", MP3)])
    assert r.status_code == 400 and r.json()["field"] == "files", r.text
    assert "Недопустим" not in r.json()["detail"] and r.json()["detail"]
    assert not any((env.data / "imports").iterdir())


def test_import_job_youtube_alternatives_from_chosen_song_link(env, ic, http):
    """Фронт присылает ссылку песни как есть: она не «своя», запасные — прочие ссылки песни (≤ 5)."""
    http.route("POST", USDB, usdb_page("login_ok.html"))
    http.route("POST", USDB + "index.php?link=gettxt", usdb_page("gettxt.html"))
    http.route("GET", USDB + "index.php?link=detail", usdb_page("detail.html"))
    http.route("GET", "https://usdb.animux.de/data/cover/10101.jpg", body=JPG)
    assert ic.put("/api/settings/usdb", json={"user": "karaoke", "password": "pw-test"}).status_code == 200
    body = ic.post("/api/import/inspect", data={"source": "usdb", "usdb_id": "10101"}).json()
    r = import_job(ic, body["token"], 0, "Кино", "Звезда по имени Солнце",
                   youtube_url="https://www.youtube.com/watch?v=ZyXwVuTsRq9")
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["youtube_url"] == "https://www.youtube.com/watch?v=ZyXwVuTsRq9" and p["youtube_from_user"] is False
    assert p["youtube_alternatives"] == ["https://www.youtube.com/watch?v=AbCdEfGhIj0",
                                         "https://www.youtube.com/watch?v=Qq_-1234567"]


def test_import_job_youtube_alternatives_are_limited(env, ic):
    links = [f"https://www.youtube.com/watch?v=Link{i:07d}" for i in range(8)]
    pack = make_zip({"s/s.txt": txt("Много", "Ссылок", video=f"v={links[0][-11:]}")})
    body = inspect_files(ic, [("p.zip", pack)]).json()
    # у песни 8 ссылок с повтором (подмена разбора в meta.json)
    meta_path = env.data / "imports" / body["token"] / "meta.json"
    meta = json.loads(meta_path.read_text("utf-8"))
    meta["songs"][0]["youtube"] = links + [links[1], " "]
    meta_path.write_text(json.dumps(meta), "utf-8")
    p = import_job(ic, body["token"], 0, "Много", "Ссылок").json()["params"]
    assert p["youtube_url"] == links[0] and p["youtube_alternatives"] == links[1:6]


# --------------------------------------------------------------------------- видео (истории 25, 26, 29)

VIDEO_PACK = {
    "p/song.txt": txt("Ария", "Штиль", audio="a.mp3", video="Clip.MP4\n#VIDEOGAP:1,5"),
    "p/a.mp3": MP3,
    "p/Clip.MP4": b"MP4-DATA",
}


def _video_pack(ic):
    r = inspect_files(ic, [("p.zip", make_zip(VIDEO_PACK))])
    assert r.status_code == 200, r.text
    return r.json()


def test_inspect_and_import_video_from_pack(env, ic):
    body = _video_pack(ic)
    (s,) = body["songs"]
    assert (s["video_file"], s["video_links"], s["videogap"]) == ("Clip.MP4", [], 1.5)
    r = import_job(ic, body["token"], 0, "Ария", "Штиль", video_mode="pack", videogap="1.5")
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["video"] == {"mode": "pack", "gap": 1.5}  # качество — только у ссылки
    assert p["inputs"]["video"].endswith("/in/video.mp4")
    assert (env.data / p["inputs"]["video"]).read_bytes() == b"MP4-DATA"
    # «без видео» — как раньше: ни params.video, ни файла
    r = import_job(ic, _video_pack(ic)["token"], 0, "Ария", "Штиль 2", video_mode="none")
    p = r.json()["params"]
    assert "video" not in p and "video" not in p["inputs"]


def test_import_video_url_and_file_and_errors(env, ic):
    token = _video_pack(ic)["token"]
    r = import_job(ic, token, 0, "Ария", "Штиль", video_mode="url",
                   video_url="https://vk.com/video-1_2", video_height="1080")
    assert r.status_code == 201, r.text
    assert r.json()["params"]["video"] == {"mode": "url", "url": "https://vk.com/video-1_2", "height": 1080}

    def err(**form):
        files = form.pop("files", None)
        data = {"token": _video_pack(ic)["token"], "index": "0", "artist": "Ария", "title": "Ш", **form}
        r = ic.post("/api/jobs/import", data=data, files=files)
        return r.status_code, r.json().get("field")

    assert err(video_mode="url", video_url="https://music.yandex.ru/album/1/track/2") == (400, "video_url")
    assert err(video_mode="url") == (400, "video_url")
    assert err(video_mode="file") == (400, "video_file")
    assert err(video_mode="file", files={"video_file": ("x.exe", b"1")}) == (400, "video_file")
    assert err(video_mode="source") == (400, "video_mode")  # у пакета нет ссылки на видео
    assert err(video_mode="кино") == (400, "video_mode")
    assert err(video_mode="url", video_url="https://vk.com/video-1_2", video_height="5") == (400, "video_height")
    assert err(video_mode="pack", videogap="x") == (400, "videogap")
    r = import_job(ic, _video_pack(ic)["token"], 0, "Ария", "Штиль 3", video_mode="file")
    assert r.status_code == 400
    r = ic.post("/api/jobs/import", data={"token": _video_pack(ic)["token"], "index": "0", "artist": "Ария",
                                          "title": "Штиль 4", "video_mode": "file"},
                files={"video_file": ("my.webm", b"WEBM")})
    assert r.status_code == 201, r.text
    p = r.json()["params"]
    assert p["video"] == {"mode": "file"}
    assert (env.data / p["inputs"]["video"]).read_bytes() == b"WEBM" and p["inputs"]["video"].endswith("video.webm")


def test_import_video_file_over_limit_413(env, http):
    with env.client(extra_env={"MAX_VIDEO_MB": "1"}, http=http) as c:
        token = _video_pack(c)["token"]
        r = c.post("/api/jobs/import", data={"token": token, "index": "0", "artist": "Ария", "title": "Ш",
                                             "video_mode": "file"},
                   files={"video_file": ("my.mp4", b"0" * (1024 * 1024 + 1))})
        assert (r.status_code, r.json().get("field")) == (413, "video_file")


def test_usdb_video_link_is_source(env, ic, http):
    http.route("POST", USDB, usdb_page("login_ok.html"))
    http.route("POST", USDB + "index.php?link=gettxt", usdb_page("gettxt.html"))
    http.route("GET", USDB + "index.php?link=detail", usdb_page("detail.html"))
    http.route("GET", "https://usdb.animux.de/data/cover/10101.jpg", body=JPG)
    assert ic.put("/api/settings/usdb", json={"user": "karaoke", "password": "pw-test"}).status_code == 200
    body = ic.post("/api/import/inspect", data={"source": "usdb", "usdb_id": "10101"}).json()
    (s,) = body["songs"]
    assert s["video_links"] == ["https://www.youtube.com/watch?v=AbCdEfGhIj0"] and s["video_file"] is None
    r = import_job(ic, body["token"], 0, "Кино", "Звезда по имени Солнце", video_mode="source",
                   youtube_url="https://www.youtube.com/watch?v=Qq_-1234567", video_height="0")
    assert r.status_code == 201, r.text
    # v= из #VIDEO важнее ссылки звука
    assert r.json()["params"]["video"] == {"mode": "source", "url": "https://www.youtube.com/watch?v=AbCdEfGhIj0",
                                           "height": 0}


def test_source_video_falls_back_to_chosen_audio_link(env, ic):
    body = inspect_files(ic, [("s.txt", txt("Ария", "Ангел", video="a=AbCdEfGhIj0"))]).json()
    assert body["songs"][0]["video_links"] == []
    r = import_job(ic, body["token"], 0, "Ария", "Ангел", video_mode="source")
    assert r.status_code == 201, r.text
    assert r.json()["params"]["video"]["url"] == "https://www.youtube.com/watch?v=AbCdEfGhIj0"
