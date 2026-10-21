# Интерфейсы

## Правила проекта (для каждого исполнителя)

- Прочитай `CLAUDE.md` в корне — там структура, команды, соглашения, подводные камни. Он важнее любых догадок.
- Python 3.12, `from __future__ import annotations`, docstring/комментарии/ошибки — по-русски. Ошибки API — `ApiError`, задания — `JobFailed(reason, user_message)`.
- Тесты Python — только в Linux-контейнере: `docker --context desktop-linux compose --profile test run --rm tests` (подмножество: `... run --rm tests pytest -q tests/…`). На Windows-хосте pytest не запускать. Фронт: `node --test tests/frontend/`.
- Новая переменная окружения → `.env.example` с русским комментарием строкой выше.
- Никаких новых зависимостей. Не хватает зависимости → верни `BLOCKED`, не ставь ничего.
- Не трогать: форк `D:/Projects/UltraSinger`, `patches/`, `.autopilot/`, `CLAUDE.md` (память правит оркестратор), чужие зоны тасков своей волны.
- Коммиты делает оркестратор, не исполнитель.
- В одной волне параллельно работают несколько исполнителей в одном дереве: правь только файлы своей зоны; полный прогон pytest может видеть чужие недописанные правки — если падает чужое, укажи это в отчёте, а не чини.

## Границы, решённые в спецификации

| Модуль | Владеет | Выставляет | Прячет |
|---|---|---|---|
| `core/ultrastar` | формат `.txt` | `Song.tracks()` → `{1: [lines], 2: [lines]}` (соло → только `1`); `singer_names(song) -> (p1, p2)`; `set_singer_names(song, p1, p2)` | поиск `#P1`/`#DUETSINGERP1` |
| `web/notes` | GET/PUT нот | GET: `lines[].player` (1/2 у дуэта, нет у соло), `singers: {p1, p2}`, `duet: bool`; PUT: `lines[].player: 1\|2\|null`, `singers: {p1, p2}?` | раскладку блоков P1/P2, переиспользование меток, проверку по партиям |
| `editors/notes-model.js` | состояние редактора | нота `{…, voice: 1\|2\|'both', src2}`; State `{…, duet, singers: {p1, p2}}`; `setVoice(state, ids, voice)`, `makeDuet(state)`, `makeSolo(state)`, `setSingers(state, p1, p2)`, `voiceNotes(state, v)`; прежние операции — в пределах партии; `fromPayload` склеивает одинаковые строки P1/P2 в «оба», `toPayload` раскладывает | порядок по партиям |
| `naming` | имена файлов | `video_suffix(ext)`, `VIDEO_EXTS` | — |
| `postprocess.finalize` | папку результата | kwargs `video_path=None, videogap=None` → `<A - T>.<ext>` + `#VIDEO`/`#VIDEOGAP` | — |
| `worker handlers` | задания | `HANDLERS["video"]` (`needs_gpu=False`); `download_video(ctx, job_id, url, dest_dir, height) -> Path`; ветка `video` в `PublishHandler` | yt-dlp-аргументы, перенос видео в `publish_song` |
| `web api_jobs` | приём заданий | `POST /api/jobs/video` multipart `{song_id, video(File)?, video_url?, video_height?, videogap?, remove?}`; generate и import принимают `video_mode (none\|source\|url\|file\|pack), video_url, video_file, video_height, videogap` → `params.video = {mode, url?, height, gap?}`, файл → `inputs.video` | `Staging` |
| `db`/`storage` | индекс | `LibraryItem.video`, `SongEntry.video` (имя файла из `#VIDEO` или None) | миграция V2 |
| фронт `api.js` | HTTP | `api.video(songId, form)`, `generateForm({…, video_mode, video_url, video_file, video_height, videogap})`, `importForm` с теми же полями | — |
| фронт `video-block.js` | блок «Видео» | разметка блока (режимы — параметр), чистая `videoFields(state)` → поля multipart; качество в `localStorage` `video.height` | — |

Задание `video`: `params = {rel_dir, txt_name, target_id, video_url?, video_height?, videogap?, remove?, inputs.video?}`.
`/api/defaults`: `max_video_mb` (env `MAX_VIDEO_MB`, 2000), `video_heights` `[360, 480, 720, 1080, 0]` (0 = лучшее), `default_video_height` 720.

**Швы для тестов:** `tests/core` (ultrastar, songpack, postprocess, db, naming, storage), `tests/api` через `TestClient`, `tests/worker` через `run_forever` с фейками (`fake_ytdlp.py` — видеорежим без `-x`, с `-f`, пишет `.mp4`; `FAKE_YTDLP_MODE=novideo`), `tests/frontend`. Экран редактора и диалоги — вручную в браузере.

## Что построили таски

