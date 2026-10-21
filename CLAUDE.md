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
- Python-тесты (pytest в Linux-контейнере): `docker --context desktop-linux compose --profile test run --rm tests` → 679 passed, 2 skipped (после смены зависимостей — `run --build`).
- Подмножество: `docker --context desktop-linux compose --profile test run --rm tests pytest -q tests/worker/test_runner_queue.py`.
- Фронт-тесты (Node 24, встроенный node:test): `node --test tests/frontend/` → 162 pass.
- Бэкап патча UltraSinger в `patches/karaoke-local.patch`: `./scripts/export-ultrasinger-patch.ps1` (читает `D:/Projects/UltraSinger`).
- CLI воркера внутри образа: `python -m karaoke_worker gpucheck|selfcheck|run`; entrypoint пропускает эти слова в CLI, прочее (`bash`, `python`) исполняет как есть.

## Структура

```
core/karaoke_core/        общий пакет web+worker: db, paths, naming, ultrastar, postprocess, trash, http, songpack
core/karaoke_core/storage/  Storage: base (интерфейс, SongEntry), local, smb (smbprotocol)
core/Dockerfile.test      образ сервиса tests (editable core+web, pytest по tests/)
web/app/                  FastAPI: main (create_app, Basic-auth, очистка корзины), api_jobs/songs/settings/import/lyrics/usdb, context, params, notes, lyrics (LRCLIB), usdb (клиент)
web/static/js/            SPA по хэшу (#queue #new #import #songs #trash #settings), api.js, ui.js, id3.js, import.js, import-logic.js, folder-logic.js, lyrics-search.js, lyrics-dialog.js, video-block.js (блок «Видео»), songs.js (карточка, диалог «Видео…»)
web/static/js/editors/    редакторы песни: lyrics (перегенерация с новым текстом), notes-* («Редактор нот»: таймлайн, звук, волна, панель текста), shell (общее окно)
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
- `core/karaoke_core/paths.py` — `DataPaths`: единственное место раскладки тома data; имена входов `INPUT_*`, в т.ч. `INPUT_VIDEO_STEM = "video"` (`in/video.<ext>`; `handlers.INPUT_VIDEO_STEM` — реэкспорт).
- `core/karaoke_core/naming.py` — `safe_name`, `song_dir`, `base_name`, `song_file`, `SUFFIX_*`, `VIDEO_EXTS` (`.mp4 .m4v .mkv .webm .avi .mov .mpg .mpeg`), `VIDEO_EXT_ORDER`, `video_file_name(value)` → имя видеофайла из `#VIDEO` или None (единое правило для `Storage` и воркера), `video_suffix(ext)` → `.<ext>` в нижнем регистре; все имена файлов песен — только отсюда.
- `core/karaoke_core/ultrastar.py` — разбор/запись `.txt` с сохранением кодировки, BOM и переводов строк; `decode`, `set_header_line`, `fix_zero_length`; дуэт: `Song.is_duet`, `Song.tracks()` → `{1: [lines], 2: [lines]}` (строка без метки `P` — певец 1, у соло только ключ 1), `singer_names(song)` → `(p1, p2)` из `#P1/#P2`, иначе `#DUETSINGERP1/2`; `set_singer_names(song, p1, p2)` пишет `#P1/#P2`, `#DUETSINGERP*` — только если уже были, пустое имя удаляет оба.
- `core/karaoke_core/postprocess.py` — `finalize()`: выход UltraSinger → готовая папка (имена, обложка, `#VERSION:1.2.0`, `#AUDIO`, отброс MusicBrainz при чужом исполнителе); kwargs `video_path=None, videogap=None` → `<A - T>.<ext>` + `#VIDEO`/`#VIDEOGAP`; `format_videogap(value)` — до 3 знаков, без «.0», 0/пусто → None.
- `core/karaoke_core/storage/base.py` — `Storage` (`upload_dir`: медиа сначала, `.txt` последним, через `.part`), `read_song`, `is_song_txt_name`, `StorageError`/`StorageNotFound` с русским текстом без пароля.
- `core/karaoke_core/http.py` — `Http` (единственный исходящий HTTP: `request`, `download` потоком с `max_bytes`, `session()` со своей cookie-банкой), `HttpResponse`, `HttpError(message, status)` (статус ≥400; `None` — сеть/таймаут).
- `core/karaoke_core/songpack.py` — `safe_extract` (zip без `..`/абсолютных путей, симлинки пропускает, лимит распаковки; при сбое папку чистит вызывающий), `find_songs` → `FoundSong` (+`video_links`, `video_file` — видеофайл пакета по `#VIDEO`, `videogap` — `v-gap=` usdb, иначе `#VIDEOGAP`), `youtube_links(#VIDEO)`, `video_links(#VIDEO)` (`v=` usdb или URL целиком; `a=` — только звук, не видео), `PackError`, `AUDIO_EXTS/IMAGE_EXTS/VIDEO_EXTS`, `ALLOWED_EXTS` (с видео).
- `core/karaoke_core/linealign.py` — `align_line_starts(note_texts, lyrics, existing_starts=())` → `LineAlign(starts, unmatched, total)`: границы строк по исходному тексту (слова нот — по правилу `wordStart` фронта, сравнение без регистра/ё/пунктуации, опечатки ≥0,75; где строка текста не нашлась — прежние границы), `line_starts(song)`, `align_song(song, lyrics)`; запись — `ultrastar.set_line_starts(song, starts)` (соло; стоявший разрыв байт-в-байт, новый `- <конец предыдущей ноты>`). Воркер generate выравнивает после UltraSinger (`handlers.align_lines`), если текст есть и LRC не применялся — строка лога «Строки выровнены по тексту: X из Y»; `POST /api/songs/{id}/notes/lines` `{texts, starts?}` → `{starts, unmatched, total}` по `source/lyrics.txt` (409 — нет текста) — кнопка «Строки как в тексте» в `notes-tools.js` (`M.lineStartsRequest`, `M.setLineStarts`).
- `core/karaoke_core/trash.py` — `Trash`: перенос в корзину, версии `.txt`, restore (только в ту же цель), purge по `TRASH_DAYS`.
- `web/app/api_jobs.py` — общие помощники приёма файлов (`Staging`, `queue_duplicate`, `is_mp3`, `cover_ext_of`, `copy_limited`; их же зовёт `api_import`); generate (multipart, staging → `jobs/<id>/in/`), instrumental, `POST /video`, cancel/restart/republish, лог `?from=|tail=` и SSE; проверки видео — только `video_link`, `video_ext_of`, `parse_video_height`, `parse_videogap`, `video_choice(mode, url, file, height, gap, *, source_url, pack, default_gap)` → `(params.video|None, ext)`, `stage_video_file` (их же зовёт `api_import`), `VIDEO_MODES`.
- `web/app/api_import.py` — `POST /api/import/inspect` (usdb | `files[]` | url: zip или GitHub → codeload-архив), `POST /api/jobs/import`, staging `imports/<token>/`, `purge_imports`, `max_import_mb`.
- `core/karaoke_core/musiclink.py` — ссылки на музыку: `classify` (Яндекс трек/альбом/плейлист или yt-dlp; аудио VK и адреса домашней сети — отказ; у YouTube снимается `list=`), `ytdlp_info` (`-4 -J --flat-playlist`), `YandexMusic` (токен аккаунта, `info`/`download`/`check`), `MusicLinkError`, CLI `python -m karaoke_core.musiclink download <url> <dest>` (токен — в env `YANDEX_MUSIC_TOKEN`); токен — `Settings.get_yandex/set_yandex`.
- `web/app/api_link.py` — `POST /api/link/inspect` → треки `{url, artist, title, duration, thumbnail, existing_song_id, video}` (`video` — ссылка годится для видео, `api_jobs.is_video_link`); generate принимает `audio_url` (вместо файла) и `cover_url` (обложку качает web, `api_jobs.download_cover`); worker качает звук в `handlers.download_link` (yt-dlp или `MUSICLINK_CMD`); `/api/settings/yandex` — `has_token`.
- `web/app/lyrics.py` — `LrclibProvider`, `LyricsHit(..., synced)`, `strip_lrc`, `synced_lrc`; `web/app/usdb.py` — `UsdbClient` (вход, поиск, `fetch_song`), `UsdbAuthError/UsdbUnavailable/UsdbNotFound`, HTML-разборщики; `web/app/api_usdb.py` — `usdb_api_error`.
- `web/app/params.py` — модели, языки, лимиты (`MAX_COVER_MB`, `MAX_LYRICS_MB`, `MAX_FOLDER_AUDIO_MB`, `max_video_mb(ctx)`), `VIDEO_HEIGHTS` `[360, 480, 720, 1080, 0]` (0 — лучшее), `DEFAULT_VIDEO_HEIGHT` 720, `/api/defaults` (+`max_video_mb`, `video_heights`, `default_video_height`).
- `web/app/context.py` — `AppContext` (`.http`, `.usdb()` — кэш клиента сохранённой учётки, `reset_usdb()`), `ApiError`, `match_key` (ключ дубля песни).
- `worker/karaoke_worker/handlers.py` — `HANDLERS` generate/instrumental/import/publish/video, `ytdlp_failure(e, what, *, reason, texts, gone_reason)` — единый разбор сбоя yt-dlp для звука и видео, `ultrasinger_args(..., lyrics_timing=)`, `publish_song` (замена с откатом из корзины), `download_youtube`, `to_mp3`; LRC: `parse_lrc`, `lyrics_lines`, `lrc_matches`, `LRC_NOT_USED`; видео: `download_video(ctx, job_id, url, dest_dir, height)` → `dest_dir/video.mp4` (yt-dlp `-f bv* -S res:H,vcodec:h264,ext:mp4 --remux-video mp4` во временную `.video-download`; Яндекс → `VIDEO_YANDEX`), `chosen_video(ctx, job, in_dir)` → kwargs `finalize` (сбой — строка `VIDEO_SKIPPED`, песня без видео), `publish_video`, `_carry_video` (перенос видео заменяемой песни в `publish_song`).
- `worker/karaoke_worker/base.py` — `JobContext`, `run_command` (группа процессов, отмена, убийство зависших), `explain_failure`, `JobFailed(reason, user_message)`.
- `worker/karaoke_worker/progress.py` — `STAGES`: маркер строки лога UltraSinger → русский этап и процент; `STAGE_DOWNLOAD`, `STAGE_VIDEO_DOWNLOAD` («Загрузка видео», 5), `IMPORT_PREPARE`, `DownloadTracker(start, end, stage=)` (`[download] NN%` yt-dlp).
- `worker/karaoke_worker/selfcheck.py` — 7 проверок образа; `REQUIRED_FLAGS` форка (`lyrics`, `vad_onset`, `vad_offset`, `lyrics_timing`), `check_yt_dlp`, `check_deno`.
- `web/static/js/api.js` — `api`, `ApiError`, `generateForm()` (единственная сборка multipart generate, с `lyrics_lrc`), `inspectForm()`/`importForm()` (generate и import — с полями блока «Видео» `video_mode, video_url, video_file, video_height, videogap`), `api.video(songId, FormData | поля | {remove:true})`, `videoForm`, `PARAM_KEYS`, `canRepublish`.
- `web/static/js/video-block.js` — блок «Видео» (диалог «Видео…» в `songs.js`, `new-song.js`, `import.js`): чистые `VIDEO_MODES`, `MODE_LABELS`, `videoFields(state{mode,url,file,height,gap})` → поля multipart, `videoError`, `videoChoices({source, pack})` → `{modes, mode}`, `VIDEO_EXTS` (запасной список; настоящий — `/api/defaults::video_exts`), `videoAccept(exts)`, `fileHint(exts, maxMb)`, `normGap`, `rememberedHeight/rememberHeight` (`localStorage` `video.height`); разметка `createVideoBlock({modes, mode, sourceUrl, exts, heights, defaultHeight, gap, maxMb, onChange})` → `{el, state(), fields(), setModes, setSource, setGap, reset, validate, showError, showApiError(e) → bool, clearErrors}`.
- `web/static/js/folder-logic.js` (`splitFolder`, `trackMeta`, `nextLyricsRow`, `trackFields`) — вкладка «Импорт → Папка»: готовые .txt-песни → inspect `source=files` с относительными путями (`webkitRelativePath`), прочие mp3 → `generate` по одному с авто-поиском текста; `web/static/js/lyrics-dialog.js` — общий диалог поиска текста (форма новой песни и папка).
- `web/static/js/import-logic.js` (`pickAudioSource`, `importWarnings`, `importOutcome`) и `web/static/js/lyrics-search.js` (`stripLrc`, `usableHits`, `lrcPlainText`, `lrcTimingDefault`) — чистая логика под node-тесты.
- `web/static/js/extensions.js` — `registerSongEditor(id, {label, open, enabled})`; редакторы подключаются одной строкой в `web/static/js/app.js` (`import './editors/index.js'`).
- `web/app/notes.py` — `notes_payload` (GET), `apply_notes(song, NotesIn)` (PUT: сопоставление по `id`, неизменённое — байт в байт, строки тела удалённых нот переходят к следующей уцелевшей), `read_only_reason` (`MANY_SINGERS_REASON` — метки `P3`+, `RELATIVE_REASON`, `NO_BPM_REASON`), `_fmt_gap` (до 3 знаков, без «.0»); дуэт: проверки по партиям (`_validate(player, …)`), `_break_before_p2`, метки `P1/P2` переиспользуются.
- `web/static/js/editors/notes-model.js` — чистая модель «Редактора нот»: State `{editable, reason, bpm, gap, headers, notes, nextId, created, duet, singers: {p1, p2}, p1Break}` (`p1Break` — `break_beat` последней строки P1 из GET, «- N» перед `P2`; `toPayload` отдаёт max(p1Break, конец её нот)), нота `{id, src, type, start, length, pitch, text, ls, brk, voice: 1|2|'both', src2, brk2}` (`id` — ключ в редакторе, `src` — `id` из GET, у новых null; у «оба» `src2`/`brk2` — копия в партии P2); `fromPayload/toPayload`, операции (move, resize, addNote, splitNote, joinNext, setLineText, shiftTextBy(state, id, k, scope 'word'|'line'|'song') — сдвиг текста по нотам без потери слогов, shiftText = её частный случай, retime…) неизменяемы, ошибка — `throw Error` по-русски; `validate`, `isDirty`, `history()`, `beatToMs/msToBeat`; дуэт: `fromPayload` склеивает одинаковые строки P1/P2 в «оба», `toPayload` у дуэта → `{gap, singers, lines:[{break_beat, player, notes}]}` (блок P1, потом P2, копии «оба» с `id: src2`), `setVoice(state, ids, voice)`, `makeDuet`, `makeSolo`, `setSingers`, `voiceNotes(state, v)` (партия v вместе с «оба»), `voiceLines`, `inVoice`, `VOICE_LABELS` (подписи певцов, на экран — через `ctx.voiceLabel`), `parts(state)`, `partOf(note)`, `partNotes(state, id)`, `allVoice(state, ids, v)`, `mergeLineAt(state, id, voice)` (партия полосы; «оба» склеивается, только если соседние в обеих партиях), `NOT_DUET_ERROR/VOICE_ERROR/OTHER_VOICE_ERROR`; `addNote(…, voice = 1)`; прежние операции — в пределах партии; `lines(state)` у дуэта — строки обеих партий, «оба» один раз.
- `web/static/js/editors/syllables.js` — `toSyllables(text)`: слог на гласную, `й ь ъ` остаются с предыдущим, `|` — принудительная граница, пробел перед словом — в начале первого слога.
- `web/static/js/editors/notes-editor.js` — `openNotesEditor(song, {reload})` (DOM, мышь, `<audio>`, сохранение `api.saveNotes`); `addNotesEditorPlugin(fn)` — `fn(ctx)` на каждом открытии (`ctx.els.slot*`/`panel`, `apply(fn, okText, {amend})`, `select`, `play`, `addKey`, `onRender/onSelect/onTick`, `partNotes(id)` — ноты партии этой ноты (у соло — все), `singerLabel(v)` → «Певец 2 (имя)»); плагины регистрируются в `editors/index.js`; дуэт на экране: CSS `--ne-p2`/`--ne-both`, классы `.p1/.p2/.both` у `.ne-note/.ne-chip/.ne-brk`, `.ne-lane.duet`; новая нота (двойной клик / N) получает певца выбранной, без выделения — певца 1; `editors/lyrics-editor.js` перед перегенерацией дуэта спрашивает `DUET_REGEN_WARNING`.
- `web/static/js/editors/notes-text-panel.js` (`textPanelPlugin`: панель «Текст», `localStorage` `notesEditor.textPanelClosed`) и `notes-tools.js` (`toolsPlugin`: ⇠/⇢ текст с областью слово/строка/песня (`localStorage` `notesEditor.shiftScope`) и перетаскиванием слога по дорожке, `Alt+←/→` всегда гасятся — иначе браузер уходит «Назад», Разрезать, Слить, ↵ Строка, отстукивание `T`/`J`, справка `?`); их чистая логика — `notes-panel-logic.js` (`lineAt(lines, beat, voice?)`, `lineStatus`, `plural`, `tapTiming`, `tapQueue` — до конца партии, `liveNotes(state, beat)`, `liveLines(state, lines, beat)`, `panelRows(state, lines)` — группы панели и номера строк внутри партии, как в `validate`).
- `web/static/js/editors/timeline-math.js` (координаты, масштаб `ZOOM_MIN..MAX`, `peaks`, `rebaseBeat`) и `waveform.js` (`loadPeaks` — fetch `/audio` → `decodeAudioData`, пики по 10 мс, лимит `WAVE_MAX_BYTES` 60 МБ; `drawWave` — только видимая часть).

