# notes.md — код на HEAD 72b00ab (2026-10-28)

`js/` = `web/static/js/`. Карта проекта — `CLAUDE.md`.

## 1. Редактор нот (`js/editors/`)
- `editors/index.js`: `registerSongEditor`, плагины по порядку `textPanelPlugin`, `toolsPlugin`, `notesChecksPlugin`.
- `openNotesEditor(song, {reload})` — `notes-editor.js:52`, одно замыкание. `song` — карточка `GET /api/songs/{id}`: есть `song_id, audio, instrumental` (имена файлов или null), **нет `vocals`** (он только в `/details` → `media.vocals`).
- Окно: `openShell({title, wide:true, isDirty})` (`editors/shell.js`), `<dialog class="editor wide">`; при закрытии событие `editor-close` на `dlg`, затем `dlg.remove()`. CSS — `web/static/css/editors.css`.
- `ctx` плагинов (`notes-editor.js:1007`): `song, shell, dlg, M, els{bar, slotPlay, slotTools, slotEnd, centerTop, panel, hint, main, scroll, inner, roll, lane, brkLayer}`, геттеры `state, selection, lastSel, posMs, playing`, функции `playReason, editable, apply, select, revealNote, editChip, render, renderSel, toast, play, stopPlay, seekMs, playLine, msOf, beatOf, bx, xBeat, py, partNotes, singerLabel, voiceLabel`, хуки `onRender, onSelect, onTick, addKey`. **`audio` и `rateSel` в ctx нет.**
- Звук: `:406` `const audio = new Audio()` (`preservesPitch`), `:412` `audio.src = api.audioUrl(song.song_id)` если `song.audio`; `audioError`; события `error`, `loadedmetadata` (→ `duration`), `pause` (→ `stopPlay`). `playReason()` `:425`.
- Состояние `posMs`, `playing`, `stopAt`, `raf`. `play(fromMs, untilMs)` `:442` (тумблер без аргумента; ставит `audio.playbackRate = Number(rateSel.value)`, `currentTime`, `await audio.play()`, rAF `loop`: `posMs = audio.currentTime*1000`). `stopPlay()` `:431`, `seekMs(ms, reveal)` `:473`, `playLine()` `:503`.
- `updatePlayhead()` `:482` → в конце `hooks.tick.forEach(f => f(posMs, playing))`; tick зовётся и из rAF, и при seek/stop/render.
- `rateSel` `:92` (`0.5 / 0.75 / 1`), `change` → `audio.playbackRate` (`:873`).
- Закрытие `:995`: `stopPlay(); audio.removeAttribute('src'); audio.load(); waveAbort.abort(); ro.disconnect()`.
- Тулбар `.ne-bar` `:108`: `playBtn · lineBtn · timeEl · rateSel · followBtn(.on, aria-pressed) · sep · zout · zin · sep · slotPlay · .ne-grow · selAll · selInfo · textBtn · slotTools · gold · del · slotEnd`. Слоты `span.ne-slot` (`display: contents`). `slotPlay`: «⏺ Отстукивать» (tools), «♪» (checks). `slotEnd`: «Сделать дуэтом/соло», «Певцу», «?». Помощник `btn(label, title, attrs)` (`:83`, и в notes-tools.js:32). Тоггл-образцы: `followBtn` или `label.check` + checkbox («подсветка», ключ `notesEditor.suspectsOn`).
- **Клавиатура-пианино слева**: `div.ne-keys[aria-hidden=true] > div.ne-keys-in` (`:112`), сетка `.ne-tl {grid-template-columns: 40px 1fr}`. `renderKeys()` `:216` пересоздаёт голые `<div>` на каждый pitch от `pr.max` до `pr.min` (top = `RULER_H(24)+waveH()+(pr.max-p)*row`, `.blk` для чёрных, подпись `octaveLabel(p)`), **без data-pitch и без обработчиков**. `drawVisible()` `:362` двигает `keysIn` по `scroll.scrollTop`. CSS `editors.css:108-112`.
- «♪» (`notes-checks-plugin.js:33`): `playTone(pitch, ms)` выбранной ноты, клавиша `P`, `ms = length*60000/(bpm*4)`, иначе 600.
- Клавиши: один `dlg` keydown (`:936`), выход при фокусе в `input, select, textarea, [contenteditable]`; `[...extraKeys, ...KEYS]`, `matches(k,e)` по `e.code`. Заняты: Space, Ctrl+Z/Y/S/A, Shift+Ctrl+Z, Delete, Backspace, Tab, F2, Enter, L, N, G, =/-, P, Shift+1, J, Shift+J, T, S, Alt+←/→, Esc, стрелки (±бит, полутон, Ctrl — длина), `?` по `e.key`. **Свободны**: V, M, B, K, O, H, R, E, Q, W, D, F, C, X, U, I, цифры. `ctx.addKey({code, ctrl?, shift?, alt?, fn})`.
- Справка: `HELP` (notes-tools.js:34-60, `[[клавиши], описание]`) и `DUET_HELP` — единственный источник; `dialog.ne-help`, кнопка «?» в `slotEnd`, строка в `els.hint`.
- localStorage: `notesEditor.ppb`, `.suspectsOn`, `.shiftScope`, `.textPanelClosed`, `.textPanelWidth`.

