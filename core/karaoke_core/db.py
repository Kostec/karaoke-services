"""SQLite (WAL) в томе ``data``: очередь заданий, настройки, индекс песен, свои песни.

Каждый процесс/поток открывает своё соединение через :func:`connect`.
Транзакции явные (``BEGIN IMMEDIATE``), поэтому захват задания атомарен даже
при нескольких конкурирующих соединениях.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import urllib.parse
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Any, Callable, Iterator, Mapping

from .naming import song_tag_key

__all__ = [
    "connect", "Jobs", "Job", "Settings", "OutputTarget", "Target", "LOCAL_TARGET_ID",
    "TARGET_KINDS", "legacy_target_id", "Library", "LibraryItem",
    "Songs", "OwnSong", "song_id_for", "JOB_STATES", "FINAL_STATES",
    "INTERRUPTED_MESSAGE", "ACTIVE_STATES", "STAGE_PUBLISH", "GPU_STATUS_KEY",
    "UsdbAccount", "USDB_KEY", "YANDEX_KEY",
    "Tags", "Tag", "TagError", "TAG_COLORS", "DEFAULT_TAG_COLOR", "TAG_NAME_MAX",
    "TelegramSettings", "TELEGRAM_KEY", "Mirror", "MIRRORS_KEY", "parse_start_at",
]

JOB_STATES = ("queued", "running", "publishing", "done", "failed", "cancelled")
FINAL_STATES = ("done", "failed", "cancelled")
ACTIVE_STATES = tuple(s for s in JOB_STATES if s not in FINAL_STATES)
# Значение jobs.stage, когда задание упало на выкладке: по нему веб предлагает «Выложить повторно».
STAGE_PUBLISH = "publish"
# Ключ settings, куда воркер при старте пишет результат gpucheck.check().
GPU_STATUS_KEY = "gpu_status"
# Ключ settings с учёткой usdb (JSON {user, password}); API отдаёт только has_password.
USDB_KEY = "usdb"
# Ключ settings с OAuth-токеном Яндекс Музыки (JSON {"token": …}); API отдаёт только has_token.
YANDEX_KEY = "yandex_music"
# Ключ settings с уведомлениями Telegram (JSON TelegramSettings); API отдаёт только has_token.
TELEGRAM_KEY = "telegram"
# Ключ settings со списком зеркал хранилищ (JSON [Mirror]).
MIRRORS_KEY = "mirrors"
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

# V2: видео песни (имя файла из #VIDEO или NULL).
_SCHEMA_V2 = """
ALTER TABLE library ADD COLUMN video TEXT
"""

# V3: song_id строки library — поиск песни по id через индекс (заполняется и у старых строк).
_SCHEMA_V3 = """
ALTER TABLE library ADD COLUMN song_id TEXT;
UPDATE library SET song_id = karaoke_song_id(target_id, rel_dir);
CREATE INDEX library_song_id ON library(song_id)
"""

# V4: свои теги пользователя и их связь с песнями по ключу «исполнитель — название»
# (naming.song_tag_key) — общие для копий во всех хранилищах.
_SCHEMA_V4 = """
CREATE TABLE tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE song_tags (
    song_key TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (song_key, tag_id)
);
CREATE INDEX song_tags_tag ON song_tags(tag_id)
"""

# V5: ключ копий песни в library (naming.song_tag_key, с индексом) — копии по индексу,
# а не перебором всей таблицы. Ручной порядок очереди (position, у старых NULL — по id)
# и время запуска задания (start_at, ISO UTC как db.now(), NULL — сразу).
_SCHEMA_V5 = """
ALTER TABLE library ADD COLUMN match_key TEXT;
UPDATE library SET match_key = karaoke_match_key(artist, title);
CREATE INDEX library_match_key ON library(match_key);
ALTER TABLE jobs ADD COLUMN position INTEGER;
ALTER TABLE jobs ADD COLUMN start_at TEXT
"""

_MIGRATIONS = [_SCHEMA_V1, _SCHEMA_V2, _SCHEMA_V3, _SCHEMA_V4, _SCHEMA_V5]


def now(after_s: float = 0.0) -> str:
    """Время UTC в ISO 8601 (секунды); ``after_s`` — через столько секунд от текущего
    (единый формат отметок, в т.ч. ``params.retry_at``)."""
    return (datetime.now(timezone.utc) + timedelta(seconds=after_s)).isoformat(timespec="seconds")


def connect(path) -> sqlite3.Connection:
    """Открыть БД (создать и мигрировать при необходимости). WAL, ожидание блокировок."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.create_function("karaoke_song_id", 2, song_id_for, deterministic=True)
    conn.create_function("karaoke_match_key", 2, _library_key, deterministic=True)
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
    position: int | None = None  # ручной порядок очереди; NULL (старые задания) — по id
    start_at: str | None = None  # не раньше этого времени (ISO UTC); None — сразу

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        d = dict(row)
        d["params"] = json.loads(d["params"] or "{}")
        d["cancel_requested"] = bool(d["cancel_requested"])
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)


_JOB_UPDATABLE = {"state", "stage", "percent", "artist", "title", "song_id", "params",
                  "error", "cancel_requested", "started_at", "finished_at", "position", "start_at"}

# Порядок очереди: ручной (position), у старых заданий без него — по id.
_QUEUE_ORDER = "COALESCE(position, id), id"
JOB_MOVES = ("up", "down", "first")
MOVE_NOT_QUEUED = "Переставлять можно только ожидающие задания"
SCHEDULE_NOT_QUEUED = "Отложить можно только ожидающее задание"
TIME_PASSED = "Время уже прошло"
BAD_TIME = "Неверное время"


def parse_start_at(value: str | None) -> str | None:
    """Время запуска из ISO 8601 → формат :func:`now` (UTC, секунды); ``None``/пусто — ``None``.
    Время без пояса считается UTC. Не разбирается — ``ValueError(BAD_TIME)``."""
    if value is None or not str(value).strip():
        return None
    try:
        at = datetime.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(BAD_TIME) from None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


