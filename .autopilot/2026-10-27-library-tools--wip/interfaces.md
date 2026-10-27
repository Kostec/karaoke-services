# Границы и правила проекта

Сначала прочитай `notes.md` (карта кода, точные имена). Этот файл — то, что решено, и оно главнее.

## Правила проекта (из CLAUDE.md, обязательны)

- Python 3.12, `from __future__ import annotations`, тексты, докстринги и комментарии — по-русски. Ошибки API — `raise ApiError(status, "текст", field=...)`, ошибки задания — `raise JobFailed(reason, user_message)`. Запись в БД — `with _tx(conn)`. Миграция — `_SCHEMA_V5` в `_MIGRATIONS`: скрипт режется по `;`, поэтому `;` внутри строк и комментариев нельзя.
- Пути тома data — только через `DataPaths`, имена файлов песен — только через `naming`, запись в хранилище — только через `Storage` хранилища песни (`ctx.storage(item.target_id)`). Исходящий HTTP — только через `ctx.http` (`karaoke_core.http.Http`); в тестах — `FakeHttp`, реальные сервисы не трогать.
- Фронт: раздел — `mount(section, ctx)`, `show(params)`, опц. `hide()`; чистая логика — в отдельных модулях без `document` ради `node --test`; DOM — `h()` из `ui.js`; все тексты по-русски.
- Тесты: pytest только в Linux-контейнере (`docker --context desktop-linux compose --profile test run --rm tests`), фронт — `node --test tests/frontend/`. Было 848 passed, 2 skipped и 205 pass — не уменьшаются.
- Не писать в коде вне `tests/` `password|token|secret` со значением после `=` или `:` (сканер `test_repo_config`): `b['token']`, позиционно, другое имя переменной.
- Новая переменная окружения — в `.env.example` с русским комментарием строкой выше.
- CLAUDE.md и `.autopilot/` обновляет оркестратор, не исполнитель.
- Новый тип задания: класс в `HANDLERS` (`needs_gpu = False`), этап в `progress.py`, подпись в `queue.js::TYPE_LABEL`, restart в `api_jobs.restart`, ветка в `PublishHandler` (если есть выкладка), `BUSY_TYPES` (если меняет файлы песни).

### Договорились с пользователем — не пересматривать (из прошлых сборок, дословно)

- Вкладки «Новая песня» в меню и кнопки «+ Новая песня» в «Очереди» нет — только плавающая «+», сразу в форму
- Свои теги — в базе сервиса по «исполнитель — название», файлы песни не меняются; палитра из 8 цветов, по умолчанию синий
- Дизайн экранов согласован с пользователем по макету `.autopilot/2026-10-26-songs-ui-ux/mockup.html` — крупные изменения вида снова согласовывать (новые экраны этой сборки — по макету `.autopilot/2026-10-27-library-tools--wip/mockup.html`, когда он согласован)

### Ответы этого брифинга

- Плейлисты не делаем. Микрофона нет; вместо него — «проиграть ноту» в редакторе.
- Сервис открывают с ПК, Pi, телефона — по http: всё, что требует secure context (уведомления браузера), — с пояснением и запасным Telegram.
- Зеркало само ничего не удаляет.

### Команды и общие файлы (для исполнителей)

- Проверка целиком: `docker --context desktop-linux compose --profile test run --rm tests` (pytest) **и** `node --test tests/frontend/`. Один файл: `docker --context desktop-linux compose --profile test run --rm tests pytest -q tests/api/test_tags.py`; `node --test tests/frontend/select-logic.test.mjs`. Docker — только с `--context desktop-linux`. Bash-инструмент — Git Bash, кириллицу в curl не слать.
- Новые зависимости не нужны (Web Audio, `ctx.http`, stdlib). Нужна — верни `BLOCKED`.
- **Общие файлы-реестры** пишут несколько тасков, поэтому в зоны не входят: `web/static/js/api.js` (методы `api`), `web/static/css/app.css`, `web/static/index.html` (секции разделов), `web/static/js/app.js` (`VIEWS`, одна строка подключения), `web/app/main.py` (подключение роутеров), `worker/karaoke_worker/handlers.py` (только строка в `HANDLERS`, `BUSY_TYPES`/ветка в `PublishHandler`), `worker/karaoke_worker/progress.py` (константы этапов), `web/static/js/queue.js::TYPE_LABEL`, `web/app/api_jobs.py::BUSY_TYPES`/`restart`. В них — **только дописывать свой блок инструментом Edit** (не переписывать файл целиком, не переставлять чужое), с комментарием-меткой своего раздела. Всё остальное своё — в новых модулях (`worker/karaoke_worker/<тип>.py`, `web/app/api_<что>.py`, `web/static/js/<что>.js`).
- Новые роутеры с путями под `/api/jobs/...` подключаются в `main.py` **до** `jobs_router` (как `import_router`).

