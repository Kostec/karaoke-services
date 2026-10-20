"""SQLite (WAL) в томе ``data``: очередь заданий, настройки, индекс песен, свои песни.

Каждый процесс/поток открывает своё соединение через :func:`connect`.
Транзакции явные (``BEGIN IMMEDIATE``), поэтому захват задания атомарен даже
при нескольких конкурирующих соединениях.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

__all__ = [
    "connect", "Jobs", "Job", "Settings", "OutputTarget", "Library", "LibraryItem",
    "Songs", "OwnSong", "song_id_for", "JOB_STATES", "FINAL_STATES",
    "INTERRUPTED_MESSAGE",
]

JOB_STATES = ("queued", "running", "publishing", "done", "failed", "cancelled")
FINAL_STATES = ("done", "failed", "cancelled")
INTERRUPTED_MESSAGE = "прервано перезапуском"

_SCHEMA_V1 = """
CREATE TABLE jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    type             TEXT NOT NULL,
    state            TEXT NOT NULL DEFAULT 'queued',
    stage            TEXT,
    percent          REAL,
    artist           TEXT NOT NULL DEFAULT '',
    title            TEXT NOT NULL DEFAULT '',
    song_id          TEXT,
    params           TEXT NOT NULL DEFAULT '{}',
    error            TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    parent_id        INTEGER,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT
);
CREATE INDEX jobs_state ON jobs(state, id);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE library (
    target_id    TEXT NOT NULL,
    rel_dir      TEXT NOT NULL,
    txt_name     TEXT NOT NULL,
    artist       TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    audio        TEXT,
    instrumental TEXT,
    cover        TEXT,
    is_duet      INTEGER NOT NULL DEFAULT 0,
    own_song_id  TEXT,
    mtime        REAL,
    scanned_at   TEXT,
    PRIMARY KEY (target_id, rel_dir)
);

CREATE TABLE songs (
    id         TEXT PRIMARY KEY,
    rel_dir    TEXT NOT NULL UNIQUE,
    artist     TEXT NOT NULL,
    title      TEXT NOT NULL,
    params     TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_MIGRATIONS = [_SCHEMA_V1]


def now() -> str:
    """Текущее время UTC в ISO 8601."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path) -> sqlite3.Connection:
    """Открыть БД (создать и мигрировать при необходимости). WAL, ожидание блокировок."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    with _tx(conn):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(_MIGRATIONS[version:], start=version + 1):
            for stmt in filter(str.strip, script.split(";")):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {i}")


@contextmanager
def _tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# --------------------------------------------------------------------------- задания

@dataclass
class Job:
    id: int
    type: str
    state: str
    stage: str | None
    percent: float | None
    artist: str
    title: str
    song_id: str | None
    params: dict
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    cancel_requested: bool = False
    parent_id: int | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        d = dict(row)
        d["params"] = json.loads(d["params"] or "{}")
        d["cancel_requested"] = bool(d["cancel_requested"])
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)


_JOB_UPDATABLE = {"state", "stage", "percent", "artist", "title", "song_id", "params",
                  "error", "cancel_requested", "started_at", "finished_at"}


def _song_ref(song_ref: Any) -> tuple[str, str, str | None]:
    if song_ref is None:
        return "", "", None
    if isinstance(song_ref, Mapping):
        get = song_ref.get
    else:
        def get(k, default=None):
            return getattr(song_ref, k, default)
    return get("artist", "") or "", get("title", "") or "", get("song_id")


