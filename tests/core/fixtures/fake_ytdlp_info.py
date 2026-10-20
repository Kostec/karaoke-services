"""Фейковый yt-dlp для ytdlp_info: печатает JSON по последнему аргументу (ссылке), без сети."""

import json
import sys
import time

args = sys.argv[1:]
url = args[-1]

NET_ERRORS = {
    "net-webpage": "ERROR: [youtube] abc: Unable to download webpage: HTTP Error 502: Bad Gateway",
    "net-dns": "ERROR: [generic] Unable to resolve: <urlopen error [Errno -3] Temporary failure in name resolution>",
    "net-timeout": "ERROR: [vk] 1_2: Read timed out. (read timeout=20.0)",
    "net-conn": "ERROR: [rutube] x: Connection reset by peer",
}
for marker, line in NET_ERRORS.items():
    if marker in url:
        print(line, file=sys.stderr)
        sys.exit(1)
if "error" in url:
    print("WARNING: что-то не так", file=sys.stderr)
    print("ERROR: [generic] Unsupported URL: " + url, file=sys.stderr)
    sys.exit(1)
if "sleep" in url:
    time.sleep(10)
if "notjson" in url:
    print("<html>")
    sys.exit(0)

if "list=" in url:
    data = {
        "_type": "playlist", "title": "Мой плейлист", "_args": args,
        "entries": [
            {"_type": "url", "ie_key": "Youtube", "id": "aaa", "url": "https://www.youtube.com/watch?v=aaa",
             "title": "Кино - Группа крови", "uploader": "Kino Fan", "duration": 285.0,
             "thumbnails": [{"url": "https://i.ytimg.com/vi/aaa/1.jpg"}, {"url": "https://i.ytimg.com/vi/aaa/2.jpg"}]},
            {"_type": "url", "ie_key": "Youtube", "id": "bbb", "url": "bbb",
             "title": "Звезда по имени Солнце", "uploader": "Кино - Topic", "duration": None},
            None,
        ],
    }
elif "swap" in url or "dup" in url:
    data = {"title": "Numb (Official Music Video) [4K UPGRADE] – Linkin Park", "uploader": "Linkin Park",
            "duration": 187, "webpage_url": url, "_args": args}
    if "dup" in url:
        data["artist"] = "Linkin Park"
elif "rutube" in url:
    data = {"title": "Песня без исполнителя", "uploader": "Канал", "duration": 120,
            "webpage_url": url, "thumbnail": "https://rutube.example/t.jpg", "_args": args}
else:
    data = {"id": "kXYiU_JCYtU", "title": "Linkin Park - Numb (Official Video)", "track": "Numb",
            "artist": "Linkin Park", "uploader": "Linkin Park", "duration": 187,
            "webpage_url": "https://www.youtube.com/watch?v=kXYiU_JCYtU",
            "thumbnail": "https://i.ytimg.com/vi/kXYiU_JCYtU/maxresdefault.jpg", "_args": args}
print(json.dumps(data, ensure_ascii=False))