## Архитектура

- web ↔ worker общаются только через SQLite `/data/karaoke.sqlite` (WAL, явные `BEGIN IMMEDIATE`) и файлы тома `data`; HTTP между ними нет.
- web: ставит задания (`Jobs.enqueue_with`), читает статус GPU из `settings[gpu_status]` (нет записи → `gpu.ok=null`), отдаёт лог из `/data/logs/<id>.log`, раз в 6 ч чистит корзину.
- worker: при старте `Settings.set_gpu_status(gpucheck.check())`, `Jobs.fail_interrupted()`, уборка `jobs/.new-*` старше часа и логов/входов старше `LOG_DAYS`; затем цикл `claim_next()` по одному заданию (8 ГБ VRAM). Без GPU берёт только `publish`, `import` и `video` (`needs_gpu=False`), GPU перепроверяет раз в минуту; при старте же удаляет `imports/*` старше часа.
- Отмена: web ставит `cancel_requested`, worker проверяет раз в секунду, убивает группу процессов (SIGTERM → 10 с → SIGKILL); `in/` сохраняется для «Перезапустить».
- Состояния: `queued → running → publishing → done|failed|cancelled`; `stage` — русское название этапа, на выкладке `STAGE_PUBLISH="publish"` (UI переводит). Упавшее на выкладке → `republish` создаёт задание `publish` с `source_job_id`.
- Поток generate: форма → `songs/<A>/<A - T>/jobs/.new-*` → rename в `jobs/<id>/in/` (`input.mp3`, `lyrics.txt`, `cover.<ext>`), `params.inputs` — пути от `DATA_DIR` → UltraSinger в `jobs/<id>/us|out` → `finalize` в `jobs/<id>/result` → `Storage.upload_dir` → `in/` копируется в `source/` (+`params.json`), обновляются Songs/Library, `jobs/<id>/` удаляется.
- Типы заданий: `generate`, `instrumental`, `import`, `publish`, `video`; `import` с `instrumental=true` после выкладки ставит `instrumental` (`parent_id` = импорт; сбой постановки — только предупреждение в логе).
- Текст из LRCLIB: `GET /api/lyrics/search` → до 10 вариантов (`text`, `synced`); форма шлёт `lyrics_lrc` → `in/lyrics.lrc`, `params.inputs.lrc`, флаг `lrc_timing`; worker передаёт `--lyrics_timing` только при `lrc_matches` (иначе в лог `LRC_NOT_USED`); строка LRC с N метками = N строк, фронт строит чистый текст в том же порядке (`lrcPlainText`).
- Поток import: inspect → `imports/<token>/{files/…, meta.json}` (жизнь — час по mtime `meta.json`, потом 410) → `{token, source, songs[{index, artist, title, audio, cover, youtube, existing_song_id, warnings…}]}` → `POST /api/jobs/import` (`token, index, artist, title, audio? | youtube_url?, instrumental, replace`) копирует в `jobs/<id>/in/` (`song.txt`, `audio.<ext>` или `input.mp3`, `cover.<ext>`; обложку по `cover_url` качает веб) → worker: yt-dlp, если нет звука → `in/input.mp3` + `in/cover.jpg` (restart не качает заново) → ffmpeg mp3 → `.txt` без `#VIDEO/#BACKGROUND/#VIDEOGAP` → `finalize(**chosen_video)` (видео блока «Видео» возвращает свои `#VIDEO/#VIDEOGAP`) → `publish_song`; в `source/params.json` добавляются `source` (`usdb|files|url`) и `usdb_id`.
- usdb: учётка в `settings[usdb]` (`UsdbAccount`; PUT сохраняет только после успешного входа, пустой логин — удалить); без учётки → 400 `code=usdb_no_account`; неверный вход → 400 `field=password`, нет песни → 404, иначе 503.
- Замена песни: та же папка — старая в корзину, выкладка, при сбое откат из корзины; другая папка — сначала выкладка, потом старая в корзину.
- Блок «Видео» generate/import: поля `video_mode` (`none|source|url|file|pack`), `video_url`, `video_file`, `video_height`, `videogap` → `params.video = {mode, url?, height, gap?}`, файл → `in/video.<ext>` и `params.inputs.video`; `source` у generate — ссылка звука, у import — `v=` из `#VIDEO`, иначе выбранная/первая ссылка звука; `pack` — видеофайл архива (meta.json `video_rel`), пустой `videogap` при `source/pack` берёт смещение из архива; inspect отдаёт у песни `video_links`, `video_file`, `videogap`. generate качает видео на шаге finalize (после UltraSinger); `in/video.*` в `source/` не копируется, в `source/params.json` — `video_url`.
- Задание `video` (`POST /api/jobs/video`, multipart `song_id, video(File)? | video_url? (+video_height), videogap?, remove?` — ровно один источник): ref `{artist, title, song_id}`, params `{rel_dir, txt_name, target_id, video_url?, video_height?, videogap?, remove?, inputs: {dir, video?}}` → `result/<основа .txt>.<ext>` (hardlink) → `publish_video`: в `.txt` меняются только `#VIDEO/#VIDEOGAP` (прежняя версия — в корзину), старый видеофайл с другим именем удаляется; `videogap` None — `#VIDEOGAP` не трогается, 0 — удаляется; restart не качает заново (`in/video.*`); такое же задание песни уже в очереди → 409.
- Замена песни (`publish_song`): если у старой было видео, а в новом `result/` своего нет — видео переносится под новое имя с `#VIDEO/#VIDEOGAP` (сбой — предупреждение в логе).
- instrumental: demucs `--two-stems vocals` → ffmpeg mp3 → `<аудио> [Instrumental].mp3` рядом с аудио, в `.txt` меняется только `#INSTRUMENTAL`.
- Раскладка тома data: `karaoke.sqlite`; `logs/<id>.log`; `songs/<A>/<A - T>/{source/,jobs/<id>/in/,debug/}`; `trash/<UTC>__<id>/{<A>/<A - T>/…, meta.json}` (без `meta.json` запись считается недописанной); `imports/<token>/{files/…, meta.json}` (токен `[A-Za-z0-9_-]{1,64}`, `DataPaths.import_dir`). Том `models` (`/models`) — кэши HF/torch/xdg/hyphen.
- Папка результата: `<A>/<A - T>/<A - T>{.txt,.mp3, [Vocals].mp3, [Instrumental].mp3,.mid, [CO].jpg,.<видео>}`; БД: миграция V2 `library.video` → `LibraryItem.video` (в карточке песни), `SongEntry.video` — имя файла из `#VIDEO` или None; цель — из `settings` (веб «Настройки»), иначе из `OUTPUT_*` env; локальная цель — корень `/output`.
- REST: ответы JSON, ошибки `{"detail": "по-русски", "field"?}`; 422 переводится в 400; папка результата недоступна → 503; неверный Range → 416. Пароли API никогда не возвращает (`has_password`).
- Эндпоинты: `/api/status`, `/api/defaults` (+`max_import_mb`, `max_video_mb`, `video_heights`, `default_video_height`), `/api/jobs` (`generate`, `instrumental`, `import`, `video`, `{id}`, `cancel`, `restart`, `republish`, `log`, `log/stream`), `/api/import/inspect`, `/api/lyrics/search`, `/api/usdb/search` (по 50; без `language` — `Russian`, пустой — без фильтра), `/api/songs` (`rescan`, `exists`, `{id}` с `source`, `lyrics`, `notes` GET/PUT, `audio` с Range, `cover`, DELETE), `/api/trash` (+`restore`), `/api/settings/output` и `/api/settings/usdb` (GET/PUT, `test`).
- `import_router` подключается раньше `jobs_router` (`web/app/main.py`), иначе `POST /api/jobs/import` уйдёт в маршруты `/api/jobs/{id}`.
- SSE лога: первым `event: start` с байтовым смещением, `id:` = смещение, в конце `event: end`; без `from` — последние 500 строк.
- GET `/api/songs/{id}/notes` → `{editable, reason?, bpm, gap, headers:[[k,v]], duet, singers:{p1, p2}, lines:[{break_beat, player?, notes:[{id, type, start, length, pitch, text}]}]}` (`player` 1/2 — только у дуэта, `singers` у соло — пустые строки); `id` ноты — её порядковый номер в файле (0…N-1), `break_beat` — разрыв после строки (у последней `null`).
- PUT тот же адрес `{gap, singers?, lines:[{break_beat, player?, notes:[{id|null, type, start, length, pitch, text}]}]}`: тайминги, высоты, типы, текст, новые (`id: null`) и удалённые (нет в теле) ноты, границы строк; `editable/reason/bpm/headers` игнорируются, прочие заголовки не меняются; `break_beat: null` у непоследней строки → конец её последней ноты; `gap` null или равен текущему → `#GAP` не трогается; дуэт пишется, если у какой-то строки с нотами `player=2` (иначе соло без `P`-меток и без `#P1/#P2/#DUETSINGERP*`), `player` — у всех строк или ни у одной; `break_beat` последней строки певца 1 не null → `- N` перед `P2`; имена перезаписываются, только если отличаются от прочитанных.
- PUT 400: нет нот, неизвестный тип, начало < 0, длина < 1 (ноту длины 0 тоже отклоняет), высота вне −40…100, перевод строки в слоге, перекрытие, разрыв не между строками, чужой/повторный `id`, `gap` < 0, у дуэта — нет/неверный `player` строки (ошибки «Певец N, строка K: …», K — внутри партии); 409: певцы `P3`+, `#RELATIVE`, нет `#BPM` (GET тогда `editable:false` + `reason`), сбой корзины. Изменился файл → старая версия в корзину, `write_atomic`; ответ — карточка песни.


