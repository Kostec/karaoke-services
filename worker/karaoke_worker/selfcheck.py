"""Проверка, что в UltraSinger на месте наши правки из ветки karaoke-local (история 56).

Проверяется:
- флаги командной строки --lyrics, --vad_onset, --vad_offset (список getopt в arg_options);
- модуль modules.Speech_Recognition.lyrics_alignment импортируется;
- midi_creator не падает на сегменте нулевой длины и не пишет такую ноту в MIDI.

Импорты UltraSinger выполняются в отдельном процессе с рабочей папкой src/ — так, как его
запускает воркер; процесс самой проверки модули UltraSinger не загружает.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ULTRASINGER_DIR = "/app/UltraSinger"
REQUIRED_FLAGS = ("lyrics", "vad_onset", "vad_offset")


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str


def ultrasinger_dir() -> Path:
    return Path(os.environ.get("ULTRASINGER_DIR", DEFAULT_ULTRASINGER_DIR))


def _getopt_long_options(entry: Path) -> set[str]:
    """Строки из функции arg_options() файла UltraSinger.py — без импорта UltraSinger."""
    tree = ast.parse(entry.read_text(encoding="utf-8"), filename=str(entry))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "arg_options":
            return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    raise ValueError("в UltraSinger.py нет функции arg_options()")


def check_flags(src: Path) -> CheckResult:
    name = "флаги --lyrics / --vad_onset / --vad_offset"
    entry = src / "UltraSinger.py"
    try:
        options = _getopt_long_options(entry)
    except (OSError, SyntaxError, ValueError) as exc:
        return CheckResult(name, False, f"не удалось прочитать {entry}: {exc}")
    missing = [f"--{flag}" for flag in REQUIRED_FLAGS if f"{flag}=" not in options]
    if missing:
        return CheckResult(name, False, "пропала правка karaoke-local: UltraSinger не знает флаг(и) "
                                        + ", ".join(missing))
    return CheckResult(name, True, "флаги на месте")


def _run_in_ultrasinger(src: Path, code: str, timeout: float = 300) -> tuple[bool, str]:
    """Выполнить код отдельным процессом в src/ UltraSinger. Возвращает (успех, вывод)."""
    env = dict(os.environ, PYTHONPATH=str(src), PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run([sys.executable, "-c", code], cwd=src, env=env, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"не уложилось в {timeout:.0f} с"
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out


def _last_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else "без вывода"


_LYRICS_CODE = """
from modules.Speech_Recognition import lyrics_alignment as la
missing = [n for n in ("find_lyrics_file", "read_lyrics") if not callable(getattr(la, n, None))]
if missing:
    raise SystemExit("в lyrics_alignment нет функций: " + ", ".join(missing))
"""


def check_lyrics_alignment(src: Path) -> CheckResult:
    name = "модуль lyrics_alignment"
    ok, out = _run_in_ultrasinger(src, _LYRICS_CODE)
    if not ok:
        return CheckResult(name, False, "пропала правка karaoke-local: модуль "
                                        "modules.Speech_Recognition.lyrics_alignment не импортируется — "
                                        + _last_line(out))
    return CheckResult(name, True, "импортируется")


_MIDI_CODE = """
import os, sys, tempfile
from modules.Midi.MidiSegment import MidiSegment
from modules.Midi import midi_creator
segments = [MidiSegment("C4", 1.0, 2.0, "la"), MidiSegment("D4", 2.0, 2.0, "zero"),
            MidiSegment("E4", 2.5, 3.0, "la")]
instrument = midi_creator.create_midi_instrument(segments)
bad = [n for n in instrument.notes if n.end <= n.start]
if bad:
    raise SystemExit("в MIDI попала нота нулевой длины")
with tempfile.TemporaryDirectory() as tmp:
    midi_creator.create_midi_file(120.0, tmp, segments, "selfcheck")
    if not os.path.isfile(os.path.join(tmp, "selfcheck.mid")):
        raise SystemExit("MIDI-файл не создан")
"""


def check_midi_zero_length(src: Path) -> CheckResult:
    name = "midi_creator: сегмент нулевой длины"
    ok, out = _run_in_ultrasinger(src, _MIDI_CODE)
    if not ok:
        return CheckResult(name, False, "пропала правка karaoke-local: midi_creator не пропускает "
                                        "сегмент нулевой длины — " + _last_line(out))
    return CheckResult(name, True, "сегмент нулевой длины пропущен, MIDI записан")


def run_checks(us_dir: Path | str | None = None) -> list[CheckResult]:
    src = Path(us_dir or ultrasinger_dir()) / "src"
    return [check_flags(src), check_lyrics_alignment(src), check_midi_zero_length(src)]


def main(us_dir: Path | str | None = None) -> int:
    results = run_checks(us_dir)
    for r in results:
        print(f"[{'OK' if r.ok else 'ОШИБКА'}] {r.name}: {r.message}")
    bad = [r for r in results if not r.ok]
    if bad:
        print(f"selfcheck: пропали правки UltraSinger ({len(bad)}). Пересобери worker из ветки karaoke-local.")
        return 1
    print("selfcheck: все правки karaoke-local на месте")
    return 0
