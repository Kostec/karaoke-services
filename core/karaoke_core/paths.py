"""Раскладка тома ``data`` (Решения §3, история 33) — единственное место, где она задана.

    <DATA_DIR>/karaoke.sqlite
    <DATA_DIR>/logs/<job-id>.log
    <DATA_DIR>/songs/<Исполнитель>/<Исполнитель - Название>/source/      исходники для перегенерации
    <DATA_DIR>/songs/<Исполнитель>/<Исполнитель - Название>/jobs/<id>/in/ вход задания
    <DATA_DIR>/trash/
    <DATA_DIR>/imports/<token>/                                         распаковка импорта (час)

Папка песни — :func:`karaoke_core.naming.song_dir`. Пути в ``params`` заданий —
относительные от ``DATA_DIR`` (:meth:`DataPaths.rel`).
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path, PurePosixPath
from typing import Mapping

from . import naming

__all__ = ["DataPaths", "INPUT_AUDIO", "INPUT_LYRICS", "INPUT_LRC", "INPUT_COVER_STEM", "INPUT_PARAMS"]

# Имена файлов входа задания и исходников (одинаковые в in/ и source/).
INPUT_AUDIO = "input.mp3"
INPUT_LYRICS = "lyrics.txt"
INPUT_LRC = "lyrics.lrc"  # LRC с метками строк рядом с lyrics.txt (UTF-8, его читает --lyrics_timing)
INPUT_COVER_STEM = "cover"  # cover.<jpg|png|webp>
INPUT_PARAMS = "params.json"

_IMPORT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class DataPaths:
    def __init__(self, root: str | Path | None = None, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        self.root = Path(root if root is not None else (env.get("DATA_DIR") or "/data"))

    @property
    def db(self) -> Path:
        return self.root / "karaoke.sqlite"

    @property
    def trash(self) -> Path:
        return self.root / "trash"

    @property
    def imports_root(self) -> Path:
        """Временные распаковки импорта (сборники, файлы, usdb) — ``imports/<token>/``."""
        return self.root / "imports"

    def import_dir(self, token: str) -> Path:
        if not _IMPORT_ID_RE.fullmatch(token or ""):
            raise ValueError(f"Недопустимый токен импорта: {token!r}")
        return self.imports_root / token

    def log(self, job_id: int) -> Path:
        return self.root / "logs" / f"{job_id}.log"

    # Папка песни: по исполнителю и названию (через naming) или по готовому rel_dir.
    def song(self, artist: str, title: str) -> Path:
        return self.song_at(naming.song_dir(artist, title))

    def song_at(self, rel_dir: str) -> Path:
        parts = PurePosixPath(rel_dir).parts
        if not parts or any(p in ("..", ".", "/") for p in parts):
            raise ValueError(f"Недопустимая папка песни: {rel_dir!r}")
        return self.root.joinpath("songs", *parts)

    def source(self, rel_dir: str) -> Path:
        return self.song_at(rel_dir) / "source"

    def job(self, rel_dir: str, job_id: int) -> Path:
        return self.song_at(rel_dir) / "jobs" / str(job_id)

    def job_in(self, rel_dir: str, job_id: int) -> Path:
        return self.job(rel_dir, job_id) / "in"

    def staging(self, rel_dir: str) -> Path:
        """Временная папка для входа, пока id задания ещё не известен (потом — rename в in/)."""
        return self.song_at(rel_dir) / "jobs" / f".new-{secrets.token_hex(6)}"

    def rel(self, path: str | Path) -> str:
        """Путь от DATA_DIR в POSIX-виде — так он хранится в params заданий."""
        return Path(path).relative_to(self.root).as_posix()

    def abs(self, rel: str) -> Path:
        return self.root.joinpath(*PurePosixPath(rel).parts)