## Границы, решённые в спецификации

### core: схема V5 — `core/karaoke_core/db.py`
- `library.match_key TEXT` = `naming.song_tag_key(artist, title)`; `CREATE INDEX library_match_key ON library(match_key)`; бэкфилл `UPDATE library SET match_key = karaoke_match_key(artist, title)` (SQL-функция регистрируется в `connect()` рядом с `karaoke_song_id`). `Library._insert` пишет колонку, `LibraryItem.from_row` её выбрасывает (как `song_id`).
- `Library.copies(artist, title) -> list[LibraryItem]` — `SELECT * FROM library WHERE match_key=?` (поведение прежнее). Новый `Library.by_key(key: str) -> list[LibraryItem]` — то же по готовому ключу.
- `jobs.position INTEGER` (NULL у старых — порядок `COALESCE(position, id)`), `jobs.start_at TEXT` (ISO UTC как `db.now()`, NULL — сразу). `Job` получает поля `position: int | None = None`, `start_at: str | None = None`; оба в `_JOB_UPDATABLE`.
- `Jobs.claim_next(types=None)`: дополнительно `AND (start_at IS NULL OR start_at <= :now)`, порядок `ORDER BY COALESCE(position, id), id`.
- `Jobs.move(id, where: "up"|"down"|"first") -> list[Job]` — только среди `queued`; не `queued` → `ValueError("Переставлять можно только ожидающие задания")`. Новое задание получает `position = id` при вставке.
- `Jobs.schedule(id, start_at: str | None) -> Job` — только `queued`; `start_at` в прошлом → `ValueError("Время уже прошло")`. `Jobs.schedule_all(start_at) -> int` — все `queued` без `start_at`.
- `restart` создаёт задание без `start_at` (новое `position = id`).

### core: теги — `Tags.create/update`
- `create(name, color)`: `color` `None` недопустим на уровне `Tags` → `TagError("Неизвестный цвет","color")` (как сейчас для `""`). Нарушение `UNIQUE(name_key)` (`sqlite3.IntegrityError`) и в `create`, и в `update` → `TagError("Такой тег уже есть","name")`.
- Новое для массовых тегов: `Tags.change_for_songs(keys: list[str], add: list[str], remove: list[str]) -> int` — одна транзакция, неизвестный id → `KeyError`; возвращает число изменённых ключей.
- `api_tags.create_tag`: поле не прислано (`color` отсутствует в теле) → `DEFAULT_TAG_COLOR`; прислано `""`/`null`/чужое → 400 «Неизвестный цвет» `field=color`. Отличать по `body.model_fields_set`.

### core: имена — `naming.py`
- `SUFFIX_BACKGROUND` нет — `background_suffix(ext) -> " [BG].<ext>"` (jpeg → jpg), как `cover_suffix`.
- `rough_key(artist, title) -> str` — грубый ключ дублей: `match_key` → без всех не-букв/цифр, латинские двойники кириллицы (`a e o p c x y k m t h b` и заглавные) → кириллица, если в строке есть кириллица. Используется только проверкой библиотеки.

