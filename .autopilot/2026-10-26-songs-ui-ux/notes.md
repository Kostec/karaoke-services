# Заметки по коду: «Песни» UI/UX (кнопка «+», меню «…», страница песни, теги)

Только чтение кода; ничего не менялось и не запускалось. Пути от корня `D:\Projects\karaoke-services`.

## 1. Фронт: оболочка

### `web/static/index.html` (54 строки)
- `<head>`: `<link rel="stylesheet" href="/css/app.css">`, `<script type="module" src="/js/app.js">`. `editors.css` подключает сам `editors/shell.js` (`document.head.append(h('link', …))`).
- `<header class="top"><div class="top-inner">`: `.brand` (`<h1>Караоке</h1>`, `#status` с `#status-gpu`, `#status-output`) и `<nav class="tabs" aria-label="Разделы">`.
- Ссылки nav (`a[data-view]`): `#queue` (+ `<span class="badge-count" id="queue-count" hidden>`), **`#new` «Новая песня» (строка 23 — удалять)**, `#import`, `#songs`, `#trash`, `#settings`.
- `<main>`: `<section id="view-<name>" data-view="<name>" hidden>` для queue/new/import/songs/trash/settings. Новая секция `view-song` нужна здесь же.
- Затем `<dialog id="confirm">` (`#confirm-text`, `#confirm-cancel`, `#confirm-ok`, форма `method="dialog"`) и `<div class="toasts" id="toasts" aria-live="polite">`. Плавающую «+» естественно класть сюда же (после `main`) статично, либо создавать в `app.js`.

### `web/static/js/app.js` (93 строки)
- `VIEWS = { queue, new: newSong, import: importView, songs, trash, settings }` — модули `import * as …`. Ключ = имя хэша = `data-view` = суффикс `id="view-…"`.
- `parseHash()`: `location.hash` без `#`, `split('?')` → `{name, params: new URLSearchParams(query)}`; неизвестное имя → `'queue'`. Значит `#song?id=…` заработает после добавления `song: songPage` в `VIDEOS`/`VIEWS` и секции `view-song`.
- `route()`: прячет все `main > section` кроме текущей (`s.hidden = s.dataset.view !== name`); у `nav.tabs a` ставит/снимает `aria-current="page"` по `data-view`; `VIEWS[current].hide?.()` при смене раздела; `VIEWS[name].show(params)` вызывается КАЖДЫЙ раз (в т.ч. при повторном заходе на тот же раздел с другими params).
- Запуск: `for (const [name, view] of Object.entries(VIEWS)) view.mount(document.getElementById('view-'+name), { setQueueCount, refreshStatus })` — mount вызывается один раз для всех разделов на старте; затем `hashchange → route`, `route()`, `queue.startPolling()`, `refreshStatus` каждые 15 с.
- Контракт раздела: `export function mount(section, ctx)`, `export function show(params)` (может быть async), опц. `hide()`.
- Экспорты `renderStatus`, `setQueueCount`. `import './editors/index.js'` регистрирует редакторы.
- Для страницы песни (нет вкладки в nav): `nav.tabs a[data-view="song"]` не существует → `aria-current` не ставится ни у кого; логично подсвечивать «Песни» (править `route()`: для `song` активна ссылка `songs`).

### `web/static/js/ui.js` (114 строк) — помощники
- `h(tag, attrs, ...children)`: `class`→className, `dataset:{}`, `on*` — только функции (addEventListener), `true`→атрибут без значения, `false/null/undefined` пропускаются, дети: Node или текст, массивы выпрямляются (`flat()`), falsy пропускаются.
- `field(label, input, hint)` → `<label class="field">`; `clear(el)` → очищает и возвращает el.
- `confirmDialog(text, okLabel='Да', {danger=false})` → `Promise<boolean>` через общий `<dialog id="confirm">` (`ok.className = danger ? 'danger' : 'primary'`).
- `toast(text, kind='')` (`kind==='err'` — красный, 7 с; иначе 3,5 с) в `#toasts`.
- `runAction(button, fn, okText)` — блокирует кнопку, при ошибке `toast(e.detail||e.message,'err')`, возвращает результат или `undefined`.
- `fmtDate(iso)` (сегодня — время, иначе «д мес, чч:мм» ru-RU), `fmtDuration`, `plural`, `days(n)`, `debounce(fn, ms)`, `songName(artist, title)` → `«A - T»` (с `?` для пустых).
- Готовых помощников «выпадающее меню» / popover / tab-диалога НЕТ — меню «…» писать с нуля. Диалоги в `songs.js` строятся вручную: `h('dialog', {class:'copy-dlg'|'video-dlg'}, …)` → `document.body.append` → `showModal()` (fallback `setAttribute('open','')`) → `el.addEventListener('close', () => el.remove())`.

