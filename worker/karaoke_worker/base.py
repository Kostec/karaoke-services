"""Общее для обработчиков заданий: контекст, ошибки, запуск внешних процессов.

Внешние команды подменяются переменными окружения (шов 3):
  ULTRASINGER_CMD  команда UltraSinger (по умолчанию ``python $ULTRASINGER_DIR/src/UltraSinger.py``)
  DEMUCS_CMD       команда demucs (по умолчанию ``python -m demucs.separate``)
  FFMPEG_CMD       ffmpeg (по умолчанию ``ffmpeg``)
  YTDLP_CMD        yt-dlp для импорта и ссылок (по умолчанию ``python -m yt_dlp``)
  MUSICLINK_CMD    загрузка с Яндекс Музыки (по умолчанию ``python -m karaoke_core.musiclink``)
"""

from __future__ import annotations

import os
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Callable, Mapping

from karaoke_core.db import Jobs, Library, Settings, Songs, Tags, Target, connect
from karaoke_core.paths import DataPaths
from karaoke_core.http import Http
from karaoke_core.storage import Storage, make_storage
from karaoke_core.storage.registry import StorageRegistry
from karaoke_core.trash import Trash

from .progress import LineSplitter, ProgressTracker, clean_line

__all__ = ["JobContext", "JobFailed", "JobCancelled", "run_command", "explain_failure", "remove_tree"]

CANCEL_CHECK_S = 1.0  # флаг отмены проверяется раз в секунду (Решения §2)
TERM_GRACE_S = 10.0  # SIGTERM → через 10 с SIGKILL (история 20)
# UltraSinger после необработанного исключения может не завершиться (живые потоки torch/whisperx):
# после трассировки с кадром «in <module>» столько секунд полной тишины (таймер сбрасывается
# каждой новой строкой) — процесс считается зависшим и останавливается.
FATAL_GRACE_S = 30.0

OOM_MESSAGE = "Не хватило видеопамяти — попробуйте batch size 2 или модель поменьше"
FLOAT16_MESSAGE = ("Видеокарта не поддерживает float16 (GTX 1080, Pascal) — выберите тип вычислений "
                   "int8 или float32")
NETWORK_MESSAGE = ("Нет сети: не удалось скачать модель или обратиться к MusicBrainz — "
                   "проверьте интернет и перезапустите задание")
_NETWORK_MARKERS = ("Temporary failure in name resolution", "Name or service not known",
                    "Failed to establish a new connection", "Max retries exceeded", "Network is unreachable",
                    "ConnectionError", "ConnectTimeout", "LocalEntryNotFoundError",
                    "We couldn't connect to", "Connection refused", "getaddrinfo failed")


class JobFailed(Exception):
    """Задание упало; ``user_message`` — понятная причина по-русски (поле ``error``)."""

    def __init__(self, reason: str, user_message: str):
        super().__init__(user_message)
        self.reason = reason
        self.user_message = user_message


class JobCancelled(Exception):
    """Пользователь отменил задание."""


def explain_failure(tail: list[str], returncode: int | None, what: str = "UltraSinger") -> tuple[str, str]:
    """Причина и сообщение по последним строкам лога и коду выхода (история 24)."""
    text = "\n".join(tail)
    if "CUDA out of memory" in text or "OutOfMemoryError" in text:
        return "oom", OOM_MESSAGE
    if "float16" in text and ("ValueError" in text or "compute type" in text):
        return "float16", FLOAT16_MESSAGE
    if any(m in text for m in _NETWORK_MARKERS):
        return "network", NETWORK_MESSAGE
    return "exit", f"{what} завершился с ошибкой (код выхода {returncode})"


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    parent = path.parent
    if parent.name == "jobs":
        try:
            parent.rmdir()  # пустая jobs/ не нужна
        except OSError:
            pass


