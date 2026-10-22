# Интерфейсы

## Правила проекта (для каждого исполнителя)

- Проект описан в `CLAUDE.md` в корне — прочитай его первым: команды, структура, соглашения, подводные камни. Всё, что там сказано, обязательно.
- Python 3.12, `from __future__ import annotations`, docstring/комментарии/тексты ошибок — по-русски. Ошибки API — `ApiError(status, "текст", field=...)`. Ошибки задания — `JobFailed(reason, user_message)`.
- Пути тома data — только через `DataPaths`; имена песен — только через `naming`; запись в хранилище — только через `Storage`; исходящий HTTP — только через `karaoke_core.http.Http`.
- Тесты Python — только в Linux-контейнере: `docker --context desktop-linux compose --profile test run --rm tests` (полный прогон; базовая линия до этой сборки — 679 passed, 2 skipped), подмножество — `... run --rm tests pytest -q tests/api/test_x.py`. После смены зависимостей — `run --build`. Фронт: `node --test tests/frontend/` (базовая линия 162 pass).
- Реальные Яндекс/Google/SMB в тестах не трогать: `FakeHttp`, `storage_factory=`, фейки `*_CMD`.
- Новая переменная окружения → `.env.example` с русским комментарием строкой выше (проверяет `tests/core/test_repo_config.py`). Слова `password|token|secret` с `=`/`:` и значением вне `tests/` — запрещены сканером: в коде `b['password']`, позиционные аргументы, иные имена переменных.
- Не хватает зависимости → верни `BLOCKED`, ничего не ставь сам (кроме явно названного в таске).
- Форк UltraSinger (`D:/Projects/UltraSinger`) не трогать.
- Docker — только `--context desktop-linux`; движок не переключать. Пересобирать/перезапускать боевые контейнеры web/worker не нужно — это делает оркестратор.

## Границы, решённые в спецификации

| Модуль | Владеет | Выставляет | Прячет |
|---|---|---|---|
| `karaoke_core.db` (Settings) | список хранилищ, основная цель, миграция | `Target` (dataclass: `id, name, kind, path, host, share, user, url, preset, client_id, secret, token`, `.public()`, `.label`), `Settings.get_targets() -> list[Target]`, `get_target(id) -> Target\|None`, `save_target(Target) -> Target` (секрет None — прежний), `delete_target(id)`, `get_default_target_id()/set_default_target_id(id)`, `LOCAL_TARGET_ID = "local"` | формат JSON в `settings`, миграцию `output → targets`, переписывание `library/trash` |
| `karaoke_core.storage` | доступ к файлам хранилища | `make_storage(target: Target, *, http=None) -> Storage`; классы `LocalStorage`, `SmbStorage`, `WebDavStorage`, `GDriveStorage` с прежним интерфейсом `Storage` | протоколы, кэши путей, обновление токена |
| `web/app/api_targets.py` | REST хранилищ | `GET/POST /api/targets`, `PUT/DELETE /api/targets/{id}`, `POST /api/targets/test`, `PUT /api/targets/default {id}`, `GET /api/targets/browse`, `GET /api/targets/gdrive/auth`, `/gdrive/callback`, `/gdrive/draft/{draft}` | проверку перед сохранением, правило «пустой секрет — прежний», OAuth-черновики |
| контексты (`AppContext`, `JobContext`) | кэш открытых хранилищ | `storage(target_id=None)`, `targets()`, `default_target()` | закрытие/пересоздание при смене конфигурации |
| worker `handlers` | выкладку, копирование | `publish_song` (локально + цель), `HANDLERS["copy"]` | ожидание цели, порядок замены |
| `songs-filter.js` | фильтры/сортировка «Песен» | `filterSongs`, `artistCounts`, `parseFilter`, `filterParams`, `SORTS` | — |
| `notes-model.js` | модель | `moveBreak(state, id, beat, voice?)` | — |

`/api/settings/output` (GET/PUT/test) остаётся для совместимости: GET — основная цель в прежнем формате, PUT — правит её (или создаёт SMB/локальную и делает основной). Новый фронт им не пользуется.

**Швы для тестов** (существующие): `create_app(..., storage_factory=, http=FakeHttp())` + `TestClient` для API; `run_forever(...)` для воркера; `node --test` для чистых модулей. `WebDavStorage`/`GDriveStorage` проверяются через `FakeHttp`. Экран редактора и «Настроек» — вручную.

## Что построено (дописывается по мере сдачи тасков)

## Из таска 06 — редактор нот

- `notes-model.js`: `moveBreak(state, id, beat, voice = null) -> state` (`id` — первая нота строки; без изменений — то же состояние; ошибки по-русски, в т.ч. `OTHER_VOICE_ERROR`)
- `notes-panel-logic.js`: `PANEL_WIDTH = 320`, `panelWidth(w, winW) -> px` (240…70 % окна)
- DOM: `.ne-brk > i.ne-brk-grip[data-id][data-voice]`, призрак `.ne-brk.ghost`, `.ne-inner.brk-dragging`; ручка панели `.ne-pgrip`, CSS `--ne-panel-w`, `localStorage` `notesEditor.textPanelWidth`; строка панели — `textarea rows=1` (перенос), пунктир разрыва рисуется на бите `- N`, если он в паузе

