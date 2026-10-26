# Границы и правила проекта

## Правила проекта (из CLAUDE.md, обязательны)
- Python 3.12, `from __future__ import annotations`, тексты/докстринги — по-русски. Ошибки API — `raise ApiError(status, "текст", field=...)`, не `HTTPException`. Запись в БД — `with _tx(conn)`; новая миграция — `_SCHEMA_V4` в `_MIGRATIONS` (скрипт режется по `;`).
- Чтение файлов песни — только через `Storage` хранилища песни (`ctx.storage(item.target_id)`), через `_storage_call` в `api_songs.py`. Имена файлов — через `naming`.
- Фронт: раздел — `mount(section, ctx)`, `show(params)`, опц. `hide()`; чистая логика — в отдельных модулях без `document` ради `node --test`; DOM — `h()` из `ui.js`; все тексты по-русски.
- Тесты: pytest только в Linux-контейнере (`docker --context desktop-linux compose --profile test run --rm tests`), фронт — `node --test tests/frontend/`. Было 794 passed, 2 skipped и 185 pass — не уменьшаются.
- Не писать в коде `password|token|secret` со значением после `=`/`:` (сканер `test_repo_config`).
- CLAUDE.md обновляет оркестратор, не исполнитель.

## Границы, решённые в спецификации

### core: ключ песни — `core/karaoke_core/naming.py`
- `match_key(artist: str, title: str) -> tuple[str, str]` — переезжает сюда из `web/app/context.py` без изменения поведения; в `context.py` — реэкспорт (`from karaoke_core.naming import match_key`).
- `song_tag_key(artist: str, title: str) -> str` = `"\n".join(match_key(artist, title))` — единственное правило ключа тегов.

### core: теги — `core/karaoke_core/db.py`
- `_SCHEMA_V4`: `CREATE TABLE tags (id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, color TEXT NOT NULL, created_at TEXT NOT NULL)`; `CREATE TABLE song_tags (song_key TEXT NOT NULL, tag_id TEXT NOT NULL, PRIMARY KEY (song_key, tag_id))`; `CREATE INDEX song_tags_tag ON song_tags(tag_id)`.
- `TAG_COLORS = ("blue", "violet", "pink", "orange", "yellow", "teal", "gray", "red")`, `DEFAULT_TAG_COLOR = "blue"`, `TAG_NAME_MAX = 40`.
- `@dataclass Tag(id, name, color, created_at)` + `from_row`, `to_dict()` → `{id, name, color}`.
- `class TagError(ValueError)` с `.field` (`name|color`).
- `class Tags(conn)`:
  - `list() -> list[Tag]` (по имени без регистра), `get(id) -> Tag | None`;
  - `create(name, color=DEFAULT_TAG_COLOR) -> Tag`, `update(id, *, name=None, color=None) -> Tag`, `delete(id) -> int` (сколько связей снято);
  - ошибки `TagError`: пусто «Введите название тега», > 40 «Не длиннее 40 символов», дубль по `name_key` (strip, пробелы схлопнуты, casefold, ё→е) «Такой тег уже есть», цвет не из палитры «Неизвестный цвет»; `update`/`delete` неизвестного id → `KeyError`;
  - `for_songs(keys: Iterable[str]) -> dict[str, list[str]]` — id тегов по ключам одним запросом (порядок — по имени тега);
  - `set_for_song(key: str, tag_ids: list[str]) -> list[str]` — заменяет набор; неизвестный id → `KeyError`;
  - `counts() -> dict[str, int]` — сколько ключей песен у тега.
- `AppContext` получает `self.tags = Tags(conn)` там же, где `songs`/`library`.

