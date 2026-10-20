<!-- autopilot:start -->
# karaoke-services

Домашний сервис (docker-compose на Windows-ПК с GPU) для генерации караоке-песен UltraStar через UltraSinger из браузера, импорта готовых (usdb, zip, GitHub) и выкладки их на Samba-шару Raspberry Pi.
Два контейнера: `web` (FastAPI + статический фронт на ES-модулях без сборки) ставит задания в SQLite, `worker` (CUDA, UltraSinger, demucs, ffmpeg, yt-dlp + deno) их исполняет и выкладывает песню в папку результата (SMB или папка ПК). Интерфейс и все сообщения пользователю — на русском.

## Команды

Docker — только Linux-движок: `docker --context desktop-linux compose ...` или обёртка `./scripts/compose.ps1 ...` (PowerShell).
- Запуск/пересборка: `./scripts/compose.ps1 up -d --build`; веб — http://localhost:8090, API-доки — http://localhost:8090/api/docs.
- Проверка GPU и правок UltraSinger: `./scripts/compose.ps1 run --rm worker gpucheck` (успех — RC=0, последняя строка `gpucheck: OK …`).
- Только образ worker (15–30 мин с нуля): `./scripts/compose.ps1 build worker`.
- Логи: `./scripts/compose.ps1 logs --tail 100 worker` (или `web`).
- Python-тесты (pytest в Linux-контейнере): `docker --context desktop-linux compose --profile test run --rm tests` → 564 passed, 2 skipped (после смены зависимостей — `run --build`).
- Подмножество: `docker --context desktop-linux compose --profile test run --rm tests pytest -q tests/worker/test_runner_queue.py`.
- Фронт-тесты (Node 24, встроенный node:test): `node --test tests/frontend/` → 76 pass.
- Бэкап патча UltraSinger в `patches/karaoke-local.patch`: `./scripts/export-ultrasinger-patch.ps1` (читает `D:/Projects/UltraSinger`).
- CLI воркера внутри образа: `python -m karaoke_worker gpucheck|selfcheck|run`; entrypoint пропускает эти слова в CLI, прочее (`bash`, `python`) исполняет как есть.

## Структура

```
core/karaoke_core/        общий пакет web+worker: db, paths, naming, ultrastar, postprocess, trash, http, songpack
core/karaoke_core/storage/  Storage: base (интерфейс, SongEntry), local, smb (smbprotocol)
core/Dockerfile.test      образ сервиса tests (editable core+web, pytest по tests/)
web/app/                  FastAPI: main (create_app, Basic-auth, очистка корзины), api_jobs/songs/settings/import/lyrics/usdb, context, params, notes, lyrics (LRCLIB), usdb (клиент)
web/static/js/            SPA по хэшу (#queue #new #import #songs #trash #settings), api.js, ui.js, id3.js, import.js, import-logic.js, folder-logic.js, lyrics-search.js, lyrics-dialog.js
web/static/js/editors/    редакторы песни: lyrics (перегенерация с новым текстом), lines (слоги/строки)
worker/karaoke_worker/    runner (цикл очереди), handlers, base (JobContext, процессы), progress, gpucheck, selfcheck
worker/build/             entrypoint.sh, lock_constraints.py (uv.lock → constraints), check_torch_arch.py, link_hyphen_dir.py
worker/Dockerfile         CUDA 12.6 + Python 3.12 + torch cu126 + UltraSinger из контекста `ultrasinger`
tests/core|api|worker/    три шва pytest; tests/worker/fixtures/fake_*.py — подмены UltraSinger/demucs/ffmpeg/yt-dlp
tests/fakes_http.py       FakeHttp — подмена karaoke_core.http.Http; tests/api/usdb_fixtures/ — HTML-страницы usdb
tests/frontend/           *.test.mjs, index.js подгружает их все
scripts/                  compose.ps1, export-ultrasinger-patch.ps1
patches/karaoke-local.patch  резервная копия правок форка UltraSinger (git am)
```

## Ключевые файлы

