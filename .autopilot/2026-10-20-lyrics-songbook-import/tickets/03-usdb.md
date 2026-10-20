# 03 — usdb: учётка в «Настройках» и поиск песен

**Требования:** R03, R03.1, R03.2, R08i, G03
**Blocked by:** 01
**Зона:** `web/app/usdb.py` · `web/app/api_usdb.py` · `web/app/api_settings.py` (блок usdb) · `web/app/main.py` (только подключение роутера) · `web/app/context.py` (клиент usdb) · `core/karaoke_core/db.py` (только `Settings.get_usdb/set_usdb`, `UsdbAccount`) · `web/static/js/settings.js` · `web/static/js/api.js` (только `api.usdb*`) · `tests/api/test_usdb*.py` (+ HTML-фикстуры usdb)
**Волна:** 2
**Status:** ready

## Что должно заработать

В «Настройках» — вторая карточка «usdb»: логин, пароль, «Проверить», «Сохранить». Пароль не возвращается (`has_password`), пустой пароль при том же логине — оставить прежний (как у шары). Сервер умеет войти в usdb и искать песни по исполнителю/названию/языку (по умолчанию «Russian»), постранично по 50. Ещё — `fetch_song(id)`: ноты (.txt байтами), ссылки YouTube из комментариев, обложка — этим воспользуется таск 04.

## Из брифа, дословно

> «Добавь возможность добавить песню из сборников для UltraStar (usdb и прочие)»
> «Интересуют сборники песен русских исполнителей»

## Разделы спецификации

Истории 7–10; Решения §3; Границы: `usdb.py`.

## Критерии приёмки

- [ ] `UsdbClient(http, user, password)`: `login()`, `search(...) -> UsdbPage`, `fetch_song(id) -> UsdbSong` — запросы и строки-признаки ровно как в Решениях §3; сессия в памяти, один повторный вход на «You are not logged in…»; клиент живёт в `AppContext` и сбрасывается при смене учётки
- [ ] `GET/PUT /api/settings/usdb` (`{user, has_password}`), `POST /api/settings/usdb/test` → `{ok:true}` или 400 «usdb не принял логин или пароль» (field=password); usdb недоступен → 503 «usdb недоступен, попробуйте позже»
- [ ] `GET /api/usdb/search?artist=&title=&language=&start=` → `{items:[{id, artist, title, language, rating, views, existing_song_id}], has_more}`; без учётки → 400 «Впишите логин и пароль usdb в Настройках» (`code: "usdb_no_account"`); `existing_song_id` — через `ctx.find_by_name`
- [ ] Разбор HTML-таблицы списка, `<textarea>` gettxt, ссылок YouTube в комментариях detail — по HTML-фикстурам, сделанным по разметке, которую разбирает usdb_syncer (github.com/bohning/usdb_syncer, `usdb_scraper.py`); где точную разметку не установить без входа — фикстура по описанию и пометка `DONE_WITH_CONCERNS`
- [ ] Пароль никогда не попадает в ответ, лог и текст ошибки
- [ ] Карточка «usdb» в `settings.js` в стиле карточки «Папка результата»; полный pytest и node-тесты зелёные
