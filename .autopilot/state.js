window.STATE =
{
  "version": 2,
  "slug": "library-tools",
  "dir": "2026-10-27-library-tools--wip",
  "title": "Баги страницы песни и тегов, фон, обложка из сети, плейлисты, массовые действия, проверка библиотеки и другое",
  "mode": "semi",
  "depth": "deep",
  "tier": "T3",
  "briefFile": "2026-10-27-brief.md",
  "memoryFile": "CLAUDE.md",
  "memoryOwner": "autopilot",
  "skillDir": "C:/Users/work/.agents/skills/autopilot",
  "baseCommit": null,
  "startedAt": "2026-10-27T18:41:46+03:00",
  "updatedAt": "2026-10-27T19:14:58+03:00",
  "finishedAt": null,
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
      "status": "active",
      "startedAt": "2026-10-27T19:10:43+03:00"
    },
    {
      "id": "build",
      "status": "pending"
    },
    {
      "id": "review",
      "status": "pending"
    },
    {
      "id": "final",
      "status": "pending"
    }
  ],
  "requirements": {
    "total": 45,
    "done": 1,
    "inTicket": 41,
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0
    }
  ],
  "tests": null,
  "debt": {
    "placeholders": [],
    "assumptions": [],
    "emptyEnv": []
  },
  "additions": [],
  "coverage": {
    "found": 4,
    "fixed": 4,
    "deferred": 0,
    "items": []
  },
  "concerns": [],
  "blind": null,
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
    "2026-10-27T19:14:58+03:00"
  ],
  "rev": 18,
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
    }
  ],
  "reqList": [
    {
      "id": "R01",
      "text": "«Страница песни перерисовывается целиком после «Теги…», копирования или готового задания. Из-за этого останавливается играющий плеер»",
      "status": "in-ticket"
    },
    {
      "id": "R02",
      "text": "«старые плееры не освобождаются»",
      "status": "in-ticket"
    },
    {
      "id": "R03",
      "text": "«Стоит обновлять только изменившиеся блоки»",
      "status": "in-ticket"
    },
    {
      "id": "R04",
      "text": "«POST /api/tags с пустым color создаёт синий тег, а должен отвечать 400»",
      "status": "in-ticket"
    },
    {
      "id": "R05",
      "text": "«При двух одновременных созданиях тега с одним именем второе падает с ошибкой 500 вместо «Такой тег уже есть»»",
      "status": "in-ticket"
    },
    {
      "id": "R06",
      "text": "«Блок «Хранилища» на странице песни перебирает весь индекс. Достаточно запроса по match_key с индексом»",
      "status": "in-ticket"
    },
    {
      "id": "R07",
      "text": "«Пункты меню «…» не гаснут, если хранилище отвалилось после открытия страницы»",
      "status": "in-ticket"
    },
    {
      "id": "R08",
      "text": "«Нужно проверить, как на самом деле, и поправить записи» (теги при переименовании: «Подводные камни» и «Не доделано» против Tags.copy_key)",
      "status": "done"
    },
    {
      "id": "R09",
      "text": "«Своё фоновое изображение (#BACKGROUND): поставить или заменить его»",
      "status": "in-ticket"
    },
    {
      "id": "R10",
      "text": "«так же, как видео, отдельным заданием без GPU»",
      "status": "in-ticket"
    },
    {
      "id": "R11",
      "text": "«Обложка из сети: поиск через iTunes, Deezer или MusicBrainz по исполнителю и названию»",
      "status": "in-ticket"
    },
    {
      "id": "R12",
      "text": "«с выбором из нескольких вариантов»",
      "status": "in-ticket"
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
      "status": "in-ticket"
    },
    {
      "id": "R16",
      "text": "«скопировать» (несколько песен сразу)",
      "status": "in-ticket"
    },
    {
      "id": "R17",
      "text": "«скачать zip» (несколько песен сразу)",
      "status": "in-ticket"
    },
    {
      "id": "R18",
      "text": "«удалить» (несколько песен сразу)",
      "status": "in-ticket"
    },
    {
      "id": "R19",
      "text": "«сделать минусовку» (несколько песен сразу)",
      "status": "in-ticket"
    },
    {
      "id": "R20",
      "text": "«Проверка библиотеки: найти песни без звука или обложки»",
      "status": "in-ticket"
    },
    {
      "id": "R21",
      "text": "«со ссылкой #VIDEO на несуществующий файл»",
      "status": "in-ticket"
    },
    {
      "id": "R22",
      "text": "«с битой кодировкой»",
      "status": "in-ticket"
    },
    {
      "id": "R23",
      "text": "«дубли с разным написанием»",
      "status": "in-ticket"
    },
    {
      "id": "R24",
      "text": "«копии, которые разошлись между хранилищами»",
      "status": "in-ticket"
    },
    {
      "id": "R25",
      "text": "«Каждую находку можно будет исправить одной кнопкой»",
      "status": "in-ticket"
    },
    {
      "id": "R26",
      "text": "«Зеркало хранилища: автоматически поддерживать одно хранилище копией другого, например «Локальное» и Pi»",
      "status": "in-ticket"
    },
    {
      "id": "R27",
      "text": "«Задание copy для этого уже есть» (зеркало — через задание copy)",
      "status": "in-ticket"
    },
    {
      "id": "R28",
      "text": "«Подсветка подозрительных мест в «Редакторе нот»: очень короткие или очень длинные ноты»",
      "status": "in-ticket"
    },
    {
      "id": "R29",
      "text": "«скачки высоты больше октавы»",
      "status": "in-ticket"
    },
    {
      "id": "R30",
      "text": "«строки, которые не совпали с текстом (данные выравнивания уже есть)»",
      "status": "in-ticket"
    },
    {
      "id": "R31",
      "text": "«Пакетная генерация по ссылке на плейлист или альбом: каждый трек становится отдельным заданием»",
      "status": "in-ticket"
    },
    {
      "id": "R32",
      "text": "«текст ищется автоматически» (у пакетной генерации)",
      "status": "in-ticket"
    },
    {
      "id": "R33",
      "text": "«Ночная очередь: задания, поставленные на время»",
      "status": "in-ticket"
    },
    {
      "id": "R34",
      "text": "«возможность менять порядок очереди»",
      "status": "in-ticket"
    },
    {
      "id": "R35",
      "text": "«Уведомления о готовности или сбое задания: через Telegram-бота»",
      "status": "in-ticket"
    },
    {
      "id": "R36",
      "text": "«или уведомления браузера»",
      "status": "in-ticket"
    },
    {
      "id": "R37",
      "text": "«Пробный прогон песни в браузере: бегущий текст с нотами»",
      "status": "in-ticket"
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
      "status": "in-ticket"
    },
    {
      "id": "R40i",
      "text": "(подразумевается) раскрытый текст и прочее состояние страницы песни переживают обновление блоков",
      "status": "in-ticket"
    },
    {
      "id": "R41i",
      "text": "(подразумевается) массовые действия не ломаются, когда часть песен не подходит (нет хранилища, уже есть минусовка, занята заданием) — итог по каждой",
      "status": "in-ticket"
    },
    {
      "id": "R42i",
      "text": "(подразумевается) зеркало не удаляет в цели песни, которых нет в источнике, без явного согласия",
      "status": "in-ticket"
    },
    {
      "id": "R43i",
      "text": "(подразумевается) фон можно и убрать, как видео",
      "status": "in-ticket"
    },
    {
      "id": "G01",
      "text": "«баннер «хранилище недоступно» и «Файл недоступен» на странице песни вживую не проверялись» — взять (ответ «1. Ок»)",
      "status": "in-ticket"
    },
    {
      "id": "G02",
      "text": "«лучше предусмотреть возможность проиграть ноту в редакторе нот»",
      "status": "in-ticket"
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
      "at": "2026-10-27T19:14:58+03:00",
      "problems": 0
    }
  },
  "result": null
}