- `core/karaoke_core/db.py` — схема (jobs, settings, library, songs), `Jobs/Settings/Library/Songs`, `OutputTarget`, `JOB_STATES`, `STAGE_PUBLISH`, `GPU_STATUS_KEY`, единственный формат `target_id`/label (`smb_target_id`, `local_target_id`).
- `core/karaoke_core/paths.py` — `DataPaths`: единственное место раскладки тома data.
- `core/karaoke_core/naming.py` — `safe_name`, `song_dir`, `base_name`, `song_file`, `SUFFIX_*`; все имена файлов песен — только отсюда.
- `core/karaoke_core/ultrastar.py` — разбор/запись `.txt` с сохранением кодировки, BOM и переводов строк; `decode`, `set_header_line`, `fix_zero_length`.
- `core/karaoke_core/postprocess.py` — `finalize()`: выход UltraSinger → готовая папка (имена, обложка, `#VERSION:1.2.0`, `#AUDIO`, отброс MusicBrainz при чужом исполнителе).
- `core/karaoke_core/storage/base.py` — `Storage` (`upload_dir`: медиа сначала, `.txt` последним, через `.part`), `read_song`, `is_song_txt_name`, `StorageError`/`StorageNotFound` с русским текстом без пароля.
- `core/karaoke_core/http.py` — `Http` (единственный исходящий HTTP: `request`, `download` потоком с `max_bytes`, `session()` со своей cookie-банкой), `HttpResponse`, `HttpError(message, status)` (статус ≥400; `None` — сеть/таймаут).
- `core/karaoke_core/songpack.py` — `safe_extract` (zip без `..`/абсолютных путей, симлинки пропускает, лимит распаковки; при сбое папку чистит вызывающий), `find_songs` → `FoundSong`, `youtube_links(#VIDEO)`, `PackError`, `AUDIO_EXTS/IMAGE_EXTS`.
- `core/karaoke_core/trash.py` — `Trash`: перенос в корзину, версии `.txt`, restore (только в ту же цель), purge по `TRASH_DAYS`.
- `web/app/api_jobs.py` — общие помощники приёма файлов (`Staging`, `queue_duplicate`, `is_mp3`, `cover_ext_of`, `copy_limited`; их же зовёт `api_import`); generate (multipart, staging → `jobs/<id>/in/`), instrumental, cancel/restart/republish, лог `?from=|tail=` и SSE.
- `web/app/api_import.py` — `POST /api/import/inspect` (usdb | `files[]` | url: zip или GitHub → codeload-архив), `POST /api/jobs/import`, staging `imports/<token>/`, `purge_imports`, `max_import_mb`.
- `core/karaoke_core/musiclink.py` — ссылки на музыку: `classify` (Яндекс трек/альбом/плейлист или yt-dlp; аудио VK и адреса домашней сети — отказ; у YouTube снимается `list=`), `ytdlp_info` (`-4 -J --flat-playlist`), `YandexMusic` (токен аккаунта, `info`/`download`/`check`), `MusicLinkError`, CLI `python -m karaoke_core.musiclink download <url> <dest>` (токен — в env `YANDEX_MUSIC_TOKEN`); токен — `Settings.get_yandex/set_yandex`.
- `web/app/api_link.py` — `POST /api/link/inspect` → треки `{url, artist, title, duration, thumbnail, existing_song_id}`; generate принимает `audio_url` (вместо файла) и `cover_url` (обложку качает web, `api_jobs.download_cover`); worker качает звук в `handlers.download_link` (yt-dlp или `MUSICLINK_CMD`); `/api/settings/yandex` — `has_token`.
- `web/app/lyrics.py` — `LrclibProvider`, `LyricsHit(..., synced)`, `strip_lrc`, `synced_lrc`; `web/app/usdb.py` — `UsdbClient` (вход, поиск, `fetch_song`), `UsdbAuthError/UsdbUnavailable/UsdbNotFound`, HTML-разборщики; `web/app/api_usdb.py` — `usdb_api_error`.
- `web/app/params.py` — модели, языки, лимиты (`MAX_COVER_MB`, `MAX_LYRICS_MB`, `MAX_FOLDER_AUDIO_MB`), `/api/defaults`.
- `web/app/context.py` — `AppContext` (`.http`, `.usdb()` — кэш клиента сохранённой учётки, `reset_usdb()`), `ApiError`, `match_key` (ключ дубля песни).
- `worker/karaoke_worker/handlers.py` — `HANDLERS` generate/instrumental/import/publish, `ultrasinger_args(..., lyrics_timing=)`, `publish_song` (замена с откатом из корзины), `download_youtube`, `to_mp3`; LRC: `parse_lrc`, `lyrics_lines`, `lrc_matches`, `LRC_NOT_USED`.
- `worker/karaoke_worker/base.py` — `JobContext`, `run_command` (группа процессов, отмена, убийство зависших), `explain_failure`, `JobFailed(reason, user_message)`.
- `worker/karaoke_worker/progress.py` — `STAGES`: маркер строки лога UltraSinger → русский этап и процент; `STAGE_DOWNLOAD`, `IMPORT_PREPARE`, `DownloadTracker` (`[download] NN%` yt-dlp).
- `worker/karaoke_worker/selfcheck.py` — 7 проверок образа; `REQUIRED_FLAGS` форка (`lyrics`, `vad_onset`, `vad_offset`, `lyrics_timing`), `check_yt_dlp`, `check_deno`.
- `web/static/js/api.js` — `api`, `ApiError`, `generateForm()` (единственная сборка multipart generate, с `lyrics_lrc`), `inspectForm()`/`importForm()`, `PARAM_KEYS`, `canRepublish`.
- `web/static/js/folder-logic.js` (`splitFolder`, `trackMeta`, `nextLyricsRow`, `trackFields`) — вкладка «Импорт → Папка»: готовые .txt-песни → inspect `source=files` с относительными путями (`webkitRelativePath`), прочие mp3 → `generate` по одному с авто-поиском текста; `web/static/js/lyrics-dialog.js` — общий диалог поиска текста (форма новой песни и папка).
- `web/static/js/import-logic.js` (`pickAudioSource`, `importWarnings`, `importOutcome`) и `web/static/js/lyrics-search.js` (`stripLrc`, `usableHits`, `lrcPlainText`, `lrcTimingDefault`) — чистая логика под node-тесты.
- `web/static/js/extensions.js` — `registerSongEditor(id, {label, open, enabled})`; редакторы подключаются одной строкой в `web/static/js/app.js` (`import './editors/index.js'`).

