# Интерфейсы и правила сборки

Читать первым. Карта проекта — `CLAUDE.md`; код как он есть — `notes.md`; что строим — `spec.md`.

## Правила проекта

- Интерфейс и все тексты — по-русски. Python 3.12, `from __future__ import annotations`, ошибки API — `ApiError`, исходящий HTTP — только `karaoke_core.http.Http` (`ctx.http`), в тестах — `FakeHttp`, реальные сервисы не трогать.
- Фронт без сборки, ES-модули; чистая логика — отдельными модулями под `node --test tests/frontend/` (новый `*.test.mjs` подхватывается `tests/frontend/index.js` сам — проверь).
- Общие файлы-реестры (`api.js`, `app.css`, `main.py`, `index.html`, `app.js`) — правь точечно, не переписывай.
- `test_repo_config` считает секретом `password|token|secret` с значением после `=`/`:` вне `tests/`.
- Тесты Python — только в Linux-контейнере: `docker --context desktop-linux compose --profile test run --rm tests` (подмножество — `... run --rm tests pytest -q <путь>`). Фронт — `node --test tests/frontend/`.

### Договорились с пользователем — не пересматривать
- Вкладки «Новая песня» в меню и кнопки «+ Новая песня» в «Очереди» нет — только плавающая «+», сразу в форму
- Свои теги — в базе сервиса по «исполнитель — название», файлы песни не меняются; палитра из 8 цветов, по умолчанию синий
- Крупные изменения вида — сначала макет и согласование («Макет ок, собирай» — `.autopilot/2026-10-27-library-tools/mockup.html`)
- Плейлисты (.upl) не делаем: «Пока что не добавляй плейлисты» (R13, R14)
- Микрофона нет: «Думаю можно обойтись без микрофона» — вместо него «проиграть ноту» в редакторе (R38, G02)
- Сервис открывают по `https://karaoke.home` через Caddy с `tls internal`; `http://<IP>:8090` остаётся; основной канал уведомлений — Telegram
- Зеркало само ничего не удаляет: только добавляет и заменяет изменённые
- Звук песни берётся только по ссылке `#VIDEO` или из копии

Новые элементы этой сборки — переключатели и кнопки в существующих панелях, крупной смены вида нет; рамка фокуса пульта — новое CSS-правило, не меняет вёрстку.

## Границы, решённые в спецификации

### `js/tone.js` (дополнить)
- `toneSequence(notes, fromMs = 0, { gain, rate = 1 } = {})` — при `rate ≠ 1` время старта и длительность делятся на `rate` (длительность всё равно через `toneMs`).
- `closeTone()` — останавливает всё звучащее, `audioCtx.close()`, `audioCtx = null`; следующий звук создаёт новый контекст. Безопасна без контекста.

### `js/melody.js` (новый) — планировщик мелодии
- `createMelody({ notes: () => [{pitch, startMs, ms}], rate: () => number }) → { tick(ms, playing), stop(), invalidate() }`
  - `tick` зовут на каждом кадре; планирует порции `MELODY_AHEAD_MS = 4000` (перепланирование, когда до конца порции < 2000 мс), как сейчас в `play.js`; `playing=false` → `stop()`.
  - `stop()` — тишина, сброс плана (пауза, seek, смена скорости).
  - `invalidate()` — ноты изменились: следующая порция берётся из новых `notes()` (уже запланированное доигрывает).
- Чистая часть (что планировать для `ms`, `scheduledUntil`) — экспортируемая функция `nextChunk(all, ms, scheduledUntil, aheadMs)` → `{chunk|null, until}` с тестом в `tests/frontend/melody.test.mjs`. `melodySlice/melodyNotes` остаются в `play-logic.js` (реэкспорт не нужен; `melody.js` их импортирует).

### `js/vocals-logic.js` (новый, чистый) + `js/vocals.js` (DOM)
- `vocalsState({ audio, instrumental }, pref)` → `{ available: bool, reason: ''|NO_INSTRUMENTAL, useInstrumental: bool }`; `NO_INSTRUMENTAL = 'Нет минусовки'`; `readVocalsPref()/saveVocalsPref(on)` — `localStorage audio.vocals` (`'0'` — выкл., иначе вкл.), обёрнуто в try/catch.
- `vocals.js`: `switchSource(audio, url) → Promise` — меняет `src`, восстанавливает `currentTime` и `playbackRate`, продолжает играть, если играло; `createVocalsToggle({ songId, instrumental, onChange(useInstrumental), onReady(instrumentalName) }) → { el, set(on), setInstrumental(name), dispose() }` — переключатель «Вокал» + «Нет минусовки» + кнопка «Сделать минусовку» (`api.instrumental(songId, false)` → `watchJob` из `song-actions.js`; 409 «уже в очереди» → состояние «готовится», опрос карточки `api.song(songId)` раз в 5 с до появления `instrumental`). Класс корня `.vocals-tg`; внешний вид — как `label.pv-tg` в «Прогоне» и `label.check` в редакторе (параметр `variant: 'play'|'editor'`).

