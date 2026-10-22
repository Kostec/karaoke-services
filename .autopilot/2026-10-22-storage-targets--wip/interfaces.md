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
