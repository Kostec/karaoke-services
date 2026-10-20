<!-- autopilot:start -->
# karaoke-services

Домашний сервис (docker-compose на Windows-ПК с GPU) для генерации караоке-песен UltraStar через UltraSinger из браузера и выкладки их на Samba-шару Raspberry Pi.
Два контейнера: `web` (FastAPI + статический фронт на ES-модулях без сборки) ставит задания в SQLite, `worker` (CUDA, UltraSinger, demucs, ffmpeg) их исполняет и выкладывает песню в папку результата (SMB или папка ПК). Интерфейс и все сообщения пользователю — на русском.

## Команды

Docker — только Linux-движок: `docker --context desktop-linux compose ...` или обёртка `./scripts/compose.ps1 ...` (PowerShell).
- Запуск/пересборка: `./scripts/compose.ps1 up -d --build`; веб — http://localhost:8090, API-доки — http://localhost:8090/api/docs.
- Проверка GPU и правок UltraSinger: `./scripts/compose.ps1 run --rm worker gpucheck` (успех — RC=0, последняя строка `gpucheck: OK …`).
- Только образ worker (15–30 мин с нуля): `./scripts/compose.ps1 build worker`.
- Логи: `./scripts/compose.ps1 logs --tail 100 worker` (или `web`).
- Python-тесты (pytest в Linux-контейнере): `docker --context desktop-linux compose --profile test run --build --rm tests` → 291 passed, 2 skipped.
- Подмножество: `docker --context desktop-linux compose --profile test run --rm tests pytest -q tests/worker/test_runner_queue.py`.
- Фронт-тесты (Node 24, встроенный node:test): `node --test tests/frontend/`.
- Бэкап патча UltraSinger в `patches/karaoke-local.patch`: `./scripts/export-ultrasinger-patch.ps1` (читает `D:/Projects/UltraSinger`).
- CLI воркера внутри образа: `python -m karaoke_worker gpucheck|selfcheck|run`; entrypoint пропускает эти слова в CLI, прочее (`bash`, `python`) исполняет как есть.

## Структура

