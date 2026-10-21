# 04 — Видео: ядро, индекс и задание `video`

**Требования:** R03, R03.2, R03.3, R04, A01, R05, R06, R07, R10i, R11i, R11i.1, G01
**Blocked by:** —
**Зона:** `core/karaoke_core/naming.py` · `core/karaoke_core/db.py` · `core/karaoke_core/storage/` · `core/karaoke_core/postprocess.py` · `worker/karaoke_worker/` · `tests/core/` (кроме `test_ultrastar.py`, `test_songpack.py`) · `tests/worker/` (кроме `test_runner_duet.py`)
**Волна:** 1
**Status:** ready

## Что должно заработать

Воркер исполняет задание `video` (`needs_gpu=False`) у существующей песни. Источник видео — файл из `in/video.<ext>` или ссылка (yt-dlp, качество `video_height`, 0 = лучшее). Итог: `<A - T>.<ext>` в папке песни, `#VIDEO`, `#VIDEOGAP` (если не 0) через `set_header_line`, версия `.txt` в корзину, старый видеофайл с другим именем удаляется. `remove` убирает заголовки и файл. Индекс знает видео: миграция V2 `library.video`, `SongEntry.video`. `finalize` принимает `video_path`/`videogap`. `publish_song` при замене переносит старое видео, если в результате своего нет. `_save_sources` не копирует видео. `PublishHandler` умеет `video`. `download_video` — общая функция для 04 и 06.

## Из брифа, дословно

> «добавление/замена видео, независимо от способа добавления прикрепить можно как ссылку, так и файл»
> Дополнение: «По умолчанию 720p, в случае отсутствия выбор в пользу ближайшего. У пользователя должен быть выбор»

## Разделы спецификации

Истории 14–23; Решения «Видео — отдельное задание», «Скачивание видео», «Файл видео», «Имя файла», «Индекс», «Корзина и видео», «`_save_sources`», «Перенос видео при замене», «Прогресс»; Границы — `naming`, `postprocess.finalize`, `worker handlers`, `db`/`storage`.

## Критерии приёмки

- [ ] `naming.video_suffix(ext)`, `VIDEO_EXTS` (mp4, m4v, mkv, webm, avi, mov, mpg, mpeg); миграция V2 и `LibraryItem.video`/`SongEntry.video` (`present("VIDEO")`), старая БД мигрирует
- [ ] `download_video(ctx, job_id, url, dest_dir, height) -> Path`: `yt-dlp -4 --no-playlist -f "bv*" -S "res:<H>,vcodec:h264,ext:mp4" --remux-video mp4` (без `res` при 0), этап «Загрузка видео» (`DownloadTracker` с подписью параметром), ошибки по-русски (нет видеоформата, 403, сеть); `fake_ytdlp.py` получает видеорежим и `FAKE_YTDLP_MODE=novideo`
- [ ] задание `video` (params из спецификации): файл / ссылка / `remove`; перезапуск не качает заново `in/video.*`; отмена; при сбое выкладки — `republish` через `PublishHandler`
- [ ] `.txt` меняется ровно на строки `#VIDEO`/`#VIDEOGAP` (для remove — `ultrastar.parse` + `Song.remove_header` + `render`: неизменённые строки пишутся по `raw`, кодировка и BOM сохраняются; проверь тестом байт-в-байт. `ultrastar.py` **не редактировать** — его в той же волне правит таск 01), версия `.txt` в корзину, видеофайл в корзину не идёт
- [ ] `finalize(..., video_path=None, videogap=None)`; `publish_song` переносит видео заменяемой песни, если в `result/` его нет; `_save_sources` пропускает `in/video.*`, а `video_url` пишет в `params.json`
- [ ] тесты воркера (по образцу `test_runner_instrumental.py`): файл, ссылка, замена, удаление, без GPU, ошибка ссылки, перенос при перегенерации; core-тесты naming/db/storage/postprocess; полный pytest зелёный