### `web/static/js/extensions.js`
- `EDITOR_SLOTS = ['lyrics','notes']`; `registerSongEditor(kind, {label, open(song,{reload}), enabled?(song)→true|строка-причина})`; `songEditors()` → `[{kind,label,open,enabled}]` в порядке слотов; `onEditorsChanged(fn)`.
- Регистрация в `editors/index.js`: `lyrics` — «Править текст» (`enabled: lyricsEnabled`), `notes` — «Редактор нот»; `open: (song, opts) => openLyricsEditor|openNotesEditor(song, opts)`. `song` — элемент `GET /api/songs` (минимум `song_id, artist, title, own, …`); `reload` — колбэк перечитать список (на странице песни нужно передавать свой `reload`, перечитывающий `api.song(id)`).

## 2. `web/static/js/songs.js` (464 строки) — устройство

Состояние модуля: `root, listEl, infoEl, bannerEl, emptyEl, errEl, rescanBtn, targetSel, copyAllBtn, resetBtn`, `ctl` (элементы фильтров: `q, artist, instrumental, video, duet, cover, origin, sort`), `data` (ответ `GET /api/songs`), `target` ('' — основная цель), `filter`, `shown`, `scanTimer`, `seq`, `waits`, `watched` (Set id заданий), `trashDays`.
Константы: `TARGET_KEY='songs.target'` (localStorage), `IMPORT_SOURCES=['usdb','files','url']` (дубль из `songs-filter.js`), `WATCH_MS=3000`.

Функции:
- `stored()/remember(id)` — localStorage-запоминание хранилища (с try/catch).
- `watchJob(job)` — опрос `api.job(id)` раз в 3 с; на `JOB_FINAL` (`done|failed|cancelled`) → `load()`, если `root` не скрыт; 404 — снять.
- `choice(name, label, options)` — `<select>` фильтра: `change → setFilter({[name]: value})`, кладёт в `ctl[name]`. Все фильтры-выборы строятся ею и перечислены в `mount()` вручную + в `syncControls()` списком `['instrumental','video','duet','cover','origin','sort']`.
- `mount(section)` — строит DOM (`.view-head h2 Песни`, `.songs-tools` с селектом хранилища и «Обновить», баннеры, `.songs-filters`, `.songs-summary` с `infoEl` и `copyAllBtn`, `emptyEl`, `listEl.songs`); `onEditorsChanged(() => data && render())`.
- `show(params)` — `target = params.get('target') || stored()`, `filter = parseFilter(params)`, `syncControls(); syncHash(); load()`, подгружает `getDefaults().trash_days`. `hide()` — `clearTimeout(scanTimer)`.
- `syncHash()` — `history.replaceState(null,'', '#songs?…')` (не будит роутер). `setFilter(patch)` → merge, `syncControls`, `syncHash`, `render()`.
- `load()` (export) — `api.targetSongs(target)`; на 400 `field=target` — сброс на основную; защита от гонок через `seq`; повтор каждые 2 с, пока `res.scanning || !res.scanned_at` (до 30 раз).
- `rescan()`, `outputOk()` (`data.output.ok !== false`), `targetName(t)`, `otherTargets()` (все кроме `data.target.id`), `renderTargets()`, `renderArtists()` (опции с `artistCounts`).
- `render()` — баннер недоступности хранилища, `shown = filterSongs(data.items, filter)`, строка `infoEl`, `copyAllBtn`, пустые состояния (ссылка `<a class="btn primary" href="#new">Добавить песню</a>` — остаётся валидной), `clear(listEl).append(...shown.map(card))`.
- `tag(text, on, extra)` → `<span class="tag[ on][ extra]">`.
- `downloadZip(e, song)` — `probeDownload(`${link.href}?check=1`)` потом скрытая `<a download>` клик; `aria-busy` как замок; ошибки — `toast(…,'err')`.
- **`card(song)`** — сейчас: `<article class="card song" dataset.id=song_id>`; сетка `64px 1fr` (css `.song`): обложка (`<img class="cover" src=api.coverUrl(id) loading=lazy onerror→noCover()>` или `noCover()` = `div.cover ♪`), `.song-info` (`.song-title` = `song.title || song.txt_name`, `.song-artist`, `.small.muted` = `rel_dir`, `.tags`), `.actions` (на всю ширину, `grid-column: 1 / -1`).
  Теги (`.tag.on`): `song.instrumental` «есть минусовка»; `IMPORT_SOURCES.includes(song.source)` «импорт» / `song.source==='generated'||song.own` «создана сервисом»; `source==='usdb'` «из usdb»; `is_duet` «дуэт»; `video` «видео»; `pending_copies[]` → `.tag.wait` «ждёт копирования в «name»».
  Кнопки `.actions` (все — под `enabled = outputOk()`):
  1. `<a class="btn" href="#new?song=<song_id>">Перегенерировать</a>` (`aria-disabled`, preventDefault если недоступно);
  2. `button` «Минусовка» / «Пересоздать минусовку» → `instrumental(e.target, song)` (disabled без `song.audio`, title «У песни нет аудиофайла»);
  3. «Видео…» → `openVideoDialog(song)`;
  4. `<a class="btn" href=api.zipUrl(id) download>Скачать .zip</a>` → `downloadZip(e, song)`;
  5. «Копировать в…» → `openCopyDialog([song])` (disabled, если `others` пуст; title-подсказка);
  6. `span.song-editors{display:contents}` с кнопками `songEditors()`: `button[data-editor=kind]`, `disabled: !enabled || st !== true`, `title` = строка-причина, `onclick: () => ed.open(song, { reload: load })`;
  7. `button.danger` «Удалить» → `remove(e.target, song)`.
  НЕТ кликабельности самой карточки и НЕТ кнопки «▶» (нужно добавить; плеер — `api.audioUrl(id)` + `<audio>`/`new Audio()` с Range уже поддержан сервером).
