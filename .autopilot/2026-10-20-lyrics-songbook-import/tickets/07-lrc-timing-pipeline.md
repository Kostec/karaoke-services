# 07 — Синхронизированный текст: от LRCLIB до UltraSinger

**Требования:** G06, G06.1, G06.2, G06.3
**Blocked by:** 01, 04, 05, 06, 08
**Зона:** `web/app/lyrics.py` · `web/app/api_jobs.py` · `web/app/params.py` · `web/static/js/new-song.js` · `web/static/js/lyrics-search.js` · `web/static/js/api.js` (`generateForm`, `PARAM_KEYS`) · `worker/karaoke_worker/handlers.py` (`ultrasinger_args`) · `worker/karaoke_worker/selfcheck.py` · `tests/api/` · `tests/worker/` (+ `fake_ultrasinger.py`) · `tests/frontend/`
**Волна:** 5
**Status:** ready

## Что должно заработать

В списке вариантов LRCLIB — метка «есть синхронизация». При вставке такого варианта в поле идёт чистый текст, а LRC держится рядом в форме; появляется галочка «Использовать тайминги строк» — включена, если длительность LRCLIB отличается от длительности mp3 (из файла в форме) не больше чем на 3 с, иначе выключена с подсказкой. Ручная очистка поля или вставка другого текста сбрасывает LRC. Generate принимает `lyrics_lrc` и параметр `lrc_timing`, кладёт `in/lyrics.lrc` (→ `source/lyrics.lrc`). Воркер при `lrc_timing` сверяет строки текста со строками LRC: совпали — передаёт UltraSinger `--lyrics_timing <in/lyrics.lrc>`, нет — пишет в лог «Тайминги LRC не использованы: текст отличается» и генерирует без флага. Перегенерация из `source/` подхватывает сохранённый LRC.

## Из брифа, дословно

> «у LRCLIB есть уже синхронизированные по времени тексты, будем ли мы их использовать?» → «Добавь, я разрешаю тебе редактировать `D:/Projects/UltraSinger`»

## Разделы спецификации

Истории 26–29; Решения §11; флаг UltraSinger — из таска 08 (`interfaces.md`).

## Критерии приёмки

- [ ] `LyricsHit.synced` (текст LRC или `null`), в ответе `/api/lyrics/search`; метка в диалоге
- [ ] Форма: LRC держится, пока текст в поле — тот, что вставлен (правка текста не сбрасывает, очистка/новая вставка/загрузка файла — сбрасывает); галочка и правило 3 с; `generateForm` шлёт `lyrics_lrc`; `PARAM_KEYS` и его тест обновлены
- [ ] Generate: `lyrics_lrc` ≤ `MAX_LYRICS_MB`, `in/lyrics.lrc`, `params.inputs.lrc`, `lrc_timing` в `/api/defaults` (по умолчанию `false`) и в `parse_params`; restart/regen копируют `lyrics.lrc` из `source/`
- [ ] Воркер: проверка совпадения строк даёт тот же ответ, что `lrc_timing.match_lrc_lines` форка (нормализация и развёртка многометочных строк — как в `interfaces.md`, «Из таска 08»); флаг только при совпадении; при любом расхождении в логе задания русская строка «Тайминги LRC не использованы: текст отличается» (английская строка форка её не заменяет); `fake_ultrasinger.py` принимает флаг
- [ ] Форма строит чистый текст из LRC в развёрнутом порядке (строка с N метками — N раз)
- [ ] `selfcheck` проверяет, что UltraSinger знает `--lyrics_timing` (как остальные флаги форка)
- [ ] Тесты: api (lrc сохраняется, лимит), worker (флаг есть/нет), frontend (правило 3 с, сброс LRC); полный pytest и `node --test tests/frontend/` зелёные
