# 02 — Сетевые хранилища: WebDAV (Яндекс Диск) и Google Диск

**Требования:** R17, R18, R20 (сетевой путь WebDAV)
**Blocked by:** 01
**Зона:** `core/karaoke_core/storage/webdav.py` · `core/karaoke_core/storage/gdrive.py` · регистрация в `core/karaoke_core/storage/__init__.py` (только словарь фабрик) · `tests/core/test_storage_webdav.py` · `tests/core/test_storage_gdrive.py` · `tests/fakes_http.py` (только дополнять)
**Волна:** 2
**Status:** ready

## Что должно заработать

Две новые реализации `Storage` с прежним интерфейсом (`read`, `open_read`, `write_atomic`, `upload_dir`, `download_dir`, `delete_dir`, `list_songs`, `read_song`, `probe`, …), так что весь остальной код — индекс, выкладка, корзина, zip, копирование — работает с ними без изменений.

- `WebDavStorage(url, user, password, path, *, http, target_id, label)`: PROPFIND (Depth 0/1), GET (потоком), PUT, MOVE (`Overwrite: T`), DELETE, MKCOL по цепочке. Запись — во временный файл и PUT целиком при закрытии. Яндекс Диск — тот же класс с url `https://webdav.yandex.ru`. 401/403 → `StorageError` «Неверный логин или пароль приложения», сеть → «Хранилище недоступно: …», 404 → `StorageNotFound`. Пароль в тексты ошибок не попадает. Если `Http` не умеет нестандартные методы (PROPFIND/MOVE/MKCOL) или тело-файл — расширь `Http.request` минимально и совместимо (это допустимо в зоне: `core/karaoke_core/http.py`).
- `GDriveStorage(client_id, client_secret, token_json, path, *, http, target_id, label)`: Drive REST v3 — путь → id папок (кэш на время жизни объекта), `files.list` с `q`, скачивание `alt=media`, загрузка multipart/resumable, `_replace` — смена имени/родителя (файл с тем же именем в цели удаляется), удаление — `files.delete`. Access-токен обновляется по refresh-токену через `https://oauth2.googleapis.com/token` при 401 или истечении. `probe()` — создать и удалить пробный файл в папке. Невалидный refresh → `StorageError` «Google Диск: доступ отозван — подключите заново в «Настройках»».
- Сканирование библиотеки у обоих — без повторных запросов на одну папку (кэш листинга в пределах `list_songs`).
- Получение токена OAuth — **не здесь**, это таск 03; здесь — статический `GDriveStorage.exchange_code(http, client_id, client_secret, code, redirect_uri) -> token_json` (строка JSON с `access_token, refresh_token, expiry`), которую вызовет веб.
- `make_storage(target, http=...)` строит их по `kind` `webdav`/`gdrive` (поле `preset` на класс не влияет).

## Из брифа, дословно

> «Дать возможность добавлять другие пути (Яндекс Диск, Google диск, другая локальная папка, SMB или другой сетевой путь)»
> «Для сетевых сервисов, должна быть возможность сетевого подключения»

## Разделы спецификации

`spec.md`: Решения §3, §4, §5 (только `exchange_code` и формат токена); истории 28–31; «Границы и швы» (`karaoke_core.storage`).

## Критерии приёмки

- [ ] Оба класса проходят общий набор поведения `Storage` (запись атомарно через `.part`, `upload_dir` — `.txt` последним, `list_songs` находит песню, `read_song`, `delete_dir`, `download_dir`) на `FakeHttp`-эмуляции сервера (маленький in-memory WebDAV и in-memory Drive в фикстуре)
- [ ] Ошибки 401/403/404/сеть переведены в `StorageError`/`StorageNotFound` с русским текстом без пароля/токена
- [ ] Обновление access-токена по refresh при 401 покрыто тестом; `exchange_code` покрыт тестом
- [ ] Число HTTP-запросов при `list_songs` на 3 песнях не растёт квадратично (тест считает вызовы `FakeHttp.calls`)
- [ ] Полный прогон pytest зелёный