- `openCopyDialog(songs, {bulk})` — `dialog.copy-dlg`: радио `copy-target` (другие хранилища), `copy-exists` skip/replace, чекбокс `only-missing` (bulk), → `api.copySongs({song_ids, target_id, replace, only_missing})`, тосты по `{queued, skipped, errors}`, потом `load()`. Использует `otherTargets()`/`targetName`/`data` — для страницы песни нужно вынести (экспортировать или передавать `targets`, `currentTargetId`).
- `noCover()`, `remove(btn, song)` (`confirmDialog` + `api.deleteSong` + тост «перемещена в корзину», `load()`; текст про `trashDays`), `instrumental(btn, song)` (confirm при пересоздании, `api.instrumental(song_id, !!song.instrumental)`, `watchJob`), `currentVideoGap(song)` (`api.notes` → заголовок `VIDEOGAP`), `openVideoDialog(song)` (`createVideoBlock({modes:['url','file'], …})`, `api.video(song_id, form)`, «Убрать видео» через `{remove:true}`, `watchJob`).
- Экспортируются только `mount, show, hide, load`. Диалоги/действия не экспортируются — для страницы песни их надо вынести в общий модуль (напр. `song-actions.js` с `instrumental/openVideoDialog/openCopyDialog/remove/downloadZip` и `watchJob`) и использовать из `songs.js` (меню «…») и `song-page.js`.
- Перезагрузка списка после действий: `load()` (в карточке — после remove/copy/watchJob-финала; редакторам передаётся `reload: load`).

## 3. `web/static/js/songs-filter.js` (119 строк) — чистая логика
- `SORTS` `[{id,label}]` (`artist,title,date_desc,date_asc`); `CHOICES` `{instrumental,video,cover:[all,yes,no], duet:[all,duet,solo], origin:[all,generated,import,foreign]}`; `DEFAULT_FILTER` (frozen): `{q:'', artist:'', instrumental:'all', video:'all', duet:'all', cover:'all', origin:'all', sort:'artist'}`.
- `originOf(song)`, внутренние `has(choice, value)`, `byName/byDate`, `COMPARE`, `fold` (casefold + ё→е).
- `filterSongs(items, f)` — одно большое `items.filter(... && ...)` + `sort(COMPARE[f.sort])`; `artistCounts(items)`; `parseFilter(params)` (URLSearchParams ИЛИ обычный объект; CHOICES валидируются по списку, `q`/`artist` — строки как есть); `filterParams(f)` — только отличное от умолчаний (перебор `Object.keys(DEFAULT_FILTER)`, значения `String`); `isDefaultFilter(f)` (игнорирует `sort`); `publishLine`.
- **Как добавить новый фильтр «теги»**: (1) добавить ключ в `DEFAULT_FILTER` (напр. `tag: ''` — id или список через запятую; `filterParams`/`isDefaultFilter` подхватят сами, т.к. идут по `Object.keys(DEFAULT_FILTER)`); (2) в `parseFilter` — строковый ключ по образцу `artist` (`tag: String(get('tag'))`), т.к. значения не из фиксированного `CHOICES`; (3) в `filterSongs` — условие по `s.tags` (у песни должен быть массив тегов в элементе списка) — ключ сопоставления; (4) в `songs.js` — контрол (select/чипы) в `mount()`, ключ в `syncControls()`, чтение в `setFilter`; (5) тест в `tests/frontend/songs-filter.test.mjs` (хелпер `S(id, o)` с дефолтами — добавить `tags: []`; хелпер `ids(f)`).

