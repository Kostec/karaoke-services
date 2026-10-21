# 05 — Видео: диалог «Видео…» на карточке песни

**Требования:** R03, R03.1, R03.3, R04, A01, R05, R06, R07, R11i, G01
**Blocked by:** 04
**Зона:** `web/app/api_jobs.py` · `web/app/params.py` · `web/app/context.py` (если нужно) · `.env.example` · `web/static/js/api.js` · `web/static/js/songs.js` · `web/static/js/video-block.js` (новый) · `web/static/js/queue.js` · `web/static/css/` (кроме `editors.css`) · `tests/api/test_video.py` (новый) · `tests/frontend/` (новые video-тесты, `api.test.mjs`)
**Волна:** 2
**Status:** ready

## Что должно заработать

У любой песни в «Песнях» есть метка «видео» (если оно есть) и кнопка «Видео…». Диалог: «своя ссылка» с качеством (360/480/720/1080/лучшее, по умолчанию 720, запоминается в `localStorage` `video.height`) или «файл»; поле «Смещение видео, с» (текущее или 0); у песни с видео — предупреждение «старое видео удалится» и «Убрать видео» с подтверждением. `POST /api/jobs/video` проверяет вход и ставит задание `video`. `video-block.js` — общий блок «Видео» (разметка + чистая `videoFields(state)`), который таск 06 переиспользует в формах.

## Из брифа, дословно

> «добавление/замена видео, независимо от способа добавления прикрепить можно как ссылку, так и файл»
> Дополнение: «У пользователя должен быть выбор»

## Разделы спецификации

Истории 14–22, 28 (качество в `localStorage`); Решения «Лимит»; Границы — `web api_jobs`, фронт `api.js`.

## Критерии приёмки

- [ ] `POST /api/jobs/video` multipart `{song_id, video(File)?, video_url?, video_height?, videogap?, remove?}`: ровно один источник или `remove`; Яндекс/не-публичная ссылка → 400 `field=video_url`; расширение не из `VIDEO_EXTS` → 400 `field=video`; больше `MAX_VIDEO_MB` → 413; нет песни → 404; задание `video` этой песни уже в очереди → 409; `remove` без видео → 409
- [ ] `MAX_VIDEO_MB` в `.env.example` с русским комментарием, `/api/defaults` отдаёт `max_video_mb`, `video_heights`, `default_video_height`; `test_repo_config` зелёный
- [ ] карточка: метка «видео», кнопка «Видео…», диалог по спецификации; ошибки API показываются у полей; `queue.js` подписывает тип «Видео»
- [ ] `video-block.js`: режимы `none|source|url|file|pack` (какие показать — параметр), качество, смещение; чистая `videoFields(state)` → поля multipart; node-тесты
- [ ] `api.video(songId, form)`; api-тесты эндпоинта; `node --test tests/frontend/` и полный pytest зелёные
- [ ] вручную в браузере: диалог открывается, ссылка и файл ставят задание, «Убрать видео» работает
