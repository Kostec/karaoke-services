window.STATE =
{
  "slug": "lyrics-songbook-import",
  "dir": "2026-10-20-lyrics-songbook-import",
  "title": "Текст из сервиса текстов и импорт песен из сборников UltraStar",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T2",
  "briefFile": "2026-10-20-brief.md",
  "memoryFile": "CLAUDE.md",
  "skillDir": "C:/Users/work/.claude/skills/autopilot",
  "startedAt": "2026-10-20T10:18:24+03:00",
  "updatedAt": "2026-10-20T12:42:32+03:00",
  "finishedAt": "2026-10-20T12:42:32+03:00",
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-10-20T10:18:24+03:00",
      "finishedAt": "2026-10-20T10:18:50+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-10-20T10:18:50+03:00",
      "finishedAt": "2026-10-20T10:19:06+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-10-20T10:19:06+03:00",
      "note": "3 вопроса",
      "finishedAt": "2026-10-20T10:30:59+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "finishedAt": "2026-10-20T10:38:30+03:00"
    },
    {
      "id": "plan",
      "status": "done",
      "startedAt": "2026-10-20T10:40:16+03:00",
      "note": "6 тасков, ярус T2, 4 волны",
      "finishedAt": "2026-10-20T10:40:35+03:00"
    },
    {
      "id": "build",
      "status": "done",
      "startedAt": "2026-10-20T10:40:35+03:00",
      "note": "11 из 11 тасков готовы",
      "finishedAt": "2026-10-20T11:57:26+03:00"
    },
    {
      "id": "review",
      "status": "done",
      "startedAt": "2026-10-20T10:47:02+03:00",
      "note": "проверено 11 из 11",
      "finishedAt": "2026-10-20T11:57:26+03:00"
    },
    {
      "id": "final",
      "status": "done",
      "startedAt": "2026-10-20T11:57:26+03:00",
      "finishedAt": "2026-10-20T12:42:32+03:00",
      "note": "слепая приёмка: 2 расхождения — исправлены; папка добавлена после неё"
    }
  ],
  "requirements": {
    "total": 16,
    "done": 16,
    "inTicket": 0,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Поиск текста в LRCLIB из формы песни",
      "requirements": [
        "R01",
        "R05i"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "core/karaoke_core/http.py",
        "web/app/lyrics.py",
        "web/app/api_lyrics.py",
        "web/static/js/new-song.js"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-20T10:40:35+03:00",
      "finishedAt": "2026-10-20T10:50:26+03:00",
      "commit": "766f2c5",
      "tests": {
        "passed": 293,
        "failed": 0
      },
      "files": [
        "core/karaoke_core/http.py",
        "web/app/lyrics.py",
        "web/app/api_lyrics.py",
        "web/static/js/lyrics-search.js",
        "web/static/js/new-song.js"
      ]
    },
    {
      "id": "02",
      "title": "Разбор сборника: zip, песни, ссылки YouTube",
      "requirements": [
        "G01",
        "R04",
        "R07i"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "core/karaoke_core/songpack.py",
        "core/karaoke_core/paths.py"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-20T10:40:35+03:00",
      "repairFindings": [
        "тест лимита распаковки не краснеет — падает через «Архив повреждён»"
      ],
      "finishedAt": "2026-10-20T10:51:59+03:00",
      "commit": "38e7a87",
      "files": [
        "core/karaoke_core/songpack.py",
        "core/karaoke_core/paths.py",
        "tests/core/test_songpack.py"
      ]
    },
    {
      "id": "03",
      "title": "usdb: учётка в «Настройках» и поиск",
      "requirements": [
        "R03",
        "R08i",
        "G03"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "web/app/usdb.py",
        "web/app/api_usdb.py",
        "web/static/js/settings.js",
        "core/karaoke_core/db.py"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-20T10:50:26+03:00",
      "finishedAt": "2026-10-20T11:02:10+03:00",
      "commit": "e561d73",
      "tests": {
        "passed": 310,
        "failed": 0
      },
      "files": [
        "web/app/usdb.py",
        "web/app/api_usdb.py",
        "web/app/api_settings.py",
        "core/karaoke_core/db.py",
        "web/static/js/settings.js"
      ]
    },
    {
      "id": "05",
      "title": "Задание «Импорт» в воркере",
      "requirements": [
        "R02",
        "R06i",
        "R07i",
        "G05"
      ],
      "blockedBy": [
        "02"
      ],
      "wave": 2,
      "zone": [
        "worker/",
        "tests/worker/"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-20T10:47:02+03:00",
      "repairFindings": [
        "рестарт не проверяет повторное использование in/input.mp3; обложка теряется на рестарте"
      ],
      "finishedAt": "2026-10-20T11:13:33+03:00",
      "commit": "5a5ee6b",
      "tests": {
        "passed": 381,
        "failed": 0
      },
      "files": [
        "worker/karaoke_worker/handlers.py",
        "worker/Dockerfile",
        "worker/karaoke_worker/selfcheck.py",
        "tests/worker/test_runner_import.py"
      ]
    },
    {
      "id": "04",
      "title": "Импорт на сервере: разбор и постановка",
      "requirements": [
        "R02",
        "R04",
        "G01",
        "G02",
        "G04",
        "R07i"
      ],
      "blockedBy": [
        "02",
        "03"
      ],
      "wave": 3,
      "zone": [
        "web/app/api_import.py",
        ".env.example"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 2,
      "handoffs": 0,
      "startedAt": "2026-10-20T11:02:10+03:00",
      "repairFindings": [
        "`..` в папке GitHub-ссылки",
        "тест путей вне files/ не краснел для cover/audio"
      ],
      "finishedAt": "2026-10-20T11:17:14+03:00",
      "commit": "955d28e",
      "tests": {
        "passed": 391,
        "failed": 0
      },
      "files": [
        "web/app/api_import.py",
        "tests/api/test_import.py"
      ]
    },
    {
      "id": "06",
      "title": "Раздел «Импорт» в интерфейсе",
      "requirements": [
        "R02",
        "R03",
        "R04",
        "G01",
        "G02",
        "G03",
        "G04",
        "G05",
        "R06i",
        "R07i"
      ],
      "blockedBy": [
        "04",
        "05"
      ],
      "wave": 4,
      "zone": [
        "web/static/js/import.js",
        "web/static/index.html"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-20T11:17:14+03:00",
      "finishedAt": "2026-10-20T11:29:39+03:00",
      "commit": "7a40047",
      "tests": {
        "passed": 393,
        "failed": 0
      },
      "files": [
        "web/static/js/import.js",
        "web/static/js/import-logic.js",
        "web/static/index.html",
        "web/app/api_songs.py"
      ]
    },
    {
      "id": "08",
      "title": "UltraSinger: тайминги строк из LRC",
      "requirements": [
        "G06",
        "G07"
      ],
      "blockedBy": [],
      "wave": 2,
      "zone": [
        "D:/Projects/UltraSinger"
      ],
      "status": "done",
      "startedAt": "2026-10-20T10:50:26+03:00",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "repairFindings": [
        "LRC не в UTF-8 роняет прогон UltraSinger"
      ],
      "finishedAt": "2026-10-20T10:59:00+03:00",
      "commit": "UltraSinger 8c6008c",
      "tests": {
        "passed": 14,
        "failed": 0
      },
      "files": [
        "UltraSinger: src/modules/Speech_Recognition/lrc_timing.py",
        "src/Settings.py",
        "src/UltraSinger.py",
        "src/modules/Speech_Recognition/Whisper.py"
      ]
    },
    {
      "id": "07",
      "title": "Синхронизированный текст: от LRCLIB до UltraSinger",
      "requirements": [
        "G06"
      ],
      "blockedBy": [
        "01",
        "04",
        "05",
        "06",
        "08"
      ],
      "wave": 5,
      "zone": [
        "web/app/api_jobs.py",
        "worker/karaoke_worker/handlers.py"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-20T11:29:39+03:00",
      "finishedAt": "2026-10-20T11:44:16+03:00",
      "commit": "4345cdc",
      "tests": {
        "passed": 403,
        "failed": 0
      },
      "files": [
        "web/app/lyrics.py",
        "web/app/api_jobs.py",
        "web/static/js/new-song.js",
        "worker/karaoke_worker/handlers.py"
      ]
    },
    {
      "id": "09",
      "title": "Долг сервера: повторы, надёжный usdb, сеть",
      "requirements": [
        "R03",
        "R02",
        "G01",
        "G06"
      ],
      "blockedBy": [
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08"
      ],
      "wave": 6,
      "zone": [
        "web/app/",
        "core/karaoke_core/",
        "worker/karaoke_worker/handlers.py"
      ],
      "status": "done",
      "startedAt": "2026-10-20T11:57:26+03:00",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "repairFindings": [
        "непроверенный признак входа usdb ломает вход целиком"
      ],
      "finishedAt": "2026-10-20T12:17:08+03:00",
      "commit": "8e50219",
      "tests": {
        "passed": 415,
        "failed": 0
      },
      "files": [
        "core/karaoke_core/http.py",
        "web/app/usdb.py",
        "web/app/api_import.py",
        "web/app/api_jobs.py"
      ]
    },
    {
      "id": "10",
      "title": "Долг интерфейса: тексты, сохранность LRC, пак",
      "requirements": [
        "R01",
        "G06",
        "G01"
      ],
      "blockedBy": [
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08"
      ],
      "wave": 6,
      "zone": [
        "web/static/js/",
        "web/static/css/"
      ],
      "status": "done",
      "startedAt": "2026-10-20T11:57:26+03:00",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "finishedAt": "2026-10-20T12:09:40+03:00",
      "commit": "9a845ad",
      "tests": {
        "passed": 57,
        "failed": 0
      },
      "files": [
        "web/static/js/lyrics-search.js",
        "web/static/js/new-song.js",
        "web/static/js/import.js",
        "web/static/js/import-logic.js"
      ]
    },
    {
      "id": "11",
      "title": "Загрузка целой папки: импорт и генерация",
      "requirements": [
        "G08"
      ],
      "blockedBy": [
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08",
        "09",
        "10"
      ],
      "wave": 7,
      "zone": [
        "web/static/js/import.js",
        "web/static/js/folder-logic.js",
        "web/app/api_import.py"
      ],
      "status": "done",
      "startedAt": "2026-10-20T12:17:08+03:00",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "repairFindings": [
        "правка строки во время поиска текстов навсегда блокирует «Сгенерировать»; OSError → 500 в files"
      ],
      "finishedAt": "2026-10-20T12:42:32+03:00",
      "commit": "dd23ee1",
      "tests": {
        "passed": 426,
        "failed": 0
      },
      "files": [
        "web/static/js/folder-logic.js",
        "web/static/js/lyrics-dialog.js",
        "web/static/js/import.js",
        "web/app/api_import.py"
      ]
    }
  ],
  "singlePass": null,
  "tests": {
    "passed": 426,
    "failed": 0
  },
  "debt": {
    "placeholders": [],
    "assumptions": [],
    "emptyEnv": []
  },
  "additions": [],
  "coverage": {
    "findings": 2,
    "note": "G2: 2 наполовину — строки usdb (вписаны из usdb_syncer), API прочих сборников (добавлен GitHub, ист. 12a); сверх брифа — углубления R/G, не A"
  },
  "concerns": [
    "songpack.py:192 — co= без схемы → fanart.tv: допущение по памяти об usdb_syncer, не сверено",
    "songpack.py:136 — маркер [CO] захардкожен, есть naming.cover_suffix",
    "songpack.py:71,161 — скрытые пути отсекаются в двух местах разными правилами",
    "tests/core/test_songpack.py:216 — тест DataPaths.import_dir не рядом с тестами paths",
    "tests/core/test_http.py:105 — обрезка ответа без Content-Length не проверяется",
    "lyrics-search.js:19 / lyrics.py:173 — срез LRC в двух языках, правила разошлись",
    "new-song.js:285 — текст 503 продублирован на фронте вместо detail сервера",
    "tests/api/test_lyrics.py:137 — sys.path.insert в тесте вместо tests/conftest.py",
    "new-song.js:246 — стили диалога inline, а не в CSS",
    "new-song.js insertLyrics — при отказе от замены список вариантов закрывается",
    "UltraSinger lrc_timing.py:73,110 — фильтр спетых строк написан дважды",
    "UltraSinger lrc_timing.py:12 — импорт приватного _norm_words из lyrics_alignment",
    "UltraSinger lrc_timing.py:15 — MIN_WINDOW дублирует константу lyrics_alignment",
    "UltraSinger lrc_timing.py:94 — ветка «метка у конца аудио» без теста",
    "UltraSinger Whisper.py:173 / UltraSinger.py:632 — выбор lrc/whisper и разбор флага без тестов",
    "UltraSinger common_print.py:44 — в --help заодно добавлена строка про --lyrics",
    "api_settings.py:109 / db.py:413 — правило «пустой пароль — прежний» дважды, ветка password=None в set_usdb мёртвая",
    "api_settings.py:136 — удаление учётки usdb без теста",
    "api_usdb.py:261 — тексты ошибок usdb повторяют умолчания исключений",
    "usdb.py:99 — вход удачен при любом ответе без LOGIN_INVALID (нет положительного признака)",
    "usdb.py:109,177 — has_more по разобранным строкам: одна кривая строка обрывает «Показать ещё»",
    "usdb.py:145,161 — html.unescape до разбора: экранированные <…> в названиях вырезаются как теги",
    "usdb.py:151 — разбор строки зависит от порядка атрибутов",
    "usdb.py:29 — _WATCH повторяет songpack._WATCH",
    "api_settings.py:139 — после PUT лишний повторный вход, тест закрепляет два входа",
    "usdb — HTML-разметка не сверена с живым usdb (нет входа)",
    "worker: DownloadTracker (проценты 5…60) без теста",
    "worker: «сбой постановки минусовки не валит импорт» без теста",
    "worker: fake_ytdlp режим nothumb не используется",
    "worker: в фикстуре нет #VIDEOGAP — удаление не проверяется",
    "worker handlers._log_tail — хвост лога разбором текста JobFailed",
    "worker _enqueue_instrumental — состав params минусовки повторяет web api_jobs",
    "test_selfcheck test_missing_yt_dlp_is_reported зависит от отсутствия yt_dlp в образе tests",
    "worker: минусовка при импорте ставится с replace=True — перезапишет свой [Instrumental] из пака (UI выключает галочку, таск 06)",
    "YTDLP_CMD не прокинут в docker-compose.yml (используется значение по умолчанию)",
    "api_import.py:158 — 413 по подстроке текста HttpError; тест сверяет текст сам с собой",
    "api_import.py:177 — _has_instrumental повторяет songpack._resolve",
    "test_import.py:99 — нет случая «#INSTRUMENTAL есть, файла нет»",
    "test_import.py:95 — isinstance(warnings, list) ничего не утверждает",
    "api_import.py:238 — _existing копия api_usdb._existing",
    "api_import.py:54 / params.py — умолчание MAX_IMPORT_MB в двух местах",
    "test_import.py — не покрыты 413 для files, перегенерация song_id, ошибка api.github.com, уборка imports/",
    "api_import.py:115 — одинаковые имена в россыпи файлов затирают друг друга; текст ошибки размера «Архив…» для россыпи",
    "api_import.py:28 — приватные _Staging/_queue_duplicate/_is_mp3/_cover_ext/_copy_limited из api_jobs",
    "api_import.py:50 — ветка GitHub со слешем (feature/x) не поддерживается",
    "import.js — 409/410 на экране вживую не проверены (только node-тесты importOutcome)",
    "import.js:270 — текст дубля строкой при наличии DUP_TEXT",
    "import-logic.js:4 — NEED_AUDIO/WARN_SYNC копии серверных строк, сравнение по тексту",
    "import.js:368 — при 410 на N-й песне теряется, что первые уже в очереди",
    "import.js:233 — токен разбора лежит в pack.id",
    "import.js:17 — переменные t/u/c",
    "import-logic.js:41 — youtube[0] без trim, правило расходится с pickAudioSource",
    "api_songs.py:46 — N+1 запросов к SQLite на GET /api/songs",
    "api_songs.py:46 — own=None смешивает «не передали» и «нет в БД»",
    "importForm не шлёт song_id (замена работает по существующей песне)",
    "фильтр языка usdb: добавлены «английский» и «украинский» сверх «русский/любой»",
    "new-song.js:604 — перегенерация с выключенными таймингами удаляет сохранённый source/lyrics.lrc",
    "lyrics-search.js:65 — подсказка «длительность mp3 неизвестна» сверх спеки (галочка выключена)",
    "api_jobs.py — INPUT_LRC объявлен вне paths.py",
    "tests/worker/test_runner_lrc.py — не закреплены offset, [mm:ss] без долей, [mm:ss:xx], BOM",
    "handlers.py:313 — нечитаемый LRC пишет в лог «текст отличается» вместо настоящей причины",
    "new-song.js:319,535 — сброс LRC при новой вставке/загрузке файла только в DOM, форма вживую не открывалась",
    "new-song.js:604 — вложенный тернарник для lyrics_lrc",
    "lyrics-search.js — два разборщика LRC (stripLrc и parseLrc) без пояснения ролей",
    "http.py — нет теста «POST не повторяется»",
    "http.py:95 — str(cause) может вывести URL с query в лог (секретов в query сейчас нет)",
    "http.py:150 — повтор после таймаута удваивает ожидание (GitHub до ~10 мин)",
    "params.py:505 — max_import_mb посреди блока констант",
    "test_http Handler.flaky — общее состояние класса между тестами",
    "редактор текста (editors/lyrics-editor.js) не шлёт lyrics_lrc — после замены текста сохранённый LRC остаётся (воркер его не применит: строки не совпадут)",
    "import-logic.js — при своём звуке серверные предупреждения заменяются WARN_SYNC (сейчас сервер шлёт только звуковые)",
    "import.js runGenerate — разбор 409 повторяет importOutcome",
    "folder-logic.js:78 — расширения и признак песни повторяют songpack (расхождение → песня молча «пропущена»)",
    "тест NUL в пути убран (TestClient не передаёт NUL), проверка в коде осталась",
    "телефон определяется по webkitdirectory и user-agent"
  ],
  "reviewers": {
    "manifestSpec": "a34441b84c8e86d8c",
    "craft": "a69e12ac952feb33f"
  },
  "blind": {
    "found": 2,
    "drift": [
      "работающий контейнер worker на старом образе — импорт и тайминги LRC не исполнились бы (новый образ собран)",
      "сеть из web нестабильна: LRCLIB 503 в 2 из 5, GitHub «нет связи» до перезапуска web"
    ],
    "notVerifiable": [
      "вход/поиск/скачивание usdb — нет аккаунта",
      "реальные задания импорта/генерации/минусовки не ставились"
    ]
  }
}