### `js/remote-logic.js` (новый, чистый)
- `pickNeighbor(fromRect|null, dir: 'up'|'down'|'left'|'right', candidates: [{rect, id}]) → id|null` — ближайший в полуплоскости направления; вес: расстояние по оси + 2 × смещение поперёк; без `fromRect` — первый сверху-слева.
- `keyCommand(e: {key, code, ctrlKey, altKey, metaKey, shiftKey}, ctx: {inText, inMultiline, inSelect, view})` → `{type: 'move', dir} | {type:'back'} | {type:'tab', index} | {type:'new'} | {type:'search'} | {type:'help'} | {type:'blur'} | null`.
- `GLOBAL_KEYS` — `[[клавиши], описание]` для подсказки.

### `js/remote.js` (новый, DOM) — глобальный пульт
- `initRemote({ views: ['queue','import','songs','trash','settings'] })` — из `app.js` один раз; слушатель `keydown` на `window` (всплытие); пропускает `e.defaultPrevented`, Ctrl/Alt/Meta, открытый `dialog.editor`, открытое меню «…» (`menu.js`).
- Область навигации: открытый модальный `dialog` (кроме редактора) или активная `section[data-view]` + `nav.tabs` + `#fab-new`; кандидаты — видимые `a[href], button:not(:disabled), input:not(:disabled), select, textarea, [tabindex]:not([tabindex="-1"])`.
- `setScreenKeys(view, list)` — список `[[клавиши], описание]` экрана для подсказки (зовут экраны в `show`; пусто — только общие).
- `openRemoteHelp()` — диалог «Клавиши пульта» (`openModal`): «Общие» (`GLOBAL_KEYS`) + «Этот экран».
- Кнопка «⌨» (`button.remote-help`, `aria-label="Клавиши пульта"`) — в шапке `index.html` рядом с вкладками; первый `move` за всё время → тост, ключ `remote.hinted`.
- CSS: `body.kbd` ставится при навигации с клавиатуры (снимается при `pointerdown`); `body.kbd :focus-visible` — рамка 3px `var(--accent)` с отступом.
- Клавиши экранов, которые обрабатывает сам экран (вызывая `preventDefault`): «Песни» (`songs.js`: `P`/⏯, `R`), «Прогон» (`play.js`), редактор (`notes-editor.js` на `dlg`).
- Media Session: `setMediaHandlers({ play, pause, previoustrack, nexttrack } | null)` экспортируется `remote.js` — «Прогон» и редактор ставят и снимают (null).

### Тексты — бэкенд `web/app/lyrics.py`
- `LyricsHit` + поля `source: str = "lrclib"` и `url: str | None = None`; `id` уникален среди источников — строка `"<source>:<id>"`.
- Протокол провайдера: атрибуты `id`, `name`; `search(artist, title) -> list[LyricsHit]`; сбой — `LyricsUnavailable`.
- `LrclibProvider` (как есть, `source="lrclib"`), `NeteaseProvider(http)` (`source="netease"`, до 5 текстов, `synced` из LRC, `text` = `strip_lrc` без строк авторов, «纯音乐» и пустые — пропуск, таймаут 10 с), `GeniusProvider(http)` (`source="genius"`, `text=""`, `url` страницы, `album=None`, до 5, таймаут 15 с).
- `PROVIDERS = ("lrclib", "netease", "genius")`, `make_providers(http) -> dict[id, provider]`, `search_all(providers, artist, title) -> (hits, sources)` — параллельно (`ThreadPoolExecutor`), `sources = [{id, name, ok, error?}]`, сортировка: синхронные первыми, затем порядок источников.
- `GET /api/lyrics/search?artist=&title=&source=` → `{items, sources}`; `source` неизвестен → 400 `field=source`; с `source` и его сбоем → 503 «<Имя> не ответил»; без `source` → 503 «Сервисы текстов недоступны, попробуйте позже», только если не ответил ни один.
- Тесты `tests/api/test_lyrics.py` (дополнить; прежние кейсы LRCLIB живы).

### Тексты — фронт
- `api.lyricsSearch(artist, title, source?)`.
- `lyrics-search.js`: `usableHits` оставляет варианты с `url` и без текста (Genius); `SOURCE_LABELS`, `sortHits`, `isLinkHit(hit)`, `hitLines(text)`; `mergeHits(prev, next)`.
- `lyrics-dialog.js`: `openLyricsDialog` прежней сигнатуры; без `hits` опрашивает источники по одному параллельно, дорисовывает варианты; строки статуса источников; «Просмотр» (полный текст в диалоге, «Вставить», «← К списку»); вариант-ссылка — «Открыть на Genius ↗» без «Вставить».
- `import.js::runLyricsQueue` — `api.lyricsSearch(artist, title)` без `source` (все), выбор как сейчас по `usableHits` без ссылок.

### Очередь
- `db.Jobs.list(limit=50)` — все задания в `queued/running/publishing` + `limit` новейших прочих, `ORDER BY id DESC`; `GET /api/jobs?limit=` без изменения контракта; тест в `tests/core/test_db.py` или `tests/api/test_queue_order.py`.

## Швы тестов
- Python: `tests/api/test_lyrics.py` (провайдеры через `FakeHttp`), тест `Jobs.list`.
- Node: `melody.test.mjs`, `vocals-logic.test.mjs`, `remote-logic.test.mjs`, дополнения `lyrics-search.test.mjs`, `tone.test.mjs`.
- DOM (редактор, «Прогон», пульт, диалог текстов) — вручную в браузере.

## Что построили законченные таски
<!-- дописывается после каждого таска -->