def _future_start(value: str | None) -> str | None:
    """:func:`parse_start_at` + проверка, что время ещё не наступило."""
    at = parse_start_at(value)
    if at is not None and at <= now():
        raise ValueError(TIME_PASSED)
    return at


def _song_ref(song_ref: Any) -> tuple[str, str, str | None]:
    if song_ref is None:
        return "", "", None
    if isinstance(song_ref, Mapping):
        get = song_ref.get
    else:
        def get(k, default=None):
            return getattr(song_ref, k, default)
    return get("artist", "") or "", get("title", "") or "", get("song_id")


def instrumental_params(*, rel_dir: str, txt_name: str, audio: str, instrumental: str | None,
                        target_id: str) -> dict:
    """params задания ``instrumental`` для песни в папке результата — одни и для веба
    (``POST /api/jobs/instrumental``), и для воркера (минусовка после импорта)."""
    return {"rel_dir": rel_dir, "txt_name": txt_name, "audio": audio, "instrumental": instrumental,
            "replace": bool(instrumental), "target_id": target_id}


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
            job_id = self.conn.execute(
                "INSERT INTO jobs (type, state, artist, title, song_id, params, parent_id, created_at)"
                " VALUES (?, 'queued', ?, ?, ?, ?, ?, ?) RETURNING id",
                (type, artist, title, song_id, json.dumps(params or {}, ensure_ascii=False),
                 parent_id, now()),
            ).fetchone()[0]
            row = self.conn.execute("UPDATE jobs SET position=id WHERE id=? RETURNING *", (job_id,)).fetchone()
        return Job.from_row(row)

    def enqueue_with(self, type: str, song_ref: Any, make_params: Callable[[int], dict],
                     *, parent_id: int | None = None) -> Job:
        """Поставить задание, параметры которого зависят от его id (например, папка входа
        ``jobs/<id>/in``). ``make_params(id)`` вызывается внутри той же транзакции, поэтому
        воркер не увидит задание без параметров; исключение в ней — задания нет."""
        artist, title, song_id = _song_ref(song_ref)
        with _tx(self.conn):
            job_id = self.conn.execute(
                "INSERT INTO jobs (type, state, artist, title, song_id, params, parent_id, created_at)"
                " VALUES (?, 'queued', ?, ?, ?, '{}', ?, ?) RETURNING id",
                (type, artist, title, song_id, parent_id, now()),
            ).fetchone()[0]
            params = make_params(job_id)
            row = self.conn.execute(
                "UPDATE jobs SET params=?, position=id WHERE id=? RETURNING *",
                (json.dumps(params or {}, ensure_ascii=False), job_id),
            ).fetchone()
        return Job.from_row(row)

    def claim_next(self, types: Iterable[str] | None = None) -> Job | None:
        """Атомарно забрать первое задание очереди (queued → running) — по ручному порядку
        ``COALESCE(position, id), id``. ``types`` — только задания этих типов (например, без GPU —
        только выкладка). Задание с ``params.retry_at`` (копирование ждёт хранилище) или
        ``start_at`` (отложено) в будущем пропускается."""
        stamp = now()
        where, args = "state='queued'", []
        if types is not None:
            args = list(types)
            if not args:
                return None
            where += f" AND type IN ({', '.join('?' * len(args))})"
        where += " AND (json_extract(params, '$.retry_at') IS NULL OR json_extract(params, '$.retry_at') <= ?)"
        where += " AND (start_at IS NULL OR start_at <= ?)"
        with _tx(self.conn):
            row = self.conn.execute(
                "UPDATE jobs SET state='running', started_at=?"
                f" WHERE id = (SELECT id FROM jobs WHERE {where} ORDER BY {_QUEUE_ORDER} LIMIT 1)"
                " RETURNING *",
                (stamp, *args, stamp, stamp),
            ).fetchone()
        return Job.from_row(row) if row else None

    def queued(self) -> list[Job]:
        """Ожидающие задания в порядке очереди (как их возьмёт :meth:`claim_next`)."""
        rows = self.conn.execute(f"SELECT * FROM jobs WHERE state='queued' ORDER BY {_QUEUE_ORDER}")
        return [Job.from_row(r) for r in rows]

    def move(self, id: int, where: str) -> list[Job]:
        """Переставить ожидающее задание: ``up`` — на одно раньше, ``down`` — на одно позже,
        ``first`` — в начало очереди. Ожидающие получают те же ключи порядка в новом порядке,
        поэтому новые задания (``position = id``) по-прежнему встают в конец. Не ``queued`` —
        ``ValueError(MOVE_NOT_QUEUED)``. Возвращает ожидающие в новом порядке."""
        if where not in JOB_MOVES:
            raise ValueError(f"Неизвестное направление: «{where}»")
        with _tx(self.conn):
            rows = self.conn.execute(
                f"SELECT id, COALESCE(position, id) AS k FROM jobs WHERE state='queued' ORDER BY {_QUEUE_ORDER}"
            ).fetchall()
            ids = [r["id"] for r in rows]
            if id not in ids:
                raise ValueError(MOVE_NOT_QUEUED)
            i = ids.index(id)
            order = list(ids)
            if where == "first":
                order.insert(0, order.pop(i))
            elif where == "up" and i > 0:
                order[i - 1], order[i] = order[i], order[i - 1]
            elif where == "down" and i < len(order) - 1:
                order[i + 1], order[i] = order[i], order[i + 1]
            keys = [r["k"] for r in rows]
            self.conn.executemany("UPDATE jobs SET position=? WHERE id=?",
                                  [(k, j) for k, j in zip(keys, order)])
        return self.queued()

    def schedule(self, id: int, start_at: str | None) -> Job:
        """Отложить ожидающее задание до ``start_at`` (ISO 8601) или снять время (``None`` —
        «Запустить сейчас»). Не ``queued`` — ``ValueError``; время в прошлом —
        ``ValueError(TIME_PASSED)``."""
        at = _future_start(start_at)
        with _tx(self.conn):
            row = self.conn.execute("UPDATE jobs SET start_at=? WHERE id=? AND state='queued' RETURNING *",
                                    (at, id)).fetchone()
        if row is None:
            raise ValueError(SCHEDULE_NOT_QUEUED)
        return Job.from_row(row)

    def schedule_all(self, start_at: str) -> int:
        """Отложить до ``start_at`` все ожидающие задания без своего времени; сколько отложено."""
        at = _future_start(start_at)
        if at is None:
            raise ValueError(BAD_TIME)
        with _tx(self.conn):
            return self.conn.execute(
                "UPDATE jobs SET start_at=? WHERE state='queued' AND start_at IS NULL", (at,)).rowcount

    def active_copy(self, rel_dir: str, from_target: str, to_target: str) -> Job | None:
        """Незавершённое «Копирование» этой песни в эту цель (правило дубля, история 21)."""
        for job in self.active("copy"):
            p = job.params
            if (p.get("rel_dir"), p.get("from_target"), p.get("to_target")) == (rel_dir, from_target, to_target):
                return job
        return None

    def enqueue_copy(self, song_ref: Any, *, rel_dir: str, txt_name: str, from_target: str, to_target: str,
                     replace: bool = False, wait: bool = False, replace_rel_dir: str | None = None,
                     after_job: int | None = None, parent_id: int | None = None) -> Job:
        """Задание «Копирование» (Решения §9) — единственная сборка его params; такое же
        незавершённое (песня → цель) возвращается вместо нового. ``replace_rel_dir`` — прежняя
        папка заменённой песни (уйдёт в корзину цели), ``after_job`` — ждать конца этого задания."""
        existing = self.active_copy(rel_dir, from_target, to_target)
        if existing is not None:
            return existing
        params: dict[str, Any] = {"rel_dir": rel_dir, "txt_name": txt_name, "from_target": from_target,
                                  "to_target": to_target, "replace": bool(replace), "wait": bool(wait)}
        if replace_rel_dir and replace_rel_dir != rel_dir:
            params["replace_rel_dir"] = replace_rel_dir
        if after_job:
            params["after_job"] = after_job
        return self.enqueue("copy", song_ref, params, parent_id=parent_id)

    def active(self, type: str) -> list[Job]:
        """Незавершённые задания типа ``type`` (queued/running/publishing), старые первыми."""
        marks = ", ".join("?" * len(ACTIVE_STATES))
        rows = self.conn.execute(
            f"SELECT * FROM jobs WHERE type=? AND state IN ({marks}) ORDER BY id", (type, *ACTIVE_STATES))
        return [Job.from_row(r) for r in rows]

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