*(дописывается по мере сдачи)*

### Из таска 01 — формат и API нот (дуэты)

- `ultrastar`: `Song.tracks() -> {1: [lines], 2: [lines]}` (строка без метки P — певец 1; у соло только ключ 1); `singer_names(song) -> (p1, p2)`; `set_singer_names(song, p1, p2)`
- GET `/notes`: + `duet: bool`, `singers: {p1, p2}` (у соло пустые строки); `lines[].player` только у дуэта
- PUT `/notes`: `lines[].player: 1|2|null`, `singers?`; дуэт пишется, если у какой-то строки с нотами `player=2`, иначе соло без `P`-меток и без `#P1/#P2/#DUETSINGERP*`. `break_beat` последней строки певца 1: не null → `- N` перед `P2`; null — без разрыва
- Ошибки дуэта: «Певец N, строка K: <что>, слог «x»» (K — внутри партии); «Строка K: не указан певец (1 или 2)», «Строка K: певец — 1 или 2, а не X»
- `MANY_SINGERS_REASON` — только просмотр, если в файле есть `P3` и дальше (вместо `DUET_REASON`)
- Имена перезаписываются, только если отличаются от прочитанных

### Из таска 03 — экран редактора (дуэты)

- ctx плагинов: `ctx.partNotes(id)` (ноты партии этой ноты, у соло — все), `ctx.singerLabel(v)` → «Певец 2 (имя)»
- `lyrics-editor.js`: `DUET_REGEN_WARNING`
- CSS: `--ne-p2`, `--ne-both` (обе темы); классы `.p1/.p2/.both` у `.ne-note/.ne-chip/.ne-brk`, `.ne-lane.duet`, `.ne-legend`, `.ne-singers`, `.ne-pgroup`, `.ne-pv`, `.ne-vgroup`
- Новая нота (двойной клик / N) получает певца выбранной ноты, без выделения — певца 1

### Из таска 04 — видео: ядро и задание `video`

- `naming.VIDEO_EXTS` (frozenset `.mp4 .m4v .mkv .webm .avi .mov .mpg .mpeg`); `naming.video_suffix(ext) -> ".<ext>"` (нижний регистр)
- БД: миграция V2 `library.video`; `LibraryItem.video` (есть в `to_dict()` карточки), `SongEntry.video` = `present("VIDEO")`
- `postprocess.finalize(out_dir, artist, title, cover_path=None, *, dest_dir=None, video_path=None, videogap=None)`; `postprocess.format_videogap(value) -> str | None` (до 3 знаков, без «.0»; 0/пусто → None)
- `progress.STAGE_VIDEO_DOWNLOAD = ("Загрузка видео", 5)`; `DownloadTracker(start, end, stage=…)`
- `handlers`: `HANDLERS["video"] = VideoHandler()` (`needs_gpu=False`); `download_video(ctx, job_id, url, dest_dir, height) -> Path` (кладёт `dest_dir/video.mp4`; height 0/None = лучшее; Яндекс и ошибки → `JobFailed` по-русски); `publish_video(ctx, job, src)`; `INPUT_VIDEO_STEM = "video"`; `PublishHandler` выкладывает и `video`
- Задание `video`: `type "video"`, ref `{artist, title, song_id}`, params `{rel_dir, txt_name, target_id, video_url?, video_height?, videogap?, remove?, inputs: {dir, video?}}`; `inputs.dir` — путь от DATA_DIR до `jobs/<id>/in/` (по нему «Перезапустить» находит скачанное `in/video.*`), `inputs.video` — путь до `in/video.<ext>`; `videogap` None → `#VIDEOGAP` не трогается, 0 → удаляется
- `_save_sources`: `in/video.*` не копируется; `params.json` получает `video_url` из `params.video.url` или `params.video_url`
- `publish_song`: видео заменяемой песни переносится как `<основа .txt>.<ext>` с `#VIDEO/#VIDEOGAP`, если в `result/` своего нет (сбой — предупреждение в логе)
- Генерацию/импорт с `params.video` к `finalize` подключает таск 06

### Из таска 05 — диалог «Видео…» и блок «Видео»