### core: кодировка — `ultrastar.py`
- `encoding_problem(data: bytes) -> EncodingFix | None`; `@dataclass EncodingFix(kind: "latin1"|"replacement"|"mojibake", fixed_text: str, preview_before: str, preview_after: str)`. `mojibake` — текст, прочитанный как cp1251, перекодируется `encode('cp1251').decode('utf-8')` без ошибок и становится «правдоподобнее» (больше кириллицы, нет `Р°/С‚`-пар); `latin1` — пробуются `koi8-r`, `cp866`, выбирается кандидат с наибольшей долей кириллицы; не нашёлся правдоподобный — `fixed_text = ""` (кнопка тогда погашена: «Не удалось угадать кодировку»).

### core: выравнивание — `linealign.py`
- `LineAlign` получает `unmatched_lines: list[int]` — номера строк текста (0…), для которых пары в нотах не нашлось; `unmatched == len(unmatched_lines)`. `POST /api/songs/{id}/notes/lines` отдаёт его как есть.

### core: отчёт проверки — `DataPaths`
- `DataPaths.libcheck_report() -> Path` = `data/reports/libcheck.json`. Формат: `{started_at, finished_at, job_id, target_ids, skipped:[{target_id, name, error}], findings:[{id, kind, target_id, song_id, artist, title, detail, fix: {action, ...}}]}`; `kind ∈ no_audio|no_cover|video_missing|encoding|duplicate|diverged`; `id` — стабильный (`sha1(kind + song_id [+ other])[:12]`).
- `fix.action` ∈ `copy_from` `{from_target, from_song_id}` | `audio_from_video` | `trash` | `cover_search` | `video_remove` | `encoding` | `keep_this` `{trash_song_id}` | `make_like` `{from_target, from_song_id}`. Несколько вариантов — `fixes: [...]` (первый — основной).

### worker: новые задания — `worker/karaoke_worker/handlers.py`
- `artwork` (`ArtworkHandler`, `needs_gpu=False`): params `{rel_dir, txt_name, target_id, kind: "cover"|"background", remove?: bool, inputs: {dir, image?}}`; ref `{artist, title, song_id}`. Выкладка `publish_artwork(ctx, job, src)`: файл `naming.song_file(...)` + `cover_suffix`/`background_suffix`, `set_header_line(txt, "COVER"|"BACKGROUND", name)` (remove — строку снять), старая версия `.txt` в корзину, старый файл с другим именем удалить, `_index`. Этап «Обложка»/«Фон» в `progress.py`. Ветка в `PublishHandler`. В `BUSY_TYPES`.
- `audio` (`AudioHandler`, `needs_gpu=False`): params `{rel_dir, txt_name, target_id, url}`; качает `download_youtube` → `to_mp3` → `<A - T>.mp3`, ставит `#AUDIO` и `#MP3` (у кого они есть; нет ни одной — `#MP3`), выкладка как `publish_instrumental`. Restart не качает заново (`in/input.mp3`).
- `libcheck` (`LibCheckHandler`, `needs_gpu=False`): params `{target_ids: [..] | null (все)}`; пишет отчёт атомарно (временный файл + `os.replace`), прогресс в `percent`/`stage` («Проверка «X»»). Одна активная проверка — второй `POST` → 409 «Проверка уже идёт».
- `mirror` (`MirrorHandler`, `needs_gpu=False`): params `{mirror_id}`; пересканирует оба хранилища общим кодом сканирования (если он в `web/app/context.py` — вынести в `core/karaoke_core/scan.py::scan_target(storage, library, target_id) -> list[LibraryItem]` без смены поведения, `AppContext.rescan` зовёт его), ставит `copy` через `Jobs.enqueue_copy`, итог пишет в `Settings.set_mirror_result(id, {...})`. Цель недоступна на сканировании — `wait_retry`.
- Планировщик зеркал — в `runner` (цикл `_loop`): раз в минуту проверяет `Settings.get_mirrors()`; для включённого зеркала без активного `mirror` и с `last_run_at` старше `MIRROR_EVERY_S = 1800` ставит задание.
- Уведомления — `worker/karaoke_worker/notify.py`: `notify_job(ctx, job) -> None` (никогда не бросает; сбой — строка в лог задания без токена), `notify_queue_empty(ctx, counts)`. Зовутся из `runner.run_job` после конечного состояния; «очередь опустела» — когда после задания нет `queued/running` (кроме `copy` с `wait`, ждущих хранилище), не чаще раза в 10 мин. Типы для «готово»: `generate, import, instrumental, video, artwork, audio, rename`; «сбой» — все.