## 2. tone.js и «Прогон»
- `tone.js`: `TONE_MIN_MS=150`, `TONE_MAX_MS=2000`, `pitchHz`, `toneMs`, `toneSupported`, `playTone(pitch, ms, {gain}) → stop()`, `toneSequence(notes:[{pitch,startMs,ms}], fromMs=0, {gain}) → {stop()}` (все ноты сразу на часах AudioContext; **нет учёта скорости**). Модульный `audioCtx`, лениво в `context()`; **нет close/dispose** (баг «Прогона»). `waveform.js::loadPeaks` свой контекст закрывает сам.
- `play.js` (`#play?id=`): `mount/show/hide`; `Promise.all([api.songDetails(id), api.notes(id)])`, `playProblem` → баннер; `build()` `:161`: `audio.src = api.audioUrl(id)` (только оригинал). Константы `WINDOW_MS=8000, STEP_MS=5000, MELODY_AHEAD_MS=4000, MELODY_KEY='play.melody'`; `readMelody/saveMelody`. Тоггл `label.pv-tg > input + span.pv-tgl` «Мелодия нот», ряд `.pv-row` с `span.pv-hint`. `melodyTick(ms)` порциями `melodySlice` → `toneSequence(chunk, ms)`, `melodyStop()`. `onKey` на `document` (`:303/348`): Space, ←/→ ±5 с. `teardown()` `:354` — tone-контекст не закрывает.
- `play-logic.js`: `playProblem, timeline, voiceLines, frameAt, melodyNotes, melodySlice, laneY, fmtClock`; тесты `play-logic.test.mjs`.

## 3. Минусовка и вокал на фронте
- `GET /api/songs/{id}/details` → `media.{audio, instrumental, vocals, video, cover, background, midi}` (имена или null).
- `GET /api/songs/{id}/file?name=` — Range, inline для аудио; `api.fileUrl(id, name)`. `GET /api/songs/{id}/audio` — только оригинал.
- Карточка песни/списка: `song.audio`, `song.instrumental`.
- `api.instrumental(songId, replace)` → `POST /api/jobs/instrumental` (201 job; 409 «Эта песня уже в очереди», «У песни нет аудиофайла», «Минусовка уже есть…»). `song-actions.js:112 makeInstrumental`, `watchJob(job, onFinal)` (`:36`, опрос 3 с до done/failed/cancelled). `api.song(id)` — карточка.

