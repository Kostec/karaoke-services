# Интерфейсы

## Правила проекта

- Читать сначала `CLAUDE.md` в корне: команды, соглашения, подводные камни. Python 3.12, `from __future__ import annotations`, тексты ошибок/комментарии — по-русски; ошибки API — `ApiError`, задания — `JobFailed(reason, user_message)`; пути тома — `DataPaths`, имена песен — `naming`, запись в папку результата — `Storage`.
- Тесты только в Linux-контейнере: `docker --context desktop-linux compose --profile test run --build --rm tests` (до этой сборки: 291 passed, 2 skipped). Фронт: `node --test tests/frontend/`. pytest на Windows-хосте не запускать.
- Docker — только `--context desktop-linux`; движок не переключать. Репозиторий `D:/Projects/UltraSinger` не трогать.
- Новая переменная окружения — в `.env.example` с русским комментарием строкой выше (проверяет `tests/core/test_repo_config.py`, он же ловит `PASSWORD|SECRET|TOKEN` со значением — в коде и фикстурах не писать литералов вида `password=...`/`TOKEN: ...` вне `tests/`).
- Недостающая зависимость — не ставить самому, а вернуть `BLOCKED` с объяснением (исключение — то, что таск прямо разрешает: `deno` в образе worker, таск 05).
- Реальные сайты (LRCLIB, usdb, GitHub, YouTube) в тестах не трогать — только `FakeHttp` / `fake_ytdlp.py`.
- Коммитит оркестратор; исполнитель не коммитит и не переключает ветки.

## Контракты, общие для тасков

### `core/karaoke_core/http.py` (таск 01, пользуются 03 и 04)

```python
@dataclass(frozen=True)
class HttpResponse:
    status: int
    url: str              # итоговый после редиректов
    headers: dict[str, str]  # ключи в нижнем регистре
    body: bytes

class HttpError(Exception):       # текст по-русски, без паролей и тел запросов
    status: int | None             # None — сеть/таймаут

class Http:
    def request(self, method: str, url: str, *, params: dict | None = None,
                data: dict | bytes | None = None, headers: dict | None = None,
                timeout: float = 10, max_bytes: int = 5 * 2**20) -> HttpResponse: ...
    def download(self, url: str, dest: Path, *, max_bytes: int, timeout: float = 60) -> HttpResponse: ...  # потоком в файл, body=b""
    def session(self) -> "Http": ...   # копия со своей cookie-банкой
```
`data: dict` — form-urlencoded. Статус ≥400 → `HttpError(status=…)`. Фейк для тестов: `tests/fakes_http.py` (`FakeHttp` — маршруты по (method, url-префикс) → ответ/исключение; записывает запросы) — его создаёт таск 01, остальные дополняют, не переписывают.
`create_app(..., http: Http | None = None)` → `AppContext.http`.

### params задания `import` (таск 04 пишет, таск 05 читает)

```json
{
  "source": "usdb" | "files" | "url",
  "usdb_id": 12345,                 // только для usdb
  "youtube_url": "https://…",       // если звук не из файлов
  "instrumental": true,
  "rel_dir": "<A>/<A - T>", "replace": false, "replace_rel_dir": null, "target_id": "…",
  "inputs": {"dir": "songs/<A>/<A - T>/jobs/<id>/in",
             "txt": ".../in/song.txt",
             "audio": ".../in/input.mp3" | ".../in/audio.<ext>",   // нет, если звук с YouTube
             "cover": ".../in/cover.<ext>"}                      // опционально
}
```
Пути в `inputs` — от `DATA_DIR`, как у generate. `artist`/`title` — колонки задания (из формы). Ровно один из `inputs.audio` / `youtube_url` обязателен.

### Задание `instrumental`, поставленное импортом (таск 05)

Те же params, что ставит веб `POST /api/jobs/instrumental` для песни (смотреть `api_jobs.py`), `parent_id` = id задания импорта.

### `params.json` в `source/` импортированной песни

Плюс к обычному: `"source": "usdb"|"files"|"url"`, `"usdb_id"` при usdb. API песни (таск 06) отдаёт `source` (или `null`).

## Границы, решённые в спецификации

| Модуль | Владеет | Выставляет | Прячет |
|---|---|---|---|
| `core/karaoke_core/http.py` | исходящие HTTP-запросы | `Http.request(method, url, *, data=None, headers=None, timeout=10, max_bytes) -> HttpResponse(status, url, headers, body: bytes)`; `Http.session() -> Http` (своя cookie-банка); `HttpError(message)` | urllib, cookie, обрезку по размеру |
| `web/app/lyrics.py` | поиск текстов | `LyricsProvider.search(artist, title) -> list[LyricsHit(id, artist, title, album, duration, text)]`; `LrclibProvider(http)`; `LyricsUnavailable` | API LRCLIB, срез LRC, отбор инструменталов |
| `web/app/usdb.py` | разговор с usdb | `UsdbClient(http, user, password)`: `login()`, `search(artist, title, language, start) -> UsdbPage(items[UsdbHit(id, artist, title, language, rating, views)], has_more)`, `fetch_song(id) -> UsdbSong(txt: bytes, youtube: list[str], cover_url: str|None)`; `UsdbAuthError`, `UsdbUnavailable` | HTML-разбор, сессию, повторный вход |
| `core/karaoke_core/songpack.py` | разбор сборника | `safe_extract(zip_path, dest, max_total_bytes)`, `find_songs(dir) -> list[FoundSong(txt_rel, artist, title, language, duet, audio_rel|None, cover_rel|None, youtube: list[str], cover_url|None)]`, `youtube_links(video_header) -> (audio_urls, cover_url)`; `PackError(message)` | правила zip, сопоставление файлов без учёта регистра |
| `web/app/api_import.py` | REST импорта и поиска | `GET /api/lyrics/search?artist=&title=`, `GET /api/usdb/search?artist=&title=&language=&start=`, `POST /api/import/inspect`, `POST /api/jobs/import`, `GET/PUT /api/settings/usdb`, `POST /api/settings/usdb/test` | staging `imports/<token>`, `meta.json` с результатом разбора |
| `worker` `ImportHandler` | превращение импорта в выложенную песню | `HANDLERS["import"]`; params: `{source, usdb_id?, youtube_url?, instrumental, rel_dir, replace, replace_rel_dir, target_id, inputs:{dir, txt, audio?, cover?}}` | yt-dlp, ffmpeg, сборку папки |
| фронт `import.js` / `import-logic.js` / `lyrics-search.js` | экран «Импорт», диалог текста | `mount/show/hide`; `pickAudioSource(song, form)`, `importWarnings(...)`, `stripLrc(text)`, `usableHits(list)` | DOM |

**Ответ inspect** (контракт web ↔ фронт):

```json
{"token": "hex", "source": "usdb|files|url", "songs": [
  {"index": 0, "artist": "…", "title": "…", "language": "Russian", "duet": false,
   "audio": "song.mp3" , "cover": true, "youtube": ["https://youtu.be/…"],
   "existing_song_id": null, "warnings": []}]}
```

**Швы для тестов** (существующие):
- `create_app(..., http=FakeHttp)` + `TestClient` — LRCLIB, usdb, ссылка на zip, inspect, jobs/import (`tests/api/`);
- `run_forever(...)` с `YTDLP_CMD=fake_ytdlp.py`, `FFMPEG_CMD` (`tests/worker/`);
- чистые функции `songpack` (`tests/core/`) и `import-logic.js`/`lyrics-search.js` (`tests/frontend/`).


## Что построили таски

(пополняется после каждого таска)