### core: настройки — `Settings`
- `get_telegram() -> TelegramSettings(bot_token, chat_id, on_done, on_failed, on_queue_empty)` / `set_telegram(...)`; `.public()` → `{has_token, chat_id, on_done, on_failed, on_queue_empty}`. Ключ `telegram`.
- `get_mirrors() -> list[Mirror]`, `save_mirror(Mirror) -> Mirror`, `delete_mirror(id)`, `set_mirror_result(id, result)`; `Mirror(id, from_target, to_target, enabled, last_run_at, last_result)`, `last_result = {added, updated, only_in_target: [{song_id, artist, title, rel_dir}], error?}`. Ключ `mirrors`. Удаление хранилища (`delete_target`) выключает его зеркала.
- `core/karaoke_core/telegram.py`: `send_message(http, token_value, chat_id, text) -> None` (raise `TelegramError` с русским текстом без токена), `find_chat(http, token_value) -> str | None` (последний `chat.id` из `getUpdates`). Позиционные аргументы — ради сканера.

### web: API
- `POST /api/jobs/artwork` (multipart: `song_id`, `kind`, `image(File)? | url? | remove?` — ровно один) → 201 Job; ошибки 400 `field=image|url|kind`, 404, 409 дубль.
- `GET /api/covers/search?artist=&title=` → `{items:[{source:"itunes"|"deezer"|"musicbrainz", url, thumb, album, artist, title, width?, height?}]}`; 400 `field=title` при пустых обоих полях; 503, когда все три упали. Модуль `web/app/covers.py` (`CoverHit`, `search_covers(http, artist, title) -> list[CoverHit]`).
- `POST /api/songs/tags {song_ids, add, remove}` → `{updated: N, errors:[{song_id, detail}]}`.
- `POST /api/songs/zip` (form `song_ids` через запятую) → потоковый zip `Песни (N).zip`; песня недоступна — файл `НЕ ВОШЛО.txt` в архиве со списком причин; `GET /api/songs/zip?check=1&song_ids=` не нужен.
- `POST /api/songs/delete {song_ids}` → `{removed:[song_id], errors:[{song_id, detail}]}`.
- `POST /api/jobs/instrumental/bulk {song_ids, replace=false}` → `{queued:[job_id], skipped:[{song_id, reason}], errors:[{song_id, detail}]}`. Маршрут объявлен до `/{id}`.
- `MAX_BULK_SONGS = 1000`, `MAX_ZIP_SONGS = 500` в `web/app/params.py`.
- `POST /api/songs/{id}/encoding` → карточка песни; нет проблемы → 409 «Кодировка в порядке»; не угадать → 409 «Не удалось угадать кодировку».
- `POST /api/jobs/audio {song_id}` → 201; нет YouTube-ссылки в `#VIDEO` → 409 «В песне нет ссылки на видео YouTube».
- `POST /api/library/check {target_ids?}` → 201 Job; `GET /api/library/check` → отчёт или `{findings: null}` до первой проверки, плюс `job` (активное задание, если идёт). Модуль `web/app/api_library.py`.
- `GET /api/targets/{id}/status` → `{ok, error, label}` (кэш `output_status`, `fresh=0|1`).
- Зеркала: `GET /api/mirrors` → `{mirrors:[...+ from_name, to_name, job?]}`, `POST /api/mirrors`, `PUT /api/mirrors/{id}`, `DELETE /api/mirrors/{id}`, `POST /api/mirrors/{id}/run` → 201 Job (активное — 409). Модуль `web/app/api_mirrors.py`.
- Очередь: `POST /api/jobs/{id}/move {where}` → `{jobs:[...queued]}`; `POST /api/jobs/{id}/schedule {start_at: ISO | null}` → Job; `POST /api/jobs/schedule {start_at}` → `{count}`. `GET /api/jobs` отдаёт `position`, `start_at`. Маршруты без `{id}` — до `/{id}`.
- Telegram: `GET/PUT /api/settings/telegram` (`{bot_token?, chat_id, on_done, on_failed, on_queue_empty}`; пустой `bot_token` — прежний), `POST /api/settings/telegram/test` → `{ok}` / 400, `POST /api/settings/telegram/find-chat` → `{chat_id}` / 404 «Напишите боту любое сообщение и повторите».
- Резервная копия: `GET /api/settings/backup` → JSON-файл (`Content-Disposition: attachment; filename="karaoke-settings-YYYY-MM-DD.json"`); `POST /api/settings/backup?apply=0|1` (multipart `file`) → `{tags_added, tag_links_added, targets_added, targets_updated, mirrors_added, usdb_user_set, needs_password:[name], needs_google:[name]}`; формат: `{format:"karaoke-services-settings", version:1, created_at, default_target_id, targets:[{id,name,kind,path,host,share,user,url,preset,client_id}], tags:[{name,color,songs:[song_key]}], usdb:{user}, telegram:{chat_id,on_done,on_failed,on_queue_empty}, mirrors:[{from_target,to_target,enabled}]}`. Модуль `web/app/api_backup.py`, чистая сборка/разбор — `core/karaoke_core/backup.py` (`export_settings(settings, tags) -> dict`, `plan_import(data, settings, tags) -> ImportPlan`, `apply_import(plan, settings, tags)`).

