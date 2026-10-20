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

### Из таска 02 — разбор сборника

- `songpack.PackError(message)` (`.message`); `songpack.FoundSong(txt_rel, artist, title, language|None, duet, audio_rel|None, cover_rel|None, youtube: list[str], cover_url|None)` — frozen, пути POSIX относительно папки разбора
- `songpack.safe_extract(zip_path, dest, max_total_bytes) -> list[str]` — распакованные пути от `dest`; `..`/абсолютные пути — `PackError` на весь архив, симлинки пропускаются; при сбое на середине уже записанное остаётся — **вызывающий удаляет `imports/<token>`**
- `songpack.find_songs(dir) -> list[FoundSong]` (по `txt_rel`); `songpack.youtube_links(video_header) -> (audio_urls, cover_url)`; `co=` без схемы → `https://images.fanart.tv/fanart/<value>`
- `songpack.AUDIO_EXTS`, `IMAGE_EXTS`, `ALLOWED_EXTS`
- `DataPaths.imports_root`, `DataPaths.import_dir(token)` (токен `[A-Za-z0-9_-]{1,64}`, иначе `ValueError`)

### Из таска 01 — HTTP и поиск текста

- `karaoke_core.http`: `HttpResponse(status, url, headers, body)`; `HttpError(message, status=None)`; `Http(cookies=None).request(method, url, *, params, data, headers, timeout=10, max_bytes=5 MiB)`, `.download(url, dest, *, max_bytes, timeout=60)` (недокачанный файл удаляется), `.session()`; User-Agent `karaoke-services` по умолчанию
- `create_app(..., http=None)` → `AppContext.http` (по умолчанию `Http()`)
- `web/app/lyrics.py`: `LyricsHit(id, artist, title, album, duration, text).to_dict()`, `LyricsProvider` (Protocol), `LrclibProvider(http).search(artist, title)`, `LyricsUnavailable`, `strip_lrc`, `clean_text`; роутер — `web/app/api_lyrics.py`, `GET /api/lyrics/search`
- `tests/fakes_http.py`: `FakeHttp().route(method, prefix, resp | **response_kw)`, `.requests`, `.calls(prefix)` → `FakeRequest(method, url, params, data, headers, timeout, max_bytes, session, .query)`; `response(status, body, json=, url=, headers=)`; самый длинный префикс побеждает; статус ≥400 → `HttpError`; `session()` — общие маршруты и журнал. **Импорт в тестах**: корневого `tests/conftest.py` нет (`--import-mode=importlib`), поэтому тест сам добавляет `tests/` в `sys.path` перед `from fakes_http import FakeHttp` — делать так же
- фронт: `lyrics-search.js` — `stripLrc`, `usableHits`, `previewLines`, `fmtSeconds`, `searchBlocker`, `needsReplaceConfirm`; `api.lyricsSearch(artist, title)`

### Из таска 08 — UltraSinger `--lyrics_timing` (репозиторий D:/Projects/UltraSinger, ветка karaoke-local)

- Флаг `--lyrics_timing <file.lrc>` (`Settings.lyrics_timing_path`), работает только вместе с текстом (`--lyrics` или `<input>.lyrics.txt`); без текста — предупреждение и ничего
- `lrc_timing.parse_lrc(text) -> [(sec, text)]` по времени; `[mm:ss]`, `[mm:ss.xx]`, `[mm:ss.xxx]`, несколько меток на строку **разворачиваются по времени** (строка с двумя метками = две строки), `[offset:±ms]` (плюс — раньше), метаданные пропускаются
- Нормализация строки (повторить в сервисе один в один): каждое слово — нижний регистр, `ё→е`, удалить всё, что не `\w` (`[^\w]`), пустые слова выкинуть, склеить одним пробелом. Строки LRC пропускаются, если после меток пусто, нормализуется в пусто или это голый `[..]`. Сопоставление — всё или ничего: число строк и каждая строка совпадают, иначе вывод `LRC line timing not used: …` и старая логика
- Окна: [метка − 0,5; следующая метка + 0,5], последняя — до конца аудио, обрезка по [0; длительность]; `lyrics_debug.json` → `"lyrics_windows_source": "lrc" | "whisper"`; ключ кэша транскрипции получает суффикс `-lrc<md5[:8]>`
- **Для таска 07**: чистый текст из LRC в форме строится в том же развёрнутом порядке (строка с N метками — N раз), иначе метки не применятся

