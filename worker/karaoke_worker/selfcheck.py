"""Проверка, что в UltraSinger на месте наши правки из ветки karaoke-local (история 56).

Проверяется:
- флаги --lyrics, --vad_onset, --vad_offset принимает getopt со списком UltraSinger.arg_options()
  (тот же вызов, что в init_settings);
- модуль modules.Speech_Recognition.lyrics_alignment импортируется;
- midi_creator не падает на сегменте нулевой длины и не пишет такую ноту в MIDI;
- swift-f0 принимает SwiftF0(fmin, fmax, confidence_threshold), как его вызывает pitcher.

Импорты UltraSinger выполняются в отдельном процессе с рабочей папкой src/ — так, как его
запускает воркер; процесс самой проверки модули UltraSinger не загружает.
"""

from __future__ import annotations

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


_FLAGS_CODE = """
import getopt, sys
import UltraSinger
long_opts, short_opts = UltraSinger.arg_options()
missing = []
for flag in FLAGS:
    try:
        getopt.getopt(["--" + flag, "1"], short_opts, long_opts)
    except getopt.GetoptError:
        missing.append("--" + flag)
if missing:
    print("MISSING:" + ",".join(missing))
    sys.exit(3)
"""


def check_flags(src: Path) -> CheckResult:
    """Флаги проверяются тем же getopt и тем же списком arg_options(), что и при запуске UltraSinger."""
    name = "флаги --lyrics / --vad_onset / --vad_offset"
    ok, out = _run_in_ultrasinger(src, f"FLAGS = {REQUIRED_FLAGS!r}\n" + _FLAGS_CODE)
    if ok:
        return CheckResult(name, True, "флаги принимаются getopt UltraSinger")
    missing = [ln[len("MISSING:"):] for ln in out.splitlines() if ln.startswith("MISSING:")]
    if missing:
        return CheckResult(name, False, "пропала правка karaoke-local: UltraSinger не принимает флаг(и) "
                                        + missing[-1].replace(",", ", "))
    return CheckResult(name, False, "не удалось получить флаги UltraSinger (arg_options): " + _last_line(out))


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


_SWIFT_F0_CODE = """
import inspect, sys
from swift_f0 import SwiftF0
try:
    inspect.signature(SwiftF0).bind(fmin=46.875, fmax=2093.75, confidence_threshold=0.9)
except TypeError as exc:
    print("SIGNATURE:" + str(inspect.signature(SwiftF0)))
    sys.exit(3)
"""


def check_swift_f0(src: Path) -> CheckResult:
    """pitcher.py вызывает SwiftF0(fmin, fmax, confidence_threshold); проверяется сигнатура, модель не грузится."""
    name = "swift-f0: SwiftF0(fmin, fmax, confidence_threshold)"
    ok, out = _run_in_ultrasinger(src, _SWIFT_F0_CODE)
    if ok:
        return CheckResult(name, True, "сигнатура совместима с pitcher UltraSinger")
    sig = [ln[len("SIGNATURE:"):] for ln in out.splitlines() if ln.startswith("SIGNATURE:")]
    detail = f"у установленного SwiftF0 сигнатура {sig[-1]}" if sig else _last_line(out)
    return CheckResult(name, False, "пропала совместимость swift-f0 с UltraSinger: pitcher вызывает "
                                    "SwiftF0(fmin, fmax, confidence_threshold), а " + detail
                                    + ". Версия swift-f0 должна совпадать с uv.lock UltraSinger.")


def run_checks(us_dir: Path | str | None = None) -> list[CheckResult]:
    src = Path(us_dir or ultrasinger_dir()) / "src"
    return [check_flags(src), check_lyrics_alignment(src), check_midi_zero_length(src),
            check_swift_f0(src)]


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
