"""Фейковый ffmpeg (FFMPEG_CMD): требует libmp3lame ``-q:a 0`` и пишет в выходной файл
ID3-заголовок и байты входа."""

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if "-q:a" not in argv or argv[argv.index("-q:a") + 1] != "0" or "libmp3lame" not in argv:
        print(f"bad args: {argv}", flush=True)
        return 2
    src = Path(argv[argv.index("-i") + 1])
    Path(argv[-1]).write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00FAKE-MP3 " + src.read_bytes())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
