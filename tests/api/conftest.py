"""Шов 2: REST API через TestClient с LocalStorage во временной папке и временной БД."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from karaoke_core.storage import LocalStorage, make_storage

MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
SONG_TXT = (
    "#TITLE:Song\n#ARTIST:Artist\n#MP3:Artist - Song.mp3\n#AUDIO:Artist - Song.mp3\n"
    "#COVER:Artist - Song [CO].jpg\n#BPM:300\n#GAP:1000\n#X-CUSTOM:keep\n"
    ": 0 4 5 При\n: 4 4 5 вет\n- 10\n: 12 4 7 мир\n* 16 2 7 !\nE\n"
).encode("utf-8")
DUET_TXT = (
    "#TITLE:Duet\n#ARTIST:Pair\n#MP3:Pair - Duet.mp3\n#BPM:300\n#GAP:0\n"
    "P1\n: 0 4 5 Раз\n- 6\nP2\n: 8 4 5 Два\nE\n"
).encode("utf-8")


ENV_EXAMPLE = dict(
    m.groups() for m in (re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line) for line in
                         (Path(__file__).resolve().parents[2] / ".env.example")
                         .read_text("utf-8").splitlines()) if m)


class Env:
    MP3, SONG_TXT, DUET_TXT = MP3, SONG_TXT, DUET_TXT

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.out = tmp_path / "output"
        self.out.mkdir(exist_ok=True)
        self.data = tmp_path / "data"

    def put_song(self, rel_dir: str, txt: bytes, base: str, *, audio: bytes = MP3,
                 cover: bytes | None = b"\xff\xd8\xff\xe0jpeg") -> Path:
        d = self.out.joinpath(*rel_dir.split("/"))
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{base}.txt").write_bytes(txt)
        (d / f"{base}.mp3").write_bytes(audio)
        if cover is not None:
            (d / f"{base} [CO].jpg").write_bytes(cover)
        return d

    def factory(self, target):
        if target.kind == "local":
            root = self.out / target.path if target.path else self.out
            return LocalStorage(root, target_id=target.target_id, label=target.label)
        return make_storage(target)

    def client(self, password: str = "", *, storage_factory=None, extra_env: dict | None = None,
               **kw) -> TestClient:
        # Умолчания — из .env.example (единственный источник), поверх — тестовые значения.
        env = {**ENV_EXAMPLE, "OUTPUT_KIND": "local", "WEB_PASSWORD": password, "MAX_UPLOAD_MB": "1",
               **(extra_env or {})}
        app = create_app(data_dir=self.data, env=env, storage_factory=storage_factory or self.factory, **kw)
        return TestClient(app)


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def client(env) -> TestClient:
    with env.client() as c:
        yield c


@pytest.fixture
def song(env, client) -> dict:
    """Чужая песня в папке результата, индекс пересканирован; возвращает SongEntry из API."""
    env.put_song("Artist/Artist - Song", SONG_TXT, "Artist - Song")
    assert client.post("/api/songs/rescan").status_code == 202
    items = client.get("/api/songs").json()["items"]
    return next(i for i in items if i["title"] == "Song")