## Архитектура

- web ↔ worker общаются только через SQLite `/data/karaoke.sqlite` (WAL, явные `BEGIN IMMEDIATE`) и файлы тома `data`; HTTP между ними нет.
- web: ставит задания (`Jobs.enqueue_with`), читает статус GPU из `settings[gpu_status]` (нет записи → `gpu.ok=null`), отдаёт лог из `/data/logs/<id>.log`, раз в 6 ч чистит корзину.
- worker: при старте `Settings.set_gpu_status(gpucheck.check())`, `Jobs.fail_interrupted()`, уборка `jobs/.new-*` старше часа и логов/входов старше `LOG_DAYS`; затем цикл `claim_next()` по одному заданию (8 ГБ VRAM). Без GPU берёт только `publish` и `import` (`needs_gpu=False`), GPU перепроверяет раз в минуту; при старте же удаляет `imports/*` старше часа.
- Отмена: web ставит `cancel_requested`, worker проверяет раз в секунду, убивает группу процессов (SIGTERM → 10 с → SIGKILL); `in/` сохраняется для «Перезапустить».
- Состояния: `queued → running → publishing → done|failed|cancelled`; `stage` — русское название этапа, на выкладке `STAGE_PUBLISH="publish"` (UI переводит). Упавшее на выкладке → `republish` создаёт задание `publish` с `source_job_id`.
- Поток generate: форма → `songs/<A>/<A - T>/jobs/.new-*` → rename в `jobs/<id>/in/` (`input.mp3`, `lyrics.txt`, `cover.<ext>`), `params.inputs` — пути от `DATA_DIR` → UltraSinger в `jobs/<id>/us|out` → `finalize` в `jobs/<id>/result` → `Storage.upload_dir` → `in/` копируется в `source/` (+`params.json`), обновляются Songs/Library, `jobs/<id>/` удаляется.
- Типы заданий: `generate`, `instrumental`, `import`, `publish`; `import` с `instrumental=true` после выкладки ставит `instrumental` (`parent_id` = импорт; сбой постановки — только предупреждение в логе).
- Текст из LRCLIB: `GET /api/lyrics/search` → до 10 вариантов (`text`, `synced`); форма шлёт `lyrics_lrc` → `in/lyrics.lrc`, `params.inputs.lrc`, флаг `lrc_timing`; worker передаёт `--lyrics_timing` только при `lrc_matches` (иначе в лог `LRC_NOT_USED`); строка LRC с N метками = N строк, фронт строит чистый текст в том же порядке (`lrcPlainText`).
- Поток import: inspect → `imports/<token>/{files/…, meta.json}` (жизнь — час по mtime `meta.json`, потом 410) → `{token, source, songs[{index, artist, title, audio, cover, youtube, existing_song_id, warnings…}]}` → `POST /api/jobs/import` (`token, index, artist, title, audio? | youtube_url?, instrumental, replace`) копирует в `jobs/<id>/in/` (`song.txt`, `audio.<ext>` или `input.mp3`, `cover.<ext>`; обложку по `cover_url` качает веб) → worker: yt-dlp, если нет звука → `in/input.mp3` + `in/cover.jpg` (restart не качает заново) → ffmpeg mp3 → `.txt` без `#VIDEO/#BACKGROUND/#VIDEOGAP` → `finalize` → `publish_song`; в `source/params.json` добавляются `source` (`usdb|files|url`) и `usdb_id`.
- usdb: учётка в `settings[usdb]` (`UsdbAccount`; PUT сохраняет только после успешного входа, пустой логин — удалить); без учётки → 400 `code=usdb_no_account`; неверный вход → 400 `field=password`, нет песни → 404, иначе 503.
- Замена песни: та же папка — старая в корзину, выкладка, при сбое откат из корзины; другая папка — сначала выкладка, потом старая в корзину.
- instrumental: demucs `--two-stems vocals` → ffmpeg mp3 → `<аудио> [Instrumental].mp3` рядом с аудио, в `.txt` меняется только `#INSTRUMENTAL`.
- Раскладка тома data: `karaoke.sqlite`; `logs/<id>.log`; `songs/<A>/<A - T>/{source/,jobs/<id>/in/,debug/}`; `trash/<UTC>__<id>/{<A>/<A - T>/…, meta.json}` (без `meta.json` запись считается недописанной); `imports/<token>/{files/…, meta.json}` (токен `[A-Za-z0-9_-]{1,64}`, `DataPaths.import_dir`). Том `models` (`/models`) — кэши HF/torch/xdg/hyphen.
- Папка результата: `<A>/<A - T>/<A - T>{.txt,.mp3, [Vocals].mp3, [Instrumental].mp3,.mid, [CO].jpg}`; цель — из `settings` (веб «Настройки»), иначе из `OUTPUT_*` env; локальная цель — корень `/output`.
- REST: ответы JSON, ошибки `{"detail": "по-русски", "field"?}`; 422 переводится в 400; папка результата недоступна → 503; неверный Range → 416. Пароли API никогда не возвращает (`has_password`).
- Эндпоинты: `/api/status`, `/api/defaults` (+`max_import_mb`), `/api/jobs` (`generate`, `instrumental`, `import`, `{id}`, `cancel`, `restart`, `republish`, `log`, `log/stream`), `/api/import/inspect`, `/api/lyrics/search`, `/api/usdb/search` (по 50; без `language` — `Russian`, пустой — без фильтра), `/api/songs` (`rescan`, `exists`, `{id}` с `source`, `lyrics`, `notes` GET/PUT, `audio` с Range, `cover`, DELETE), `/api/trash` (+`restore`), `/api/settings/output` и `/api/settings/usdb` (GET/PUT, `test`).
- `import_router` подключается раньше `jobs_router` (`web/app/main.py`), иначе `POST /api/jobs/import` уйдёт в маршруты `/api/jobs/{id}`.
- SSE лога: первым `event: start` с байтовым смещением, `id:` = смещение, в конце `event: end`; без `from` — последние 500 строк.
- PUT notes меняет только текст слогов, склейку/разбивку строк и удаление нот; тайминги, высоты и заголовки — только чтение; дуэты и `#RELATIVE` — только просмотр.