## Из таска 01 — ядро хранилищ

- `db.Target(id="", name="", kind="local", path="", host="", share="", user="", url="", preset="", client_id="", secret=None, token=None)`; `.label`, `.public()` → `{id,name,kind,path,host,share,user,url,preset,client_id,has_password,connected,label,builtin}`, `.password` (= secret), `.builtin`, `._to_dict()`; у `local` `path` — абсолютный путь в контейнере (`/output…`, `/host…`)
- `db`: `LOCAL_TARGET_ID="local"`, `TARGET_KINDS`, `NO_DEFAULT_DELETE`, `builtin_local_target()`, `legacy_target_id(target) -> str|None`, `new_target_id()`
- `Settings`: `get_targets()` (local первым; при первом чтении — миграция), `get_target(id)`, `save_target(Target) -> Target` (пустой id → `t_<8hex>`; secret/token None — прежние; ValueError: local/неизвестный тип/id), `delete_target(id)` (ValueError: local, основная — «Сначала выберите другую основную цель»; стирает строки library), `get_default_target_id() -> str` (нет/удалена → "local"), `set_default_target_id(id)` (ValueError, если нет), `resolve_target_id(any_id) -> str|None` (новый или старый `smb://…`/`local:/output…`)
- `Settings.get_output()/set_output(OutputTarget)` — только совместимость `/api/settings/output`
- `Library.find(song_id) -> LibraryItem|None` (по всем хранилищам); `Trash.retarget(resolve) -> int`
- `storage.make_storage(target: Target, *, http=None) -> Storage`; `STORAGE_KINDS: dict[kind, factory(target, http)]` — точка регистрации `webdav`/`gdrive`; `Storage.target_id == Target.id`
- `AppContext`/`JobContext`: `storage(target_id=None)` (любой формат id, None — основная; удалено → StorageError), `targets()`, `default_target()`, `target()` (= основная, Target), `target_of(id)`, `local_storage()`, `reset_storage(target_id=None)`, `migrate_targets()` (lifespan веба, старт воркера); `storage_factory` получает `Target`
- `AppContext.output_status(fresh=False, target_id=None)` → `{ok,label,error,id,name}` (+`default`, `local` без target_id), `mark_output_error(e, target_id=None)`, `refresh_song(rel_dir, target_id=None)`
- `api_jobs.replace_target_id(ctx, existing, source) -> str` (и в `api_import`); перегенерация с заменой пишет в хранилище заменяемой песни (`params.target_id`)
- `song_id` по-прежнему `sha1(target_id + rel_dir)` — после миграции id песен новые
- репар таска 01: `handlers._reset(ctx, target_id)` сбрасывает одно хранилище; `_publish_error(ctx, e, note="", *, target_id=None)`; миграция чистит строки library со старым id

## Из таска 02 — сетевые хранилища

- `WebDavStorage(url, user, password, path="", *, http, target_id="", label="", tmp_dir=None)`; Яндекс Диск — url `https://webdav.yandex.ru`
- `GDriveStorage(client_id, client_key, oauth_json, path="", *, http, target_id="", label="", tmp_dir=None)` (позиционно; имена из-за сканера секретов)
- `GDriveStorage.exchange_code(http, client_id, client_secret, code, redirect_uri) -> str` — JSON `{access_token, refresh_token, expiry}` (expiry — Unix-секунды); сбой → `StorageError` «Google не дал доступ: …»; эту строку кладут в `Target.token`
- `STORAGE_KINDS["webdav"|"gdrive"]`; `make_storage(target, http=None)` без http создаёт `Http()`
- `Http.request(data=<двоичный файл>)` (Content-Length задаёт вызывающий), `Http.download(..., headers=None)`
- `tests/fakes_http.py`: `FakeWebDav(http, base_url, root, user, pw)` (`.fail`), `FakeDrive(http, root, client_id=, client_key=, refresh=, page_size=)` (`.expire()`, `.revoked`, `.codes`, `API/UPLOAD/TOKEN`)
- `probe()` у сетевых: папки из пути нет → «не найдена» (запись создаёт её сама)

## Из таска 04 — выкладка и копирование