- `POST /api/jobs/video` multipart `song_id, video(File)?, video_url?, video_height?, videogap?, remove?` → задание `video` (params как в блоке 04); restart `video` → 409, если такое задание этой песни уже в очереди
- `api_jobs`: `video_link(url, field)`, `video_ext_of(filename, field)`, `parse_video_height(raw, field)`, `parse_videogap(raw, field)` — переиспользовать в generate/import, не писать свои проверки
- `params`: `VIDEO_HEIGHTS`, `DEFAULT_VIDEO_HEIGHT`, `max_video_mb(ctx)`; `/api/defaults` → `max_video_mb`, `video_heights`, `default_video_height`
- `api.js`: `api.video(songId, FormData | {video_url, video_file, video_height, videogap} | {remove:true})`; `videoForm(songId, fields)`
- `video-block.js` (чистое): `VIDEO_MODES`, `MODE_LABELS`, `videoFields(state{mode,url,file,height,gap})` → `{video_mode, video_url?, video_file?, video_height?, videogap?}`, `videoError(state)` → `{field, text} | null`, `normGap`, `rememberedHeight(heights, dflt, ls?)`, `rememberHeight(h, ls?)` (ключ `video.height`), `heightLabel`
- `video-block.js` (разметка): `createVideoBlock({modes, mode, labels, sourceUrl, heights, defaultHeight, gap, maxMb, onChange})` → `{el, state(), fields(), setMode, setModes(modes, mode?), setSource(url), setGap, validate(), showError(field, text), showApiError(e) → bool, clearErrors()}`
- Поля multipart generate/import (таск 06): `video_mode, video_url, video_file, video_height, videogap` — ровно то, что отдаёт `videoFields`
- `docker-compose.yml` пока не передаёт `MAX_VIDEO_MB` в web — добавить `MAX_VIDEO_MB: ${MAX_VIDEO_MB:-2000}` (таск 06)

### Из таска 06 — видео при создании и импорте

- `songpack`: `video_links(header) -> list[str]` (v= usdb или URL целиком; a= — только звук), `VIDEO_EXTS`; `ALLOWED_EXTS` с видео; `FoundSong.video_links/video_file/videogap`
- `paths.INPUT_VIDEO_STEM = "video"` (единственное место; `handlers.INPUT_VIDEO_STEM` — реэкспорт)
- `api_jobs`: `VIDEO_MODES`, `video_choice(mode, url, file, height, gap, *, source_url, pack, default_gap) -> (params.video|None, ext|None)`, `stage_video_file(ctx, staging, file, ext)`; ошибки по полям `video_mode/video_url/video_file/video_height/videogap`
- inspect: у песни `video_links`, `video_file`, `videogap`; meta.json `video_rel`; import `source` — `v=` из `#VIDEO`, иначе выбранная/первая ссылка звука
- `params.video = {mode, url?, height, gap?}`, файл → `inputs.video`
- `handlers.chosen_video(ctx, job, in_dir) -> dict` (kwargs для `finalize`), `VIDEO_SKIPPED`; generate качает видео на шаге finalize (после UltraSinger)
- `video-block.js`: `videoChoices({source, pack}) -> {modes, mode}`, `isVideoLink(url)`; `state().gapTouched`, `reset(mode?, gap?)`; `showApiError` — и `video_mode`, `video_file`
- `docker-compose.yml`: web получает `MAX_VIDEO_MB`

### Из таска 02 — модель редактора (дуэты)

- нота `{id, src, type, start, length, pitch, text, ls, brk, voice: 1|2|'both', src2, brk2}`; State `{…, duet, singers: {p1, p2}}`
- `fromPayload` склеивает одинаковые строки P1/P2 в «оба»; `toPayload`: соло `{gap, lines}` как раньше, дуэт `{gap, singers, lines:[{break_beat, player, notes}]}` — блок P1, потом P2 (копии «оба» с `id: src2`)
- `setVoice(state, ids, voice)`, `makeDuet(state)`, `makeSolo(state)`, `setSingers(state, p1, p2)`, `voiceNotes(state, v)` (ноты партии v вместе с «оба»), `voiceLines(state, v)`, `inVoice(note, v)`; константы `VOICES`, `NOT_DUET_ERROR`, `VOICE_ERROR`, `OTHER_VOICE_ERROR`
- `addNote(state, {start, pitch, length?, text?, type?, voice = 1})`; `lines(state)` у дуэта — строки обеих партий, «оба» один раз, в порядке списка нот (индексы li для `setLineText`/`addNotesToLine`)
- `shiftRange` отдаёт номера нот в `voiceNotes` партии ноты
- `notes-panel-logic`: `lineAt(lines, beat, voice?)` (порядок строк любой), `tapQueue(notes, fromId)` — до конца партии; `timeline-math.noteAt(notes, beat)` — и для неотсортированного списка
- Для экрана: живая нота — `noteAt(voiceNotes(state, v), beat)` по каждому певцу; перетаскивание слога — индексы из `voiceNotes` партии; `addNote` на дорожке P2 — с `voice`; подсветка строки — `lineAt(lines, beat, v)`. Общий `state.notes` — слияние партий по времени, порядок осмыслен только внутри партии
- Тексты ошибок `validate` у дуэта: «Певец N, строка K: ноты перекрываются», «<ошибка>: Певец N, строка K, слог «x»»; строки нумеруются внутри блока партии, «оба» считается в обеих
