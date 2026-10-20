"""Фейковый yt-dlp (YTDLP_CMD) — без сети.

Требует ``-4 -x --audio-format mp3 --no-playlist -o <шаблон> <ссылка>``; пишет ``<шаблон>`` с
расширением mp3 (ID3 + ``YT-AUDIO <ссылка>``), а при ``--write-thumbnail --convert-thumbnails jpg`` —
ещё и миниатюру ``.jpg``. FAKE_YTDLP_MODE:
  fail     — «ERROR: … Video unavailable», код 1;
  hang     — печатает начало загрузки и висит (для отмены);
  nothumb  — звук есть, миниатюры нет;
  forbidden — «ERROR: … HTTP Error 403: Forbidden», код 1;
  network  — «ERROR: … Temporary failure in name resolution», код 1.
FAKE_YTDLP_DEAD — id роликов через запятую: их загрузка падает «Video unavailable … removed».
Поиск: ``-4 -J --flat-playlist -- ytsearchN:<запрос>`` печатает одну строку JSON плейлиста,
entries — из FAKE_YTDLP_SEARCH (JSON-список, по умолчанию пусто).
"""

import json
import os
import sys
import time
from pathlib import Path


def search(argv: list[str]) -> int:
    for flag in ("-4", "--flat-playlist"):
        if flag not in argv:
            print(f"bad args (нет {flag}): {argv}", flush=True)
            return 2
    query = argv[-1]
    if not query.startswith("ytsearch"):
        print(f"bad args (не ytsearch): {argv}", flush=True)
        return 2
    print(f"[youtube:search] Searching: {query}", file=sys.stderr, flush=True)
    entries = json.loads(os.environ.get("FAKE_YTDLP_SEARCH") or "[]")
    print(json.dumps({"_type": "playlist", "id": query, "entries": entries}, ensure_ascii=False), flush=True)
    return 0


def main(argv: list[str]) -> int:
    if "-J" in argv:
        return search(argv)
    for flag in ("-4", "-x", "--no-playlist", "-o"):
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
    dead = [x for x in os.environ.get("FAKE_YTDLP_DEAD", "").split(",") if x]
    if any(x in url for x in dead):
        print(f"ERROR: [youtube] {url[-11:]}: Video unavailable. This video has been removed by the uploader",
              flush=True)
        return 1
    if mode == "fail":
        print(f"ERROR: [youtube] {url[-11:]}: Video unavailable. This video is private", flush=True)
        return 1
    if mode == "forbidden":
        print("ERROR: unable to download video data: HTTP Error 403: Forbidden", flush=True)
        return 1
    if mode == "network":
        print(f"ERROR: [youtube] {url[-11:]}: Unable to download API page: <urlopen error [Errno -3] "
              "Temporary failure in name resolution> (caused by TransportError)", flush=True)
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