# --------------------------------------------------------------------------- хранилища

LOCAL_TARGET_ID = "local"
LOCAL_TARGET_NAME = "Локальное хранилище"
TARGET_KINDS = ("local", "smb", "webdav", "gdrive")
TARGETS_KEY = "targets"
DEFAULT_TARGET_KEY = "default_target"
# {старый target_id: новый id} — что переписала миграция (старые задания и корзина).
TARGET_ALIASES_KEY = "target_aliases"
NO_DEFAULT_DELETE = "Сначала выберите другую основную цель"
NO_LOCAL_DELETE = "Локальное хранилище удалить нельзя"
TARGET_NOT_FOUND = "Хранилище не найдено"


@dataclass
class Target:
    """Хранилище песен со стабильным ``id`` (``local`` или ``t_<8 hex>``).

    ``path``: у ``local`` — абсолютный путь в контейнере (``/output/…`` или ``/host/…``),
    у прочих — папка внутри шары/диска. ``secret`` — пароль (SMB/WebDAV) или Client secret
    (Google), ``token`` — OAuth refresh-токен Google; в API не попадают."""
    id: str = ""
    name: str = ""
    kind: str = "local"  # local | smb | webdav | gdrive
    path: str = ""
    host: str = ""
    share: str = ""
    user: str = ""
    url: str = ""
    preset: str = ""  # webdav: "yandex" — Яндекс Диск
    client_id: str = ""
    secret: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)

    @property
    def password(self) -> str | None:
        """Пароль SMB/WebDAV (то же, что ``secret``)."""
        return self.secret

    @property
    def builtin(self) -> bool:
        return self.id == LOCAL_TARGET_ID

    @property
    def label(self) -> str:
        """Адрес хранилища для сообщений и списка."""
        if self.kind == "local":
            return local_label(self.path or LOCAL_OUTPUT_MOUNT)
        if self.kind == "smb":
            return smb_label(self.host, self.share, self.path)
        if self.kind == "webdav":
            return f"{self.url.rstrip('/')}/{self.path.strip('/')}".rstrip("/")
        if self.kind == "gdrive":
            return f"Google Диск: /{self.path.strip('/')}"
        return self.name

    def public(self) -> dict:
        """Для API: без секрета и токена, только ``has_password`` и ``connected``."""
        return {"id": self.id, "name": self.name, "kind": self.kind, "path": self.path,
                "host": self.host, "share": self.share, "user": self.user, "url": self.url,
                "preset": self.preset, "client_id": self.client_id,
                "has_password": bool(self.secret), "connected": bool(self.token),
                "label": self.label, "builtin": self.builtin}

    def _to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def builtin_local_target() -> Target:
    return Target(id=LOCAL_TARGET_ID, name=LOCAL_TARGET_NAME, kind="local", path=LOCAL_OUTPUT_MOUNT)


def legacy_target_id(target: Target) -> str | None:
    """``target_id`` прежнего формата (``smb://…``, ``local:/output…``), которым это хранилище
    было бы помечено до списка хранилищ; у WebDAV/Google Диска его не было — ``None``."""
    if target.kind == "local":
        return local_target_id(target.path or LOCAL_OUTPUT_MOUNT)
    if target.kind == "smb":
        return smb_target_id(target.host, target.share, target.path)
    return None