## 4. `web/static/js/queue.js` — кнопки «Новая песня»
- `mount()` (стр. ~28–35): пустое состояние `emptyEl` — `h('a', {class:'btn primary', href:'#new'}, 'Добавить песню')` (текст «Заданий нет — добавьте песню»; можно оставить как призыв) и **`view-head`: `h('a', {class:'btn primary', href:'#new'}, '+ Новая песня')` — это удалять**. Больше ссылок на `#new` вне `songs.js` и `index.html` нет (grep): `songs.js` — `Добавить песню` в пустом состоянии и «Перегенерировать» → `#new?song=<id>`; `new-song.js` читает `params.get('song')`.
- `TYPE_LABEL` в queue.js не знает `copy` (генерация/минусовка/выкладка/импорт/видео) — к задаче не относится, но заметка.

## 5. `web/static/css/app.css` (378 строк) — тема и классы
- Тема: переменные в `:root` (`--bg --surface --surface-2 --text --muted --border --accent --accent-text --ok --ok-bg --warn --warn-bg --err --err-bg --log-bg --log-text --radius(10px) --shadow`) и их тёмные значения в `@media (prefers-color-scheme: dark)`. Переключателя темы нет, только системная.
- База: `button, .btn` (min-height/width 44px, `--surface-2`, border), `button.primary/.btn.primary` (accent), `button.danger` (красный контур, прозрачный фон), `.actions` (flex wrap gap 8), `.banner(.err/.warn/.ok)`, `.empty`, `.card` (surface, border, radius, padding 12, margin 10 0), `.muted`, `.small`, `[hidden]{display:none!important}`, `.field`, `.check`, `.row2`, `details.more`, `button.link`, `.tag.bad`.
- Песни: `.songs-tools/.songs-filters/.songs-search/.songs-filter/.songs-target/.songs-summary`, `.song{display:grid;grid-template-columns:64px 1fr;gap:12px}`, `.cover` (64×64, radius 8, `--surface-2`, flex-центр «♪»), `.song-info`, `.song-artist` (muted .9rem), `.song-title` (600), `.tags{flex wrap gap 4 mt 4}`, **`.tag{font-size:.75rem;padding:1px 8px;border-radius:10px;background:var(--surface-2);color:var(--muted)}`, `.tag.on{background:var(--ok-bg);color:var(--ok)}`, `.tag.wait` (warn)**, `.song .actions{grid-column:1/-1;margin-top:0}`.
- Диалоги: `dialog{… width:min(440px, calc(100vw - 24px)); padding:16px}`, `dialog::backdrop`, `dialog .actions{justify-content:flex-end}`, `dialog.lyrics-dlg`, `dialog.video-dlg` (560), `dialog.copy-dlg fieldset`.
- Тосты: `.toasts{position:fixed; left:12px; right:12px; bottom:12px; z-index:50; pointer-events:none}` — **низ экрана уже занят тостами → плавающую «+» ставить `right`, `bottom` с запасом (например bottom: 76px) или z-index ниже 50 и учитывать пересечение на мобильном**.
- Шапка: `.top` sticky только при `min-width:640px` (z-index 10). `main, .top-inner {max-width:960px; margin:0 auto; padding:8px 12px}`.
- Медиазапросы в app.css: `(min-width:640px)` ×4 (sticky шапка, `.row2`, `.target-item`, `.target-kind-grid`), `(max-width:600px)` для `.songs-filter`; в `editors.css`: `(max-width:767px)`, `(max-width:639px)` ×2. Мобильная ширина поддержана (кнопки 44px, flex-wrap, `viewport` meta есть).
- Нет: классов меню/popover, `.tag-chip`, `position:fixed` кнопки, `<audio>/<video>` стилей, hero-обложки. Всё придётся добавлять (CSS-переменные палитры тегов — добавить в оба блока темы).

## 6. API песен (`web/app/api_songs.py`, router prefix `/api`)

Эндпоинты:
- `GET /songs?q=&target=` → `{scanned_at, scanning, output, target: Target.public(), targets: [{id,name,kind}], items: [...]}`; пустой индекс первого показа → `background.add_task(ctx.rescan)`.
- `POST /songs/rescan?target=` (202); `GET /songs/exists?artist=&title=`;
- `GET /songs/{id}` — карточка; `GET /songs/{id}/lyrics`; `GET/PUT /songs/{id}/notes`; `POST /songs/{id}/notes/lines`; `GET /songs/{id}/audio` (Range); `GET /songs/{id}/cover` (Range); `GET /songs/{id}/zip` (`?check=1`); `DELETE /songs/{id}`; `GET /trash`; `POST /trash/{id}/restore`.
- Остальные работающие с песней: `POST /api/jobs/{generate|instrumental|video|copy|import}` в `api_jobs.py`.

