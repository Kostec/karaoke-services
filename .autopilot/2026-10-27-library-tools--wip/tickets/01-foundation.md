# 01 — Фундамент: схема V5, теги, копии по индексу, порядок и время в очереди (ядро)

**Требования:** R04, R05, R06, R33, R34
**Зависит от:** —
**Зона:** `core/karaoke_core/db.py` · `core/karaoke_core/naming.py` · `core/karaoke_core/paths.py` · `web/app/api_tags.py` · `tests/core/test_db.py` · `tests/core/test_tags.py` · `tests/core/test_naming.py` · `tests/api/test_tags.py`
**Волна:** 1
**Ревью:** да — фундамент
**Модель:** сильная

## Что должно заработать

Одна миграция V5 (library.match_key + индекс, jobs.position, jobs.start_at), исправленные баги тегов, `Library.copies` по индексу, ядро очереди (`claim_next` со временем и порядком, `move`, `schedule`, `schedule_all`), `Tags.change_for_songs`, `naming.background_suffix/rough_key`, `DataPaths.libcheck_report`, хранение настроек Telegram и зеркал в `Settings`. Всё — по `interfaces.md`, раздел «Границы». На этом стоят остальные таски.

## Из брифа, дословно

> «POST /api/tags с пустым color создаёт синий тег, а должен отвечать 400. При двух одновременных созданиях тега с одним именем второе падает с ошибкой 500 вместо «Такой тег уже есть».»
> «Блок «Хранилища» на странице песни перебирает весь индекс. Достаточно запроса по match_key с индексом.»
> «Ночная очередь: задания, поставленные на время, и возможность менять порядок очереди.»

## Разделы спецификации

Истории 6–8, 56–58 (ядро); «Решения по реализации» — схема V5, очередь; interfaces.md «core: схема V5», «core: теги», «core: имена», «core: отчёт проверки», «core: настройки».

## Критерии приёмки

- [ ] `POST /api/tags` с `color: ""` и с `color: null` → 400 `{detail:"Неизвестный цвет", field:"color"}`; без поля `color` → 201 синий
- [ ] Два параллельных `Tags.create` с одним именем на двух соединениях к одному файлу → один успех, второй `TagError("Такой тег уже есть","name")`; так же `update`; `sqlite3.IntegrityError` наружу не выходит
- [ ] БД версии 4 поднимается до 5: `library.match_key` заполнен, индекс `library_match_key` есть, `Library.copies` — запрос `WHERE match_key=?` (тест через `EXPLAIN QUERY PLAN`), результаты как прежде
- [ ] `claim_next` не берёт задание с `start_at` в будущем, берёт в порядке `COALESCE(position,id), id`; `move(id, up|down|first)` и `schedule` работают только для `queued` (иначе `ValueError` с русским текстом), время в прошлом → «Время уже прошло»; `schedule_all` откладывает все ожидающие без времени
- [ ] `Tags.change_for_songs(keys, add, remove)` добавляет и снимает без замены набора, неизвестный id → `KeyError`
- [ ] `naming.background_suffix("jpeg") == " [BG].jpg"`; `rough_key` склеивает «Kино»/«Кино» (латинская K) и «Ленинград!» с «ленинград»; `Settings` хранит Telegram (`public()` без токена) и зеркала; `delete_target` выключает зеркала хранилища
- [ ] Все прежние тесты зелёные (было 848 passed, 2 skipped)
