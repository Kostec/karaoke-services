# Интерфейсы

## Правила проекта (вывести самому нельзя)

- Язык: Python 3.12. Интерфейс и все сообщения пользователю — на русском.
- Docker: Docker Desktop на Windows, **Linux-движок через контекст `desktop-linux`** (по умолчанию активен Windows-движок — его не переключать). Все команды: `docker --context desktop-linux compose ...` (обёртка `scripts/compose.ps1`).
- Тесты запускаются **в Linux-контейнере** (сервис `tests` в compose, профиль `test`): `docker --context desktop-linux compose --profile test run --rm tests` (+ `pytest -q <путь>` для подмножества). На хосте Windows тесты не гоняем — воркер использует POSIX-группы процессов.
- БД — SQLite (WAL) в именованном томе `data` (`/data`), не в bind-mount. Модели — том `models` (`/models`).
- UltraSinger в образе worker: `/app/UltraSinger` из `ULTRASINGER_GIT` (по умолчанию `https://github.com/Kostec/UltraSinger.git#karaoke-local`). **Репозиторий `D:/Projects/UltraSinger` не редактировать.**
- torch 2.8.0 / torchaudio 2.8.0 / torchvision 0.23.0 с индекса cu126; `numpy<2.5`. GPU — GTX 1080 (sm_61, 8 ГБ): compute type `int8`, никогда float16.
- Секреты только в `.env` (в `.gitignore`); в коде, тестах, фикстурах, логах — никаких паролей. Пароли не возвращаются API.
- Нужна зависимость, которой нет и которую нельзя добавить в pyproject/Dockerfile своей зоны → вернуть `BLOCKED`, а не ставить в обход.
- Пути к файлам песен — всегда через `karaoke_core.naming`; запись в папку результата — только через `karaoke_core.storage`.
- Спецификация: `.autopilot/2026-10-19-karaoke-services--wip/spec.md` (истории, Решения §1–§12, API).

## Границы, решённые в спецификации


| Модуль | Владеет | Выставляет | Прячет |
|---|---|---|---|
| `karaoke_core.db` | схема SQLite, миграции | `connect(path) -> Connection`; `Jobs.enqueue(type, song_ref, params) -> Job`, `Jobs.claim_next() -> Job\|None`, `Jobs.update(id, **fields)`, `Jobs.request_cancel(id)`, `Jobs.list(limit)`, `Jobs.get(id)`, `Jobs.fail_interrupted()`; `Settings.get_output() -> OutputTarget`, `Settings.set_output(OutputTarget)`; `Library.replace_all(target_id, items)`, `Library.upsert(item)`, `Library.remove(target_id, rel_dir)`, `Library.list(target_id, q)`; `Songs.get/ upsert / by_rel_dir` | SQL, WAL, атомарный захват |
| `karaoke_core.naming` | правила имён | `safe_name(s) -> str`, `song_dir(artist, title) -> "<A>/<A - T>"`, `base_name(artist, title) -> "<A - T>"`, `normalize_artist(s) -> str` (для сравнения) | таблицу замен символов |
| `karaoke_core.ultrastar` | формат .txt | `parse(bytes) -> Song`, `render(Song) -> bytes`, `set_header_line(bytes, key, value) -> bytes`, `fix_zero_length(Song) -> int`, `beat_to_ms(Song, beat) -> float`, `extract_lyrics(Song) -> str` | кодировки, BOM, переводы строк |
| `karaoke_core.postprocess` | превращение выхода UltraSinger в готовую песню | `finalize(out_dir, artist, title, cover_path\|None) -> FinalizedSong{dir, files, mb_dropped: bool, zero_fixed: int}` | переименования, фильтр MusicBrainz |
| `karaoke_core.storage` | папка результата | `Storage`: `list_songs(max_depth=4) -> [SongEntry]`, `read(rel) -> bytes`, `open_read(rel)`, `write_atomic(rel, bytes\|stream)`, `exists(rel)`, `download_dir(rel_dir, local)`, `upload_dir(local, rel_dir)`, `delete_dir(rel_dir)`, `probe() -> None\|raise`; `make_storage(OutputTarget) -> Storage` | smbclient, пути, повторы |
| `karaoke_core.trash` | корзина в томе | `move_to_trash(storage, rel_dir, reason) -> TrashItem`, `save_version(storage, rel_file) -> TrashItem`, `list() -> [TrashItem]`, `restore(storage, id)`, `purge(older_than_days) -> int` | раскладку на диске, meta.json |
| `karaoke_worker.runner` | исполнение заданий | `handlers: dict[type, Handler]`; `Handler.run(job, ctx) -> None` (бросает `JobFailed(reason, user_message)`); `run_forever()`; CLI `gpucheck` | subprocess, группы процессов, парсинг прогресса, demucs/ffmpeg |
| `karaoke_worker.progress` | лог → этап и % | `ProgressTracker.feed(line) -> (stage, percent)\|None`, `clean_line(raw) -> str` | таблицу маркеров |
| `web` (FastAPI) | HTTP | REST API ниже | шаблоны, статика, middleware |

**REST API** (все ответы JSON, ошибки — `{"detail": "<текст по-русски>"}`):