### web: API — `web/app/api_tags.py` (новый, подключён в `main.py`) и `api_songs.py`
- `GET /api/tags` → `{tags: [{id, name, color, count}], colors: [...TAG_COLORS], default_color}`.
- `POST /api/tags {name, color?}` → 201 `{id, name, color, count: 0}`; `PUT /api/tags/{id} {name?, color?}` → тег с `count`; `DELETE /api/tags/{id}` → `{ok: true, removed: N}`; ошибки 400 `field=name|color`; нет тега → 404.
- `PUT /api/songs/{song_id}/tags {tag_ids: [str]}` → `{tags: [id]}`; песни нет → 404; неизвестный тег → 400 `field=tag_ids`.
- `GET /api/songs` — у каждого элемента `tags: [id]` (через `Tags.for_songs` одним вызовом); `GET /api/songs/{id}` — тоже `tags`.
- `GET /api/songs/{id}/details` → `{song: <как GET /api/songs/{id}>, headers: {author, bpm, gap, language, year, genre, edition, creator, videogap} (только непустые, строки как в файле), singers: {p1, p2} | null (только у дуэта), media: {audio, instrumental, vocals, video, cover, background, midi} (имя файла или null; `vocals` — `<основа .txt> [Vocals].mp3`, `midi` — первый `.mid`, `background` — из `#BACKGROUND`, если файл есть в папке, сравнение без регистра), files: [{name, size, mtime}] (по имени), copies: [{song_id, target_id, target_name, current}], usdb_url: str | null}`; ошибки как у карточки (404, 503).
- `GET /api/songs/{id}/file?name=<имя>` — отдача с Range через существующий `_media`; имя без `/` и `\` и ровно среди файлов папки (без учёта регистра, отдаётся настоящее имя), иначе 404 «У песни нет такого файла»; `?download=1` → `Content-Disposition: attachment; filename*=UTF-8''<имя>`.
- Копии (`copies`) — песни во всех хранилищах индекса с тем же `match_key(artist, title)`; новый `Library.by_key`/перебор — на усмотрение исполнителя, без N+1 запросов к хранилищам (только индекс).

### фронт: модули и их контракт
- `web/static/js/api.js` — добавить: `api.songDetails(id)`, `api.fileUrl(id, name, {download}={})`, `api.tags()`, `api.createTag({name, color})`, `api.updateTag(id, patch)`, `api.deleteTag(id)`, `api.setSongTags(songId, tagIds)`.
- `web/static/js/menu.js` (DOM) — `openMenu(anchor, items) -> {close}`; `items: [{label, onSelect?, href?, download?, disabled?: string|false, danger?} | 'sep']`; одно открытое меню на странице; Esc/клик вне/выбор закрывают; ↑/↓/Enter; `menuButton(itemsFn, {label='…', title='Ещё действия'}) -> HTMLButtonElement` (`aria-haspopup="menu"`, `aria-expanded`; `itemsFn()` зовётся при каждом открытии).
- `web/static/js/song-actions.js` (DOM) — вынесено из `songs.js`: `songMenuItems(song, env) -> items` (весь набор пункта 4 спецификации), `regenerateHref(song)`, `makeInstrumental(btn, song, env)`, `openVideoDialog(song, env)`, `openCopyDialog(songs, env, {bulk})`, `downloadZip(song)`, `removeSong(btn, song, env)`, `openSongTagsDialog(song, env)`, `watchJob(job, onFinal)`; `env = {targets, currentTargetId, outputOk, trashDays, reload, afterRemove?, tags?}`.
- `web/static/js/tags-logic.js` (чистый) — `TAG_COLORS`, `DEFAULT_TAG_COLOR`, `TAG_NAME_MAX`, `COLOR_LABELS` (по-русски), `tagNameKey(name)`, `tagNameError(name, tags, exceptId=null) -> string|null` (те же тексты, что сервер), `tagsById(tags)`, `songTagList(song, byId) -> [{id,name,color}]` по имени.
- `web/static/js/tags-ui.js` (DOM) — `tagChip(tag, {onClick}?) -> span.tag.user.c-<color>`, `colorPicker(value, onChange)`, `openTagsManager({onChanged})` («Мои теги…»), `openTagsDialog(song, {onSaved})` (её зовёт `song-actions.openSongTagsDialog`).
- `web/static/js/songs-filter.js` — `DEFAULT_FILTER.tag = ''` (`''` все, `'none'` без своих, иначе id); `parseFilter` — строкой; `filterSongs` по `s.tags`; `activeFilterCount(f)` (без `q` и `sort`).
- `web/static/js/song-page-logic.js` (чистый) — `mediaRows(details) -> [{kind: audio|instrumental|vocals|video, label, name|null}]`, `infoRows(details) -> [[label, value]]` (пустые пропущены), `fmtSize(bytes)`, `originLabel(song)`, `lyricsPreview(text, n=12) -> {head, more}`.
- `web/static/js/song-page.js` — раздел `song` (`mount/show/hide`): `<section id="view-song" data-view="song" hidden>` в `index.html`, `song: songPage` в `VIEWS` `app.js`; в `route()` для `song` подсвечивается ссылка `songs`.
- `web/static/js/player.js` (DOM) — `playToggle(button, url)` — одна общая дорожка для «▶» списка; `soloPlayback(mediaEl)` — один играющий плеер на странице.
- `index.html`: убрать `#new` из nav; `<a class="fab" id="fab-new" href="#new" aria-label="Новая песня" title="Новая песня">+</a>` после `<main>`; `app.js` прячет её на разделе `new`.
- CSS (`app.css`): `.fab`, `.menu`, `.menu-item`, `.menu-sep`, `.tag.user` + `.c-<color>` (переменные `--tag-<color>-bg/-fg` в обеих темах), `.song-page`, `.song-hero`, плееры; карточка `.song`: ссылка-область + `.song-quick` (▶ …).