def new_target_id() -> str:
    return f"t_{secrets.token_hex(4)}"


def default_target_name(target: Target) -> str:
    """Имя хранилища, если пользователь его не задал (форма «Настроек» и миграция)."""
    if target.kind == "local":
        return f"Папка ПК: {target.path}" if target.path else LOCAL_TARGET_NAME
    if target.kind == "smb":
        return f"SMB {target.label}"
    if target.kind == "webdav":
        return "Яндекс Диск" if target.preset == "yandex" else             f"WebDAV {urllib.parse.urlsplit(target.url).hostname or target.url}"
    return "Google Диск"


def _target_from_output(target: OutputTarget) -> Target:
    """Хранилище из прежней «папки результата» (без id)."""
    if target.kind == "local":
        t = Target(kind="local", path=target.local_root)
    else:
        t = Target(kind="smb", host=target.host, share=target.share, path=target.path, user=target.user)
        t.secret = target.password or None
    t.name = default_target_name(t)
    return t


@dataclass(frozen=True)
class UsdbAccount:
    """Учётка usdb.animux.de (только из «Настроек», переменных окружения нет)."""
    user: str = ""
    password: str | None = field(default=None, repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password)

    def public(self) -> dict:
        """Для API: без пароля, только признак его наличия."""
        return {"user": self.user, "has_password": bool(self.password)}


@dataclass(frozen=True)
class TelegramSettings:
    """Уведомления в Telegram: токен бота (в API не отдаётся), чат и события."""
    bot_token: str | None = field(default=None, repr=False)
    chat_id: str = ""
    on_done: bool = True
    on_failed: bool = True
    on_queue_empty: bool = False

    def public(self) -> dict:
        """Для API: без токена, только признак его наличия."""
        return {"has_token": bool(self.bot_token), "chat_id": self.chat_id, "on_done": self.on_done,
                "on_failed": self.on_failed, "on_queue_empty": self.on_queue_empty}


MIRROR_NOT_FOUND = "Зеркало не найдено"
MIRROR_SAME_TARGET = "Откуда и куда — одно и то же хранилище"


