"""Фейковый ``python -m karaoke_core.musiclink`` (MUSICLINK_CMD) — без сети.

Требует ``download <url> <dest.mp3>``; пишет ``dest`` (ID3 + ``YM-AUDIO <ссылка>``).
FAKE_MUSICLINK_TRACE — файл, куда пишется JSON ``{"argv", "has_key", "key"}`` (ключ из окружения
YANDEX_MUSIC_TOKEN). FAKE_MUSICLINK_MODE:
  fail  — прогресс в stdout, русская ошибка последней строкой stderr, код 1;
  hang  — печатает начало загрузки и висит (для отмены);
  echo  — печатает ключ в stdout (проверка, что лог его прячет).
"""

import json
import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    key = os.environ.get("YANDEX_MUSIC_TOKEN") or ""
    trace = os.environ.get("FAKE_MUSICLINK_TRACE")
    if trace:
        Path(trace).write_text(json.dumps({"argv": argv, "has_key": bool(key), "key": key},
                                          ensure_ascii=False), "utf-8")
    if len(argv) != 3 or argv[0] != "download":
        print(f"bad args: {argv}", file=sys.stderr, flush=True)
        return 2
    _, url, dest = argv
    mode = os.environ.get("FAKE_MUSICLINK_MODE", "")
    print(f"musiclink: загрузка {url}", flush=True)
    if mode == "fail":
        print("Traceback-free detail line", file=sys.stderr, flush=True)
        print("Яндекс Музыка не отдала трек: нужна подписка Плюс (и, возможно, российский IP)",
              file=sys.stderr, flush=True)
        return 1
    if mode == "hang":
        time.sleep(120)
        return 0
    if mode == "echo":
        print(f"debug key {key}", flush=True)
    Path(dest).write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00YM-AUDIO " + url.encode())
    print(f"musiclink: OK {dest}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
