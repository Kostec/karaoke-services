# Интерфейсы

## Правила проекта (выведены не из кода — соблюдать)

- Полные правила — `CLAUDE.md` в корне. Интерфейс и все тексты — по-русски.
- Python 3.12, `from __future__ import annotations`; ошибки API — `raise ApiError(status, "текст")`, не `HTTPException`.
- Фронт — ES-модули без сборки (`web/static/js/`); чистая логика — отдельными модулями без DOM ради node-тестов.
- Python-тесты — ТОЛЬКО в Linux-контейнере: `docker --context desktop-linux compose --profile test run --rm tests` (было 564 passed, 2 skipped); подмножество: `docker --context desktop-linux compose --profile test run --rm tests pytest -q tests/api/test_songs.py`. На Windows-хосте pytest не запускать.
- Фронт-тесты: `node --test tests/frontend/` (было 76 pass). Новые `*.test.mjs` подхватываются сами через `tests/frontend/index.js`.
- Не трогать: форк UltraSinger, worker, `.env`. Не хватает зависимости — вернуть `BLOCKED`, ничего не ставить.
- `tests/core/test_repo_config.py` считает секретом `password|token|secret` со значением после `:`/`=` вне `tests/` — не писать так в коде.
- Согласованный дизайн — `.autopilot/2026-10-20-note-editor--wip/design.html` (рабочий макет: брать раскладку, жесты и подписи как образец; данные в нём выдуманные, звука нет).

## Границы, решённые в спецификации


| Модуль | Владеет | Выставляет | Прячет |
|---|---|---|---|
| `web/app/notes.py` | перевод нот ⇄ модель `.txt` | `notes_payload(song) -> dict` (у нот `id`); `apply_notes(song, body: NotesIn) -> None` (ApiError 400/409); `NotesIn` (`gap: float \| None`, `lines[].notes[].id: int \| None`) | сопоставление нот по `id`, перенос неразобранных строк, сохранение байт неизменённого |
| `editors/notes-model.js` | состояние редактора и все правки | `fromPayload(data) -> State`; `toPayload(state) -> body PUT`; `lines(state) -> [[note]]`; операции `move(state, ids, dBeat, dPitch)`, `resize(state, id, edge, dBeat)`, `addNote(state, {start, pitch, length})`, `deleteNotes(state, ids)`, `setText(state, id, text)`, `setLineText(state, li, text)`, `addNotesToLine(state, li, k)`, `shiftText(state, id, dir)`, `splitNote(state, id)`, `joinNext(state, id)`, `startLine(state, id)`, `mergeLineAt(state, id)`, `toggleGold(state, ids)`, `retime(state, id, start, length)`; `overlaps(state) -> Set<id>`; `validate(state) -> null \| {message, id}`; `isDirty(state, original)`; история `history(): {push, undo, redo, canUndo, canRedo}`; `beatToMs`, `msToBeat` | нормализацию порядка и `gap`, вычисление битов разрыва |
| `editors/syllables.js` | деление строки на слоги | `toSyllables(text) -> string[]` | правила гласных/согласных |
| `editors/notes-editor.js` (+ при надобности `editors/timeline.js`, `editors/waveform.js`) | экран редактора: таймлайн, панель текста, транспорт, отстукивание, клавиши | `openNotesEditor(song, {reload})` | DOM, мышь, аудио, волна |

**Швы тестов:** `PUT/GET /api/songs/{id}/notes` через `TestClient` (`tests/api/test_songs.py`) и чистые функции `notes-model.js` / `syllables.js` (`node --test tests/frontend/`). UI проверяется вручную в браузере.


## Что построили таски

(дописывается по мере готовности тасков)

## Из таска 01 — сервер нот

- GET `/api/songs/{id}/notes` → `{editable, reason?, bpm, gap, headers:[[k,v]], lines:[{break_beat, player?, notes:[{id, type, start, length, pitch, text}]}]}`; `id` — порядковый номер ноты в файле 0…N-1; `break_beat` строки — разрыв ПОСЛЕ неё (у последней `null`).
- PUT тот же адрес, тело `{gap: number|null, lines:[{break_beat: int|null, notes:[{id: int|null, type, start, length, pitch, text}]}]}`; `id: null` — новая нота, отсутствующие id — удалённые; `editable/reason/bpm/headers` игнорируются. `break_beat: null` у непоследней строки → сервер ставит конец её последней ноты (правило §4 считает клиент). Порядок нот в теле = порядок в файле.
- `gap` null или равен текущему → `#GAP` не трогается; иначе пишется (целое без «.0»).
- 400 `detail` (тексты): «В песне должна остаться хотя бы одна нота»; «Неизвестный тип ноты «X»: строка K, слог «…»»; «Начало ноты раньше бита 0: …»; «Длина ноты — не меньше 1 бита: …»; «Высота ноты — от −40 до 100: …»; «В слоге не может быть перевода строки: строка K»; «Ноты перекрываются: строка K, слог «…»»; «Разрыв строки K должен стоять между концом её последней ноты и началом строки K+1»; «Нота с id N не найдена в файле»; «Нота с id N встречается дважды»; «Раньше начала трека сдвигать некуда: #GAP не может быть меньше 0».
- 409: дуэт / `#RELATIVE` (тексты прежние); нет `#BPM` → «В песне нет #BPM — редактор только для просмотра» (GET отдаёт `editable:false` с этим `reason`).
- Python: `notes_payload(song)`, `apply_notes(song, body: NotesIn)`, `read_only_reason(song)`, `NO_BPM_REASON`.

