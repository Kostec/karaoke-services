window.STATE =
{
  "slug": "storage-targets",
  "dir": "2026-10-22-storage-targets",
  "title": "Редактор нот: границы строк перетаскиванием и широкая панель «Текст»; «Песни»: фильтры, zip, переключение и копирование между хранилищами; несколько целей выкладки",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T2",
  "briefFile": "2026-10-22-brief.md",
  "memoryFile": "CLAUDE.md",
  "skillDir": "C:/Users/work/.claude/skills/autopilot",
  "startedAt": "2026-10-22T12:00:25+03:00",
  "updatedAt": "2026-10-22T18:08:40+03:00",
  "finishedAt": "2026-10-22T18:08:40+03:00",
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-10-22T12:00:25+03:00",
      "finishedAt": "2026-10-22T12:02:30+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-10-22T12:02:30+03:00",
      "finishedAt": "2026-10-22T12:09:40+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-10-22T12:09:40+03:00",
      "note": "2 вопроса: облака сетевым подключением, всегда локально + цель",
      "finishedAt": "2026-10-22T12:16:05+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-10-22T12:16:05+03:00",
      "finishedAt": "2026-10-22T12:41:30+03:00"
    },
    {
      "id": "plan",
      "status": "done",
      "startedAt": "2026-10-22T12:41:30+03:00",
      "note": "6 тасков, ярус T2, 3 волны",
      "finishedAt": "2026-10-22T12:58:20+03:00"
    },
    {
      "id": "build",
      "status": "done",
      "startedAt": "2026-10-22T12:58:20+03:00",
      "note": "7 из 7 тасков готовы",
      "finishedAt": "2026-10-22T16:49:00+03:00"
    },
    {
      "id": "review",
      "status": "done",
      "startedAt": "2026-10-22T13:24:40+03:00",
      "note": "проверено 7 из 7",
      "finishedAt": "2026-10-22T16:49:00+03:00"
    },
    {
      "id": "final",
      "status": "done",
      "startedAt": "2026-10-22T16:49:00+03:00",
      "finishedAt": "2026-10-22T18:08:40+03:00",
      "note": "слепая приёмка: 20 реализовано, 2 частично (живые облака/SMB без учёток; «любая папка» в пределах корня)"
    }
  ],
  "requirements": {
    "total": 22,
    "done": 22,
    "inTicket": 0,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Несколько хранилищ в ядре: модель, миграция, хранилище песни по её цели",
      "requirements": [
        "R14",
        "R15",
        "R16",
        "R22i"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "core/karaoke_core/db.py",
        "core/karaoke_core/trash.py",
        "web/app/context.py",
        "worker/karaoke_worker/base.py"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-22T13:01:05+03:00",
      "repairFindings": [
        "после миграции в library остаются строки со старым target_id (UPDATE OR IGNORE); сброс всех хранилищ при сбое одного; склеенные переносы строк в context/api_songs"
      ],
      "tests": {
        "passed": 696,
        "failed": 0
      },
      "commit": "c14d790",
      "finishedAt": "2026-10-22T14:12:30+03:00"
    },
    {
      "id": "06",
      "title": "Редактор нот: перетаскивание разрыва строки, широкая панель «Текст»",
      "requirements": [
        "R01",
        "R02",
        "R03",
        "R04"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "web/static/js/editors/",
        "web/static/css/editors.css"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-22T13:01:05+03:00",
      "finishedAt": "2026-10-22T13:31:50+03:00",
      "tests": {
        "passed": 166,
        "failed": 0
      },
      "commit": "293c089",
      "files": [
        "web/static/js/editors/notes-model.js",
        "web/static/js/editors/notes-editor.js",
        "web/static/js/editors/notes-text-panel.js",
        "web/static/js/editors/notes-panel-logic.js",
        "web/static/css/editors.css"
      ]
    },
    {
      "id": "02",
      "title": "Сетевые хранилища: Яндекс Диск (WebDAV) и Google Диск",
      "requirements": [
        "R17",
        "R18",
        "R20"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "core/karaoke_core/storage/webdav.py",
        "core/karaoke_core/storage/gdrive.py"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-22T14:01:40+03:00",
      "repairFindings": [
        "gdrive _replace удаляет старый файл до переноса — потеря при сбое",
        "probe() не создаёт отсутствующую папку — нельзя подключить новую",
        "нет повторов на лимит запросов Google (429/403 rateLimit)"
      ],
      "finishedAt": "2026-10-22T15:20:30+03:00",
      "tests": {
        "passed": 777,
        "failed": 0
      },
      "commit": "1b41b49"
    },
    {
      "id": "03",
      "title": "«Настройки → Куда выкладывать»: список хранилищ, любой тип, вход в Google",
      "requirements": [
        "R14",
        "R15",
        "R16",
        "R17",
        "R18",
        "R19",
        "R20"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "web/app/api_targets.py",
        "web/static/js/settings.js",
        "docker-compose.yml"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-22T14:01:40+03:00",
      "repairFindings": [
        "«Папка ПК» = /output дублирует локальное хранилище",
        "callback Google выводит str(e) любого исключения",
        "мёртвая заглушка exchange_code в тестах",
        "чистая логика settings.js без модуля и node-тестов"
      ],
      "finishedAt": "2026-10-22T15:37:10+03:00",
      "tests": {
        "passed": 784,
        "failed": 0
      },
      "commit": "ea89bd8"
    },
    {
      "id": "04",
      "title": "Выкладка «локально + основная цель» и задание «Копирование»",
      "requirements": [
        "R09",
        "R10",
        "R11",
        "R12"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "worker/karaoke_worker/",
        "web/app/api_jobs.py"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-22T14:12:30+03:00",
      "repairFindings": [
        "R12: минусовка после импорта только в одной копии",
        "отложенная копия при замене с другим rel_dir не убирает прежнюю версию в цели",
        "правило дубля copy продублировано в API и воркере; род в логе; выбор хранилища по published[-1]"
      ],
      "finishedAt": "2026-10-22T15:58:40+03:00",
      "tests": {
        "passed": 784,
        "failed": 0
      },
      "commit": "4c96e61"
    },
    {
      "id": "05",
      "title": "Вкладка «Песни»: хранилища, фильтры, zip, «Копировать в…»",
      "requirements": [
        "R05",
        "R06",
        "R07",
        "R08",
        "R09",
        "R10",
        "R13",
        "R21i"
      ],
      "blockedBy": [
        "01",
        "03",
        "04"
      ],
      "wave": 3,
      "zone": [
        "web/static/js/songs.js",
        "web/static/js/songs-filter.js",
        "web/app/api_songs.py"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-22T15:58:40+03:00",
      "repairFindings": [
        "zip скачивается дважды (проверка полным GET)",
        "rescan глушит сбой открытия хранилища",
        "rescan другого хранилища во время скана пропадает",
        "лог обрыва zip, дата файлов в архиве, _chosen_target через target_of"
      ],
      "finishedAt": "2026-10-22T16:47:20+03:00",
      "tests": {
        "passed": 791,
        "failed": 0
      },
      "commit": "992d8fd"
    },
    {
      "id": "07",
      "title": "Уборка дублей после сборки (разбор отложенных замечаний)",
      "requirements": [
        "R14",
        "R16",
        "R22i",
        "R09",
        "R04"
      ],
      "blockedBy": [
        "01",
        "02",
        "03",
        "04",
        "05",
        "06"
      ],
      "wave": 4,
      "zone": [
        "core/karaoke_core/",
        "web/app/context.py",
        "worker/karaoke_worker/base.py",
        "web/app/api_targets.py"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-22T17:20:30+03:00",
      "finishedAt": "2026-10-22T18:08:40+03:00",
      "tests": {
        "passed": 794,
        "failed": 0
      },
      "commit": "54a3409"
    }
  ],
  "singlePass": null,
  "tests": {
    "passed": 794,
    "failed": 0
  },
  "debt": {
    "placeholders": [
      "R18 — Client ID/secret своего OAuth-клиента Google вводятся в «Настройках»",
      "R17 — пароль приложения Яндекса вводится в «Настройках»"
    ],
    "assumptions": [
      "Google Диск — свой OAuth-клиент Google (Desktop), вход только с ПК, где запущен сервис",
      "Яндекс Диск — WebDAV с паролем приложения",
      "«Любая папка» — внутри HOST_FOLDERS_ROOT (по умолчанию D:/) или /output",
      "Правка песни меняет открытую копию; выровнять вторую — «Копировать в…» с заменой",
      "Ожидание недоступной цели — бессрочно, повтор раз в минуту, отменяемо"
    ],
    "emptyEnv": []
  },
  "additions": [
    "Фильтры видео/дуэт/обложка/происхождение и сортировка — ради R07 «и т.д.»",
    "«Копировать показанные в…» с «только недостающие» — ради R09",
    "Тип WebDAV отдельно от Яндекс Диска — ради R20 «другой сетевой путь»"
  ],
  "coverage": {
    "findings": 3,
    "missing": 0,
    "half": 3,
    "extra": "19 — все R##.n/решения с родителем",
    "actions": "дописано: тайминг строки двумя способами (§14), бессрочное ожидание copy и пометка в карточке (§9), граница «любой папки» корнем HOST_FOLDERS_ROOT (§6)"
  },
  "concerns": [
    "[исправить → таск 07] 06 · editors.css .ne-plist .st — статус строки панели «Текст» под текстом, а не отдельной колонкой (спека §15)",
    "[в отчёт] 06 · notes-editor.js — Esc во время тяги разрыва не отменяет",
    "[в отчёт] 06 · экран редактора (тяга разрыва, ручка панели) проверен только тестами — пройти в браузере на собранном web",
    "[в отчёт] 06 · notes-model.js checkBreakMove — проверка «оба» через подстроки JSON вместо сравнения массивов id",
    "[в отчёт] 06 · moveBreak — ветка brk2 (бит перед «оба» в партии 2) без теста; неизменяемость при ошибке дуэта не проверена",
    "[в отчёт] 06 · порог 767 px задан и в JS (NARROW), и в CSS; тяга разрыва и ручки — дублированная заготовка pointer*",
    "[в отчёт] 06 · endBrkDrag — порядок pointerup/lostpointercapture держится неявно, нужен комментарий",
    "[в отчёт] 01 · song_id после миграции новый — старые ссылки и ref.song_id прежних заданий не указывают на песню (принято, спека §2)",
    "[исправить → таск 07] 01 · context.py и worker base.py — правило выбора/кэша хранилища написано дважды с разным ключом кэша",
    "[исправить → таск 07] 01 · Library.find — полный перебор library с sha1 на каждый запрос песни",
    "[в отчёт] 01 · resolve_target_id/target_of — повторные чтения настроек; get_targets пишет в БД при первом чтении",
    "[в отчёт] 01 · тесты миграции: нет проверки через старт веба/воркера, нет веток «env SMB вторым хранилищем» и коллизии library",
    "[в отчёт] 02 · общий контракт Storage подключён к сетевым через ручной список имён (exec test_storage.py)",
    "[исправить → таск 07] 02 · общие помощники сетевых (UploadOnClose, download_temp, ListingCache) лежат в webdav.py; перевод HttpError/OSError продублирован",
    "[в отчёт] 02 · test_http_errors_are_russian не проверяет текст для 403/500",
    "[в отчёт] 02 · access-токен Drive не сохраняется — новый объект хранилища снова идёт за токеном",
    "[снято: исправлено в репаре 04] 04 · текст лога «Хранилище песни «X» недоступна» — род",
    "[снято: исправлено в репаре 04] 04 · минусовка после импорта ставится в published[-1] — при замене из третьего хранилища не в основную цель",
    "[снято: исправлено в репаре 04] 04 · сбой основной цели при замене с другой папкой — прежняя версия в цели остаётся",
    "[снято: исправлено в репаре 04] 04 · поиск дубля copy и сборка params продублированы в api_jobs и handlers",
    "[исправить → таск 07] 04 · retry_at сравнивается строкой и пишется своим _later, а не db.now-форматом",
    "[в отчёт] 04 · _song_out без pending перебирает активные copy на каждый вызов",
    "[исправить → таск 07] 03 · проверки пути в api_targets написаны трижды; правила удаления продублированы из Settings; имена по умолчанию дублируют db._target_from_output",
    "[в отчёт] 03 · черновики Google в app.state без верхней границы числа",
    "[в отчёт] 03 · экран: формы SMB/Яндекс/WebDAV, «Удалить», реальный вход Google не проверены в браузере",
    "[в отчёт] R19 · «любая папка» — внутри HOST_FOLDERS_ROOT (по умолчанию D:/) и /output: назвать в отчёте",
    "[в отчёт] 03 · «известный текст» ошибки Google определяется по кириллице, а не по списку сообщений; BROWSE_ROOTS_MOUNT дублирует BROWSE_ROOTS",
    "[исправить → таск 07] 04 · restart copy (api_jobs) ставит задание в обход Jobs.enqueue_copy — без проверки дубля",
    "[в отчёт] 04 · активная copy без after_job может уехать раньше минусовки; копия минусовки кладёт свежую версию цели в корзину (мусор)",
    "[в отчёт] 04 · один полный прогон у исполнителя дал 1 failed, повторы зелёные — возможен мигающий тест",
    "[в отчёт] 05 · сбой файла посреди zip обрывает архив (проверяется только список и доступность до первого байта)",
    "[в отчёт] 05 · «Копировать в…» предлагает все хранилища кроме текущего — шире «пока что только SMB и локальное», по истории 18",
    "[в отчёт] 05 · экран: баннер недоступного хранилища и одиночное «Копировать в…» не проверены вручную"
  ],
  "reviewers": {
    "manifestSpec": "ad78fdfff72d7d62b",
    "craft": "a420dba297a7cd201"
  },
  "blind": {
    "agreed": 20,
    "partial": 2,
    "missing": 0,
    "drift": [],
    "notes": [
      "Добавление Яндекс/Google/SMB — API и экран есть, живые сервисы не проверены (нет учёток)",
      "«Любая папка» — только внутри HOST_FOLDERS_ROOT (по умолчанию D:/) и /output"
    ],
    "ran": "pytest 791 passed, node 185; временный веб :8099 + воркер без GPU: фильтры, zip, копирование, недоступная цель → локально и докопирование, переключение хранилищ, тяга разрыва и ширина панели в браузере"
  }
}