```
core/karaoke_core/        общий пакет web+worker: db, paths, naming, ultrastar, postprocess, trash
core/karaoke_core/storage/  Storage: base (интерфейс, SongEntry), local, smb (smbprotocol)
core/Dockerfile.test      образ сервиса tests (editable core+web, pytest по tests/)
web/app/                  FastAPI: main (create_app, Basic-auth, очистка корзины), api_jobs/songs/settings, context, params, notes
web/static/js/            SPA по хэшу (#queue #new #songs #trash #settings), api.js, ui.js, id3.js
web/static/js/editors/    редакторы песни: lyrics (перегенерация с новым текстом), lines (слоги/строки)
worker/karaoke_worker/    runner (цикл очереди), handlers, base (JobContext, процессы), progress, gpucheck, selfcheck
worker/build/             entrypoint.sh, lock_constraints.py (uv.lock → constraints), check_torch_arch.py, link_hyphen_dir.py
worker/Dockerfile         CUDA 12.6 + Python 3.12 + torch cu126 + UltraSinger из контекста `ultrasinger`
tests/core|api|worker/    три шва pytest; tests/worker/fixtures/fake_*.py — подмены UltraSinger/demucs/ffmpeg
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
- `core/karaoke_core/trash.py` — `Trash`: перенос в корзину, версии `.txt`, restore (только в ту же цель), purge по `TRASH_DAYS`.
- `web/app/api_jobs.py` — generate (multipart, staging → `jobs/<id>/in/`), instrumental, cancel/restart/republish, лог `?from=|tail=` и SSE.
- `web/app/params.py` — модели, языки, лимиты (`MAX_COVER_MB`, `MAX_LYRICS_MB`, `MAX_FOLDER_AUDIO_MB`), `/api/defaults`.
- `web/app/context.py` — `AppContext`, `ApiError`, `match_key` (ключ дубля песни).
- `worker/karaoke_worker/handlers.py` — `HANDLERS` generate/instrumental/publish, `ultrasinger_args`, `publish_song` (замена с откатом из корзины).
- `worker/karaoke_worker/base.py` — `JobContext`, `run_command` (группа процессов, отмена, убийство зависших), `explain_failure`, `JobFailed(reason, user_message)`.
- `worker/karaoke_worker/progress.py` — `STAGES`: маркер строки лога UltraSinger → русский этап и процент.
- `web/static/js/api.js` — `api`, `ApiError`, `generateForm()` (единственная сборка multipart generate), `PARAM_KEYS`, `canRepublish`.
- `web/static/js/extensions.js` — `registerSongEditor(id, {label, open, enabled})`; редакторы подключаются одной строкой в `web/static/js/app.js` (`import './editors/index.js'`).

## Архитектура

- web ↔ worker общаются только через SQLite `/data/karaoke.sqlite` (WAL, явные `BEGIN IMMEDIATE`) и файлы тома `data`; HTTP между ними нет.
- web: ставит задания (`Jobs.enqueue_with`), читает статус GPU из `settings[gpu_status]` (нет записи → `gpu.ok=null`), отдаёт лог из `/data/logs/<id>.log`, раз в 6 ч чистит корзину.
- worker: при старте `Settings.set_gpu_status(gpucheck.check())`, `Jobs.fail_interrupted()`, уборка `jobs/.new-*` старше часа и логов/входов старше `LOG_DAYS`; затем цикл `claim_next()` по одному заданию (8 ГБ VRAM). Без GPU берёт только `publish`, GPU перепроверяет раз в минуту.
- Отмена: web ставит `cancel_requested`, worker проверяет раз в секунду, убивает группу процессов (SIGTERM → 10 с → SIGKILL); `in/` сохраняется для «Перезапустить».
- Состояния: `queued → running → publishing → done|failed|cancelled`; `stage` — русское название этапа, на выкладке `STAGE_PUBLISH="publish"` (UI переводит). Упавшее на выкладке → `republish` создаёт задание `publish` с `source_job_id`.
- Поток generate: форма → `songs/<A>/<A - T>/jobs/.new-*` → rename в `jobs/<id>/in/` (`input.mp3`, `lyrics.txt`, `cover.<ext>`), `params.inputs` — пути от `DATA_DIR` → UltraSinger в `jobs/<id>/us|out` → `finalize` в `jobs/<id>/result` → `Storage.upload_dir` → `in/` копируется в `source/` (+`params.json`), обновляются Songs/Library, `jobs/<id>/` удаляется.
- Замена песни: та же папка — старая в корзину, выкладка, при сбое откат из корзины; другая папка — сначала выкладка, потом старая в корзину.
- instrumental: demucs `--two-stems vocals` → ffmpeg mp3 → `<аудио> [Instrumental].mp3` рядом с аудио, в `.txt` меняется только `#INSTRUMENTAL`.
- Раскладка тома data: `karaoke.sqlite`; `logs/<id>.log`; `songs/<A>/<A - T>/{source/,jobs/<id>/in/,debug/}`; `trash/<UTC>__<id>/{<A>/<A - T>/…, meta.json}` (без `meta.json` запись считается недописанной). Том `models` (`/models`) — кэши HF/torch/xdg/hyphen.
- Папка результата: `<A>/<A - T>/<A - T>{.txt,.mp3, [Vocals].mp3, [Instrumental].mp3,.mid, [CO].jpg}`; цель — из `settings` (веб «Настройки»), иначе из `OUTPUT_*` env; локальная цель — корень `/output`.
- REST: ответы JSON, ошибки `{"detail": "по-русски", "field"?}`; 422 переводится в 400; папка результата недоступна → 503; неверный Range → 416. Пароли API никогда не возвращает (`has_password`).
- Эндпоинты: `/api/status`, `/api/defaults`, `/api/jobs` (`generate`, `instrumental`, `{id}`, `cancel`, `restart`, `republish`, `log`, `log/stream`), `/api/songs` (`rescan`, `exists`, `{id}`, `lyrics`, `notes` GET/PUT, `audio` с Range, `cover`, DELETE), `/api/trash` (+`restore`), `/api/settings/output` (GET/PUT, `test`).
- SSE лога: первым `event: start` с байтовым смещением, `id:` = смещение, в конце `event: end`; без `from` — последние 500 строк.
- PUT notes меняет только текст слогов, склейку/разбивку строк и удаление нот; тайминги, высоты и заголовки — только чтение; дуэты и `#RELATIVE` — только просмотр.

## Соглашения кода

- Python 3.12, `from __future__ import annotations`, docstring/комментарии и все тексты ошибок — по-русски.
- Пути тома data — только через `DataPaths`; имена песен — только через `naming`; запись в папку результата — только через `Storage`.
- Ошибки задания: `raise JobFailed(reason, user_message)`; `user_message` попадает в `Job.error` как есть (+ последние 5 строк лога).
- Ошибки API: `raise ApiError(status, "текст", field=...)`, не `HTTPException`.
- Новая переменная окружения обязана появиться в `.env.example` с русским комментарием строкой выше — проверяет `tests/core/test_repo_config.py`.
- Фронт: модуль раздела экспортирует `mount(section, ctx)`, `show(params)`, опц. `hide()`; чистая логика выносится в отдельные модули (`editors/lines.js`, `editors/lyrics-text.js`, `id3.js`) ради node-тестов.
- Новые Python-зависимости для тестов добавляются в `core/Dockerfile.test` (через pyproject `core`/`web`).

## Окружение

