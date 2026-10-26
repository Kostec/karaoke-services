"""Лог UltraSinger → этап и процент (Решения §5) и очистка строк лога (история 19)."""

from __future__ import annotations

import re

from karaoke_core.db import STAGE_PUBLISH

__all__ = ["STAGES", "STAGE_PREPARE", "STAGE_POSTPROCESS", "PUBLISH", "STAGE_DOWNLOAD",
           "STAGE_VIDEO_DOWNLOAD", "STAGE_COPY_DOWNLOAD", "STAGE_COPY", "STAGE_RENAME", "IMPORT_PREPARE", "ProgressTracker", "DownloadTracker", "LineSplitter", "clean_line"]

# Маркер (подстрока строки без ANSI) → этап по-русски и минимальный процент. Порядок — как в §5.
STAGES: list[tuple[tuple[str, ...], str, int]] = [
    (("Checking GPU support",), "Подготовка", 2),
    (("Separating vocals from audio with demucs",), "Отделение вокала", 5),
    (("Reduce noise from vocal audio",), "Очистка вокала", 25),
    (("Loading whisper with model",), "Загрузка модели", 30),
    (("Transcribing",), "Распознавание", 35),
    (("Using lyrics from", "anchored"), "Выравнивание текста", 50),
    (("Hyphenate using language code",), "Расстановка слогов", 60),
    (("Pitching with SwiftF0",), "Определение высоты нот", 65),
    (("Creating UltraStar file",), "Запись песни", 80),
    (("Converting audio to mp3",), "Минусовка в mp3", 85),
    (("Creating midi file",), "MIDI", 90),
]
STAGE_PREPARE = ("Подготовка", 0)
STAGE_POSTPROCESS = ("Постобработка", 95)
# Выкладка: в stage пишется db.STAGE_PUBLISH (UI сам показывает «Выкладка»).
PUBLISH = (STAGE_PUBLISH, 97)
# Импорт (Решения §6): загрузка звука с YouTube 5→60 %, подготовка папки — 70 %.
STAGE_DOWNLOAD = ("Загрузка звука", 5)
IMPORT_PREPARE = ("Подготовка", 70)
# Видео (истории 14–15): своя шкала загрузки 5→90 %.
STAGE_VIDEO_DOWNLOAD = ("Загрузка видео", 5)
# Задание «Копирование»: скачивание из хранилища-источника и выкладка в цель.
STAGE_COPY_DOWNLOAD = ("Скачивание из хранилища", 10)
STAGE_COPY = ("Копирование", 60)
# Задание «Переименование»: скачанная папка песни выкладывается под новым именем.
STAGE_RENAME = ("Переименование", 60)

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_TQDM_RE = re.compile(r"(\d{1,3})%\|")


def clean_line(raw: str) -> str:
    """Строка для лога: без ANSI-кодов, от tqdm-перерисовок (``\\r``) остаётся последнее состояние."""
    text = _ANSI_RE.sub("", raw)
    if "\r" in text:
        parts = [p for p in text.split("\r") if p.strip()]
        text = parts[-1] if parts else ""
    return text.rstrip()


class ProgressTracker:
    """Состояние прогресса одного прогона. Процент никогда не уменьшается; внутри этапа
    уточняется по tqdm (``NN%|``), но не доходит до процента следующего этапа."""

    def __init__(self, stages: list[tuple[tuple[str, ...], str, int]] | None = None,
                 ceiling: int = STAGE_POSTPROCESS[1]):
        self.stages = STAGES if stages is None else stages
        self.ceiling = ceiling
        self.stage: str | None = None
        self.percent: float = 0.0
        self._index = -1
        self._seen: set[int] = set()

    def _next_percent(self) -> int:
        for _markers, _stage, pct in self.stages[self._index + 1:]:
            if pct > self.stages[self._index][2]:
                return pct
        return self.ceiling

    def set(self, stage: str, percent: float) -> tuple[str, float] | None:
        """Этап вне таблицы маркеров (постобработка, выкладка)."""
        if percent < self.percent or (stage == self.stage and percent == self.percent):
            return None
        self.stage, self.percent = stage, float(percent)
        return self.stage, self.percent

    def feed(self, line: str) -> tuple[str, float] | None:
        """Строка лога → новый (этап, процент) или ``None``, если ничего не изменилось."""
        text = clean_line(line)
        if not text:
            return None
        for i, (markers, stage, pct) in enumerate(self.stages):
            if any(m in text for m in markers):
                if i in self._seen:
                    return None  # повтор маркера — этап уже был
                self._seen.add(i)
                if i < self._index:
                    # UltraSinger печатает этапы не строго по таблице (например, «Using lyrics»
                    # раньше «Loading whisper»): название этапа меняется, процент — нет.
                    self.stage = stage
                    return self.stage, self.percent
                self._index = i
                return self.set(stage, max(pct, self.percent))
        m = _TQDM_RE.search(text)
        if m and self._index >= 0:
            start, end = self.stages[self._index][2], self._next_percent()
            frac = min(int(m.group(1)), 100) / 100
            value = round(min(start + (end - start) * frac, end - 0.5), 1)
            if value > self.percent:
                return self.set(self.stage or self.stages[self._index][1], value)
        return None


_YTDLP_RE = re.compile(r"^\[download\]\s+(\d{1,3}(?:\.\d+)?)%")


class DownloadTracker:
    """Прогресс yt-dlp: строки ``[download]  NN.N% of …`` → процент внутри этапа ``stage``
    (по умолчанию «Загрузка звука»)."""

    def __init__(self, start: float = STAGE_DOWNLOAD[1], end: float = 60, stage: str = STAGE_DOWNLOAD[0]):
        self.start, self.end, self.stage = start, end, stage
        self.percent = float(start)

    def feed(self, line: str) -> tuple[str, float] | None:
        m = _YTDLP_RE.match(clean_line(line).strip())
        if not m:
            return None
        value = round(self.start + (self.end - self.start) * min(float(m.group(1)), 100) / 100, 1)
        if value <= self.percent:
            return None
        self.percent = value
        return self.stage, value


class LineSplitter:
    """Разбор потока вывода процесса на строки.

    ``feed(chunk)`` возвращает список ``(text, final)``: ``final=True`` — законченная строка
    (для лога), ``False`` — промежуточная перерисовка tqdm через ``\\r`` (только для прогресса).
    Строка, перерисованная несколько раз, попадает в лог один раз — в последнем состоянии.
    """

    def __init__(self):
        self._buf = ""
        self._pending = ""

    def feed(self, chunk: str) -> list[tuple[str, bool]]:
        self._buf += chunk
        out: list[tuple[str, bool]] = []
        while True:
            idx = min((i for i in (self._buf.find("\n"), self._buf.find("\r")) if i >= 0), default=-1)
            if idx < 0:
                break
            seg, sep, self._buf = self._buf[:idx], self._buf[idx], self._buf[idx + 1:]
            if sep == "\r":
                if seg.strip():
                    self._pending = seg
                    out.append((seg, False))
                continue
            line = seg if seg.strip() else self._pending
            self._pending = ""
            out.append((line, True))
        return out

    def flush(self) -> list[tuple[str, bool]]:
        line = self._buf if self._buf.strip() else self._pending
        self._buf = self._pending = ""
        return [(line, True)] if line.strip() else []
