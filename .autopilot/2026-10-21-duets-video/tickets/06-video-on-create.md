# 06 — Видео при создании: новая песня, «Импорт → Ссылка», usdb, архивы

**Требования:** R05, R06, R07, R08, R08.1, R08.2, R09, R12i, R04.1, R05.1, G01
**Blocked by:** 04, 05
**Зона:** `core/karaoke_core/songpack.py` · `tests/core/test_songpack.py` · `web/app/api_jobs.py` (generate) · `web/app/api_import.py` · `web/app/api_link.py` (если нужно) · `worker/karaoke_worker/handlers.py` (generate/import) · `web/static/js/new-song.js` · `web/static/js/import.js` · `web/static/js/import-logic.js` · `web/static/js/folder-logic.js` · `web/static/js/link-logic.js` · `web/static/js/api.js` · `tests/api/` (import, link, jobs) · `tests/worker/` (import, link, generate) · `tests/frontend/`
**Волна:** 3
**Status:** ready

## Что должно заработать

Блок «Видео» (из `video-block.js`, таск 05) появляется в «Новой песне» (и для mp3, и для ссылки), в каждом треке «Импорт → Ссылка» и в каждой песне импорта. Варианты:
- «без видео»;
- «из ссылки песни» (звук по yt-dlp-ссылке) или «из ссылки usdb» (`v=`/YouTube из комментариев, ссылка показана);
- «из архива» — видеофайл, на который указывает `#VIDEO`; выбран по умолчанию;
- «своя ссылка»;
- «файл».

Для ссылок — выбор качества. generate/import принимают `video_mode, video_url, video_file, video_height, videogap`, кладут файл в `in/video.<ext>`, пишут `params.video`. Воркер после звука качает видео (`download_video` из 04), `finalize` кладёт его в результат. Сбой видео — предупреждение в логе, песня выкладывается без видео. Выбранное видео побеждает перенос старого при замене. В «Импорт → Папка» видео не выбирается.

## Из брифа, дословно

> «при выгрузке с YouTube, VK и прочих ссылок с видео, должна быть опция для прикрепления видео (в том числе в usdb)»
> «независимо от способа добавления прикрепить можно как ссылку, так и файл»
> Дополнение: «По умолчанию 720p, в случае отсутствия выбор в пользу ближайшего. У пользователя должен быть выбор»

## Разделы спецификации

Истории 23–31; Решения «Импорт», «Ссылки для видео у импорта», блок «Видео» в generate и import; Границы — `web api_jobs`, фронт `api.js`.

## Критерии приёмки

- [ ] `songpack`: `a=` и `v=` разделены (`FoundSong.video_links`, `video_file`, `videogap` из `v-gap=`/`#VIDEOGAP`); видеорасширения в `ALLOWED_EXTS`; существующие тесты порядка ссылок звука зелёные
- [ ] inspect отдаёт у песни `video_links`, `video_file` (имя), `videogap`; `POST /api/jobs/import` и generate принимают поля блока «Видео» с теми же проверками, что `POST /api/jobs/video` (400/413); `source` у generate без ссылки-видео или с Яндексом → 400
- [ ] воркер generate/import: видео после звука в `in/video.*` (перезапуск не качает заново), `finalize(video_path, videogap)`; ImportHandler чистит старые `#VIDEO/#BACKGROUND/#VIDEOGAP` и ставит свои; сбой видео → строка лога «Видео не скачалось: …, песня выложена без видео», задание `done`
- [ ] при замене выбранное видео побеждает перенос старого; «без видео» — перенос (история 23)
- [ ] фронт: блок в «Новой песне», в треках «Импорт → Ссылка», в карточках импорта; варианты по ситуации; по умолчанию «без видео», кроме «из архива»; `generateForm`/`importForm` шлют поля блока; node-тесты логики
- [ ] тесты api и worker на usdb с `v=`, zip с видеофайлом, generate по ссылке с видео, своя ссылка, файл, сбой видео; полный pytest и `node --test tests/frontend/` зелёные