## Соглашения кода

- Python 3.12, `from __future__ import annotations`, docstring/комментарии и все тексты ошибок — по-русски.
- Пути тома data — только через `DataPaths`; имена песен — только через `naming`; запись в папку результата — только через `Storage`.
- Ошибки задания: `raise JobFailed(reason, user_message)`; `user_message` попадает в `Job.error` как есть (+ последние 5 строк лога).
- Ошибки API: `raise ApiError(status, "текст", field=...)`, не `HTTPException`.
- Новая переменная окружения обязана появиться в `.env.example` с русским комментарием строкой выше — проверяет `tests/core/test_repo_config.py`.
- Фронт: модуль раздела экспортирует `mount(section, ctx)`, `show(params)`, опц. `hide()`; чистая логика выносится в отдельные модули (`editors/lines.js`, `editors/lyrics-text.js`, `id3.js`) ради node-тестов.
- Исходящий HTTP — только через `karaoke_core.http.Http` (`AppContext.http`); в тестах — `create_app(..., http=FakeHttp())`, реальные LRCLIB/usdb/GitHub/YouTube не трогать.
- `test_repo_config` считает секретом любое `password`/`token`/`secret` (и `*_PASSWORD…`), за которым через двоеточие или знак равенства идёт значение, во всех файлах вне `tests/` — в коде/JS писать `b['password']`, передавать позиционно или назвать переменную иначе.
- LRC пишется в UTF-8 (читается `utf-8-sig`); нормализация строк в `handlers.py` (`_norm_line`, `parse_lrc`, `lyrics_lines`) повторяет форк `src/modules/Speech_Recognition/lrc_timing.py` один в один — менять только синхронно.
- Новые Python-зависимости для тестов добавляются в `core/Dockerfile.test` (через pyproject `core`/`web`).

