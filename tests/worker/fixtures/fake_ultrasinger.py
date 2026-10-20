"""Фейковый UltraSinger для шва 3 (ULTRASINGER_CMD).

Печатает маркеры этапов с ANSI-цветами (как настоящий), tqdm-бары через ``\\r`` в stderr
и создаёт в ``-o`` одну подпапку песни из фикстуры tests/core/fixtures/ultrasinger_out.

Режим — переменная FAKE_US_MODE:
  ok        (по умолчанию) нормальный прогон
  slow      печатает «Transcribing», запускает дочерний ``sleep`` и ждёт (для отмены);
            pid дочернего процесса пишет в FAKE_US_CHILD_PID
  oom       «CUDA out of memory», код 1
  float16   ValueError про float16, код 1
  noresult  выход 0 без выходной папки (некорректная модель)
  crash_hang  необработанное исключение (трассировка), но процесс не завершается
  child_traceback  трассировка упавшего дочернего процесса, затем работа продолжается
FAKE_US_TRACE — файл, куда дописываются «start <time>» / «end <time>» (проверка очереди).
FAKE_US_ARGS — файл, куда пишутся аргументы командной строки (JSON).
FAKE_US_INPUT — файл, куда копируется вход ``-i`` (что именно получил UltraSinger).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[2] / "core" / "fixtures" / "ultrasinger_out"
HEAD = "\033[92m[UltraSinger]\033[0m"


def say(text: str) -> None:
    print(f"{HEAD} {text}", flush=True)


def bar(desc: str, steps: int = 10) -> None:
    for i in range(steps + 1):
        pct = i * 100 // steps
        sys.stderr.write(f"\r{desc}: {pct:3d}%|{'#' * i}{' ' * (steps - i)}| {i}/{steps}")
        sys.stderr.flush()
        time.sleep(0.01)
    sys.stderr.write("\n")
    sys.stderr.flush()


def trace(word: str) -> None:
    path = os.environ.get("FAKE_US_TRACE")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{word} {time.time():.6f}\n")


def main(argv: list[str]) -> int:
    args = dict(zip(argv[::1], argv[1::1]))
    if os.environ.get("FAKE_US_ARGS"):
        Path(os.environ["FAKE_US_ARGS"]).write_text(json.dumps(argv, ensure_ascii=False), "utf-8")
    if os.environ.get("FAKE_US_INPUT"):
        shutil.copyfile(args["-i"], os.environ["FAKE_US_INPUT"])
    if "--interactive" in argv:
        print("interactive mode is not allowed in tests", flush=True)
        return 2
    mode = os.environ.get("FAKE_US_MODE", "ok")
    trace("start")
    say("Checking GPU support.")
    say("Separating vocals from audio with \033[94mdemucs\033[0m with model htdemucs")
    bar("separate")
    say("Reduce noise from vocal audio with \033[94mffmpeg\033[0m.")
    say("Loading whisper with model \033[94mlarge-v2\033[0m and \033[91mcuda\033[0m as worker")
    if mode == "oom":
        print("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 MiB", flush=True)
        return 1
    if mode == "float16":
        print("ValueError: Requested float16 compute type, but the target device or backend "
              "do not support efficient float16 computation.", flush=True)
        return 1
    say("Transcribing \033[94mvocals.wav\033[0m")
    if mode == "slow":
        child = subprocess.Popen(["sleep", "300"])
        Path(os.environ["FAKE_US_CHILD_PID"]).write_text(str(child.pid), "utf-8")
        time.sleep(300)
        return 0
    bar("transcribe")
    say("Using lyrics from lyrics.txt")
    say("Hyphenate using language code: \033[94mru\033[0m")
    say("Pitching with \033[94mSwiftF0\033[0m and \033[91mcuda\033[0m as worker")
    bar("pitch")
    if mode == "crash_hang":
        print("Traceback (most recent call last):\n"
              '  File "/app/UltraSinger/src/UltraSinger.py", line 1, in <module>\n'
              "    main()\n"
              "TypeError: SwiftF0.__init__() got an unexpected keyword argument 'fmin'", flush=True)
        time.sleep(300)
        return 0
    if mode == "child_traceback":
        print("Traceback (most recent call last):", flush=True)
        print('  File "/usr/lib/python3/helper.py", line 3, in <module>', flush=True)
        print("RuntimeError: helper failed", flush=True)
        for i in range(8):
            print(f"still working {i}", flush=True)
            time.sleep(0.2)
    if mode == "noresult":
        trace("end")
        return 0
    out = Path(args["-o"])
    src = next(p for p in FIXTURE.iterdir() if p.is_dir())
    dest = out / Path(args["-i"]).stem
    shutil.copytree(src, dest)
    if "--keep_cache" in argv:
        (dest / "cache" / "lyrics_debug.json").write_text('{"debug": true}', "utf-8")
    say(f"Creating UltraStar file {dest / (dest.name + '.txt')}")
    say("Converting audio to mp3")
    say("Creating midi file")
    trace("end")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