## Соглашения кода

- Python 3.12, `from __future__ import annotations`, docstring/комментарии и все тексты ошибок — по-русски.
- Пути тома data — только через `DataPaths`; имена песен — только через `naming`; запись в папку результата — только через `Storage`.
- Ошибки задания: `raise JobFailed(reason, user_message)`; `user_message` попадает в `Job.error` как есть (+ последние 5 строк лога).
- Ошибки API: `raise ApiError(status, "текст", field=...)`, не `HTTPException`.
- Новая переменная окружения обязана появиться в `.env.example` с русским комментарием строкой выше — проверяет `tests/core/test_repo_config.py`.
- Фронт: модуль раздела экспортирует `mount(section, ctx)`, `show(params)`, опц. `hide()`; чистая логика выносится в отдельные модули (`editors/notes-model.js`, `editors/lyrics-text.js`, `id3.js`) ради node-тестов.
- Исходящий HTTP — только через `karaoke_core.http.Http` (`AppContext.http`); в тестах — `create_app(..., http=FakeHttp())`, реальные LRCLIB/usdb/GitHub/YouTube не трогать.
- `test_repo_config` считает секретом любое `password`/`token`/`secret` (и `*_PASSWORD…`), за которым через двоеточие или знак равенства идёт значение, во всех файлах вне `tests/` — в коде/JS писать `b['password']`, передавать позиционно или назвать переменную иначе.
- LRC пишется в UTF-8 (читается `utf-8-sig`); нормализация строк в `handlers.py` (`_norm_line`, `parse_lrc`, `lyrics_lines`) повторяет форк `src/modules/Speech_Recognition/lrc_timing.py` один в один — менять только синхронно.
- Новые Python-зависимости для тестов добавляются в `core/Dockerfile.test` (через pyproject `core`/`web`).