- `db.Jobs.claim_next` пропускает задания с `params.retry_at` в будущем; `Jobs.active(type) -> list[Job]`
- `handlers.HANDLERS["copy"] = CopyHandler()` (needs_gpu=False); `enqueue_copy(ctx, *, artist, title, rel_dir, txt_name, from_target, to_target, replace, wait, parent_id=None) -> Job` (возвращает уже активное такое же); `COPY_RETRY_S=60`, `COPY_LOG_EVERY_S=600`
- copy params `{rel_dir, txt_name, from_target, to_target, replace, wait}` + служебные `retry_at`, `wait_logged_at`; этап «Ждёт хранилище «X»»; `progress.STAGE_COPY_DOWNLOAD`, `STAGE_COPY`
- `POST /api/jobs/copy` `{song_ids, target_id, replace=false, only_missing=true}` → 201 `{queued, skipped, errors:[{song_id, detail}]}`; `api_jobs.active_copy(ctx, rel_dir, from_target, to_target)`; `MAX_COPY_SONGS=1000` (400 `field=song_ids`)
- у песни в `GET /api/songs` и `/{id}` — `pending_copies: [{target_id, name, job_id}]`
- `publish_song`: локально → основная цель; сбой основной → `done` + `copy` с `wait`; перегенерация с заменой — новая выкладка, прежняя версия меняется в хранилище песни

## Из таска 03 — API хранилищ и «Настройки»

- `GET /api/targets` → `{targets:[Target.public()], default_id, roots:{host: bool, output: true}}`
- `POST /api/targets`, `PUT /api/targets/{id}`: `{id?, name, kind: local|smb|webdav|yandex|gdrive, path, host, share, user, url, preset, client_id, password?}` → `Target.public()`; probe перед сохранением; `yandex` → `webdav` + `preset=yandex`; `gdrive` через POST → 400 (только через вход в Google)
- `DELETE /api/targets/{id}` → `{ok}` (local 400, основная 409, нет 404); `PUT /api/targets/default {id}`; `POST /api/targets/test` → `{ok, label}`
- `GET /api/targets/browse?root=host|output&path=` → `{root, root_name, path, abs, parent, dirs}`
- Google: `POST /api/targets/gdrive/draft` → `{draft}`; `GET /gdrive/auth?draft=` → 302; `/gdrive/callback` → HTML; `GET /gdrive/draft/{d}` → `{state, error?, target?}`
- `HOST_FOLDERS_ROOT` (по умолчанию `D:/`) → `/host` у web и worker; фронт зовёт `/api/targets` через `request()` из `api.js`
- репар таска 02: `HttpError(message, status=None, *, too_large=False, body=b"")`; Drive повторяет 429/403 rateLimit (1,2,4 с, `gdrive.SLEEP`), затем «Google Диск: превышен лимит запросов, попробуйте позже»; `_replace` без потери прежнего файла; `probe()` создаёт отсутствующую папку
- репар таска 03: «Папка ПК» = /output → 400; `targets-logic.js`: `KIND_FIELDS, formKind(t), targetBody(kind, values, {id}), savedBody(t), fieldTarget(field, kind), needsLocalHint(hostname), sameAccount(kind, values, t)`; `api_targets.GOOGLE_RETRY`
- репар таска 04: правило дубля и params copy — только `db.Jobs.active_copy(rel_dir, from_target, to_target) -> Job|None` и `Jobs.enqueue_copy(song_ref, *, rel_dir, txt_name, from_target, to_target, replace=False, wait=False, replace_rel_dir=None, after_job=None, parent_id=None) -> Job` (API и воркер зовут их; `handlers.enqueue_copy` больше нет); copy ждёт `after_job` (этап «Ждёт задание #N»); минусовка после импорта — один раз в `local`, затем copy с `replace=true, after_job` в каждое другое хранилище выкладки; отложенная copy убирает `replace_rel_dir` в корзину цели

## Из таска 05 — вкладка «Песни»

- `GET /api/songs?target=<id>` (нет — основная; неизвестный → 400 `field=target`) → +`targets:[{id,name,kind}]`, `target: Target.public()`, `output` — статус выбранного; у песни `updated_at` (ISO UTC из mtime .txt), `source: usdb|files|url|generated|null`
- `POST /api/songs/rescan?target=`; `AppContext.rescan(target_id=None)`
- `GET /api/songs/{id}/zip` — потоковый zip, `filename*=UTF-8''<A - T>.zip`, внутри `<A - T>/…`; недоступно → 503
- `songs-filter.js`: `SORTS, CHOICES, DEFAULT_FILTER, originOf(song), filterSongs(items,f), artistCounts(items), parseFilter(params), filterParams(f), isDefaultFilter(f), publishLine({targets,default_id})`
- `api.js`: `api.targetSongs(target,q), api.rescanTarget(target), api.zipUrl(id), api.copySongs(body), api.targets(), probeDownload(url)`
- адрес `#songs?target=&q=&artist=&instrumental=&video=&duet=&cover=&origin=&sort=`; `localStorage` `songs.target`
- репар таска 05: `GET /api/songs/{id}/zip?check=1` → `{ok, files}` без чтения файлов; `POST /api/songs/rescan?target=` → 202, сканы по одному через `_scan_queue`; сбой открытия/листинга → `scan_state[id].error` + `mark_output_error`