### фронт: модули и контракт
- `player.js`: + `releasePlayers(scope?: Element)` — pause, `removeAttribute('src')`, `load()`, убрать из реестра (только внутри `scope`, без него — все).
- `song-page.js`: блоки `hero, media, lyrics, info, store` — у каждого `sig(details)` и `build(details)`; `update(details)` пересобирает только блоки со сменившейся подписью; `releasePlayers(old)` перед заменой «Медиа»; `hide()` → `releasePlayers()`. Опрос `api.targetStatus(target_id)` раз в 15 с, пока раздел видим; `env.outputOk` берётся из последнего статуса; баннер `.banner.warn` «Хранилище «X» недоступно — действия с файлами отключены». Чистая часть — `song-page-logic.js::blockSigs(details) -> {hero, media, lyrics, info, store}`.
- `tone.js` (DOM/Web Audio): `pitchHz(pitch) -> number` (чистая, экспортируется и тестируется), `playTone(pitch, ms, {gain}={}) -> stop()`, `toneSequence(notes:[{pitch, startMs, ms}], fromMs) -> {stop()}`; `AudioContext` создаётся лениво в жесте пользователя.
- `editors/notes-checks.js` (чистый): `SHORT_MS = 60`, `LONG_MS = 5000`, `JUMP = 12`; `suspects(state, {unmatchedLines?: number[]}) -> Map<noteId, string[]>` (причины по-русски); плагин `editors/notes-checks-plugin.js` (подсветка `.ne-note.suspect`, счётчик, `!`, `P`/«♪»), подключён в `editors/index.js`.
- `select-logic.js` (чистый): `createSelection()` → `{has, toggle, setAll(ids), clear, ids(), size, hiddenCount(shownIds)}`; `bulkSummary(result) -> {text, lines}` («Готово: N. Пропущено: M» + причины).
- `songs.js`: режим выбора (кнопка «Выбрать» в шапке раздела), чекбокс на карточке, нижняя панель `.bulk-bar` с действиями; диалоги — в `song-actions.js` (`openBulkTagsDialog(songs, env)`, `bulkDelete`, `bulkInstrumental`, `bulkZip`).
- `artwork.js` (DOM): `openCoverDialog(song, env)`, `openBackgroundDialog(song, env)`, `openCoverPicker({artist, title}) -> Promise<CoverHit|null>` (его же зовёт форма «Новая песня»); чистая часть — `artwork-logic.js` (`imageError(file, maxMb)`, `hitLabel(hit)`).
- `check.js` — раздел `check` (`#check`), чистая часть `check-logic.js` (`groupFindings(report)`, `KIND_LABELS`, `fixButtons(finding, targets) -> [{label, action}]`). Ссылка — пункт «Проверить библиотеку» в меню раздела «Песни»; в навигации подсвечиваются «Песни».
- `play.js` — раздел `play` (`#play?id=`), чистая часть `play-logic.js` (`timeline(notesPayload) -> {lines:[{player, startMs, endMs, syllables:[{text, startMs, endMs, pitch, type}]}], pitchRange}`, `frameAt(timeline, ms) -> {current, next, syllable, progress}`); кнопка «▶ Прогон» на странице песни и пункт в «…».
- `queue.js`: на карточке `queued` — «↑», «↓», «Первым», «Отложить…» (диалог: «Сегодня ночью (01:00)», время, «Все ожидающие»), «Запустить сейчас» у отложенного; чистая часть `queue-logic.js` (`nightStart(now) -> Date` — ближайшие 01:00, `scheduleLabel(job, now)`).
- `settings.js`: карточки «Уведомления» (Telegram + браузер), «Зеркала», «Резервная копия»; чистые части — `notify-logic.js` (`browserNotifyState(win) -> {ok, reason}`, `jobNotice(prev, job) -> {title, body} | null`), `mirror-logic.js` (`mirrorError(from, to, mirrors)`), `backup-logic.js` (`planSummary(plan) -> string[]`).
- `app.js`: браузерные уведомления — по смене состояния заданий в уже идущем опросе статуса (раз в 15 с `api.jobs(50)`), только если разрешено и вкладка не в фокусе.
- `new-song.js` + `import.js`: при ссылке на альбом/плейлист — кнопка «Открыть в Импорте»: `sessionStorage['import.url']` → `#import`; `import.js::show()` забирает значение, удаляет ключ, открывает вкладку «Ссылка» и зовёт `inspectLink(url)`.
- `api.js` — по методу на каждый новый эндпоинт: `artwork(songId, form)`, `coverSearch(artist, title)`, `bulkTags`, `bulkDelete`, `bulkInstrumental`, `zipForm(ids)`, `fixEncoding(id)`, `audioFromVideo(id)`, `libraryCheck(ids)`, `libraryReport()`, `targetStatus(id)`, `mirrors/saveMirror/deleteMirror/runMirror`, `moveJob(id, where)`, `scheduleJob(id, at)`, `scheduleAll(at)`, `telegram/saveTelegram/testTelegram/findTelegramChat`, `backupUrl()`, `restoreBackup(file, apply)`.