## Окружение

- `WEB_PORT` — порт веба на хосте; `WEB_PASSWORD` — общий пароль HTTP Basic (логин любой, пусто — без пароля); `MAX_UPLOAD_MB` — лимит загрузки mp3; `MAX_IMPORT_MB` — лимит zip импорта (файлы или ссылка; распаковка — до двойного); `MAX_VIDEO_MB` — лимит видеофайла (форма, диалог «Видео…»).
- `OUTPUT_KIND` (`smb`|`local`), `OUTPUT_SMB_HOST`, `OUTPUT_SMB_SHARE`, `OUTPUT_SMB_PATH`, `OUTPUT_SMB_USER`, `OUTPUT_SMB_PASSWORD` — цель выкладки по умолчанию (веб может переопределить в БД).
- `LOCAL_OUTPUT_ROOT` — папка хоста, монтируемая как `/output`.
- `TRASH_DAYS`, `LOG_DAYS` — срок хранения корзины и логов/входов; `TZ` — часовой пояс контейнеров.
- `ULTRASINGER_GIT` — источник UltraSinger для сборки worker (git-URL `…#karaoke-local` или локальный путь).
- `DEFAULT_WHISPER_MODEL`, `DEFAULT_LANGUAGE`, `DEFAULT_COMPUTE_TYPE`, `DEFAULT_BATCH_SIZE`, `DEFAULT_ALIGN_MODEL_RU` — умолчания формы и аргументов UltraSinger.
- Задаёт compose/образ, не пользователь: `DATA_DIR`, `MODELS_DIR`, `HF_HOME`, `TORCH_HOME`, `XDG_CACHE_HOME`, `PYHYPHEN_DIR`, `ULTRASINGER_DIR`, `WEB_STATIC_DIR`.
- `YTDLP_CMD` — команда yt-dlp для web и worker (пусто — `python -m yt_dlp` образа); `MUSICLINK_CMD` — загрузчик Яндекс Музыки (пусто — `python -m karaoke_core.musiclink`); `YANDEX_MUSIC_TOKEN` — только окружение этого подпроцесса (токен пользователь вводит в «Настройках»).
- Подмена команд в тестах: `FAKE_YTDLP_MODE` (режимы `tests/worker/fixtures/fake_ytdlp.py`, `novideo` — без видео), `ULTRASINGER_CMD`, `DEMUCS_CMD`, `FFMPEG_CMD`, `YTDLP_CMD`, `MUSICLINK_CMD`; интеграция с живой шарой: `TEST_SMB_HOST`, `TEST_SMB_SHARE`, `TEST_SMB_USER`, `TEST_SMB_PASSWORD`, `TEST_SMB_PATH`.

