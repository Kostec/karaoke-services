"""Фейковый yt-dlp (YTDLP_CMD) — без сети.

Требует ``-x --audio-format mp3 --no-playlist -o <шаблон> <ссылка>``; пишет ``<шаблон>`` с
расширением mp3 (ID3 + ``YT-AUDIO <ссылка>``), а при ``--write-thumbnail --convert-thumbnails jpg`` —
ещё и миниатюру ``.jpg``. FAKE_YTDLP_MODE:
  fail     — «ERROR: … Video unavailable», код 1;
  hang     — печатает начало загрузки и висит (для отмены);
  nothumb  — звук есть, миниатюры нет.
"""

import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    for flag in ("-x", "--no-playlist", "-o"):
        if flag not in argv:
            print(f"bad args (нет {flag}): {argv}", flush=True)
            return 2
    if "--audio-format" not in argv or argv[argv.index("--audio-format") + 1] != "mp3":
        print(f"bad args (нет --audio-format mp3): {argv}", flush=True)
        return 2
    template = argv[argv.index("-o") + 1]
    url = argv[-1]
    mode = os.environ.get("FAKE_YTDLP_MODE", "")
    print(f"[youtube] Extracting URL: {url}", flush=True)
    if mode == "fail":
        print(f"ERROR: [youtube] {url[-11:]}: Video unavailable. This video is private", flush=True)
        return 1
    print("[download]   0.0% of    3.10MiB at  1.00MiB/s ETA 00:03", flush=True)
    if mode == "hang":
        time.sleep(120)
        return 0
    print("[download]  50.0% of    3.10MiB at  1.00MiB/s ETA 00:01", flush=True)
    print("[download] 100% of    3.10MiB in 00:00:02", flush=True)

    def out(ext: str) -> Path:
        return Path(template.replace("%(ext)s", ext))

    out("mp3").write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00YT-AUDIO " + url.encode())
    print(f"[ExtractAudio] Destination: {out('mp3')}", flush=True)
    if "--write-thumbnail" in argv and mode != "nothumb":
        conv = argv.index("--convert-thumbnails") + 1 if "--convert-thumbnails" in argv else None
        if conv is None or argv[conv] != "jpg":
            print(f"bad args (нет --convert-thumbnails jpg): {argv}", flush=True)
            return 2
        out("jpg").write_bytes(b"\xff\xd8\xff\xe0YT-THUMB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