### Из таска 03 — usdb

- `web/app/usdb.py`: `UsdbClient(http, user, pass_)`: `.login()`, `.search(artist, title, language, start) -> UsdbPage(items: list[UsdbHit], has_more)`, `.fetch_song(id) -> UsdbSong(txt: bytes utf-8, youtube: list[str], cover_url: str|None)`; `UsdbHit(id: int, artist, title, language, rating: float, views: int).to_dict()`; ошибки `UsdbError` ⊃ `UsdbAuthError`, `UsdbUnavailable`, `UsdbNotFound` («Песня в usdb не найдена»), тексты по-русски; чистые разборщики `parse_list`, `parse_gettxt`, `parse_detail`; ссылки YouTube — всегда `https://www.youtube.com/watch?v=<id>` (как в songpack)
- `api_usdb.usdb_api_error(e) -> ApiError`: auth → 400 field=password, not found → 404, иначе 503
- `AppContext.usdb()` — клиент для сохранённой учётки (кэш до смены), без учётки → `ApiError(400, code="usdb_no_account")`; `AppContext.reset_usdb()`
- core db: `UsdbAccount(user, password=None)` (`.configured`, `.public() -> {user, has_password}`), `Settings.get_usdb()/set_usdb(acc)`, ключ `USDB_KEY="usdb"`
- REST: `GET/PUT /api/settings/usdb` → `{user, has_password}` (PUT сохраняет только после успешного входа; пустой user без пароля — удалить учётку), `POST /api/settings/usdb/test` → `{ok:true}`; `GET /api/usdb/search?artist=&title=&language=&start=` → `{items:[…, existing_song_id], has_more}`, без параметра `language` — `"Russian"`, пустое значение — без фильтра
- JS: `api.usdbAccount()`, `saveUsdbAccount(body)`, `testUsdbAccount(body)`, `usdbSearch({artist,title,language,start})`; пустой список в UI → «В usdb ничего не нашлось» (таск 06)
- `tests/conftest.py` кладёт `tests/` в `sys.path` — `from fakes_http import FakeHttp` работает без ручных вставок
- **Ловушка `test_repo_config`**: строка вида `password: <что угодно>` или `password=<значение>` в коде/JS ловится как секрет — писать `b['password']` или передавать позиционно

### Из таска 05 — задание «Импорт» в воркере

- `HANDLERS["import"] = ImportHandler()` (`needs_gpu=False`), params — по контракту выше
- Этапы: `progress.STAGE_DOWNLOAD=("Загрузка звука",5)`, `progress.IMPORT_PREPARE=("Подготовка",70)`, затем `STAGE_PUBLISH`; `progress.DownloadTracker` — `[download] NN%` yt-dlp → 5…60 %
- `JobContext.ytdlp_cmd()` — `YTDLP_CMD`, по умолчанию `python -m yt_dlp`; `handlers.download_youtube(ctx, job_id, url, work, thumbnail) -> (mp3, jpg|None)`, ошибка → `JobFailed("youtube", "YouTube не отдал звук: …")`; `handlers.to_mp3(ctx, job_id, src, dest)` (mp3 — копия аудиопотока, остальное — libmp3lame)
- `publish_song` для `src.type=="import"` с `instrumental=true` ставит `instrumental` (params как у веба: `rel_dir, txt_name, audio, instrumental, replace, target_id`; `song_id=song_id_for(...)`; `parent_id` = импорт); сбой постановки — только предупреждение в логе
- `PublishHandler` понимает `import`; `selfcheck`: `check_yt_dlp`, `check_deno`, всего 7 проверок; образ worker содержит `deno 2.5.6`, yt-dlp 2026.02.21
- Импорт кладёт mp3 в `in/input.mp3`, миниатюру YouTube — в `in/cover.jpg`; при restart готовый `in/input.mp3` используется без повторной загрузки; уборка `imports/*` старше часа при старте воркера

