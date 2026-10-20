"""Фейковый ffmpeg (FFMPEG_CMD).

Минусовка: требует libmp3lame ``-q:a 0`` и пишет в выходной файл ID3-заголовок и байты входа.
Шаг «только аудио» (``-map 0:a:0 -c:a copy``): пишет ``AUDIO-ONLY `` + байты входа;
FAKE_FFMPEG_MODE=fail — ошибка разбора входа, код 1.
"""

import os
import sys
from pathlib import Path


def _audio_only(argv: list[str]) -> bool:
    return ("-map" in argv and argv[argv.index("-map") + 1] == "0:a:0"
            and "-c:a" in argv and argv[argv.index("-c:a") + 1] == "copy")


def main(argv: list[str]) -> int:
    if _audio_only(argv):
        src = Path(argv[argv.index("-i") + 1])
        if os.environ.get("FAKE_FFMPEG_MODE") == "fail":
            print(f"{src}: Invalid data found when processing input", flush=True)
            return 1
        Path(argv[-1]).write_bytes(b"AUDIO-ONLY " + src.read_bytes())
        return 0
    if "-q:a" not in argv or argv[argv.index("-q:a") + 1] != "0" or "libmp3lame" not in argv:
        print(f"bad args: {argv}", flush=True)
        return 2
    src = Path(argv[argv.index("-i") + 1])
    Path(argv[-1]).write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00FAKE-MP3 " + src.read_bytes())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