```
GET    /api/status                      → {gpu:{ok,name,vram_mb,error}, output:{ok,label,error}, version}
GET    /api/jobs?limit=50               → [Job]
POST   /api/jobs/generate   (multipart: artist,title,audio?,lyrics?,cover?,params(json),song_id?,replace)
POST   /api/jobs/instrumental {song_id, replace}
POST   /api/jobs/{id}/cancel
POST   /api/jobs/{id}/restart           → Job
POST   /api/jobs/{id}/republish         → Job
GET    /api/jobs/{id}/log?from=<offset> → text; /api/jobs/{id}/log/stream (SSE)
GET    /api/songs?q=                    → {scanned_at, items:[SongEntry]}
POST   /api/songs/rescan
GET    /api/songs/exists?artist=&title= → {exists, song_id?}
GET    /api/songs/{id}                  → SongEntry + {own, params?, lyrics?}
GET    /api/songs/{id}/lyrics           → {text, source:"own"|"extracted"}
GET    /api/songs/{id}/notes            → {editable, reason?, bpm, gap, headers:[[k,v]], lines:[{break_beat, notes:[{type,start,length,pitch,text}]}]}
PUT    /api/songs/{id}/notes            (то же тело) → SongEntry
GET    /api/songs/{id}/audio            (Range) ; GET /api/songs/{id}/cover
DELETE /api/songs/{id}                  → TrashItem
GET    /api/trash ; POST /api/trash/{id}/restore
GET    /api/settings/output ; PUT /api/settings/output ; POST /api/settings/output/test
GET    /api/defaults                    → модели, языки, значения по умолчанию
```

`Job = {id, type, state, stage, percent, artist, title, song_id, params, error, created_at, started_at, finished_at}`.

**Швы для тестов** (их три, все существующие границы):
1. `karaoke_core` — чистые функции и `LocalStorage` во временной папке.
2. REST API через `TestClient` с `LocalStorage` и временной БД.
3. `karaoke_worker.runner` с подменой команды UltraSinger: переменная `ULTRASINGER_CMD` указывает на фейковый скрипт, который печатает маркеры и создаёт выходную папку из фикстуры. Настоящий GPU проверяется `gpucheck` и одной реальной генерацией при приёмке.


## Что построено (дополняется по мере тасков)

### Из таска 01 — каркас и ядро

- Тесты: `docker --context desktop-linux compose --profile test run --rm tests` (образ `core/Dockerfile.test`, pytest по всей `tests/`, `--import-mode=importlib`); один файл — `… run --rm tests pytest -q tests/<путь>`. Свои зависимости для тестов api/worker таски добавляют в `core/Dockerfile.test`.
- `naming`: `safe_name(s)`, `base_name(a,t)`, `song_dir(a,t) -> "A/A - T"`, `artist_dir(a)`, `normalize_artist(s)`; константы `SUFFIX_*`.
- `ultrastar`: `parse(bytes)->Song`, `render(Song)->bytes`, `set_header_line(bytes,key,value)->bytes` (ValueError, если значение не кодируется), `fix_zero_length(Song)->int`, `beat_to_ms(Song,beat)->float`, `extract_lyrics(Song)->str`. `Song{headers, body, encoding, bom, newline; header(k), header_items(), set_header(k,v), remove_header(k), notes()->[Note], lines()->[{player,notes,break}], is_duet, relative}`; `Note{type,start,length,pitch,text,player,end}`, `LineBreak{beat,beat2}`, `PlayerMark`, `End`, `RawLine`.
- `postprocess`: `finalize(out_dir, artist, title, cover_path=None, *, dest_dir=None) -> FinalizedSong{dir, files, mb_dropped, zero_fixed, base, rel_dir}`; `FinalizeError`. `out_dir` — папка песни UltraSinger или её родитель; результат по умолчанию в `out_dir/../result` (пересоздаётся), исходники не трогаются. При несовпадении исполнителя удаляются также `#COVERURL`.
- `db`: `connect(path)` (WAL, autocommit, `check_same_thread=False`); `Jobs(conn)`: `enqueue(type, song_ref{artist,title,song_id}, params, *, parent_id=None)`, `claim_next()`, `get(id)`, `list(limit)`, `update(id, **fields)` (finished_at ставится сам), `request_cancel(id)` (queued→cancelled сразу, иначе флаг), `fail_interrupted()->int`. `Job{…, cancel_requested, parent_id; to_dict()}`. `Settings(conn, env=None).get_output()/set_output(OutputTarget)` (password=None — не менять). `OutputTarget{kind,host,share,path,user,password; from_env(), target_id, label, local_root, public()}`. `Library(conn).replace_all/upsert/remove/list(target_id,q)/get`; `LibraryItem{…; song_id, to_dict()}`; `song_id_for(target_id, rel_dir)`. `Songs(conn).get/by_rel_dir/upsert(artist,title,rel_dir,params)/delete`; `OwnSong`.
- Фикстуры: `tests/core/fixtures/` (UTF-8 UltraSinger, BOM+CRLF, cp1251 USDB, дуэт, выход UltraSinger); защищены `.gitattributes` от autocrlf.