## Тесты

- `tests/core/` — чистые функции и `LocalStorage` во временной папке; фикстуры `.txt` (CRLF, BOM, cp1251, дуэт) сравниваются байт в байт и помечены binary в `.gitattributes`.
- `tests/api/` — `create_app(data_dir=, env=, storage_factory=, http=, ...)` через `TestClient`, env берётся из `.env.example`.
- `tests/conftest.py` кладёт `tests/` в `sys.path` (pytest с `--import-mode=importlib`) — `from fakes_http import FakeHttp` без ручных вставок; `FakeHttp().route(method, prefix, …)` (побеждает самый длинный префикс), `.calls(prefix)` — журнал; дополнять, не переписывать.
- `tests/worker/` — `run_forever(..., gpu_check=, until=)` с фейками из `tests/worker/fixtures/` через `*_CMD`; без torch и GPU.
- 2 skipped — `tests/core/test_storage_smb_integration.py` без `TEST_SMB_HOST/TEST_SMB_SHARE` (передавать `-e TEST_SMB_…` в `run`).
- `tests/core/test_repo_config.py` сканирует весь репозиторий (кроме `tests/`, `.autopilot/`, `.env`), включая этот файл, на `PASSWORD|SECRET|TOKEN` со значением после `=`/`:`.
- Дуэты: `tests/worker/test_runner_duet.py` (импорт дуэта доезжает до результата), фикстура `tests/core/fixtures/duet.txt`; видео: `tests/api/test_video.py`, `tests/worker/test_runner_video.py`, `tests/frontend/video-block.test.mjs`; `fake_ytdlp.py` в видеорежиме (без `-x`, с `-f`) пишет `.mp4`.
- Настоящий GPU проверяется только `gpucheck` и реальной генерацией.
- Редактор нот: швы — `PUT/GET /api/songs/{id}/notes` в `tests/api/test_songs.py` и чистые модули (`notes-model`, `syllables`, `timeline`, `notes-panel` `*.test.mjs`); экран (`notes-editor.js`, плагины) — только вручную в браузере.

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
- Формат UltraSinger: пробел-граница слова стоит в конце слога, «~» — продолжение гласной (бывает с пробелом с любой стороны); `lineText`/`joinNext`/`setLineText` в `notes-model.js` это учитывают — не «чинить» пробелы при правке.
- Сдвиг ноты левее бита 0 (move, resize, addNote, retime) не ошибка: модель сдвигает всю песню вправо и уменьшает `gap` (`settle`); ошибка только при `#GAP` < 0. Предпросмотр перетаскивания пересчитывает биты через `rebaseBeat`.
- Код web и worker запечён в образы (исходники монтируются только у `tests`): после правок Python или фронта — `./scripts/compose.ps1 up -d --build web worker`, иначе работает старый код; в браузере ES-модули кэшируются — жёсткая перезагрузка (Ctrl+F5).
- curl из Git Bash портит кириллицу в аргументах — тестовые данные с русским текстом слать из браузера или из UTF-8 файла (`--data-binary @file`).
- `ImportHandler` всегда снимает `#VIDEO/#BACKGROUND/#VIDEOGAP` из `.txt` пакета; видео возвращает только `finalize` по выбору блока «Видео» (`chosen_video`); сбой скачивания видео задание не валит.
- Общий `state.notes` дуэта — слияние партий по времени, порядок осмыслен только внутри партии: живая нота — `noteAt(voiceNotes(state, v), beat)` по каждому певцу, индексы перетаскивания слога — из `voiceNotes`, подсветка строки — `lineAt(lines, beat, v)`.
- Шара отдаёт 503 при параллельном чтении одного файла (`<audio>` и волна одновременно) — `loadPeaks` повторяет до 3 раз через 1,5 с.

## Как здесь работает Autopilot

Сборка ведётся навыком `/autopilot`. Требования, спецификация и таски — в `.autopilot/`.
Прогресс — `.autopilot/dashboard.html`. Правило: требование из `manifest.md`
может снять только пользователь.

Если работа продолжается — скажи «продолжи автопилот»: состояние поднимется
из `.autopilot/state.js`, переспрашивать ничего не нужно.
<!-- autopilot:end -->