## Окружение

- `WEB_PORT` — порт веба на хосте; `WEB_PASSWORD` — общий пароль HTTP Basic (логин любой, пусто — без пароля); `MAX_UPLOAD_MB` — лимит загрузки mp3; `MAX_IMPORT_MB` — лимит zip импорта (файлы или ссылка; распаковка — до двойного).
- `OUTPUT_KIND` (`smb`|`local`), `OUTPUT_SMB_HOST`, `OUTPUT_SMB_SHARE`, `OUTPUT_SMB_PATH`, `OUTPUT_SMB_USER`, `OUTPUT_SMB_PASSWORD` — цель выкладки по умолчанию (веб может переопределить в БД).
- `LOCAL_OUTPUT_ROOT` — папка хоста, монтируемая как `/output`.
- `TRASH_DAYS`, `LOG_DAYS` — срок хранения корзины и логов/входов; `TZ` — часовой пояс контейнеров.
- `ULTRASINGER_GIT` — источник UltraSinger для сборки worker (git-URL `…#karaoke-local` или локальный путь).
- `DEFAULT_WHISPER_MODEL`, `DEFAULT_LANGUAGE`, `DEFAULT_COMPUTE_TYPE`, `DEFAULT_BATCH_SIZE`, `DEFAULT_ALIGN_MODEL_RU` — умолчания формы и аргументов UltraSinger.
- Задаёт compose/образ, не пользователь: `DATA_DIR`, `MODELS_DIR`, `HF_HOME`, `TORCH_HOME`, `XDG_CACHE_HOME`, `PYHYPHEN_DIR`, `ULTRASINGER_DIR`, `WEB_STATIC_DIR`.
- `YTDLP_CMD` — команда yt-dlp для web и worker (пусто — `python -m yt_dlp` образа); `MUSICLINK_CMD` — загрузчик Яндекс Музыки (пусто — `python -m karaoke_core.musiclink`); `YANDEX_MUSIC_TOKEN` — только окружение этого подпроцесса (токен пользователь вводит в «Настройках»).
- Подмена команд в тестах: `ULTRASINGER_CMD`, `DEMUCS_CMD`, `FFMPEG_CMD`, `YTDLP_CMD`, `MUSICLINK_CMD`; интеграция с живой шарой: `TEST_SMB_HOST`, `TEST_SMB_SHARE`, `TEST_SMB_USER`, `TEST_SMB_PASSWORD`, `TEST_SMB_PATH`.

## Тесты

- `tests/core/` — чистые функции и `LocalStorage` во временной папке; фикстуры `.txt` (CRLF, BOM, cp1251, дуэт) сравниваются байт в байт и помечены binary в `.gitattributes`.
- `tests/api/` — `create_app(data_dir=, env=, storage_factory=, http=, ...)` через `TestClient`, env берётся из `.env.example`.
- `tests/conftest.py` кладёт `tests/` в `sys.path` (pytest с `--import-mode=importlib`) — `from fakes_http import FakeHttp` без ручных вставок; `FakeHttp().route(method, prefix, …)` (побеждает самый длинный префикс), `.calls(prefix)` — журнал; дополнять, не переписывать.
- `tests/worker/` — `run_forever(..., gpu_check=, until=)` с фейками из `tests/worker/fixtures/` через `*_CMD`; без torch и GPU.
- 2 skipped — `tests/core/test_storage_smb_integration.py` без `TEST_SMB_HOST/TEST_SMB_SHARE` (передавать `-e TEST_SMB_…` в `run`).
- `tests/core/test_repo_config.py` сканирует весь репозиторий (кроме `tests/`, `.autopilot/`, `.env`), включая этот файл, на `PASSWORD|SECRET|TOKEN` со значением после `=`/`:`.
- Настоящий GPU проверяется только `gpucheck` и реальной генерацией.

