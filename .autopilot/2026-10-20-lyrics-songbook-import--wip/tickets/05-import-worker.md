# 05 — Задание «Импорт» в воркере: звук, сборка папки, выкладка, минусовка

**Требования:** R02, R06i, R06i.2, R06i.3, R07i, R07i.3, G05
**Blocked by:** 02
**Зона:** `worker/` (handlers, base, selfcheck, Dockerfile, progress, runner — уборка `imports/`) · `tests/worker/` (+ `fixtures/fake_ytdlp.py`) · `.env.example` (`YTDLP_CMD`)
**Волна:** 2
**Status:** ready

## Что должно заработать

Воркер исполняет задание `import` (без GPU): берёт звук (файл из `in/` или скачивает с YouTube через yt-dlp), делает mp3 с одним аудиопотоком, ставит обложку, собирает папку песни, прогоняет через `finalize` и выкладывает тем же `publish_song` (замена с откатом). Если `instrumental=true` — после выкладки ставит обычное задание `instrumental` на эту песню. «Выложить повторно» понимает `import`. В образ worker добавляется `deno` (JS-рантайм для yt-dlp), `selfcheck` это проверяет.

Задание приходит с params по контракту в `interfaces.md` — веб-часть (таск 04) пишется параллельно, в тестах `in/` собирается руками, как `World.enqueue_generate`.

## Из брифа, дословно

> «Добавь возможность добавить песню из сборников для UltraStar (usdb и прочие)»
> «YouTube + свой mp3»
> «при импорте может быть ссылка или mp3 плюса, поэтому должна быть опция генерации минуса»

## Разделы спецификации

Истории 15, 18–23; Решения §6–7, §9; Границы: `ImportHandler`.

## Критерии приёмки

- [ ] `HANDLERS["import"]`, `needs_gpu=False`; этапы «Загрузка звука» / «Подготовка» / выкладка (`STAGE_PUBLISH`) с процентами
- [ ] Звук: `inputs.audio` (mp3 → копия только аудиопотока; ogg/m4a/opus/wav/flac → ffmpeg в mp3), иначе `youtube_url` → `YTDLP_CMD` (по умолчанию `python -m yt_dlp`) `-x --audio-format mp3 --no-playlist -o …` через `run_command`; ошибка → `JobFailed(..., "YouTube не отдал звук: …")`
- [ ] Обложка: `inputs.cover` → иначе миниатюра YouTube (`--write-thumbnail --convert-thumbnails jpg`), без обложки — не ошибка
- [ ] Сборка папки: `#AUDIO`/`#MP3` на имя mp3, `#VIDEO`/`#BACKGROUND` убраны, `finalize(folder, artist, title, cover_path)`; mp3 сохраняется в `in/input.mp3` до выкладки, чтобы `source/` позволял перегенерацию; `params.json` с `source`
- [ ] `instrumental=true` → после успешной выкладки ставится `instrumental` (params как у веба, `parent_id` = импорт); сбой постановки не валит импорт
- [ ] `PublishHandler` для `src.type == "import"`; отмена убивает yt-dlp; `restart` с сохранённым `in/` работает
- [ ] Dockerfile: `deno` (фиксированная версия, бинарь в PATH); `selfcheck` — `import yt_dlp` и `deno --version`; уборка `imports/*` старше часа при старте воркера
- [ ] `YTDLP_CMD` в `.env.example` с русским комментарием; `fake_ytdlp.py` (успех/провал/миниатюра); тесты: файл mp3, ogg, YouTube, провал YouTube, замена, минусовка поставлена, republish; полный pytest зелёный