## Тестовые швы
- `tests/core/test_tags.py` — `Tags` (создание/дубль/цвет/переименование/удаление/`for_songs`/`set_for_song`/`counts`) и миграция V3 → V4 в `tests/core/test_db.py`.
- `tests/api/test_tags.py` — REST тегов, `tags` в списке, общий тег у копии во втором хранилище, `details` (vocals/mid/background/headers/files/copies), `file` (Range, чужое имя → 404, `..` → 404, `download=1`).
- `tests/frontend/tags-logic.test.mjs`, `song-page-logic.test.mjs`, дополнения в `songs-filter.test.mjs` (тег, `none`, `activeFilterCount`).
- Экран (меню, «+», страница, плееры) — вручную в браузере.

## Что построили таски

### 01 — теги, сведения, файлы (сервер)
- Всё по контракту выше; сверх него: `Library.copies(artist, title) -> list[LibraryItem]` (по `match_key`, только индекс), `AppContext.tags`, `db.tag_name_key(name)`.
- `details.files[].mtime` — число (Unix-секунды), не ISO; `files` и `/file` — только верхний уровень папки песни.
- `PUT /api/songs/{id}/tags` с неизвестным тегом → 400 «Такого тега нет — обновите страницу», `field=tag_ids`.

### 02 — «+», меню «…», теги, страница песни (фронт)
- `menu.js`: `openMenu(anchor, items) -> {close}`, `menuButton(itemsFn, {label, title, className})`, `closeMenu()`.
- `player.js`: `playToggle(button, url)`, `adoptPlayButton(button, url)`, `soloPlayback(el)`, `pausePlayers()`.
- `song-actions.js`: по контракту + `editorItems(song, env)`, `songMenuItems(song, env, {editors=true})`; `downloadZip(song)`.
- `songs-filter.js`: `DEFAULT_FILTER.tag=''`, `NO_TAG='none'`, `activeFilterCount(f)`; `songs.js` экспортирует `builtinTags(song)`, `songHref(song)`.
- `song-page-logic.js`: `infoRows(details, {date}) -> [[label, value, href?]]`; `tags-logic.tagsById -> Map`.