### Из таска 04 — импорт на сервере

- `POST /api/import/inspect` (multipart: `source=usdb|files|url`, `usdb_id` | `url` | `files[]`) → `{token, source, songs:[{index, artist, title, language, duet, audio (имя файла|null), cover (bool: файл в архиве или cover_url), has_instrumental, youtube, existing_song_id, warnings}]}`
- `POST /api/jobs/import` (multipart: `token, index, artist, title, audio?, youtube_url?, instrumental, replace, song_id?`) → 201 Job; обложку по `cover_url` скачивает он же в `in/cover.<ext>` (все источники); свой `[Instrumental]` из архива в `in/` не переносится
- Ошибки: нет песен 400; размер 413 (`field=files|url`); ссылка не скачалась/не zip/не http(s) 400 `field=url`; `PackError` 400; токен старше часа/неизвестный 410 «Загрузка устарела, загрузите заново»; нет звука 400 `field=audio`; дубль в папке 409 с `song_id`; дубль в очереди 409 «Эта песня уже в очереди»
- Раскладка `imports/<token>/{files/…, meta.json}`, срок жизни — mtime `meta.json`; `api_import.purge_imports(paths, max_age_s=3600) -> int` (старт web, каждые 6 ч, каждый inspect); `/api/defaults` → `max_import_mb`

### Из таска 06 — раздел «Импорт»

- `import-logic.js`: `pickAudioSource(song, {file?, youtube?}) → {kind:'upload'|'archive', name} | {kind:'youtube', url} | {kind:'none'}`; `importWarnings(song, audio) → string[]`; `initialCardState(song)`; `importFields(token, song, state)`; `importBlocker(items)`; `importOutcome(e) → {kind:'duplicate'|'expired'|'error', …}`; константы `NEED_AUDIO`, `WARN_SYNC`, `EXPIRED`, `DUP_TEXT`
- `api.js`: `api.importInspect(form)`, `api.importJob(form)`, `inspectForm({source, usdb_id?, url?, files?})`, `importForm({token, index, artist, title, audio?, youtube_url?, instrumental, replace})`
- `GET /api/songs`, `/api/songs/{id}` → поле `source`: `"usdb"|"files"|"url"|null`
- `#import` (`import.js`: mount/show), `TYPE_LABEL.import = 'Импорт'`, метки «импорт» / «из usdb» на карточке; `docker-compose.yml` передаёт `MAX_IMPORT_MB` в web

### Из таска 07 — синхронизированный текст

- `LyricsHit.synced: str | None`, поле `synced` в `/api/lyrics/search`; `lyrics.synced_lrc(raw)`
- generate: файловая часть `lyrics_lrc` (≤ MAX_LYRICS_MB, иначе 413 field=lyrics_lrc; пустая — удалить сохранённый) → `in/lyrics.lrc` (UTF-8), `params.inputs.lrc`; `api_jobs.INPUT_LRC="lyrics.lrc"`; restart/regen переносят `lyrics.lrc`; параметр `lrc_timing: bool` (умолчание false)
- worker: `handlers.parse_lrc`, `lyrics_lines`, `lrc_matches(lyrics, lrc) -> bool`, `LRC_NOT_USED`; `ultrasinger_args(..., *, lyrics_timing=None)`; `selfcheck.REQUIRED_FLAGS` включает `lyrics_timing`
- JS: `generateForm({..., lyrics_lrc?})`, `PARAM_KEYS += 'lrc_timing'`; lyrics-search.js: `parseLrc`, `lrcPlainText`, `lrcTimingDefault(lrcDur, mp3Dur)`, `lrcAfterEdit(held, text)`, `MAX_DURATION_DIFF_S=3`