class Jobs:
    """Очередь заданий. Состояния: queued → running → publishing → done;
    queued → cancelled; running|publishing → failed|cancelled."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def enqueue(self, type: str, song_ref: Any, params: dict | None = None,
                *, parent_id: int | None = None) -> Job:
        """Поставить задание. ``song_ref`` — mapping/объект с artist, title, song_id."""
        artist, title, song_id = _song_ref(song_ref)
        with _tx(self.conn):
            row = self.conn.execute(
                "INSERT INTO jobs (type, state, artist, title, song_id, params, parent_id, created_at)"
                " VALUES (?, 'queued', ?, ?, ?, ?, ?, ?) RETURNING *",
                (type, artist, title, song_id, json.dumps(params or {}, ensure_ascii=False),
                 parent_id, now()),
            ).fetchone()
        return Job.from_row(row)

    def claim_next(self) -> Job | None:
        """Атомарно забрать самое старое задание из очереди (queued → running)."""
        with _tx(self.conn):
            row = self.conn.execute(
                "UPDATE jobs SET state='running', started_at=?"
                " WHERE id = (SELECT id FROM jobs WHERE state='queued' ORDER BY id LIMIT 1)"
                " RETURNING *",
                (now(),),
            ).fetchone()
        return Job.from_row(row) if row else None

    def get(self, id: int) -> Job | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (id,)).fetchone()
        return Job.from_row(row) if row else None

    def list(self, limit: int = 50) -> list[Job]:
        rows = self.conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
        return [Job.from_row(r) for r in rows]

    def update(self, id: int, **fields_: Any) -> Job | None:
        """Обновить поля задания. Переход в конечное состояние ставит finished_at."""
        unknown = set(fields_) - _JOB_UPDATABLE
        if unknown:
            raise ValueError(f"Неизвестные поля задания: {', '.join(sorted(unknown))}")
        if fields_.get("state") in FINAL_STATES and "finished_at" not in fields_:
            fields_["finished_at"] = now()
        if "params" in fields_:
            fields_["params"] = json.dumps(fields_["params"] or {}, ensure_ascii=False)
        if "cancel_requested" in fields_:
            fields_["cancel_requested"] = int(bool(fields_["cancel_requested"]))
        if fields_:
            cols = ", ".join(f"{k}=?" for k in fields_)
            with _tx(self.conn):
                self.conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields_.values(), id))
        return self.get(id)

    def request_cancel(self, id: int) -> Job | None:
        """Отмена: из очереди — сразу cancelled, у выполняемого — флаг для воркера."""
        with _tx(self.conn):
            self.conn.execute(
                "UPDATE jobs SET state='cancelled', finished_at=? WHERE id=? AND state='queued'",
                (now(), id))
            self.conn.execute(
                "UPDATE jobs SET cancel_requested=1 WHERE id=? AND state IN ('running','publishing')",
                (id,))
        return self.get(id)

    def fail_interrupted(self) -> int:
        """При старте воркера: running|publishing → failed «прервано перезапуском»."""
        with _tx(self.conn):
            cur = self.conn.execute(
                "UPDATE jobs SET state='failed', error=?, finished_at=?"
                " WHERE state IN ('running','publishing')",
                (INTERRUPTED_MESSAGE, now()))
        return cur.rowcount


# --------------------------------------------------------------------------- настройки

LOCAL_OUTPUT_MOUNT = "/output"


# Единственное место, где задан формат идентификатора и подписи папки результата:
# OutputTarget и реализации karaoke_core.storage берут их отсюда.
def smb_target_id(host: str, share: str, path: str = "") -> str:
    return f"smb://{host}/{share}/{path}".rstrip("/")


def smb_label(host: str, share: str, path: str = "") -> str:
    return f"//{host}/{share}/{path}".rstrip("/")


def local_target_id(root: str) -> str:
    return f"local:{local_label(root)}"


def local_label(root: str) -> str:
    return str(root).replace("\\", "/").rstrip("/") or "/"


@dataclass
class OutputTarget:
    """Папка результата: Samba-шара или подпапка примонтированного ``/output``."""
    kind: str = "smb"  # smb | local
    host: str = ""
    share: str = ""
    path: str = ""  # путь внутри шары или внутри /output
    user: str = ""
    password: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "OutputTarget":
        env = os.environ if env is None else env
        kind = (env.get("OUTPUT_KIND") or "smb").strip().lower()
        # Локальная цель из .env — корень /output (его задаёт LOCAL_OUTPUT_ROOT);
        # подпапка внутри него выбирается в вебе.
        path = (env.get("OUTPUT_SMB_PATH") or "").strip("/\\") if kind == "smb" else ""
        return cls(
            kind=kind,
            host=env.get("OUTPUT_SMB_HOST", "192.168.0.129"),
            share=env.get("OUTPUT_SMB_SHARE", "karaoke"),
            path=path,
            user=env.get("OUTPUT_SMB_USER", ""),
            password=env.get("OUTPUT_SMB_PASSWORD") or None,
        )

    @property
    def target_id(self) -> str:
        if self.kind == "local":
            return local_target_id(self.local_root)
        return smb_target_id(self.host, self.share, self.path)

    @property
    def local_root(self) -> str:
        return f"{LOCAL_OUTPUT_MOUNT}/{self.path}".rstrip("/") if self.path else LOCAL_OUTPUT_MOUNT

    @property
    def label(self) -> str:
        if self.kind == "local":
            return local_label(self.local_root)
        return smb_label(self.host, self.share, self.path)

    def public(self) -> dict:
        """Для API: без пароля, только признак его наличия."""
        return {"kind": self.kind, "host": self.host, "share": self.share, "path": self.path,
                "user": self.user, "has_password": bool(self.password),
                "label": self.label, "target_id": self.target_id}

    def _to_json(self) -> str:
        return json.dumps({f.name: getattr(self, f.name) for f in fields(self)},
                          ensure_ascii=False)


class Settings:
    def __init__(self, conn: sqlite3.Connection, env: Mapping[str, str] | None = None):
        self.conn = conn
        self.env = env

    def _get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str) -> None:
        with _tx(self.conn):
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def get_output(self) -> OutputTarget:
        """Текущая цель; пока не сохранена в вебе — из переменных ``OUTPUT_*``."""
        raw = self._get("output")
        if raw is None:
            return OutputTarget.from_env(self.env)
        return OutputTarget(**json.loads(raw))

    def set_output(self, target: OutputTarget) -> OutputTarget:
        """Сохранить цель. ``password=None`` — оставить прежний пароль."""
        if target.password is None:
            target = OutputTarget(**{**asdict(target), "password": self.get_output().password})
        self._set("output", target._to_json())
        return target


# --------------------------------------------------------------------------- индекс песен

def song_id_for(target_id: str, rel_dir: str) -> str:
    """Стабильный идентификатор песни в папке результата."""
    return hashlib.sha1(f"{target_id}\n{rel_dir}".encode("utf-8")).hexdigest()[:16]


@dataclass
class LibraryItem:
    target_id: str
    rel_dir: str
    txt_name: str
    artist: str = ""
    title: str = ""
    audio: str | None = None
    instrumental: str | None = None
    cover: str | None = None
    is_duet: bool = False
    own_song_id: str | None = None
    mtime: float | None = None
    scanned_at: str | None = None

    @property
    def song_id(self) -> str:
        return song_id_for(self.target_id, self.rel_dir)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "LibraryItem":
        d = dict(row)
        d["is_duet"] = bool(d["is_duet"])
        return cls(**d)

    def to_dict(self) -> dict:
        return {**asdict(self), "song_id": self.song_id}


_LIB_COLS = [f.name for f in fields(LibraryItem)]


def _fold(s: str | None) -> str:
    return (s or "").casefold().replace("ё", "е")


class Library:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _insert(self, item: LibraryItem) -> None:
        values = [getattr(item, c) for c in _LIB_COLS]
        values[_LIB_COLS.index("is_duet")] = int(bool(item.is_duet))
        self.conn.execute(
            f"INSERT INTO library ({', '.join(_LIB_COLS)}) VALUES ({', '.join('?' * len(_LIB_COLS))})"
            f" ON CONFLICT(target_id, rel_dir) DO UPDATE SET "
            + ", ".join(f"{c}=excluded.{c}" for c in _LIB_COLS if c not in ("target_id", "rel_dir")),
            values)

    def replace_all(self, target_id: str, items) -> None:
        """Заменить весь индекс цели результатами нового сканирования."""
        with _tx(self.conn):
            self.conn.execute("DELETE FROM library WHERE target_id=?", (target_id,))
            for item in items:
                item.target_id = target_id
                self._insert(item)

    def upsert(self, item: LibraryItem) -> None:
        with _tx(self.conn):
            self._insert(item)

    def remove(self, target_id: str, rel_dir: str) -> None:
        with _tx(self.conn):
            self.conn.execute("DELETE FROM library WHERE target_id=? AND rel_dir=?",
                              (target_id, rel_dir))

    def list(self, target_id: str, q: str | None = None) -> list[LibraryItem]:
        """Песни цели, по исполнителю и названию; ``q`` — подстрока без учёта регистра и ё."""
        rows = self.conn.execute("SELECT * FROM library WHERE target_id=?", (target_id,))
        items = [LibraryItem.from_row(r) for r in rows]
        if q and q.strip():
            needle = _fold(q.strip())
            items = [i for i in items
                     if needle in _fold(i.artist) or needle in _fold(i.title)
                     or needle in _fold(i.rel_dir)]
        items.sort(key=lambda i: (_fold(i.artist), _fold(i.title), i.rel_dir))
        return items

    def get(self, target_id: str, rel_dir: str) -> LibraryItem | None:
        row = self.conn.execute("SELECT * FROM library WHERE target_id=? AND rel_dir=?",
                                (target_id, rel_dir)).fetchone()
        return LibraryItem.from_row(row) if row else None


# --------------------------------------------------------------------------- свои песни

@dataclass
class OwnSong:
    """Песня, созданная сервисом: исходники лежат в томе ``data/songs/<rel_dir>/source``."""
    id: str
    rel_dir: str
    artist: str
    title: str
    params: dict
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "OwnSong":
        d = dict(row)
        d["params"] = json.loads(d["params"] or "{}")
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)


class Songs:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, id: str) -> OwnSong | None:
        row = self.conn.execute("SELECT * FROM songs WHERE id=?", (id,)).fetchone()
        return OwnSong.from_row(row) if row else None

    def by_rel_dir(self, rel_dir: str) -> OwnSong | None:
        row = self.conn.execute("SELECT * FROM songs WHERE rel_dir=?", (rel_dir,)).fetchone()
        return OwnSong.from_row(row) if row else None

    def upsert(self, *, artist: str, title: str, rel_dir: str, params: dict | None = None) -> OwnSong:
        """Создать или обновить запись по ``rel_dir`` (id сохраняется)."""
        ts = now()
        with _tx(self.conn):
            row = self.conn.execute(
                "INSERT INTO songs (id, rel_dir, artist, title, params, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(rel_dir) DO UPDATE SET artist=excluded.artist, title=excluded.title,"
                " params=excluded.params, updated_at=excluded.updated_at RETURNING *",
                (uuid.uuid4().hex, rel_dir, artist, title,
                 json.dumps(params or {}, ensure_ascii=False), ts, ts),
            ).fetchone()
        return OwnSong.from_row(row)

    def delete(self, id: str) -> None:
        with _tx(self.conn):
            self.conn.execute("DELETE FROM songs WHERE id=?", (id,))