## Из таска 02 — модель редактора

- `syllables.js`: `toSyllables(text) -> string[]` (лат. гласные подряд — один слог; слово без гласных приклеивается к соседнему).
- `notes-model.js` — State `{editable, reason, bpm, gap, headers, notes, nextId, created}`; нота `{id, src, type, start, length, pitch, text, ls, brk}`: `id` — ключ в редакторе (его передают в операции), `src` — `id` ноты в файле (новые — null), `brk` — прежний бит разрыва у нот с `ls`; `created` — id нот, созданных последней операцией (addNote, splitNote, addNotesToLine). Состояния неизменяемы.
- `fromPayload(data)`, `toPayload(state) -> {gap, lines:[{break_beat, notes:[{id,type,start,length,pitch,text}]}]}`, `lines(state) -> [[note]]`, `lineText(line)` (без «~»), `isFree(text)`.
- Операции: `move(state, ids, dBeat, dPitch)`, `resize(state, id, 'left'|'right', dBeat)`, `addNote(state, {start, pitch, length=4, text='', type=':'})`, `deleteNotes(state, ids)`, `setText(state, id, text)`, `setLineText(state, li, text)`, `addNotesToLine(state, li, k)`, `shiftText(state, id, 1|-1)`, `splitNote(state, id)`, `joinNext(state, id)`, `startLine(state, id)`, `mergeLineAt(state, id)` (склеивает строку ноты с предыдущей), `toggleGold(state, ids)`, `retime(state, id, start, length)`. Ошибка — `throw Error` с русским текстом, вход не меняется.
- Любой сдвиг левее бита 0 (move, resize за левый край, addNote, retime) переносится в `gap` по §5.
- `overlaps(state) -> Set<id>`, `validate(state) -> null | {message, id}`, `isDirty(state, original)` — сравнивает два State: хранить исходное как `fromPayload(data)`.
- `history(limit=200) -> {push(prevState), undo(cur) -> State|null, redo(cur) -> State|null, canUndo(), canRedo()}`.
- `beatToMs(beat, gap, bpm)`, `msToBeat(ms, gap, bpm)`; константы `GAP_ERROR`, `PITCH_ERROR`, `LAST_NOTE_ERROR`.

## Из таска 03 — экран редактора

- `notes-editor.js`: `openNotesEditor(song, {reload})`; `addNotesEditorPlugin(fn)` — `fn(ctx)` вызывается при каждом открытии; плагины регистрируются в `editors/index.js`.
- `ctx.els`: `bar`, `slotPlay` (после масштаба — место для «Отстукивать»), `slotTools` (перед ★ — ⇠ текст / текст ⇢ / Разрезать / Слить / ↵ Строка), `slotEnd` (после «Удалить» — для «?»), `centerTop` (над таймлайном — баннер отстукивания), `panel` (пустой `aside.ne-panel`, hidden; 320px, на телефоне 100vw), `hint`, `main`, `scroll`, `inner`, `roll`, `lane`, `brkLayer` (значки ↵: `.ne-brk b[data-id]` = id ноты, начинающей строку; обработчика клика нет).
- Чтение: геттеры `state`, `selection`, `lastSel`, `posMs`, `playing`; `editable()`; `M` (notes-model).
- Действия: `apply(fn(state)→State, okText)` (история, выделение `state.created`, перерисовка, ошибка → тост); `select(ids, {reveal, add})`, `revealNote`, `editChip`, `render`, `renderSel`, `toast(text, 'err'?)`, `play(fromMs, untilMs)`, `stopPlay`, `seekMs(ms, reveal)`, `playLine`.
- Координаты: `msOf`, `beatOf`, `bx`, `xBeat`, `py`. События: `onRender(f)`, `onSelect(f)`, `onTick(f(posMs, playing))`.
- Клавиши: `addKey({code, ctrl?, shift?, alt?, fn})` — раньше встроенных; `fn` вернул `false` → не обработано; `Esc` перехватывается; `Alt+стрелки` оставлены для 04.
- `shell.js`: `openShell({..., wide})` → ещё `head`, `closeBtn`.
- `timeline-math.js` (чистый): `octaveLabel, clampZoom, zoomScroll, hitZone, peaks, noteAt, rulerStep, pitchRange, ensureVisible`. `waveform.js`: `loadPeaks(url, {signal})`, `drawWave(...)`.

## Из таска 04 — панель текста и инструменты

- Плагины `textPanelPlugin(ctx)` (`notes-text-panel.js`) и `toolsPlugin(ctx)` (`notes-tools.js`), регистрируются в `editors/index.js`; ключ `localStorage` — `notesEditor.textPanelClosed`.
- `notes-panel-logic.js` (чистый): `lineAt(lines, beat)`, `lineStatus(syllables, notes) -> {kind, text, add, addText?}`, `plural(n, forms)`, `tapTiming(downMs, upMs, gap, bpm) -> {start, length}`, `tapQueue(notes, fromId) -> ids`.
- ctx экрана: `apply(fn, okText, {amend})` (amend — дописать в последний шаг отмены), `ctx.playReason()` ('' или причина: нет аудио / нет #BPM), `stepSel` возвращает false на крайних нотах.
- Модель (D01): `lineText` и `joinNext` понимают «~» с пробелами с любой стороны и сохраняют границы слов при пробелах в конце слогов (формат UltraSinger).