Элемент `items[]` (`_song_out` = `ctx.song_dict(item)` + доп.): `LibraryItem.to_dict()` → `target_id, rel_dir, txt_name, artist, title, audio, instrumental, cover, video, is_duet, own_song_id, mtime, scanned_at, song_id` + `own` (bool) + `pending_copies:[{target_id,name,job_id}]` + `source` (`usdb|files|url|generated|null`) + `updated_at` (ISO UTC по mtime .txt или null). Имена файлов (`audio/instrumental/cover/video`) — только базовые имена или null (в `SongEntry._entry`: из заголовков `#AUDIO|#MP3`, `#INSTRUMENTAL`, `#COVER`, `#VIDEO` и только если файл реально лежит в папке).
`GET /songs/{id}` = то же + для своей песни (`own_song_id`) `params` (OwnSong.params из БД — `source`, `usdb_id`, `video_url`, inputs…) и `lyrics` (текст `source/lyrics.txt` или null). Для чужой песни `params`/`lyrics` ключей нет.
`GET /songs/{id}/lyrics` → `{text, source: "own"|"extracted"}` (свой исходный текст из `source/lyrics.txt`, иначе `ultrastar.extract_lyrics` из `.txt`). Фронт: `api.lyrics(id)`.

**Чего НЕТ в ответах**: `#BACKGROUND` (ни в `SongEntry`, ни в `LibraryItem`, ни в БД `library`), `[Vocals].mp3`, `.mid`, `created_at` песни (есть только `updated_at` из mtime; у `OwnSong` есть `created_at`/`updated_at`, но наружу не отдаются, только `params`), размеры файлов, список всех файлов папки, `#BPM/#GAP/#LANGUAGE/#YEAR`, прочие заголовки (для заголовков есть `GET /notes` → `headers: [[k,v]]`, но он тяжёлый и 409-ит `editable:false` только по флагу; `headers` отдаются всегда).
- Список «хранилища/копии песни» (та же песня в других хранилищах) тоже нигде не отдаётся: `song_id` у каждой копии свой (`sha1(target_id+rel_dir)`); искать копии нужно по `match_key(artist,title)` или `rel_dir` во `library` по всем `target_id` (в `Library` метода «все копии» нет; есть `list(target_id)` и `find(song_id)`).