- `WEB_PORT` — порт веба на хосте; `WEB_PASSWORD` — общий пароль HTTP Basic (логин любой, пусто — без пароля); `MAX_UPLOAD_MB` — лимит загрузки mp3.
- `OUTPUT_KIND` (`smb`|`local`), `OUTPUT_SMB_HOST`, `OUTPUT_SMB_SHARE`, `OUTPUT_SMB_PATH`, `OUTPUT_SMB_USER`, `OUTPUT_SMB_PASSWORD` — цель выкладки по умолчанию (веб может переопределить в БД).
- `LOCAL_OUTPUT_ROOT` — папка хоста, монтируемая как `/output`.
- `TRASH_DAYS`, `LOG_DAYS` — срок хранения корзины и логов/входов; `TZ` — часовой пояс контейнеров.
- `ULTRASINGER_GIT` — источник UltraSinger для сборки worker (git-URL `…#karaoke-local` или локальный путь).
- `DEFAULT_WHISPER_MODEL`, `DEFAULT_LANGUAGE`, `DEFAULT_COMPUTE_TYPE`, `DEFAULT_BATCH_SIZE`, `DEFAULT_ALIGN_MODEL_RU` — умолчания формы и аргументов UltraSinger.
- Задаёт compose/образ, не пользователь: `DATA_DIR`, `MODELS_DIR`, `HF_HOME`, `TORCH_HOME`, `XDG_CACHE_HOME`, `PYHYPHEN_DIR`, `ULTRASINGER_DIR`, `WEB_STATIC_DIR`.
- Подмена команд в тестах: `ULTRASINGER_CMD`, `DEMUCS_CMD`, `FFMPEG_CMD`; интеграция с живой шарой: `TEST_SMB_HOST`, `TEST_SMB_SHARE`, `TEST_SMB_USER`, `TEST_SMB_PASSWORD`, `TEST_SMB_PATH`.

## Тесты

- `tests/core/` — чистые функции и `LocalStorage` во временной папке; фикстуры `.txt` (CRLF, BOM, cp1251, дуэт) сравниваются байт в байт и помечены binary в `.gitattributes`.
- `tests/api/` — `create_app(data_dir=, env=, storage_factory=, ...)` через `TestClient`, env берётся из `.env.example`.
- `tests/worker/` — `run_forever(..., gpu_check=, until=)` с фейками из `tests/worker/fixtures/` через `*_CMD`; без torch и GPU.
- 2 skipped — `tests/core/test_storage_smb_integration.py` без `TEST_SMB_HOST/TEST_SMB_SHARE` (передавать `-e TEST_SMB_…` в `run`).
- `tests/core/test_repo_config.py` сканирует весь репозиторий (кроме `tests/`, `.autopilot/`, `.env`), включая этот файл, на `PASSWORD|SECRET|TOKEN` со значением после `=`/`:`.
- Настоящий GPU проверяется только `gpucheck` и реальной генерацией.

## Подводные камни

- У Docker Desktop активен Windows-движок — всегда `--context desktop-linux` (или `scripts/compose.ps1`); движок не переключать.
- Имена `pi`/`pi.local` в контейнерах не резолвятся — в `OUTPUT_SMB_HOST` только IP.
- Порт 8080 на хосте занят jenkins — `WEB_PORT=8090` (внутри контейнера веб слушает 8080).
- Linux-колёса torch cu126 собраны без sm_61: на Pascal исполняется sm_60 — это норма (`gpucheck.runnable_arch`); cu128 без Pascal вовсе, сборку валит `worker/build/check_torch_arch.py`.
- Зависимости UltraSinger фиксируются по его `uv.lock` (`worker/build/lock_constraints.py` → `/etc/uv-constraints.txt`), наши пины важнее (torch/torchaudio/torchvision cu126, `numpy<2.5`); без этого swift-f0 0.3.0 ломает сигнатуру SwiftF0 (ловит `selfcheck`).
- GTX 1080 не умеет float16 — compute type только `int8`.
- Тесты — только в Linux-контейнере: воркер использует POSIX-группы процессов; на Windows-хосте pytest не запускать.
- После изменения зависимостей (pyproject, Dockerfile) — `run --build`, иначе образ tests старый; исходники монтируются в `/app` editable.
- `.gitattributes` `* text=auto eol=lf`: Dockerfile/sh/py идут в Linux-контейнеры; фикстуры тестов — binary.
- Репозиторий `D:/Projects/UltraSinger` (ветка `karaoke-local`, remote `fork`) отсюда не редактировать; правки в нём делает пользователь, проверка — `gpucheck` (4 проверки selfcheck).
- Сборка worker падает на `RUN python -m karaoke_worker selfcheck`, если rebase форка потерял правку (флаги `--lyrics/--vad_onset/--vad_offset`, `lyrics_alignment`, `midi_creator`, SwiftF0).
- Тома переживают `compose down`; `compose down -v` удаляет БД и корзину.

## Как здесь работает Autopilot

Сборка ведётся навыком `/autopilot`. Требования, спецификация и таски — в `.autopilot/`.
Прогресс — `.autopilot/dashboard.html`. Правило: требование из `manifest.md`
может снять только пользователь.

Если работа продолжается — скажи «продолжи автопилот»: состояние поднимется
из `.autopilot/state.js`, переспрашивать ничего не нужно.
<!-- autopilot:end -->