## Тестовые швы
- `tests/core/test_db.py` — миграция V4 → V5 (бэкфилл `match_key`, `position`), `claim_next` со `start_at` и `position`, `move/schedule`.
- `tests/core/test_tags.py` — `None`-цвет, гонка двух соединений, `change_for_songs`.
- `tests/core/test_ultrastar.py` (или новый `test_encoding.py`) — `encoding_problem` на фикстурах (mojibake, koi8-r, норма); `tests/core/test_linealign.py` — `unmatched_lines`; `tests/core/test_backup.py`; `tests/core/test_naming.py` — `rough_key`, `background_suffix`; `tests/core/test_telegram.py` с `FakeHttp`.
- `tests/api/` — `test_tags.py` (пустой цвет, массовые теги), `test_artwork.py`, `test_covers.py` (FakeHttp-маршруты трёх сервисов), `test_bulk.py`, `test_library_check.py`, `test_mirrors.py`, `test_queue_order.py`, `test_settings_telegram.py`, `test_backup.py`, `test_encoding_fix.py`.
- `tests/worker/` — `test_runner_artwork.py`, `test_runner_audio.py`, `test_runner_libcheck.py`, `test_runner_mirror.py`, `test_runner_notify.py`, порядок/время в `test_runner_queue.py`.
- `tests/frontend/` — `song-page-logic` (`blockSigs`), `tone` (`pitchHz`), `notes-checks`, `select-logic`, `artwork-logic`, `check-logic`, `play-logic`, `queue-logic`, `notify-logic`, `mirror-logic`, `backup-logic`.
- Экраны — вручную в браузере (при приёмке): страница песни с играющим плеером, баннер, режим выбора, «Проверка», «Прогон», очередь, настройки.

## Что построили таски
