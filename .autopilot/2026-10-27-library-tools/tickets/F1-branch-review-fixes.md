# F1 — Исправления по ревью ветки

**Требования:** R01, R07, R10, R25, R26, R35, R39, R42i, G02
**Зависит от:** —
**Зона:** `web/app/main.py` · `web/app/api_backup.py` · `web/app/api_artwork.py` · `web/app/api_mirrors.py` · `web/app/api_jobs.py` · `web/app/api_bulk.py` · `web/app/api_library.py` · `web/app/api_songs.py` · `core/karaoke_core/db.py` · `core/karaoke_core/backup.py` · `worker/karaoke_worker/mirror.py` · `worker/karaoke_worker/notify.py` · `worker/karaoke_worker/artwork.py` · `worker/karaoke_worker/handlers.py` · `worker/karaoke_worker/libcheck.py` · `web/static/js/song-page.js` · `web/static/js/song-page-logic.js` · `web/static/js/ui.js` · `web/static/js/artwork.js` · `web/static/js/song-actions.js` · `web/static/js/queue.js` · `web/static/js/backup-logic.js` · `web/static/js/check-logic.js` · `web/static/js/select-logic.js` · `web/static/js/editors/notes-tools.js` · `tests/`
**Волна:** 5
**Ревью:** да — ремонт ветки
**Модель:** сильная

## Что должно заработать

Закрыты находки общего ревью ветки, которые дешевле исправить сейчас, чем оставить: подделка запроса с чужой страницы, порча данных зеркалом и регистром имени обложки, недогашенные кнопки «Медиа», повторы одного и того же правила в нескольких местах.

## Из брифа, дословно

> «Зеркало хранилища: автоматически поддерживать одно хранилище копией другого, например «Локальное» и Pi.»
> «Резервная копия настроек: выгрузка и загрузка тегов, списка хранилищ и учёток (без паролей) одним файлом.»
> «Пункты меню «…» не гаснут, если хранилище отвалилось после открытия страницы.»
> «Страница песни перерисовывается целиком после «Теги…», копирования или готового задания.»

## Разделы спецификации

Истории 1–5, 9, 12–18, 39, 44–48, 53, 59–62, 66–68; interfaces.md целиком (строки «T01:»…«T12:» внизу).

## Критерии приёмки

- [ ] Безопасность · web/app/api_backup.py:135 (вместе с web/app/main.py) · запрос, меняющий состояние (минимум этот эндпоинт и другие multipart: /api/jobs/artwork, generate), с заголовком Origin, чей host:port не совпадает с Host (или с Sec-Fetch-Site: cross-site), получает 403 и ничего не меняет. Нужен тест: POST backup?apply=1 с Origin: http://evil.example → 403, хранилищ и зеркал не прибавилось. Запросы без Origin (curl, тесты) и с тем же Origin проходят.
- [ ] worker/karaoke_worker/mirror.py:156-177 (_sync) · копия в цели, у которой `rel_dir` (без регистра) совпадает с другой папкой источника, никогда не выбирается как `there` для этой песни. Если своей копии нет, песня идёт по ветке «нет в цели» (copy без replace). Тест в test_runner_mirror: две папки источника с одним ключом, одна копия в цели. После прогона в цели обе папки, корзина цели пуста.
- [ ] worker/karaoke_worker/notify.py:119-124 (_queue_idle) · ожидающее задание с `retry_at` в будущем не мешает сводке независимо от `wait`. Тест: ждущее зеркало плюс готовое задание дают одну сводку.
- [ ] worker/karaoke_worker/artwork.py:100 · старый файл удаляется, только если `old.casefold() != image.name.casefold()`. Тест: старое имя отличается только регистром расширения, новый файл остаётся. Так же в publish_video (handlers.py:1118).
- [ ] worker/karaoke_worker/libcheck.py:84-85 · строка индекса строится через `scan.library_item(entry, tid, ctx.songs, stamp)`.
- [ ] tests/core/test_tags.py · есть тест, где один и тот же id стоит и в add, и в remove `change_for_songs`, и после вызова тег у песни есть.
- [ ] web/app/api_artwork.py:68 · битая ссылка (например «http://[::1») → 400 field=url «Нужна ссылка http(s) на картинку», задание не создано (не 500).
- [ ] Правило «активное задание этого зеркала» (web/app/api_mirrors.py:124 active_job, web/app/api_jobs.py:657 инлайн в restart, worker/karaoke_worker/mirror.py:53 active_mirror_job) — одна функция в core (Jobs или core-модуль зеркал), её зовут все три места.
- [ ] В web/app нет `from .api_songs import _…` (api_bulk.py:20 `_ZipSink, _song_files, _zip_time`; api_library.py:17 `_read_txt, _song_storage, _storage_call`): общие помощники api_songs публичны (без подчёркивания). core/backup.py:310 вместо `Settings._write_targets` зовёт публичный метод Settings для создания хранилища с заданным id, который на существующий id отвечает ValueError.
- [ ] web/static/js/song-page.js:185 · баннер имеет класс `banner err` и role `alert` (как в согласованном макете).
- [ ] song-page.js:135, 361/363 · у всех блоков один объект env (обновлять через Object.assign). При `outputOk=false` все кнопки действий с файлами в «Медиа» («Сделать минусовку», «Прикрепить видео…», «Поставить…/Заменить…» обложки и фона) получают disabled и title «Хранилище недоступно — действия с файлами отключены»; при восстановлении снова активны; плееры при этом не пересоздаются.
- [ ] song-page-logic.js `blockSigs` · `blockSigs(details).media` включает имена cover/background и size/mtime файлов из `details.files` для имён медиа; в song-page.js нет дописывания к подписи (строка 132); в song-page-logic.test.mjs есть тест «тот же файл минусовки с новым mtime меняет только media».
- [ ] Один экспорт `openModal(...)` в ui.js; в artwork.js, song-actions.js и queue.js больше нет своих вызовов `showModal`.
- [ ] backup-logic.js, check-logic.js, select-logic.js импортируют `plural` из ui.js (или из одного чистого модуля), своих определений нет.
- [ ] Текст «Хранилище недоступно — действия с файлами отключены» — одна константа (select-logic.js:6, song-actions.js:20, song-page.js:334 импортируют её).
- [ ] editors/notes-tools.js:34 `HELP` · в справке есть строки «P — сыграть выбранную ноту её высотой» и «! — к следующей подозрительной ноте».
- [ ] Все тесты зелёные: pytest (было 1056 passed, 2 skipped) и `node --test tests/frontend/` (было 288 pass).
