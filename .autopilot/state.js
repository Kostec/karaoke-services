window.STATE =
{
  "version": 2,
  "slug": "library-tools",
  "dir": "2026-10-27-library-tools",
  "title": "Баги страницы песни и тегов, фон, обложка из сети, плейлисты, массовые действия, проверка библиотеки и другое",
  "mode": "semi",
  "depth": "deep",
  "tier": "T3",
  "briefFile": "2026-10-27-brief.md",
  "memoryFile": "CLAUDE.md",
  "memoryOwner": "autopilot",
  "skillDir": "C:/Users/work/.agents/skills/autopilot",
  "baseCommit": "ad90c41",
  "startedAt": "2026-10-27T18:41:46+03:00",
  "updatedAt": "2026-10-27T21:05:41+03:00",
  "finishedAt": "2026-10-27T21:05:41+03:00",
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-10-27T18:41:46+03:00",
      "finishedAt": "2026-10-27T18:42:06+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-10-27T18:42:06+03:00",
      "finishedAt": "2026-10-27T18:42:44+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-10-27T18:42:44+03:00",
      "finishedAt": "2026-10-27T18:48:50+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-10-27T18:48:50+03:00",
      "finishedAt": "2026-10-27T19:10:43+03:00"
    },
    {
      "id": "plan",
      "status": "done",
      "startedAt": "2026-10-27T19:10:43+03:00",
      "finishedAt": "2026-10-27T19:15:20+03:00"
    },
    {
      "id": "build",
      "status": "done",
      "startedAt": "2026-10-27T19:15:20+03:00",
      "finishedAt": "2026-10-27T20:21:44+03:00"
    },
    {
      "id": "review",
      "status": "done",
      "startedAt": "2026-10-27T20:21:44+03:00",
      "finishedAt": "2026-10-27T20:42:51+03:00"
    },
    {
      "id": "final",
      "status": "done",
      "startedAt": "2026-10-27T20:42:51+03:00",
      "finishedAt": "2026-10-27T21:05:41+03:00"
    }
  ],
  "requirements": {
    "total": 45,
    "done": 42,
    "inTicket": 0,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 3
  },
  "tickets": [
    {
      "id": "01",
      "title": "Фундамент: схема V5, теги, копии по индексу, порядок и время в очереди (ядро)",
      "requirements": [
        "R04",
        "R05",
        "R06",
        "R33",
        "R34"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "core/karaoke_core/db.py",
        "core/karaoke_core/naming.py",
        "core/karaoke_core/paths.py",
        "web/app/api_tags.py",
        "tests/core/test_db.py",
        "tests/core/test_tags.py",
        "tests/core/test_naming.py",
        "tests/api/test_tags.py"
      ],
      "review": "да — фундамент",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-10-27T19:15:20+03:00",
      "finishedAt": "2026-10-27T19:31:30+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 874,
        "failed": 0
      },
      "commit": "e463823"
    },
    {
      "id": "02",
      "title": "Страница песни обновляет только изменившееся и гасит действия при недоступном хранилище",
      "requirements": [
        "R01",
        "R02",
        "R03",
        "R40i",
        "R07",
        "G01"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "web/static/js/song-page.js",
        "web/static/js/song-page-logic.js",
        "web/static/js/player.js",
        "web/app/api_targets.py",
        "tests/frontend/song-page-logic.test.mjs",
        "tests/api/test_targets.py"
      ],
      "review": "нет",
      "model": "обычная",
      "status": "done",
      "startedAt": "2026-10-27T19:15:20+03:00",
      "finishedAt": "2026-10-27T19:23:15+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 223,
        "failed": 0
      },
      "commit": "345981b"
    },
    {
      "id": "03",
      "title": "«Редактор нот»: подсветка подозрительного и проигрывание ноты",
      "requirements": [
        "R28",
        "R29",
        "R30",
        "G02"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "web/static/js/editors/notes-checks.js",
        "web/static/js/editors/notes-checks-plugin.js",
        "web/static/js/editors/index.js",
        "web/static/js/tone.js",
        "core/karaoke_core/linealign.py",
        "web/app/api_songs.py",
        "tests/core/test_linealign.py",
        "tests/frontend/notes-checks.test.mjs",
        "tests/frontend/tone.test.mjs"
      ],
      "review": "нет",
      "model": "обычная",
      "status": "done",
      "startedAt": "2026-10-27T19:15:20+03:00",
      "finishedAt": "2026-10-27T19:26:51+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 223,
        "failed": 0
      },
      "commit": "2e3470d"
    },
    {
      "id": "04",
      "title": "Очередь: отложить до времени и переставить",
      "requirements": [
        "R33",
        "R34"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "web/app/api_queue.py",
        "web/static/js/queue-logic.js",
        "web/static/js/queue.js",
        "tests/api/test_queue_order.py",
        "tests/worker/test_runner_queue.py",
        "tests/frontend/queue-logic.test.mjs"
      ],
      "review": "нет",
      "model": "обычная",
      "status": "done",
      "startedAt": "2026-10-27T19:29:39+03:00",
      "finishedAt": "2026-10-27T19:39:27+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 929,
        "failed": 0
      },
      "commit": "999f9e3"
    },
    {
      "id": "05",
      "title": "Уведомления в Telegram и в браузере",
      "requirements": [
        "R35",
        "R36",
        "A01"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "core/karaoke_core/telegram.py",
        "worker/karaoke_worker/notify.py",
        "worker/karaoke_worker/runner.py",
        "web/app/api_settings.py",
        "web/static/js/settings.js",
        "web/static/js/notify-logic.js",
        "web/static/js/notify.js",
        "tests/core/test_telegram.py",
        "tests/api/test_settings_telegram.py",
        "tests/worker/test_runner_notify.py",
        "tests/frontend/notify-logic.test.mjs"
      ],
      "review": "да — ключи и секреты (токен бота)",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-10-27T19:29:39+03:00",
      "finishedAt": "2026-10-27T19:43:29+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 243,
        "failed": 0
      },
      "commit": "9b9a801"
    },
    {
      "id": "06",
      "title": "Действия над несколькими песнями в «Песнях»",
      "requirements": [
        "R15",
        "R16",
        "R17",
        "R18",
        "R19",
        "R41i"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "web/app/api_bulk.py",
        "web/static/js/songs.js",
        "web/static/js/song-actions.js",
        "web/static/js/select-logic.js",
        "web/app/params.py",
        "tests/api/test_bulk.py",
        "tests/frontend/select-logic.test.mjs"
      ],
      "review": "да — удаление данных (массовое удаление)",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-10-27T19:29:39+03:00",
      "finishedAt": "2026-10-27T19:43:34+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 243,
        "failed": 0
      },
      "commit": "69c8564"
    },
    {
      "id": "07",
      "title": "Фон и обложка: задание без GPU, поиск обложек в сети; ссылка на альбом ведёт в Импорт",
      "requirements": [
        "R09",
        "R10",
        "R43i",
        "R11",
        "R12",
        "R31",
        "R32"
      ],
      "blockedBy": [
        "02",
        "06"
      ],
      "wave": 3,
      "zone": [
        "web/app/api_artwork.py",
        "web/app/covers.py",
        "worker/karaoke_worker/artwork.py",
        "web/static/js/artwork.js",
        "web/static/js/artwork-logic.js",
        "web/static/js/new-song.js",
        "web/static/js/import.js",
        "web/static/js/song-page.js",
        "web/static/js/song-actions.js",
        "tests/api/test_artwork.py",
        "tests/api/test_covers.py",
        "tests/worker/test_runner_artwork.py",
        "tests/frontend/artwork-logic.test.mjs"
      ],
      "review": "нет",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-10-27T19:41:53+03:00",
      "finishedAt": "2026-10-27T20:01:19+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 1027,
        "failed": 0
      },
      "commit": "9e97933"
    },
    {
      "id": "08",
      "title": "Проверка библиотеки: задание, исправления, звук по ссылке #VIDEO, кодировка",
      "requirements": [
        "R20",
        "R21",
        "R22",
        "R23",
        "R24",
        "R25"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 3,
      "zone": [
        "worker/karaoke_worker/libcheck.py",
        "worker/karaoke_worker/audiofix.py",
        "web/app/api_library.py",
        "core/karaoke_core/ultrastar.py",
        "core/karaoke_core/libcheck.py",
        "tests/core/test_encoding.py",
        "tests/core/test_libcheck.py",
        "tests/api/test_library_check.py",
        "tests/worker/test_runner_libcheck.py",
        "tests/worker/test_runner_audio.py"
      ],
      "review": "нет",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-10-27T19:39:43+03:00",
      "finishedAt": "2026-10-27T20:00:59+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 1027,
        "failed": 0
      },
      "commit": "7e95a71"
    },
    {
      "id": "09",
      "title": "Зеркало хранилища",
      "requirements": [
        "R26",
        "R27",
        "R42i"
      ],
      "blockedBy": [
        "01",
        "05"
      ],
      "wave": 3,
      "zone": [
        "worker/karaoke_worker/mirror.py",
        "worker/karaoke_worker/runner.py",
        "core/karaoke_core/scan.py",
        "web/app/context.py",
        "web/app/api_mirrors.py",
        "web/static/js/settings.js",
        "web/static/js/mirror-logic.js",
        "tests/api/test_mirrors.py",
        "tests/worker/test_runner_mirror.py",
        "tests/frontend/mirror-logic.test.mjs"
      ],
      "review": "да — удаление данных (замена копий, корзина цели)",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-10-27T19:41:53+03:00",
      "finishedAt": "2026-10-27T20:03:15+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 1027,
        "failed": 0
      },
      "commit": "4ba0f86"
    },
    {
      "id": "10",
      "title": "Экран «Проверка библиотеки»",
      "requirements": [
        "R20",
        "R25"
      ],
      "blockedBy": [
        "07",
        "08"
      ],
      "wave": 4,
      "zone": [
        "web/static/js/check.js",
        "web/static/js/check-logic.js",
        "tests/frontend/check-logic.test.mjs"
      ],
      "review": "нет",
      "model": "обычная",
      "status": "done",
      "startedAt": "2026-10-27T20:01:20+03:00",
      "finishedAt": "2026-10-27T20:09:57+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 288,
        "failed": 0
      },
      "commit": "e0fed7e"
    },
    {
      "id": "11",
      "title": "«Прогон» песни в браузере",
      "requirements": [
        "R37",
        "A02"
      ],
      "blockedBy": [
        "03",
        "07"
      ],
      "wave": 4,
      "zone": [
        "web/static/js/play.js",
        "web/static/js/play-logic.js",
        "web/static/js/song-page.js",
        "tests/frontend/play-logic.test.mjs"
      ],
      "review": "нет",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-10-27T20:01:20+03:00",
      "finishedAt": "2026-10-27T20:10:18+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 288,
        "failed": 0
      },
      "commit": "482b4bc"
    },
    {
      "id": "12",
      "title": "Резервная копия настроек",
      "requirements": [
        "R39"
      ],
      "blockedBy": [
        "01",
        "09"
      ],
      "wave": 4,
      "zone": [
        "core/karaoke_core/backup.py",
        "web/app/api_backup.py",
        "web/static/js/settings.js",
        "web/static/js/backup-logic.js",
        "tests/core/test_backup.py",
        "tests/api/test_backup.py",
        "tests/frontend/backup-logic.test.mjs"
      ],
      "review": "да — ключи и секреты (выгрузка без секретов)",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-10-27T20:01:02+03:00",
      "finishedAt": "2026-10-27T20:21:43+03:00",
      "retries": 0,
      "repairs": 1,
      "repairFindings": [
        "хранилище из файла со сменённым адресом/логином теряет secret/token; local — только внутри /host или /output"
      ],
      "tests": {
        "passed": 1044,
        "failed": 0
      },
      "commit": "87a809e"
    },
    {
      "id": "F1",
      "title": "Исправления по ревью ветки",
      "requirements": [
        "R01",
        "R07",
        "R10",
        "R25",
        "R26",
        "R35",
        "R39",
        "R42i",
        "G02"
      ],
      "blockedBy": [],
      "wave": 5,
      "zone": [
        "web/app/main.py",
        "web/app/api_backup.py",
        "web/app/api_artwork.py",
        "web/app/api_mirrors.py",
        "web/app/api_jobs.py",
        "web/app/api_bulk.py",
        "web/app/api_library.py",
        "web/app/api_songs.py",
        "core/karaoke_core/db.py",
        "core/karaoke_core/backup.py",
        "worker/karaoke_worker/mirror.py",
        "worker/karaoke_worker/notify.py",
        "worker/karaoke_worker/artwork.py",
        "worker/karaoke_worker/handlers.py",
        "worker/karaoke_worker/libcheck.py",
        "web/static/js/song-page.js",
        "web/static/js/song-page-logic.js",
        "web/static/js/ui.js",
        "web/static/js/artwork.js",
        "web/static/js/song-actions.js",
        "web/static/js/queue.js",
        "web/static/js/backup-logic.js",
        "web/static/js/check-logic.js",
        "web/static/js/select-logic.js",
        "web/static/js/editors/notes-tools.js",
        "tests/"
      ],
      "review": "да — ремонт ветки",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-10-27T20:26:10+03:00",
      "finishedAt": "2026-10-27T20:42:49+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 1073,
        "failed": 0
      },
      "commit": "d45347c"
    },
    {
      "id": "F2",
      "title": "Исправления по слепой приёмке: «Убрать ссылку» и кодировка latin-1",
      "requirements": [
        "R21",
        "R22",
        "R25"
      ],
      "blockedBy": [],
      "wave": 6,
      "zone": [
        "web/app/api_jobs.py",
        "worker/karaoke_worker/handlers.py",
        "core/karaoke_core/ultrastar.py",
        "tests/api/test_video.py",
        "tests/worker/test_runner_video.py",
        "tests/core/test_encoding.py",
        "tests/core/fixtures/"
      ],
      "review": "нет",
      "model": "сильная",
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "startedAt": "2026-10-27T20:56:20+03:00",
      "finishedAt": "2026-10-27T21:03:36+03:00",
      "tests": {
        "passed": 1083,
        "failed": 0
      },
      "commit": "4796f83"
    }
  ],
  "tests": {
    "passed": 1083,
    "failed": 0
  },
  "debt": {
    "placeholders": [],
    "assumptions": [],
    "emptyEnv": []
  },
  "additions": [
    "сводка «Очередь опустела» в Telegram — ради R35",
    "обложка своим файлом и по ссылке тем же заданием artwork — ради R11 (A03)",
    "«Мелодия нот» в «Прогоне» — ради R37 (A02)"
  ],
  "coverage": {
    "found": 4,
    "fixed": 4,
    "deferred": 0,
    "items": []
  },
  "concerns": [
    "song-page.js — баннер .banner.warn, в согласованном макете .banner.err; экран вживую не проверялся (G01 — на приёмке)",
    "notes-checks-plugin — экран (♪, P, !, подсветка) вживую не проверялся; справка «?» в notes-tools.js не знает про P и !",
    "db.py parse_start_at — время без пояса считается UTC (фронт шлёт с Z; передано T04)",
    "db.py Jobs.schedule — у не-queued с прошлым временем ответ «Время уже прошло» вместо SCHEDULE_NOT_QUEUED",
    "db.py save_mirror — проверка хранилищ вне транзакции, дубль пары from→to не отклоняется в ядре",
    "tests/core/test_tags.py — нет теста «тег и в add, и в remove — побеждает add»",
    "queue.js — читает api.jobs(50): ожидающие старше окна не видны",
    "queue.js — экран (кнопки, «Отложить», подписи) вживую не проверялся",
    "api_bulk.py — импортирует приватные _ZipSink/_song_files/_zip_time из api_songs.py",
    "массовые действия и «Уведомления» — экран вживую не проверялся",
    "notify.js — свой опрос раз в 15 с вместо опроса статуса app.js",
    "api_settings.put_telegram — сохранённый токен бота нельзя удалить (ни форма, ни REST)",
    "telegram._HideBotPath — маскирует только строковые args; объект исключения и exc_info не чистятся",
    "POST /api/settings/telegram/test — при пустом WEB_PASSWORD шлёт текст в любой chat_id (общая модель доступа)",
    "api_bulk.py:63-79 — updated считает найденные песни, а не изменённые",
    "api_bulk.py:200-214 — после первого 503 остальные песни хранилища получают ошибку без имени хранилища",
    "libcheck — сам перестраивает индекс (list_songs + replace_all) вместо core/scan.scan_target",
    "mirror — при папке, отличной только регистром, replace_rel_dir не ставится",
    "«Зеркала» — «Убрать в корзину» с общим текстом подтверждения bulkDelete; карточка вживую не проверялась",
    "song-page-logic.blockSigs не учитывает имена обложки/фона — T07 дописал их в sigs.media в song-page.js",
    "кнопки «Медиа» не гаснут вживую при отвале хранилища (тост по нажатию)",
    "artwork remove без обложки/фона не даёт 409 — задание ничего не меняет",
    "диалоги «Обложка…»/«Фон…», «Найти в сети…», «Открыть в Импорте» вживую не проверялись",
    "mirror.py:_sync — две папки источника с одним match_key: вторая не попадёт в цель, replace_rel_dir может увести в корзину копию первой (нужно сопоставление по rel_dir + тест)",
    "test_runner_mirror — нет теста папки, отличной только регистром, и включённого зеркала с несуществующим to_target",
    "api_mirrors.active_job дублирует worker mirror.active_mirror_job",
    "settings.js trashOnlyInTarget — подтверждение не называет хранилище",
    "check.js — «Найти обложку…» не помечает строку; пометки исправлений только в памяти страницы; нет «просмотрено N песен»; экран вживую не проверялся",
    "tone.js — нет toneRelease(): AudioContext «Прогона» не закрывается в hide()",
    "play.js — певцы P3+ отдельно не обработаны; «Мелодия нот» на слух не проверялась",
    "backup.apply_import зовёт приватный Settings._write_targets для новых хранилищ",
    "карточка «Резервная копия» вживую не проверялась",
    "backup.apply_import — новый id из файла может совпасть с добавленным между планом и применением (дубль id)",
    "backup — смена chat_id Telegram из файла не видна явно в предпросмотре",
    "backup.py — правила identity и локального пути скопированы из api_targets (два места)",
    "backup._target_path — плохой локальный путь отклоняет весь файл общим текстом, без имени хранилища"
  ],
  "blind": {
    "checked": 20,
    "matched": 19,
    "mismatches": [
      "R25 — «Убрать ссылку» у находки video_missing всегда 409 «У песни нет видео» (исправляется в F2)"
    ]
  },
  "beats": [
    "2026-10-27T18:41:46+03:00",
    "2026-10-27T18:42:06+03:00",
    "2026-10-27T18:42:14+03:00",
    "2026-10-27T18:42:43+03:00",
    "2026-10-27T18:42:44+03:00",
    "2026-10-27T18:43:55+03:00",
    "2026-10-27T18:48:18+03:00",
    "2026-10-27T18:48:50+03:00",
    "2026-10-27T19:03:34+03:00",
    "2026-10-27T19:06:30+03:00",
    "2026-10-27T19:10:42+03:00",
    "2026-10-27T19:10:43+03:00",
    "2026-10-27T19:14:57+03:00",
    "2026-10-27T19:14:58+03:00",
    "2026-10-27T19:15:14+03:00",
    "2026-10-27T19:15:20+03:00",
    "2026-10-27T19:23:15+03:00",
    "2026-10-27T19:23:16+03:00",
    "2026-10-27T19:26:51+03:00",
    "2026-10-27T19:26:52+03:00",
    "2026-10-27T19:29:38+03:00",
    "2026-10-27T19:29:39+03:00",
    "2026-10-27T19:31:30+03:00",
    "2026-10-27T19:31:31+03:00",
    "2026-10-27T19:39:27+03:00",
    "2026-10-27T19:39:29+03:00",
    "2026-10-27T19:39:43+03:00",
    "2026-10-27T19:41:09+03:00",
    "2026-10-27T19:41:51+03:00",
    "2026-10-27T19:41:52+03:00",
    "2026-10-27T19:41:53+03:00",
    "2026-10-27T19:41:54+03:00",
    "2026-10-27T19:41:55+03:00",
    "2026-10-27T19:43:29+03:00",
    "2026-10-27T19:43:30+03:00",
    "2026-10-27T19:43:34+03:00",
    "2026-10-27T19:43:35+03:00",
    "2026-10-27T20:00:59+03:00",
    "2026-10-27T20:01:01+03:00",
    "2026-10-27T20:01:02+03:00",
    "2026-10-27T20:01:03+03:00",
    "2026-10-27T20:01:19+03:00",
    "2026-10-27T20:01:20+03:00",
    "2026-10-27T20:01:21+03:00",
    "2026-10-27T20:03:15+03:00",
    "2026-10-27T20:03:16+03:00",
    "2026-10-27T20:09:57+03:00",
    "2026-10-27T20:09:58+03:00",
    "2026-10-27T20:10:18+03:00",
    "2026-10-27T20:10:19+03:00",
    "2026-10-27T20:13:10+03:00",
    "2026-10-27T20:13:11+03:00",
    "2026-10-27T20:13:12+03:00",
    "2026-10-27T20:14:25+03:00",
    "2026-10-27T20:14:26+03:00",
    "2026-10-27T20:20:49+03:00",
    "2026-10-27T20:20:50+03:00",
    "2026-10-27T20:21:43+03:00",
    "2026-10-27T20:21:44+03:00",
    "2026-10-27T20:26:08+03:00",
    "2026-10-27T20:26:09+03:00",
    "2026-10-27T20:26:10+03:00",
    "2026-10-27T20:41:17+03:00",
    "2026-10-27T20:41:18+03:00",
    "2026-10-27T20:42:49+03:00",
    "2026-10-27T20:42:50+03:00",
    "2026-10-27T20:42:51+03:00",
    "2026-10-27T20:56:17+03:00",
    "2026-10-27T20:56:18+03:00",
    "2026-10-27T20:56:19+03:00",
    "2026-10-27T20:56:20+03:00",
    "2026-10-27T21:03:36+03:00",
    "2026-10-27T21:03:37+03:00",
    "2026-10-27T21:05:41+03:00"
  ],
  "rev": 86,
  "waiting": null,
  "waits": [
    {
      "kind": "briefing",
      "from": "2026-10-27T18:43:55+03:00",
      "to": "2026-10-27T18:48:18+03:00"
    },
    {
      "kind": "spec",
      "from": "2026-10-27T19:06:30+03:00",
      "to": "2026-10-27T19:10:42+03:00"
    }
  ],
  "log": [
    {
      "t": "2026-10-27T18:41:46+03:00",
      "k": "init"
    },
    {
      "t": "2026-10-27T18:42:06+03:00",
      "k": "stage",
      "id": "manifest",
      "act": "start"
    },
    {
      "t": "2026-10-27T18:42:44+03:00",
      "k": "stage",
      "id": "briefing",
      "act": "start"
    },
    {
      "t": "2026-10-27T18:43:55+03:00",
      "k": "ask",
      "kind": "briefing",
      "note": "4 вопроса — хвосты и правка в дереве, микрофон/уведомления по http, папка плейлистов на Pi, удаления в зеркале"
    },
    {
      "t": "2026-10-27T18:48:18+03:00",
      "k": "answered",
      "kind": "briefing"
    },
    {
      "t": "2026-10-27T18:48:50+03:00",
      "k": "gate",
      "g": "G1",
      "ok": false,
      "open": 42,
      "total": 45
    },
    {
      "t": "2026-10-27T18:48:50+03:00",
      "k": "stage",
      "id": "spec",
      "act": "start"
    },
    {
      "t": "2026-10-27T19:03:34+03:00",
      "k": "gate",
      "g": "G2",
      "ok": true,
      "found": 4,
      "fixed": 4,
      "deferred": 0
    },
    {
      "t": "2026-10-27T19:06:30+03:00",
      "k": "ask",
      "kind": "spec",
      "note": "согласовать макет новых экранов (договорились: крупные изменения вида — по макету)"
    },
    {
      "t": "2026-10-27T19:10:42+03:00",
      "k": "answered",
      "kind": "spec"
    },
    {
      "t": "2026-10-27T19:10:43+03:00",
      "k": "stage",
      "id": "plan",
      "act": "start"
    },
    {
      "t": "2026-10-27T19:14:57+03:00",
      "k": "tier",
      "v": "T3"
    },
    {
      "t": "2026-10-27T19:14:58+03:00",
      "k": "tickets",
      "n": 12
    },
    {
      "t": "2026-10-27T19:14:58+03:00",
      "k": "gate",
      "g": "G3",
      "ok": true,
      "problems": 0
    },
    {
      "t": "2026-10-27T19:15:20+03:00",
      "k": "stage",
      "id": "build",
      "act": "start"
    },
    {
      "t": "2026-10-27T19:15:20+03:00",
      "k": "ticket",
      "ids": [
        "01",
        "02",
        "03"
      ],
      "act": "start"
    },
    {
      "t": "2026-10-27T19:23:15+03:00",
      "k": "ticket",
      "ids": [
        "02"
      ],
      "act": "done",
      "tests": {
        "passed": 223,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T19:23:16+03:00",
      "k": "add",
      "key": "concerns",
      "n": 1
    },
    {
      "t": "2026-10-27T19:26:51+03:00",
      "k": "ticket",
      "ids": [
        "03"
      ],
      "act": "done",
      "tests": {
        "passed": 223,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T19:26:52+03:00",
      "k": "add",
      "key": "concerns",
      "n": 1
    },
    {
      "t": "2026-10-27T19:29:38+03:00",
      "k": "ticket",
      "ids": [
        "01"
      ],
      "act": "done",
      "tests": {
        "passed": 874,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T19:29:39+03:00",
      "k": "ticket",
      "ids": [
        "01"
      ],
      "act": "review"
    },
    {
      "t": "2026-10-27T19:29:39+03:00",
      "k": "ticket",
      "ids": [
        "04",
        "05",
        "06"
      ],
      "act": "start"
    },
    {
      "t": "2026-10-27T19:31:30+03:00",
      "k": "ticket",
      "ids": [
        "01"
      ],
      "act": "done"
    },
    {
      "t": "2026-10-27T19:31:31+03:00",
      "k": "add",
      "key": "concerns",
      "n": 4
    },
    {
      "t": "2026-10-27T19:39:27+03:00",
      "k": "ticket",
      "ids": [
        "04"
      ],
      "act": "done",
      "tests": {
        "passed": 929,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T19:39:29+03:00",
      "k": "add",
      "key": "concerns",
      "n": 2
    },
    {
      "t": "2026-10-27T19:39:43+03:00",
      "k": "ticket",
      "ids": [
        "08"
      ],
      "act": "start"
    },
    {
      "t": "2026-10-27T19:41:09+03:00",
      "k": "ticket",
      "ids": [
        "06"
      ],
      "act": "done",
      "tests": {
        "passed": 243,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T19:41:51+03:00",
      "k": "ticket",
      "ids": [
        "05"
      ],
      "act": "done",
      "tests": {
        "passed": 243,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T19:41:52+03:00",
      "k": "ticket",
      "ids": [
        "06"
      ],
      "act": "review"
    },
    {
      "t": "2026-10-27T19:41:52+03:00",
      "k": "ticket",
      "ids": [
        "05"
      ],
      "act": "review"
    },
    {
      "t": "2026-10-27T19:41:53+03:00",
      "k": "ticket",
      "ids": [
        "07",
        "09"
      ],
      "act": "start"
    },
    {
      "t": "2026-10-27T19:41:54+03:00",
      "k": "add",
      "key": "additions",
      "n": 1
    },
    {
      "t": "2026-10-27T19:41:55+03:00",
      "k": "add",
      "key": "concerns",
      "n": 3
    },
    {
      "t": "2026-10-27T19:43:29+03:00",
      "k": "ticket",
      "ids": [
        "05"
      ],
      "act": "done"
    },
    {
      "t": "2026-10-27T19:43:30+03:00",
      "k": "add",
      "key": "concerns",
      "n": 3
    },
    {
      "t": "2026-10-27T19:43:34+03:00",
      "k": "ticket",
      "ids": [
        "06"
      ],
      "act": "done"
    },
    {
      "t": "2026-10-27T19:43:35+03:00",
      "k": "add",
      "key": "concerns",
      "n": 2
    },
    {
      "t": "2026-10-27T20:00:59+03:00",
      "k": "ticket",
      "ids": [
        "08"
      ],
      "act": "done",
      "tests": {
        "passed": 1027,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T20:01:01+03:00",
      "k": "ticket",
      "ids": [
        "09"
      ],
      "act": "done",
      "tests": {
        "passed": 1027,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T20:01:01+03:00",
      "k": "ticket",
      "ids": [
        "09"
      ],
      "act": "review"
    },
    {
      "t": "2026-10-27T20:01:02+03:00",
      "k": "ticket",
      "ids": [
        "12"
      ],
      "act": "start"
    },
    {
      "t": "2026-10-27T20:01:03+03:00",
      "k": "add",
      "key": "concerns",
      "n": 3
    },
    {
      "t": "2026-10-27T20:01:19+03:00",
      "k": "ticket",
      "ids": [
        "07"
      ],
      "act": "done",
      "tests": {
        "passed": 1027,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T20:01:20+03:00",
      "k": "ticket",
      "ids": [
        "10",
        "11"
      ],
      "act": "start"
    },
    {
      "t": "2026-10-27T20:01:20+03:00",
      "k": "add",
      "key": "additions",
      "n": 1
    },
    {
      "t": "2026-10-27T20:01:21+03:00",
      "k": "add",
      "key": "concerns",
      "n": 4
    },
    {
      "t": "2026-10-27T20:03:15+03:00",
      "k": "ticket",
      "ids": [
        "09"
      ],
      "act": "done"
    },
    {
      "t": "2026-10-27T20:03:16+03:00",
      "k": "add",
      "key": "concerns",
      "n": 4
    },
    {
      "t": "2026-10-27T20:09:57+03:00",
      "k": "ticket",
      "ids": [
        "10"
      ],
      "act": "done",
      "tests": {
        "passed": 288,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T20:09:58+03:00",
      "k": "add",
      "key": "concerns",
      "n": 1
    },
    {
      "t": "2026-10-27T20:10:18+03:00",
      "k": "ticket",
      "ids": [
        "11"
      ],
      "act": "done",
      "tests": {
        "passed": 288,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T20:10:19+03:00",
      "k": "add",
      "key": "additions",
      "n": 1
    },
    {
      "t": "2026-10-27T20:10:19+03:00",
      "k": "add",
      "key": "concerns",
      "n": 2
    },
    {
      "t": "2026-10-27T20:13:10+03:00",
      "k": "ticket",
      "ids": [
        "12"
      ],
      "act": "done",
      "tests": {
        "passed": 1044,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T20:13:11+03:00",
      "k": "ticket",
      "ids": [
        "12"
      ],
      "act": "review"
    },
    {
      "t": "2026-10-27T20:13:12+03:00",
      "k": "add",
      "key": "concerns",
      "n": 2
    },
    {
      "t": "2026-10-27T20:14:25+03:00",
      "k": "ticket",
      "ids": [
        "12"
      ],
      "act": "repair",
      "note": "хранилище из файла со сменённым адресом/логином теряет secret/token; local — только внутри /host или /output"
    },
    {
      "t": "2026-10-27T20:14:26+03:00",
      "k": "add",
      "key": "concerns",
      "n": 2
    },
    {
      "t": "2026-10-27T20:20:49+03:00",
      "k": "ticket",
      "ids": [
        "12"
      ],
      "act": "review"
    },
    {
      "t": "2026-10-27T20:20:50+03:00",
      "k": "add",
      "key": "concerns",
      "n": 1
    },
    {
      "t": "2026-10-27T20:21:43+03:00",
      "k": "ticket",
      "ids": [
        "12"
      ],
      "act": "done"
    },
    {
      "t": "2026-10-27T20:21:43+03:00",
      "k": "add",
      "key": "concerns",
      "n": 1
    },
    {
      "t": "2026-10-27T20:21:44+03:00",
      "k": "stage",
      "id": "review",
      "act": "start"
    },
    {
      "t": "2026-10-27T20:26:08+03:00",
      "k": "tickets",
      "n": 13
    },
    {
      "t": "2026-10-27T20:26:09+03:00",
      "k": "gate",
      "g": "G3",
      "ok": true,
      "problems": 0
    },
    {
      "t": "2026-10-27T20:26:10+03:00",
      "k": "add",
      "key": "report",
      "n": 15
    },
    {
      "t": "2026-10-27T20:26:10+03:00",
      "k": "ticket",
      "ids": [
        "F1"
      ],
      "act": "start"
    },
    {
      "t": "2026-10-27T20:41:17+03:00",
      "k": "ticket",
      "ids": [
        "F1"
      ],
      "act": "done",
      "tests": {
        "passed": 1073,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T20:41:18+03:00",
      "k": "ticket",
      "ids": [
        "F1"
      ],
      "act": "review"
    },
    {
      "t": "2026-10-27T20:42:49+03:00",
      "k": "ticket",
      "ids": [
        "F1"
      ],
      "act": "done"
    },
    {
      "t": "2026-10-27T20:42:50+03:00",
      "k": "add",
      "key": "report",
      "n": 1
    },
    {
      "t": "2026-10-27T20:42:51+03:00",
      "k": "stage",
      "id": "final",
      "act": "start"
    },
    {
      "t": "2026-10-27T20:56:17+03:00",
      "k": "gate",
      "g": "G4",
      "ok": false,
      "checked": 20,
      "matched": 19
    },
    {
      "t": "2026-10-27T20:56:18+03:00",
      "k": "tickets",
      "n": 14
    },
    {
      "t": "2026-10-27T20:56:19+03:00",
      "k": "gate",
      "g": "G3",
      "ok": true,
      "problems": 0
    },
    {
      "t": "2026-10-27T20:56:20+03:00",
      "k": "ticket",
      "ids": [
        "F2"
      ],
      "act": "start"
    },
    {
      "t": "2026-10-27T21:03:36+03:00",
      "k": "ticket",
      "ids": [
        "F2"
      ],
      "act": "done",
      "tests": {
        "passed": 1083,
        "failed": 0
      }
    },
    {
      "t": "2026-10-27T21:03:37+03:00",
      "k": "tests",
      "passed": 1083,
      "failed": 0
    },
    {
      "t": "2026-10-27T21:05:41+03:00",
      "k": "finish",
      "result": "Страница песни не глушит плеер, теги без багов, фон и обложка из сети, массовые действия, проверка библиотеки с исправлениями, зеркало хранилища, подсветка и звук нот, ночная очередь, уведомления в Telegram, «Прогон» и резервная копия настроек"
    }
  ],
  "reqList": [
    {
      "id": "R01",
      "text": "«Страница песни перерисовывается целиком после «Теги…», копирования или готового задания. Из-за этого останавливается играющий плеер»",
      "status": "done"
    },
    {
      "id": "R02",
      "text": "«старые плееры не освобождаются»",
      "status": "done"
    },
    {
      "id": "R03",
      "text": "«Стоит обновлять только изменившиеся блоки»",
      "status": "done"
    },
    {
      "id": "R04",
      "text": "«POST /api/tags с пустым color создаёт синий тег, а должен отвечать 400»",
      "status": "done"
    },
    {
      "id": "R05",
      "text": "«При двух одновременных созданиях тега с одним именем второе падает с ошибкой 500 вместо «Такой тег уже есть»»",
      "status": "done"
    },
    {
      "id": "R06",
      "text": "«Блок «Хранилища» на странице песни перебирает весь индекс. Достаточно запроса по match_key с индексом»",
      "status": "done"
    },
    {
      "id": "R07",
      "text": "«Пункты меню «…» не гаснут, если хранилище отвалилось после открытия страницы»",
      "status": "done"
    },
    {
      "id": "R08",
      "text": "«Нужно проверить, как на самом деле, и поправить записи» (теги при переименовании: «Подводные камни» и «Не доделано» против Tags.copy_key)",
      "status": "done"
    },
    {
      "id": "R09",
      "text": "«Своё фоновое изображение (#BACKGROUND): поставить или заменить его»",
      "status": "done"
    },
    {
      "id": "R10",
      "text": "«так же, как видео, отдельным заданием без GPU»",
      "status": "done"
    },
    {
      "id": "R11",
      "text": "«Обложка из сети: поиск через iTunes, Deezer или MusicBrainz по исполнителю и названию»",
      "status": "done"
    },
    {
      "id": "R12",
      "text": "«с выбором из нескольких вариантов»",
      "status": "done"
    },
    {
      "id": "R13",
      "text": "«Плейлисты на вечер: список песен с порядком»",
      "status": "dropped",
      "why": "пользователь: «Пока что не добавляй плейлисты»"
    },
    {
      "id": "R14",
      "text": "«выгрузка файла плейлиста UltraStar (.upl) прямо в хранилище на Pi»",
      "status": "dropped",
      "why": "пользователь: «Пока что не добавляй плейлисты»"
    },
    {
      "id": "R15",
      "text": "«Действия над несколькими песнями сразу в «Песнях»: поставить теги»",
      "status": "done"
    },
    {
      "id": "R16",
      "text": "«скопировать» (несколько песен сразу)",
      "status": "done"
    },
    {
      "id": "R17",
      "text": "«скачать zip» (несколько песен сразу)",
      "status": "done"
    },
    {
      "id": "R18",
      "text": "«удалить» (несколько песен сразу)",
      "status": "done"
    },
    {
      "id": "R19",
      "text": "«сделать минусовку» (несколько песен сразу)",
      "status": "done"
    },
    {
      "id": "R20",
      "text": "«Проверка библиотеки: найти песни без звука или обложки»",
      "status": "done"
    },
    {
      "id": "R21",
      "text": "«со ссылкой #VIDEO на несуществующий файл»",
      "status": "done"
    },
    {
      "id": "R22",
      "text": "«с битой кодировкой»",
      "status": "done"
    },
    {
      "id": "R23",
      "text": "«дубли с разным написанием»",
      "status": "done"
    },
    {
      "id": "R24",
      "text": "«копии, которые разошлись между хранилищами»",
      "status": "done"
    },
    {
      "id": "R25",
      "text": "«Каждую находку можно будет исправить одной кнопкой»",
      "status": "done"
    },
    {
      "id": "R26",
      "text": "«Зеркало хранилища: автоматически поддерживать одно хранилище копией другого, например «Локальное» и Pi»",
      "status": "done"
    },
    {
      "id": "R27",
      "text": "«Задание copy для этого уже есть» (зеркало — через задание copy)",
      "status": "done"
    },
    {
      "id": "R28",
      "text": "«Подсветка подозрительных мест в «Редакторе нот»: очень короткие или очень длинные ноты»",
      "status": "done"
    },
    {
      "id": "R29",
      "text": "«скачки высоты больше октавы»",
      "status": "done"
    },
    {
      "id": "R30",
      "text": "«строки, которые не совпали с текстом (данные выравнивания уже есть)»",
      "status": "done"
    },
    {
      "id": "R31",
      "text": "«Пакетная генерация по ссылке на плейлист или альбом: каждый трек становится отдельным заданием»",
      "status": "done"
    },
    {
      "id": "R32",
      "text": "«текст ищется автоматически» (у пакетной генерации)",
      "status": "done"
    },
    {
      "id": "R33",
      "text": "«Ночная очередь: задания, поставленные на время»",
      "status": "done"
    },
    {
      "id": "R34",
      "text": "«возможность менять порядок очереди»",
      "status": "done"
    },
    {
      "id": "R35",
      "text": "«Уведомления о готовности или сбое задания: через Telegram-бота»",
      "status": "done"
    },
    {
      "id": "R36",
      "text": "«или уведомления браузера»",
      "status": "done"
    },
    {
      "id": "R37",
      "text": "«Пробный прогон песни в браузере: бегущий текст с нотами»",
      "status": "done"
    },
    {
      "id": "R38",
      "text": "«проверка высоты голоса через микрофон»",
      "status": "dropped",
      "why": "пользователь: «Думаю можно обойтись без микрофона»"
    },
    {
      "id": "R39",
      "text": "«Резервная копия настроек: выгрузка и загрузка тегов, списка хранилищ и учёток (без паролей) одним файлом»",
      "status": "done"
    },
    {
      "id": "R40i",
      "text": "(подразумевается) раскрытый текст и прочее состояние страницы песни переживают обновление блоков",
      "status": "done"
    },
    {
      "id": "R41i",
      "text": "(подразумевается) массовые действия не ломаются, когда часть песен не подходит (нет хранилища, уже есть минусовка, занята заданием) — итог по каждой",
      "status": "done"
    },
    {
      "id": "R42i",
      "text": "(подразумевается) зеркало не удаляет в цели песни, которых нет в источнике, без явного согласия",
      "status": "done"
    },
    {
      "id": "R43i",
      "text": "(подразумевается) фон можно и убрать, как видео",
      "status": "done"
    },
    {
      "id": "G01",
      "text": "«баннер «хранилище недоступно» и «Файл недоступен» на странице песни вживую не проверялись» — взять (ответ «1. Ок»)",
      "status": "done"
    },
    {
      "id": "G02",
      "text": "«лучше предусмотреть возможность проиграть ноту в редакторе нот»",
      "status": "done"
    }
  ],
  "gates": {
    "G1": {
      "ok": false,
      "at": "2026-10-27T18:48:50+03:00",
      "open": 42,
      "total": 45
    },
    "G2": {
      "ok": true,
      "at": "2026-10-27T19:03:34+03:00",
      "found": 4,
      "fixed": 4,
      "deferred": 0
    },
    "G3": {
      "ok": true,
      "at": "2026-10-27T20:56:19+03:00",
      "problems": 0
    },
    "G4": {
      "ok": false,
      "at": "2026-10-27T20:56:17+03:00",
      "checked": 20,
      "matched": 19
    }
  },
  "result": "Страница песни не глушит плеер, теги без багов, фон и обложка из сети, массовые действия, проверка библиотеки с исправлениями, зеркало хранилища, подсветка и звук нот, ночная очередь, уведомления в Telegram, «Прогон» и резервная копия настроек",
  "report": [
    "Токен Telegram-бота можно заменить, но не стереть — уведомления выключаются галочками или очисткой chat id",
    "Без WEB_PASSWORD любой, кто открыл веб в домашней сети, может отправить тестовое сообщение от вашего бота",
    "Ссылка на картинку для обложки/фона может перенаправить сервер в домашнюю сеть; скачивается только картинка, риск низкий",
    "Предпросмотр загрузки настроек не показывает, на какой chat id Telegram переключатся уведомления",
    "Загрузка настроек применяется не одной транзакцией: сбой посередине оставит часть изменений",
    "Правила проверки хранилища продублированы в core/backup.py и api_targets.py",
    "Зеркало при папке, отличной только регистром, на Google Диске оставит две папки",
    "Очередь показывает 50 последних заданий: после массовой минусовки первые ожидающие не видны и номера мест неверны",
    "Ошибка 503 от действия гасит пункты «…» не сразу, а при следующем опросе (до 15 с)",
    "«Найти обложку…» в «Проверке» не помечает строку; пометки «Исправлено» живут, пока открыта страница",
    "Подтверждение «Убрать в корзину» в «Зеркалах» не называет песню и хранилище",
    "«Убрать» в диалоге обложки ставит задание даже без обложки; убирать обложку спецификация не требовала",
    "Двойное нажатие «Проверить»/«Синхронизировать» может поставить два задания",
    "Звук, скачанный по #VIDEO для песни с .txt вида song.txt, получит имя song.mp3",
    "Неверный текст ошибки при попытке отложить уже идущее задание с прошедшим временем",
    "Если веб когда-нибудь поставить за обратный прокси, который меняет Host и не передаёт X-Forwarded-Host, все изменяющие запросы получат отказ 403"
  ]
}