## 4. Фронт целиком
- `app.js`: `VIEWS = {queue, new, import, songs, song, trash, settings, check, play}`; `mount(section, {setQueueCount, refreshStatus})`, `show(params)`, `hide()`. `parseHash`, `route()` (секции `main > section[data-view]`, `TAB_OF = {song:'songs', check:'songs', play:'songs'}`, FAB скрыт на `#new`). Вкладки `nav.tabs a[data-view]`: Очередь, Импорт, Песни, Корзина, Настройки. Опрос очереди 2 с, статус 15 с.
- Глобальные keydown: только `play.js` (document) и `menu.js:93` (document, capture, пока открыто меню). Остальные — локальные.
- `ui.js`: `h`, `field`, `clear`, `openModal`, `confirmDialog`, `toast`, `runAction`, `plural`, `debounce`, `songName`. `menu.js`: `openMenu`, `menuButton`, `closeMenu` (↑/↓/Home/End/Enter/Esc).
- `songs.js`: `div.songs` > `article.card.song[data-id]`: `input.pick`, `a.song-cover[tabindex=-1]`, `a.song-link[href=#song?id=]`, `.tags`, `.song-quick` > `button.play` (`playToggle`) + меню «…». `songHref(song)`.
- `queue.js`: `article.card.job[data-id]`, `render(jobs)` по `displayOrder`.
- `index.html`: `a.fab#fab-new`, `dialog#confirm`, `#toasts`.

## 5. Лимит 50 заданий
- `api.js:94 jobs: (limit=50)`, `queue.js:80 api.jobs(50)`, `notify.js:76 api.jobs(50)`; `api_jobs.py:620 GET /api/jobs?limit=` (`Query(50, ge=1, le=1000)`) → `db.py:433 Jobs.list(limit)` = `ORDER BY id DESC LIMIT ?` — старые ожидающие не видны, `#queue-count` занижен. Порядок очереди `_QUEUE_ORDER`, `queue-logic.js: queuedOrder, displayOrder, queuePlaces`. Тесты `queue-logic.test.mjs`, `tests/api/test_queue_order.py`.

## 6. Тексты
- `web/app/lyrics.py`: `LRCLIB_SEARCH`, `MAX_HITS=10`, `TIMEOUT_S=10`, `LyricsHit(id, artist, title, album, duration, text, synced=None)` + `to_dict()`, `LyricsUnavailable`, `clean_text`, `strip_lrc`, `synced_lrc`, `LrclibProvider(http).search(artist, title)` (по полям, потом `q`).
- `web/app/api_lyrics.py`: `GET /api/lyrics/search?artist=&title=` → `{items}`; 400 `field=artist|title`; `LyricsUnavailable` → 503 «Сервис текстов недоступен, попробуйте позже».
- Тесты `tests/api/test_lyrics.py` (`FakeHttp.route("GET", prefix, json=…)`).
- Фронт: `lyrics-search.js` (`usableHits` — отбрасывает пустые, `previewLines(text, 3)`, `SYNCED_LABEL`, `lrcPlainText`, `lrcTimingDefault`, `NOTHING_FOUND`…), `lyrics-dialog.js` (`openLyricsDialog({artist, title, onPick, onSettled, hint, hits})`, `div.card.lyrics-hit` с 3 строками превью и «Вставить»; **полного просмотра нет**). Вызывают: `new-song.js:307` (`insertLyrics`: `hit.synced ? lrcPlainText : hit.text`), `import.js:764` (папка, `pickTrackLyrics`); автопоиск папки — `import.js::runLyricsQueue` (`api.lyricsSearch` → `usableHits`, `withHit` в folder-logic.js). CSS `app.css:464-475`.

## 7. Изменено после прошлой сборки
- `artwork.js`: `openArtworkDialog` — флаг `ready` против раннего `syncSubmit` в `tabs()`.
- `caddy/Caddyfile` + сервис `proxy` (`https://karaoke.home`, `/ca.crt`).
- `storage/smb.py`: `_out_of_credits`, `close(drop=True)`, один повтор вызова.

## 8. Тесты
- `node --test tests/frontend/` → 290 pass (28 файлов `*.test.mjs`, грузит `index.js`; тестируются только чистые модули).
- pytest: `docker --context desktop-linux compose --profile test run --rm tests` → 1085 passed, 2 skipped.