@dataclass
class Mirror:
    """Зеркало хранилищ: новое и изменённое из ``from_target`` докопируется в ``to_target``.
    ``last_result`` — ``{added, updated, only_in_target: [{song_id, artist, title, rel_dir}], error?}``."""
    id: str = ""
    from_target: str = ""
    to_target: str = ""
    enabled: bool = True
    last_run_at: str | None = None
    last_result: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def new_mirror_id() -> str:
    return f"m_{secrets.token_hex(4)}"


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

    # ------------------------------------------------------------ хранилища

    def _json(self, key: str, default):
        raw = self._get(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def _put_json(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)))

    def _stored_targets(self) -> list[Target]:
        """Добавленные хранилища (без встроенного); при первом чтении — миграция."""
        raw = self._get(TARGETS_KEY)
        if raw is None:
            self._migrate_targets()
            raw = self._get(TARGETS_KEY) or "[]"
        known = {f.name for f in fields(Target)}
        out = []
        for d in json.loads(raw):
            if isinstance(d, dict) and d.get("id") and d.get("id") != LOCAL_TARGET_ID:
                out.append(Target(**{k: v for k, v in d.items() if k in known}))
        return out

    def _migrate_targets(self) -> None:
        """Прежняя «папка результата» (``settings[output]`` или ``OUTPUT_*``) → список хранилищ;
        строки ``library`` со старым ``target_id`` — на новый id в той же транзакции.
        Корзину переписывает ``Trash.retarget(settings.resolve_target_id)``."""
        with _tx(self.conn):
            if self.conn.execute("SELECT 1 FROM settings WHERE key=?", (TARGETS_KEY,)).fetchone():
                return  # другой процесс успел раньше
            raw = self._get("output")
            if raw is not None:
                known = {f.name for f in fields(OutputTarget)}
                old = OutputTarget(**{k: v for k, v in json.loads(raw).items() if k in known})
            else:
                old = OutputTarget.from_env(self.env)
            candidates = [old]
            env_smb = OutputTarget.from_env(self.env)
            # Сохранена локальная, а в .env есть SMB — её тоже в список (иначе шара «теряется»).
            if old.kind != "smb" and env_smb.kind == "smb" and env_smb.host and env_smb.share \
                    and raw is not None and (self.env if self.env is not None else os.environ).get(
                        "OUTPUT_SMB_HOST"):
                candidates.append(env_smb)
            targets: list[Target] = []
            aliases: dict[str, str] = {}
            default = LOCAL_TARGET_ID
            for i, o in enumerate(candidates):
                if o.kind == "local" and not o.path:
                    target = builtin_local_target()
                else:
                    target = _target_from_output(o)
                    target.id = new_target_id()
                    targets.append(target)
                if i == 0:
                    default = target.id
                aliases[o.target_id] = target.id
            aliases.setdefault(local_target_id(LOCAL_OUTPUT_MOUNT), LOCAL_TARGET_ID)
            self._put_json(TARGETS_KEY, [t._to_dict() for t in targets])
            self._put_json(DEFAULT_TARGET_KEY, default)
            self._put_json(TARGET_ALIASES_KEY, aliases)
            for old_id, new_id in aliases.items():
                if old_id != new_id:
                    # строка с новым id уже есть — она свежее; старая (сирота) удаляется
                    self.conn.execute(
                        "UPDATE OR IGNORE library SET target_id=?, song_id=karaoke_song_id(?, rel_dir)"
                        " WHERE target_id=?", (new_id, new_id, old_id))
                    self.conn.execute("DELETE FROM library WHERE target_id=?", (old_id,))

    def _write_targets(self, targets: list[Target]) -> None:
        with _tx(self.conn):
            self._put_json(TARGETS_KEY, [t._to_dict() for t in targets if not t.builtin])

    def get_targets(self) -> list[Target]:
        """Все хранилища: встроенное «Локальное хранилище» первым, затем добавленные."""
        return [builtin_local_target(), *self._stored_targets()]

    def get_target(self, target_id: str | None) -> Target | None:
        return next((t for t in self.get_targets() if t.id == target_id), None) if target_id else None

    def save_target(self, target: Target) -> Target:
        """Создать (пустой ``id`` → новый ``t_…``) или изменить хранилище; ``id`` не меняется.
        ``secret``/``token`` ``None`` — оставить прежние. Встроенное не правится."""
        if target.id == LOCAL_TARGET_ID:
            raise ValueError("Локальное хранилище не меняется")
        if target.kind not in TARGET_KINDS:
            raise ValueError(f"Неизвестный тип хранилища: «{target.kind}»")
        stored = self._stored_targets()
        old = next((t for t in stored if t.id == target.id), None) if target.id else None
        if target.id and old is None:
            raise ValueError(TARGET_NOT_FOUND)
        values = target._to_dict()
        if not target.id:
            values["id"] = new_target_id()
        for key in ("secret", "token"):
            if values[key] is None and old is not None:
                values[key] = getattr(old, key)
        saved = Target(**values)
        self._write_targets([saved if t.id == saved.id else t for t in stored]
                            + ([] if old is not None else [saved]))
        return saved

    def delete_target(self, target_id: str) -> None:
        """Удалить хранилище из настроек и стереть его индекс песен (песни не трогаются).
        Встроенное и основную цель удалить нельзя — ``ValueError``."""
        if target_id == LOCAL_TARGET_ID:
            raise ValueError(NO_LOCAL_DELETE)
        if target_id == self.get_default_target_id():
            raise ValueError(NO_DEFAULT_DELETE)
        stored = self._stored_targets()
        if not any(t.id == target_id for t in stored):
            raise ValueError(TARGET_NOT_FOUND)
        with _tx(self.conn):
            self._put_json(TARGETS_KEY, [t._to_dict() for t in stored if t.id != target_id])
            self.conn.execute("DELETE FROM library WHERE target_id=?", (target_id,))
            # зеркала удалённого хранилища выключаются (сами не удаляются — их итог виден)
            mirrors = self._stored_mirrors()
            touched = [m for m in mirrors if target_id in (m.from_target, m.to_target) and m.enabled]
            for m in touched:
                m.enabled = False
            if touched:
                self._put_json(MIRRORS_KEY, [m.to_dict() for m in mirrors])

    def get_default_target_id(self) -> str:
        """id основной цели; нет или удалена — ``local``."""
        ids = {t.id for t in self.get_targets()}
        value = self._json(DEFAULT_TARGET_KEY, None)
        return value if isinstance(value, str) and value in ids else LOCAL_TARGET_ID

    def set_default_target_id(self, target_id: str) -> None:
        if self.get_target(target_id) is None:
            raise ValueError(TARGET_NOT_FOUND)
        with _tx(self.conn):
            self._put_json(DEFAULT_TARGET_KEY, target_id)

    def resolve_target_id(self, target_id: str | None) -> str | None:
        """id хранилища по ``target_id`` любого формата (новый ``t_…``/``local`` или прежний
        ``smb://…``/``local:/output…`` из старых заданий и корзины); не нашлось — ``None``."""
        if not target_id:
            return None
        targets = self.get_targets()
        ids = {t.id for t in targets}
        if target_id in ids:
            return target_id
        for t in targets:
            if legacy_target_id(t) == target_id:
                return t.id
        alias = self._json(TARGET_ALIASES_KEY, {}).get(target_id) \
            if isinstance(self._json(TARGET_ALIASES_KEY, {}), dict) else None
        return alias if alias in ids else None

    # ------------------------------------------------------------ прежняя «папка результата»

    def get_output(self) -> OutputTarget:
        """Основная цель в прежнем формате (совместимость ``/api/settings/output``)."""
        t = self.get_target(self.get_default_target_id()) or builtin_local_target()
        if t.kind == "smb":
            return OutputTarget("smb", t.host, t.share, t.path, t.user, t.secret)
        if t.kind == "local":
            sub = t.path[len(LOCAL_OUTPUT_MOUNT):] if (t.path + "/").startswith(LOCAL_OUTPUT_MOUNT + "/") \
                else t.path
            return OutputTarget(kind="local", path=sub.strip("/"), password="")
        return OutputTarget(t.kind, "", "", t.path, t.user, t.secret)

    def set_output(self, target: OutputTarget) -> OutputTarget:
        """Прежний PUT «папки результата»: правит основную цель того же типа или находит/создаёт
        хранилище и делает его основным. ``password=None`` — оставить прежний пароль."""
        if target.kind == "local" and not target.path:
            self.set_default_target_id(LOCAL_TARGET_ID)
            return self.get_output()
        wanted = _target_from_output(target)
        stored = self._stored_targets()
        current = self.get_target(self.get_default_target_id())
        if target.kind == "smb" and current is not None and current.kind == "smb":
            match = current
        else:
            match = next((t for t in stored if t.kind == wanted.kind and legacy_target_id(t)
                          == legacy_target_id(wanted)), None)
        values = wanted._to_dict()
        values["id"] = match.id if match else ""
        if match is not None and target.kind == "smb":
            values["name"] = match.name if match.host == wanted.host and match.share == wanted.share \
                else wanted.name
        values["secret"] = target.password  # None — прежний (save_target)
        saved = self.save_target(Target(**values))
        self.set_default_target_id(saved.id)
        return self.get_output()

    def get_usdb(self) -> UsdbAccount:
        raw = self._get(USDB_KEY)
        if raw is None:
            return UsdbAccount()
        try:
            value = json.loads(raw)
        except ValueError:
            return UsdbAccount()
        return UsdbAccount(str(value.get("user") or ""), value.get("password") or None)

    def set_usdb(self, account: UsdbAccount) -> UsdbAccount:
        """Сохранить учётку как есть (правило «пустой пароль — прежний» — в api_settings)."""
        self._set(USDB_KEY, json.dumps({"user": account.user, "password": account.password or ""},
                                       ensure_ascii=False))
        return account

    def get_yandex(self) -> str | None:
        """OAuth-токен Яндекс Музыки из «Настроек» или ``None``."""
        raw = self._get(YANDEX_KEY)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        ym_key = value.get("token") if isinstance(value, dict) else None
        return str(ym_key).strip() or None if ym_key else None

    def set_yandex(self, token: str | None) -> None:
        """Сохранить токен Яндекс Музыки; ``None``/пусто — удалить."""
        ym_key = (token or "").strip()
        with _tx(self.conn):
            if ym_key:
                self.conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (YANDEX_KEY, json.dumps({"token": ym_key})))
            else:
                self.conn.execute("DELETE FROM settings WHERE key=?", (YANDEX_KEY,))

    def get_gpu_status(self) -> dict | None:
        """Последний результат проверки GPU воркером (``gpucheck.check()``) или ``None``."""
        raw = self._get(GPU_STATUS_KEY)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def set_gpu_status(self, status: Mapping[str, Any]) -> None:
        """Записать результат проверки GPU (воркер — при старте); ``checked_at`` ставится сам."""
        self._set(GPU_STATUS_KEY, json.dumps({**status, "checked_at": status.get("checked_at") or now()},
                                             ensure_ascii=False, default=str))

    # ------------------------------------------------------------ Telegram

    def get_telegram(self) -> TelegramSettings:
        value = self._json(TELEGRAM_KEY, {})
        if not isinstance(value, dict):
            return TelegramSettings()
        defaults = TelegramSettings()
        return TelegramSettings(
            str(value.get("bot_token") or "").strip() or None,
            str(value.get("chat_id") or "").strip(),
            bool(value.get("on_done", defaults.on_done)),
            bool(value.get("on_failed", defaults.on_failed)),
            bool(value.get("on_queue_empty", defaults.on_queue_empty)))

    def set_telegram(self, value: TelegramSettings) -> TelegramSettings:
        """Сохранить уведомления; ``bot_token`` ``None`` — прежний токен, пустая строка — удалить."""
        with _tx(self.conn):
            bot_key = value.bot_token
            if bot_key is None:
                bot_key = self.get_telegram().bot_token
            saved = TelegramSettings((bot_key or "").strip() or None, (value.chat_id or "").strip(),
                                     bool(value.on_done), bool(value.on_failed), bool(value.on_queue_empty))
            self._put_json(TELEGRAM_KEY, {"bot_token": saved.bot_token or "", "chat_id": saved.chat_id,
                                          "on_done": saved.on_done, "on_failed": saved.on_failed,
                                          "on_queue_empty": saved.on_queue_empty})
        return saved

    # ------------------------------------------------------------ зеркала

    def _stored_mirrors(self) -> list[Mirror]:
        known = {f.name for f in fields(Mirror)}
        raw = self._json(MIRRORS_KEY, [])
        return [Mirror(**{k: v for k, v in d.items() if k in known})
                for d in (raw if isinstance(raw, list) else []) if isinstance(d, dict) and d.get("id")]

    def get_mirrors(self) -> list[Mirror]:
        """Зеркала в порядке добавления."""
        return self._stored_mirrors()

    def save_mirror(self, mirror: Mirror) -> Mirror:
        """Создать (пустой ``id`` → новый ``m_…``) или изменить зеркало; итог прошлого прогона
        (``last_run_at``/``last_result`` ``None``) сохраняется. ``ValueError``: неизвестное
        хранилище, откуда = куда, нет такого зеркала."""
        ids = {t.id for t in self.get_targets()}
        if mirror.from_target not in ids or mirror.to_target not in ids:
            raise ValueError(TARGET_NOT_FOUND)
        if mirror.from_target == mirror.to_target:
            raise ValueError(MIRROR_SAME_TARGET)
        with _tx(self.conn):
            stored = self._stored_mirrors()
            old = next((m for m in stored if m.id == mirror.id), None) if mirror.id else None
            if mirror.id and old is None:
                raise ValueError(MIRROR_NOT_FOUND)
            saved = Mirror(id=mirror.id or new_mirror_id(), from_target=mirror.from_target,
                           to_target=mirror.to_target, enabled=bool(mirror.enabled),
                           last_run_at=mirror.last_run_at if mirror.last_run_at is not None
                           else (old.last_run_at if old else None),
                           last_result=mirror.last_result if mirror.last_result is not None
                           else (old.last_result if old else None))
            out = [saved if m.id == saved.id else m for m in stored] + ([] if old else [saved])
            self._put_json(MIRRORS_KEY, [m.to_dict() for m in out])
        return saved

    def delete_mirror(self, mirror_id: str) -> None:
        """Удалить зеркало; нет такого — ``ValueError``."""
        with _tx(self.conn):
            stored = self._stored_mirrors()
            if not any(m.id == mirror_id for m in stored):
                raise ValueError(MIRROR_NOT_FOUND)
            self._put_json(MIRRORS_KEY, [m.to_dict() for m in stored if m.id != mirror_id])

    def set_mirror_result(self, mirror_id: str, result: dict) -> Mirror | None:
        """Итог прогона зеркала (``last_result``) и время (``last_run_at`` = сейчас);
        зеркало уже удалено — ``None``."""
        with _tx(self.conn):
            stored = self._stored_mirrors()
            hit = next((m for m in stored if m.id == mirror_id), None)
            if hit is None:
                return None
            hit.last_result = result
            hit.last_run_at = now()
            self._put_json(MIRRORS_KEY, [m.to_dict() for m in stored])
        return hit


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
    video: str | None = None
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
        d.pop("song_id", None)  # вычисляемое свойство; в таблице — для поиска по индексу
        d.pop("match_key", None)  # ключ копий из artist/title; в таблице — для поиска по индексу
        d["is_duet"] = bool(d["is_duet"])
        return cls(**d)

    def to_dict(self) -> dict:
        return {**asdict(self), "song_id": self.song_id}