class JobContext:
    """Всё, что нужно обработчику: БД, раскладка тома, папка результата, корзина, окружение."""

    def __init__(self, paths: DataPaths | None = None, *,
                 storage_factory: Callable[[Target], Storage] | None = None,
                 trash: Trash | None = None, env: Mapping[str, str] | None = None):
        self.env = os.environ if env is None else env
        self.paths = paths or DataPaths(env=self.env)
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.conn = connect(self.paths.db)
        self.jobs = Jobs(self.conn)
        self.settings = Settings(self.conn, self.env)
        self.library = Library(self.conn)
        self.songs = Songs(self.conn)
        self.tags = Tags(self.conn)
        self.trash = trash or Trash(self.paths.trash)
        self.http = Http()
        self.storage_factory = storage_factory or (lambda t: make_storage(t, http=self.http))
        self._last_cancel_check = 0.0
        # выбор и кэш хранилищ; фабрика читается при каждом открытии (тесты её подменяют)
        self._registry = StorageRegistry(lambda: self.settings, lambda t: self.storage_factory(t))
        self.fatal_grace = FATAL_GRACE_S

    # ------------------------------------------------------------ папка результата

    def targets(self) -> list[Target]:
        return self._registry.targets()

    def default_target(self) -> Target:
        return self._registry.default_target()

    def target(self) -> Target:
        """Основная цель (куда выкладываются новые песни)."""
        return self.default_target()

    def target_of(self, target_id: str | None) -> Target:
        """Хранилище по id любого формата (в т.ч. прежний ``smb://…`` старых заданий);
        ``None`` — основная цель; удалено из настроек — ``StorageError``."""
        return self._registry.target_of(target_id)

    def storage(self, target_id: str | None = None) -> Storage:
        """Открытое хранилище по id (``None`` — основная цель); кэш, пока конфиг тот же."""
        return self._registry.storage(target_id)

    def local_storage(self) -> Storage:
        return self._registry.local_storage()

    def migrate_targets(self) -> None:
        """Список хранилищ (миграция со старой «папки результата») и корзина на новые id."""
        self._registry.migrate(self.trash)

    def reset_storage(self, target_id: str | None = None) -> None:
        """Закрыть хранилища — все или одно (после ошибки связи или при остановке)."""
        self._registry.reset(target_id)

    # ------------------------------------------------------------ команды

    def _cmd(self, key: str, default: list[str]) -> list[str]:
        raw = (self.env.get(key) or "").strip()
        return shlex.split(raw) if raw else default

    def ultrasinger_cmd(self) -> list[str]:
        us_dir = self.env.get("ULTRASINGER_DIR") or "/app/UltraSinger"
        return self._cmd("ULTRASINGER_CMD", [sys.executable, str(Path(us_dir) / "src" / "UltraSinger.py")])

    def ultrasinger_cwd(self) -> str | None:
        if (self.env.get("ULTRASINGER_CMD") or "").strip():
            return None
        src = Path(self.env.get("ULTRASINGER_DIR") or "/app/UltraSinger") / "src"
        return str(src) if src.is_dir() else None

    def demucs_cmd(self) -> list[str]:
        return self._cmd("DEMUCS_CMD", [sys.executable, "-m", "demucs.separate"])

    def ffmpeg_cmd(self) -> list[str]:
        return self._cmd("FFMPEG_CMD", ["ffmpeg"])

    def ytdlp_cmd(self) -> list[str]:
        return self._cmd("YTDLP_CMD", [sys.executable, "-m", "yt_dlp"])

    def musiclink_cmd(self) -> list[str]:
        return self._cmd("MUSICLINK_CMD", [sys.executable, "-m", "karaoke_core.musiclink"])

    # ------------------------------------------------------------ лог и прогресс

    def log(self, job_id: int, text: str) -> None:
        path = self.paths.log(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for line in text.splitlines() or [""]:
                f.write(line + "\n")

    def progress(self, job_id: int, value: tuple[str, float] | None) -> None:
        if value is not None:
            stage, percent = value
            self.jobs.update(job_id, stage=stage, percent=round(percent, 1))

    def check_cancel(self, job_id: int, *, force: bool = False) -> None:
        """Бросает JobCancelled, если web поставил флаг отмены (не чаще раза в секунду)."""
        now = time.monotonic()
        if not force and now - self._last_cancel_check < CANCEL_CHECK_S:
            return
        self._last_cancel_check = now
        job = self.jobs.get(job_id)
        if job is not None and (job.cancel_requested or job.state == "cancelled"):
            raise JobCancelled()

    # ------------------------------------------------------------ процессы

    def run_command(self, job_id: int, cmd: list[str], *, tracker: ProgressTracker | None = None,
                    cwd: str | Path | None = None, what: str = "UltraSinger",
                    extra_env: Mapping[str, str] | None = None,
                    json_out: list[str] | None = None) -> list[str]:
        """Запустить процесс, вести лог и прогресс; код ≠ 0 → JobFailed. Возвращает хвост лога.
        ``extra_env`` дополняет окружение процесса и в лог не пишется (секреты — только так).
        ``json_out``: строки вывода, начинающиеся с ``{``, собираются туда, а не в лог (``yt-dlp -J``)."""
        self.log(job_id, "$ " + " ".join(shlex.quote(str(c)) for c in cmd))
        tail: deque[str] = deque(maxlen=40)
        hidden_values = [v for v in (extra_env or {}).values() if v]

        def on_line(text: str, final: bool) -> None:
            if tracker is not None:
                self.progress(job_id, tracker.feed(text))
            if final:
                line = clean_line(text).strip()
                if json_out is not None and line.startswith("{"):
                    json_out.append(line)
                    return
                for value in hidden_values:  # процесс мог напечатать секрет — в лог он не попадёт
                    line = line.replace(value, "***")
                if line:
                    tail.append(line)
                    self.log(job_id, line)

        env = {**os.environ, **extra_env} if extra_env else None
        rc = run_command(cmd, on_line=on_line, should_cancel=lambda: self.check_cancel(job_id), cwd=cwd,
                         env=env, fatal_grace=self.fatal_grace)
        if rc != 0:
            reason, message = explain_failure(list(tail), rc, what)
            last = "\n".join(list(tail)[-5:])
            raise JobFailed(reason, f"{message}\n\nПоследние строки лога:\n{last}" if last else message)
        return list(tail)


def _kill_group(proc: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def run_command(cmd: list[str], *, on_line: Callable[[str, bool], None],
                should_cancel: Callable[[], None] | None = None, cwd: str | Path | None = None,
                env: Mapping[str, str] | None = None, poll: float = 0.25,
                term_grace: float = TERM_GRACE_S, fatal_grace: float | None = FATAL_GRACE_S) -> int:
    """Процесс в отдельной группе (stdout+stderr вместе). ``should_cancel`` бросает
    исключение для отмены: группе SIGTERM, через ``term_grace`` с — SIGKILL, исключение
    пробрасывается дальше. Возвращает код выхода."""
    proc = subprocess.Popen([str(c) for c in cmd], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=cwd, env=dict(env) if env is not None else None,
                            start_new_session=True)
    fd = proc.stdout.fileno()
    splitter = LineSplitter()
    finished = False
    in_traceback = False
    fatal_seen = False
    last_output = time.monotonic()

    def emit(text: str, final: bool) -> None:
        nonlocal in_traceback, fatal_seen, last_output
        last_output = time.monotonic()
        if final:
            line = clean_line(text).strip()
            if line == "Traceback (most recent call last):":
                in_traceback = True
            elif in_traceback:
                in_traceback = False
                if line.startswith("File ") and line.endswith("in <module>"):
                    fatal_seen = True
        on_line(text, final)

    try:
        while True:
            if should_cancel is not None:
                should_cancel()
            ready, _, _ = select.select([fd], [], [], poll)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                for text, final in splitter.feed(chunk.decode("utf-8", errors="replace")):
                    emit(text, final)
            elif proc.poll() is not None:
                break  # процесс вышел, а трубу держит потомок — не ждём его
            if (fatal_grace is not None and fatal_seen and proc.poll() is None
                    and time.monotonic() - last_output > fatal_grace):
                on_line("Процесс не завершился после необработанной ошибки — остановлен воркером", True)
                _kill_group(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=term_grace)
                except subprocess.TimeoutExpired:
                    _kill_group(proc, signal.SIGKILL)
                    proc.wait()
                finished = True
                return proc.returncode or 1
        for text, final in splitter.flush():
            emit(text, final)
        rc = proc.wait()
        finished = True
        return rc
    except BaseException:
        _kill_group(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=term_grace)
        except subprocess.TimeoutExpired:
            pass
        raise
    finally:
        _kill_group(proc, signal.SIGKILL)  # потомки, пережившие главный процесс
        if not finished:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        proc.stdout.close()
