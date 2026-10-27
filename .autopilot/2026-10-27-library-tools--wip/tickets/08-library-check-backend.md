# 08 — Проверка библиотеки: задание, исправления, звук по ссылке #VIDEO, кодировка

**Требования:** R20, R21, R22, R23, R24, R25
**Зависит от:** 01
**Зона:** `worker/karaoke_worker/libcheck.py` · `worker/karaoke_worker/audiofix.py` · `web/app/api_library.py` · `core/karaoke_core/ultrastar.py` · `core/karaoke_core/libcheck.py` · `tests/core/test_encoding.py` · `tests/core/test_libcheck.py` · `tests/api/test_library_check.py` · `tests/worker/test_runner_libcheck.py` · `tests/worker/test_runner_audio.py`
**Волна:** 3
**Ревью:** нет
**Модель:** сильная

## Что должно заработать

Задание `libcheck` без GPU проходит выбранные хранилища и пишет отчёт с находками шести видов, у каждой — вариант(ы) исправления. Исправления: `POST /api/songs/{id}/encoding` (перекодировать `.txt` в UTF-8, старая версия в корзину), задание `audio` (звук по YouTube-ссылке из `#VIDEO`), остальные — существующими заданиями (copy, video remove, удаление).

## Из брифа, дословно

> «Проверка библиотеки: найти песни без звука или обложки, со ссылкой #VIDEO на несуществующий файл, с битой кодировкой, дубли с разным написанием, копии, которые разошлись между хранилищами. Каждую находку можно будет исправить одной кнопкой.»

## Разделы спецификации

Истории 34–43; «Решения по реализации» (проверка, кодировка, звук); interfaces.md «core: кодировка», «core: отчёт проверки», «worker: audio, libcheck», «web: API» (library, encoding, audio).

## Критерии приёмки

- [ ] `encoding_problem` находит mojibake «UTF-8 как cp1251», koi8-r/cp866 под видом cp1251 и символ замены U+FFFD; нормальные cp1251/UTF-8/BOM-фикстуры — `None`; даёт «было → станет» (pytest)
- [ ] Отчёт `reports/libcheck.json`: `no_audio`, `no_cover`, `video_missing` (URL в `#VIDEO` — не находка), `encoding`, `duplicate` (`rough_key`, одно хранилище), `diverged` (набор файлов/размеры между копиями); `fix`/`fixes` по interfaces.md; недоступное хранилище — в `skipped`, остальные проверены (тест runner)
- [ ] `POST /api/library/check` → 201, вторая во время первой → 409 «Проверка уже идёт»; `GET` отдаёт отчёт с датами и активное задание; до первой — `{findings: null}`
- [ ] `POST /api/songs/{id}/encoding` пишет UTF-8, старая версия в корзину; нет проблемы → 409 «Кодировка в порядке»; не угадать → 409
- [ ] Задание `audio`: YouTube из `#VIDEO` → `<A - T>.mp3`, `#AUDIO/#MP3`; без ссылки → 409 при постановке; без GPU; restart не качает заново (fake yt-dlp)