## Подводные камни

- У Docker Desktop активен Windows-движок — всегда `--context desktop-linux` (или `scripts/compose.ps1`); движок не переключать.
- Сеть контейнеров: `dns: 77.88.8.8, 1.1.1.1` и выключенный IPv6 (`sysctls`) в `docker-compose.yml` — DNS Docker Desktop сбоил, а AAAA-адреса без маршрута ломали Яндекс/LRCLIB; yt-dlp везде с `-4`.
- Шара на Pi не даёт переименовать поверх существующего файла (Samba на exFAT/NTFS-диске → «нет доступа»): `Storage.write_atomic` при отказе меняет файл в три шага (`_swap`: старый → `.old-*`, новый на место, старый удалить; сбой — откат), а «нет доступа»/sharing violation ещё и ждёт повторами (`BUSY_RETRY_DELAYS`).
- Имена `pi`/`pi.local` в контейнерах не резолвятся — в `OUTPUT_SMB_HOST` только IP.
- Порт 8080 на хосте занят jenkins — `WEB_PORT=8090` (внутри контейнера веб слушает 8080).
- Linux-колёса torch cu126 собраны без sm_61: на Pascal исполняется sm_60 — это норма (`gpucheck.runnable_arch`); cu128 без Pascal вовсе, сборку валит `worker/build/check_torch_arch.py`.
- Зависимости UltraSinger фиксируются по его `uv.lock` (`worker/build/lock_constraints.py` → `/etc/uv-constraints.txt`), наши пины важнее (torch/torchaudio/torchvision cu126, `numpy<2.5`); без этого swift-f0 0.3.0 ломает сигнатуру SwiftF0 (ловит `selfcheck`).
- GTX 1080 не умеет float16 — compute type только `int8`.
- Тесты — только в Linux-контейнере: воркер использует POSIX-группы процессов; на Windows-хосте pytest не запускать.
- После изменения зависимостей (pyproject, Dockerfile) — `run --build`, иначе образ tests старый; исходники монтируются в `/app` editable.
- `.gitattributes` `* text=auto eol=lf`: Dockerfile/sh/py идут в Linux-контейнеры; фикстуры тестов — binary.
- Форк `D:/Projects/UltraSinger` (ветка `karaoke-local`, remote `fork`) правится только с явного разрешения пользователя в текущей задаче; после правки — коммит в `karaoke-local`, `./scripts/export-ultrasinger-patch.ps1`, `git -C D:/Projects/UltraSinger push fork karaoke-local` — только с согласия (образ worker собирается из `ULTRASINGER_GIT`); проверка — `gpucheck`.
- Сборка worker падает на `RUN python -m karaoke_worker selfcheck`, если rebase форка потерял правку (флаги `--lyrics/--vad_onset/--vad_offset/--lyrics_timing`, `lyrics_alignment`, `midi_creator`, SwiftF0).
- yt-dlp не фиксируется по `uv.lock` (`lock_constraints.FRESH`) и ставится последним слоем образа: старая версия получает от YouTube HTTP 403. Обновить только его: `./scripts/compose.ps1 build --build-arg YTDLP_REFRESH=<дата> worker`, затем `./scripts/compose.ps1 up -d worker`.
- yt-dlp без `deno` (в образе — `denoland/deno:bin-2.5.6`) получает с YouTube не все форматы; `selfcheck` проверяет оба.
- Тома переживают `compose down`; `compose down -v` удаляет БД и корзину.

## Как здесь работает Autopilot

Сборка ведётся навыком `/autopilot`. Требования, спецификация и таски — в `.autopilot/`.
Прогресс — `.autopilot/dashboard.html`. Правило: требование из `manifest.md`
может снять только пользователь.

Если работа продолжается — скажи «продолжи автопилот»: состояние поднимется
из `.autopilot/state.js`, переспрашивать ничего не нужно.
<!-- autopilot:end -->