Выбор файлов (`/audio`, `/cover`): `_media(ctx, item, name, request, default_type)` — `name` берётся из `item.audio` / `item.cover` (одно поле), 404 «У песни нет такого файла», если None; `storage.stat(rel)`, `mimetypes.guess_type(name)`, парсинг `Range: bytes=a-b` (`_RANGE_RE`, 416 при плохом), `storage.open_read(rel)` + `seek` + чанки по 64 КБ, 200/206, `Accept-Ranges`, `Content-Length`. Параметра для минуса/вокала/видео/фона НЕТ. Эндпоинта «отдать произвольный файл песни» нет — только `_media` под `audio` и `cover` (`item.instrumental`, `item.video` в нём не используются). Для плееров минуса/вокала/видео и фона нужен новый эндпоинт, напр. `GET /api/songs/{id}/file?name=<имя файла в папке>` (проверка, что имя без `/` и `\` и реально в `storage.listdir(rel_dir)`; переиспользовать `_media(ctx, item, name, request, default_type)` как есть) либо `/media/{kind}` (`audio|instrumental|vocals|video|background|cover`). Полный список файлов папки уже умеет `_song_files(storage, rel_dir)` (используется в zip) → готовая основа для «Файлы» (`path`, `Entry.size/mtime`).
Имена по конвенции `naming`: `SUFFIX_INSTRUMENTAL = " [Instrumental].mp3"`, `SUFFIX_VOCALS = " [Vocals].mp3"`, `SUFFIX_MIDI = ".mid"`, `SUFFIX_AUDIO=".mp3"`, `SUFFIX_TXT=".txt"`, `cover_suffix`, `VIDEO_EXTS`, `video_file_name()`, `base_name(a,t)`; `ctx.library` для вокала/mid/фона ничего не хранит — вычислять из `listdir`/заголовков `.txt` на запрос страницы.

Прочее в `api_songs.py`: `_storage_call(ctx, fn, *a, target_id=)` (StorageNotFound→404/503; StorageError→503 «Папка результата недоступна: …» + `ctx.mark_output_error`), `_song_storage(ctx,item)`, `_read_txt(ctx,item)` (читает `.txt` песни), `_own_lyrics`, `_pending_copies`, `ctx_of(request)` из `api_jobs`, `ApiError(status, text, field=)`, `not_found()`; все ответы JSON, ошибки `{detail}`. Роутеры подключаются в `main.py` (`include_router`, `import_router` раньше `jobs_router`); новый `api_tags.py` — подключить там же.

### Storage (`core/karaoke_core/storage/base.py`)
- `SongEntry(rel_dir, txt_name, artist, title, audio, instrumental, cover, video, is_duet, mtime)` (+`to_dict`, `to_library_item(target_id, own_song_id, scanned_at)`); `Entry` (name, is_dir, size, mtime).
- Методы чтения: `read(rel)->bytes`, `open_read(rel)->BinaryIO` (GuardedFile; `seek/read/close`), `exists`, `stat(rel)->Entry|None`, `listdir(rel_dir)`, `sizes(rel_dir)`, `read_song(rel_dir)->SongEntry|None`, `list_songs(max_depth=4)`; запись `write_atomic`, `upload_dir`, `download_dir`, `delete_dir`, `delete_file`. `_entry()` собирает `SongEntry` из заголовков `.txt` (`existing()` — регистронезависимое сопоставление имени; видео — `naming.video_file_name(header VIDEO)`).
- Чтобы добавить в индекс/страницу `#BACKGROUND`: добавить поле в `SongEntry` + `LibraryItem` + миграцию (`library.background`), ИЛИ (проще, без миграции) читать заголовок и `listdir` в новом эндпоинте страницы песни. `ctx.library_item/refresh_song` (context.py 255–275) строят `LibraryItem` из `SongEntry`.
- `ultrastar.parse(bytes)->Song`, `song.header(key, default)`, `song.header_items()`, `ultrastar.extract_lyrics(song)`; `set_header_line`.

## 7. БД (`core/karaoke_core/db.py`, 961 строка)

- Схема: `_SCHEMA_V1` (многострочные `CREATE TABLE jobs/settings/library/songs` + `CREATE INDEX jobs_state`), `_SCHEMA_V2 = "ALTER TABLE library ADD COLUMN video TEXT"`, `_SCHEMA_V3 = "ALTER TABLE library ADD COLUMN song_id TEXT; UPDATE library SET song_id = karaoke_song_id(target_id, rel_dir); CREATE INDEX library_song_id ON library(song_id)"`; `_MIGRATIONS = [V1, V2, V3]`. `connect(path)`: WAL, `busy_timeout`, `conn.create_function("karaoke_song_id", 2, song_id_for, deterministic=True)`, `_migrate(conn)` — в `BEGIN IMMEDIATE` читает `PRAGMA user_version` и применяет `_MIGRATIONS[version:]`, каждый скрипт режется по `;` (**значит в DDL нельзя `;` внутри строк/триггеров**) и пишет `PRAGMA user_version = i`. `_tx(conn)` — контекст `BEGIN IMMEDIATE/COMMIT/ROLLBACK`; соединение `isolation_level=None`, `row_factory=sqlite3.Row`.
- **Новая миграция тегов** = `_SCHEMA_V4 = "CREATE TABLE tags (...); CREATE TABLE song_tags (...)"` + добавить в `_MIGRATIONS`. Тесты миграций из старых версий собирают БД так: `conn.executescript(db._SCHEMA_V1 + ";" + db._SCHEMA_V2 + ";PRAGMA user_version = 2;")` — имена `_SCHEMA_Vn` используются тестами напрямую.
- Обёртки: `Jobs(conn)`, `Settings(conn, env)` (приватные `_get/_set/_json/_put_json`, JSON в таблице `settings` key/value), `Library(conn)` (`_insert/replace_all/upsert/remove/list/find/get`), `Songs(conn)` (`get/by_rel_dir/get_many/upsert/delete`, dataclass `OwnSong.from_row`). Образец короткой обёртки для `Tags`:
  ```python
  class Songs:
      def __init__(self, conn: sqlite3.Connection):
          self.conn = conn
      def get(self, id): row = self.conn.execute("SELECT * FROM songs WHERE id=?", (id,)).fetchone(); return OwnSong.from_row(row) if row else None
      def delete(self, id): with _tx(self.conn): self.conn.execute("DELETE FROM songs WHERE id=?", (id,))
  ```
  с `@dataclass` + `from_row(cls, row)` + `to_dict()`; ключ-перебор `get_many(ids)` — `IN (?,?…)`. Запись — всегда `with _tx(self.conn):`; чтение — без `_tx`. `uuid.uuid4().hex` — паттерн для id; `now()` — формат времени.
- Где создаются обёртки: `AppContext.__init__` (`web/app/context.py`: `self.jobs/self.settings/self.library/self.songs/self.trash…` — смотреть, как строится `AppContext`, и добавить `self.tags = Tags(conn)`); worker-контекст `JobContext` их не обязан знать.
- `match_key(artist, title) -> tuple[str,str]` — в `web/app/context.py:329` (НЕ в core): `fold(s) = naming.safe_name((s or "").strip().casefold().replace("ё","е"))`; «без регистра и ё/е, запрещённые символы как в `safe_name`, пробелы и пунктуация значимы». Рядом `song_key(artist,title)` = `naming.song_dir(...).casefold()`. Используется в `find_by_name`/`existing_song_id`. Для тегов в БД ключ надо хранить строкой: напр. `"{a}\n{t}"` или `f"{a} — {t}"` из `match_key`; но `match_key` живёт в web — для core-класса `Tags` ключ передавать готовым (или вынести функцию в `core/karaoke_core/naming.py`; тогда `context.match_key` оставить реэкспортом, `from .context import match_key` встречается в других модулях — проверить grep перед переносом).
- ВАЖНО: `song_id` у каждой копии песни в каждом хранилище свой (`sha1(target_id\nrel_dir)[:16]`), а `OwnSong.id` (`songs.id`) — uuid только у созданных сервисом (`own_song_id`). Поэтому теги по ключу «исполнитель — название» (а не по `song_id`) — верное решение: общие для всех копий и переживают миграцию `song_id`. При переименовании песни (правка `#ARTIST/#TITLE`/перегенерация с новым именем) привязка теряется — стоит учесть.

## 8. Тесты

### `tests/api/` (pytest, `TestClient`)
- `conftest.py`: константы `MP3`, `SONG_TXT` (Artist/Song, `#MP3`, `#AUDIO`, `#COVER`, `#BPM:300`, `#GAP:1000`, `#X-CUSTOM:keep`), `DUET_TXT`; `ENV_EXAMPLE` (из `.env.example`); `class Env(tmp_path)` — `.tmp .out(output) .data`, `put_song(rel_dir, txt_bytes, base, *, audio=MP3, cover=…)` (создаёт `<base>.txt/.mp3/[CO].jpg` в `out/<rel_dir>`), `factory(target)` (local `/output`→`out`, `/host/…`→`tmp/host`), `client(password='', storage_factory=None, extra_env=None, **kw)` → `TestClient(create_app(data_dir, env, storage_factory, **kw))`. Фикстуры: `env`, `client` (контекст-менеджер), `song` (кладёт Artist/Artist - Song, `POST /api/songs/rescan`, возвращает элемент `GET /api/songs`).
- `tests/api/test_songs.py` (653 строки): `test_list_rescan_and_search`, `test_exists`, `test_song_card_and_lyrics`, `test_own_song_card_has_params_and_own_lyrics` (`Songs(connect(env.data/'karaoke.sqlite')).upsert(...)` — образец прямого доступа к БД из API-теста), notes PUT/GET, audio Range, zip, delete/restore. Для vocals/mid/background в тесте — класть файлы руками в `env.out/<rel_dir>/` (`(d / "Artist - Song [Vocals].mp3").write_bytes(...)`), заголовок `#BACKGROUND:…` дописывать в txt.
- `tests/api/test_targets_songs.py`: `_other_target(env, client)` — второе хранилище `Target(name="ПК", kind="local", path="/host/pc")` через `Settings.save_target`, `client.app.state.ctx.refresh_song(REL, target.id)`; полезно для теста «копии в нескольких хранилищах».
- Новый тест тегов: `tests/api/test_tags.py` (по образцу test_songs).

### `tests/core/test_db.py`
- Фикстуры `path` (`tmp_path/'karaoke.sqlite'`), `jobs` (`db.Jobs(db.connect(path))`); тесты обёрток вида `db.Library(db.connect(path))`; миграции: `test_old_v1_database_migrates_to_video_column`, `test_v2_database_gets_song_id_column_and_find_uses_index` (собирают БД из `db._SCHEMA_V1/_V2` через `sqlite3.connect(path).executescript(...)`, затем `db.connect(path)`). Новый `test_v3_database_gets_tags_tables` по образцу; отдельный `tests/core/test_tags.py` допустим.
- Заметка: в `tests/core/test_repo_config.py` — не писать в коде `password/token/secret` со значением.

### Фронт-тесты
- `tests/frontend/index.js` — автозагрузчик: `readdirSync(here).filter(f => f.endsWith('.test.mjs')).sort()` → `await import(...)`. Новый тест-файл `tests/frontend/<имя>.test.mjs` подхватится сам, ничего регистрировать не надо; запуск `node --test tests/frontend/` (185 pass). Формат: `import test from 'node:test'; import assert from 'node:assert/strict'; import {…} from '../../web/static/js/<модуль>.js'`. Тестируются только чистые модули без DOM (`songs-filter`, `targets-logic`, `video-block` чистые функции). Образец — `tests/frontend/songs-filter.test.mjs` (хелпер `S(id, o)`, `ids(f)`). Новые чистые модули (теги: `tags-logic.js` — палитра, `toggleTag`, фильтр; `song-page-logic.js` — состав «что есть», секции файлов, форматы) — под такие тесты; `h()`/DOM в них не импортировать (`document` в Node нет).

## 9. Как фронт получает текст/фон/вокал/mid (итог)
- Текст: `api.lyrics(id)` → `{text, source}` (own/extracted); либо `lyrics` в `GET /songs/{id}` для своих. Для страницы песни хватит `api.lyrics`.
- Фон `#BACKGROUND`: фронту недоступен; нужен серверный путь (новое поле/эндпоинт). Обложка — `api.coverUrl(id)` (`item.cover` из `#COVER`).
- `[Vocals].mp3` и `.mid`: в индексе их нет вообще (`SongEntry` не знает); определяются только по `listdir` папки. Реально ли они лежат в папке песни после `finalize` — проверить в `core/karaoke_core/postprocess.py` (использует `SUFFIX_VOCALS`/`SUFFIX_MIDI`).
- Видео: в списке есть `video` (имя файла), эндпоинта отдачи нет.

## 10. Краткие выводы (10 строк)
1. Роутер хэш-based: достаточно добавить `song: songPage` в `VIEWS`, `<section id="view-song" data-view="song">` и подсветку «Песни» в `route()`; `show(params)` получает `URLSearchParams` (`params.get('id')`).
2. Меню «…» и «▶» писать с нуля (в `ui.js` нет popover/menu/dropdown); диалоги/действия из `songs.js` (`openCopyDialog`, `openVideoDialog`, `instrumental`, `remove`, `downloadZip`, `watchJob`) не экспортируются и завязаны на `data/otherTargets/load` — их надо вынести в общий модуль и параметризовать, иначе страница песни продублирует ~250 строк.
3. Карточка сейчас НЕ кликабельна и без «▶»; кнопки редакторов идут через `songEditors()` (`ed.open(song, {reload})`, `enabled` → строка-причина) — в меню нужно отрисовать их тем же циклом.
4. `GET /songs/{id}/audio|cover` берут ровно `item.audio|cover`; для минуса/вокала/видео/фона нет эндпоинта — нужен `GET /songs/{id}/file?name=` (или `/media/{kind}`) поверх готового `_media()` (Range есть) и `_song_files()` для списка файлов.
5. Индекс (`library`) не хранит `#BACKGROUND`, `[Vocals]`, `.mid`, размеры, прочие заголовки — «что есть»/«файлы»/фон лучше собирать новым `GET /api/songs/{id}/details` (listdir + заголовки `.txt`) без миграции индекса.
6. «Копии/хранилища» песни: у каждой копии свой `song_id`; метода «все копии» в `Library` нет — искать по `match_key(artist,title)`/`rel_dir` по всем `target_id` (добавить `Library.copies(artist, title)` или считать в API).
7. Теги: миграция `_SCHEMA_V4` (скрипты режутся по `;`; тесты миграций используют `db._SCHEMA_Vn` напрямую); класс `Tags(conn)` по образцу `Songs` (`_tx` на запись); `match_key` лежит в `web/app/context.py`, не в core — ключ передавать готовой строкой или вынести в `naming`.
8. Для фильтра по тегам в списке элементу `items[]` нужно поле `tags` (id/цвета) — добавлять в `_song_out`, одним запросом на все песни (как `songs.get_many`), чтобы не делать N+1; фильтр в `songs-filter.js`: ключ в `DEFAULT_FILTER`, строка в `parseFilter` (как `artist`), условие в `filterSongs`.
9. Тост-контейнер занимает низ экрана (`position:fixed; bottom:12px; z-index:50`) — «+» поднять выше/сдвинуть вправо; CSS-переменных палитры тегов нет — добавить в светлую и тёмную темы (тёмная только через `prefers-color-scheme`).
10. Неожиданности: `IMPORT_SOURCES` и `originOf` продублированы в `songs.js`/`songs-filter.js`; `queue.js` `TYPE_LABEL` не знает `copy`; в Node-тестах нельзя импортировать модули с `document` (`ui.js` и пр.); после правок фронта — `up -d --build web` и Ctrl+F5.