_LIB_COLS = [f.name for f in fields(LibraryItem)]


def _library_key(artist: str | None, title: str | None) -> str:
    """Значение ``library.match_key``: :func:`naming.song_tag_key` (``match_key`` строкой)."""
    return song_tag_key(artist or "", title or "")


def _fold(s: str | None) -> str:
    return (s or "").casefold().replace("ё", "е")


class Library:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _insert(self, item: LibraryItem) -> None:
        cols = _LIB_COLS + ["song_id", "match_key"]
        values = [getattr(item, c) for c in cols[:-1]] + [_library_key(item.artist, item.title)]
        values[cols.index("is_duet")] = int(bool(item.is_duet))
        self.conn.execute(
            f"INSERT INTO library ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            f" ON CONFLICT(target_id, rel_dir) DO UPDATE SET "
            + ", ".join(f"{c}=excluded.{c}" for c in cols if c not in ("target_id", "rel_dir")),
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

    def find(self, song_id: str) -> LibraryItem | None:
        """Песня по ``song_id`` в индексе любого хранилища (колонка ``song_id`` с индексом)."""
        row = self.conn.execute("SELECT * FROM library WHERE song_id=? LIMIT 1", (song_id,)).fetchone()
        return LibraryItem.from_row(row) if row else None

    def get(self, target_id: str, rel_dir: str) -> LibraryItem | None:
        row = self.conn.execute("SELECT * FROM library WHERE target_id=? AND rel_dir=?",
                                (target_id, rel_dir)).fetchone()
        return LibraryItem.from_row(row) if row else None

    def copies(self, artist: str, title: str) -> list[LibraryItem]:
        """Песни всех хранилищ с тем же ключом ``naming.match_key(artist, title)`` (только индекс)."""
        return self.by_key(_library_key(artist, title))

    def by_key(self, key: str) -> list[LibraryItem]:
        """Песни всех хранилищ с готовым ключом ``naming.song_tag_key`` (колонка ``match_key`` с индексом)."""
        rows = self.conn.execute("SELECT * FROM library WHERE match_key=?", (key,))
        return [LibraryItem.from_row(r) for r in rows]


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

    def by_rel_dir_folded(self, rel_dir: str) -> OwnSong | None:
        """Своя песня с этим ``rel_dir`` без учёта регистра (в т. ч. кириллицы)."""
        key = rel_dir.casefold()
        for row in self.conn.execute("SELECT * FROM songs"):
            if row["rel_dir"].casefold() == key:
                return OwnSong.from_row(row)
        return None

    def get_many(self, ids) -> dict[str, OwnSong]:
        """Свои песни по id одним запросом: ``{id: OwnSong}`` (неизвестных id нет в ответе)."""
        ids = sorted({i for i in ids if i})
        if not ids:
            return {}
        rows = self.conn.execute(
            f"SELECT * FROM songs WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return {s.id: s for s in map(OwnSong.from_row, rows)}

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

    def rename(self, id: str, *, rel_dir: str, artist: str, title: str) -> OwnSong | None:
        """Новое имя своей песни (задание ``rename``): ``rel_dir``, исполнитель, название; id прежний."""
        with _tx(self.conn):
            row = self.conn.execute(
                "UPDATE songs SET rel_dir=?, artist=?, title=?, updated_at=? WHERE id=? RETURNING *",
                (rel_dir, artist, title, now(), id)).fetchone()
        return OwnSong.from_row(row) if row else None

    def delete(self, id: str) -> None:
        with _tx(self.conn):
            self.conn.execute("DELETE FROM songs WHERE id=?", (id,))


# --------------------------------------------------------------------------- свои теги

TAG_COLORS = ("blue", "violet", "pink", "orange", "yellow", "teal", "gray", "red")
DEFAULT_TAG_COLOR = "blue"
TAG_NAME_MAX = 40
_SQL_CHUNK = 500  # ключей в одном IN (…): с запасом до лимита переменных SQLite


class TagError(ValueError):
    """Неверный ввод тега: русский текст и поле формы ``field`` (``name|color``)."""

    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


TAG_DUPLICATE = "Такой тег уже есть"


@contextmanager
def _duplicate_as_tag_error() -> Iterator[None]:
    """Нарушение ``UNIQUE(name_key)`` (второй создатель успел между проверкой и записью) —
    ``TagError`` у поля ``name``, а не ``sqlite3.IntegrityError`` (500)."""
    try:
        yield
    except sqlite3.IntegrityError:
        raise TagError(TAG_DUPLICATE, "name") from None


def _tag_name(name: str | None) -> str:
    """Название тега: без пробелов по краям, внутренние пробелы схлопнуты."""
    return " ".join((name or "").split())


def tag_name_key(name: str | None) -> str:
    """Ключ дубля названия: пробелы схлопнуты, без регистра, ё→е."""
    return _tag_name(name).casefold().replace("ё", "е")


@dataclass
class Tag:
    id: str
    name: str
    color: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Tag":
        return cls(id=row["id"], name=row["name"], color=row["color"], created_at=row["created_at"])

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color}


class Tags:
    """Свои теги и их связи с песнями (ключ песни — ``naming.song_tag_key``)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _check_name(name: str | None) -> str:
        clean = _tag_name(name)
        if not clean:
            raise TagError("Введите название тега", "name")
        if len(clean) > TAG_NAME_MAX:
            raise TagError(f"Не длиннее {TAG_NAME_MAX} символов", "name")
        return clean

    @staticmethod
    def _check_color(color: str | None) -> str:
        if color not in TAG_COLORS:
            raise TagError("Неизвестный цвет", "color")
        return color

    def _check_unique(self, key: str, except_id: str | None = None) -> None:
        row = self.conn.execute("SELECT id FROM tags WHERE name_key=?", (key,)).fetchone()
        if row is not None and row["id"] != except_id:
            raise TagError(TAG_DUPLICATE, "name")

    def list(self) -> list[Tag]:
        """Все теги по названию без учёта регистра."""
        tags = [Tag.from_row(r) for r in self.conn.execute("SELECT * FROM tags")]
        tags.sort(key=lambda t: (tag_name_key(t.name), t.name, t.id))
        return tags

    def get(self, id: str) -> Tag | None:
        row = self.conn.execute("SELECT * FROM tags WHERE id=?", (id,)).fetchone()
        return Tag.from_row(row) if row else None

    def create(self, name: str, color: str = DEFAULT_TAG_COLOR) -> Tag:
        clean = self._check_name(name)
        color = self._check_color(color)
        key = tag_name_key(clean)
        tag = Tag(id=uuid.uuid4().hex, name=clean, color=color, created_at=now())
        with _duplicate_as_tag_error(), _tx(self.conn):
            self._check_unique(key)
            self.conn.execute("INSERT INTO tags (id, name, name_key, color, created_at) VALUES (?, ?, ?, ?, ?)",
                              (tag.id, tag.name, key, tag.color, tag.created_at))
        return tag

    def update(self, id: str, *, name: str | None = None, color: str | None = None) -> Tag:
        """Переименовать и/или сменить цвет; неизвестный id — ``KeyError``."""
        with _duplicate_as_tag_error(), _tx(self.conn):
            tag = self.get(id)
            if tag is None:
                raise KeyError(id)
            if name is not None:
                tag.name = self._check_name(name)
            if color is not None:
                tag.color = self._check_color(color)
            key = tag_name_key(tag.name)
            self._check_unique(key, except_id=id)
            self.conn.execute("UPDATE tags SET name=?, name_key=?, color=? WHERE id=?",
                              (tag.name, key, tag.color, id))
        return tag

    def delete(self, id: str) -> int:
        """Удалить тег; сколько связей с песнями снято. Неизвестный id — ``KeyError``."""
        with _tx(self.conn):
            if self.conn.execute("DELETE FROM tags WHERE id=?", (id,)).rowcount == 0:
                raise KeyError(id)
            return self.conn.execute("DELETE FROM song_tags WHERE tag_id=?", (id,)).rowcount

    def for_songs(self, keys: Iterable[str]) -> dict[str, list[str]]:
        """id тегов по ключам песен (порядок — по названию тега); песен без тегов в ответе нет."""
        keys = sorted(set(keys))
        rows = []
        for i in range(0, len(keys), _SQL_CHUNK):
            part = keys[i:i + _SQL_CHUNK]
            rows += self.conn.execute(
                "SELECT st.song_key, t.id, t.name FROM song_tags st JOIN tags t ON t.id = st.tag_id"
                f" WHERE st.song_key IN ({','.join('?' * len(part))})", part).fetchall()
        rows.sort(key=lambda r: (tag_name_key(r["name"]), r["name"], r["id"]))
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["song_key"], []).append(r["id"])
        return out

    def set_for_song(self, key: str, tag_ids: list[str]) -> list[str]:
        """Заменить набор тегов песни; неизвестный id — ``KeyError`` (ничего не меняется)."""
        ids = list(dict.fromkeys(tag_ids))
        with _tx(self.conn):
            if ids:
                known = {r["id"] for r in self.conn.execute(
                    f"SELECT id FROM tags WHERE id IN ({','.join('?' * len(ids))})", ids)}
                missing = [i for i in ids if i not in known]
                if missing:
                    raise KeyError(missing[0])
            self.conn.execute("DELETE FROM song_tags WHERE song_key=?", (key,))
            self.conn.executemany("INSERT INTO song_tags (song_key, tag_id) VALUES (?, ?)",
                                  [(key, i) for i in ids])
        return self.for_songs([key]).get(key, [])

    def change_for_songs(self, keys: list[str], add: list[str], remove: list[str]) -> int:
        """Массовые теги: песням с ключами ``keys`` добавить теги ``add`` и снять ``remove``,
        не заменяя остальной набор; тег сразу в обоих списках — добавляется. Одна транзакция;
        неизвестный id — ``KeyError`` (ничего не меняется). Сколько ключей изменилось."""
        keys = list(dict.fromkeys(keys))
        add = list(dict.fromkeys(add))
        remove = [i for i in dict.fromkeys(remove) if i not in add]
        with _tx(self.conn):
            ids = add + remove
            if ids:
                known = {r["id"] for r in self.conn.execute(
                    f"SELECT id FROM tags WHERE id IN ({','.join('?' * len(ids))})", ids)}
                missing = [i for i in ids if i not in known]
                if missing:
                    raise KeyError(missing[0])
            changed = 0
            for key in keys:
                n = 0
                for tag_id in add:
                    n += self.conn.execute("INSERT OR IGNORE INTO song_tags (song_key, tag_id) VALUES (?, ?)",
                                           (key, tag_id)).rowcount
                if remove:
                    n += self.conn.execute(
                        f"DELETE FROM song_tags WHERE song_key=? AND tag_id IN ({','.join('?' * len(remove))})",
                        (key, *remove)).rowcount
                changed += n > 0
        return changed

    def copy_key(self, old: str, new: str) -> int:
        """Теги песни с ключа ``old`` — ещё и на ``new`` (переименование песни): без дублей, повтор
        ничего не меняет; ``old`` остаётся (у ещё не переименованных копий). Сколько связей добавлено."""
        if old == new:
            return 0
        with _tx(self.conn):
            return self.conn.execute(
                "INSERT OR IGNORE INTO song_tags (song_key, tag_id)"
                " SELECT ?, tag_id FROM song_tags WHERE song_key=?", (new, old)).rowcount

    def drop_key(self, key: str) -> int:
        """Снять все теги с ключа песни (последняя копия переименована); сколько связей снято."""
        with _tx(self.conn):
            return self.conn.execute("DELETE FROM song_tags WHERE song_key=?", (key,)).rowcount

    def counts(self) -> dict[str, int]:
        """Сколько песен (ключей) у каждого тега; тегов без песен в ответе нет."""
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT tag_id, COUNT(*) FROM song_tags GROUP BY tag_id")}
