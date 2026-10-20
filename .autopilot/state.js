window.STATE =
{
  "slug": "karaoke-services",
  "dir": "2026-10-19-karaoke-services--wip",
  "title": "Сервис генерации караоке-песен (UltraSinger в docker-compose)",
  "mode": "manual",
  "depth": "normal",
  "polish": null,
  "tier": "T2",
  "briefFile": "2026-10-19-brief.md",
  "memoryFile": "CLAUDE.md",
  "skillDir": "C:/Users/work/.claude/skills/autopilot",
  "startedAt": "2026-10-19T23:17:21+03:00",
  "updatedAt": "2026-10-20T08:53:45+03:00",
  "finishedAt": null,
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-10-19T23:17:21+03:00",
      "finishedAt": "2026-10-19T23:18:38+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-10-19T23:20:00+03:00",
      "finishedAt": "2026-10-19T23:18:38+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-10-19T23:18:38+03:00",
      "finishedAt": "2026-10-19T23:43:16+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-10-19T23:43:16+03:00",
      "finishedAt": "2026-10-19T23:49:53+03:00"
    },
    {
      "id": "plan",
      "status": "done",
      "startedAt": "2026-10-19T23:49:53+03:00",
      "note": "8 тасков, ярус T2, 6 волн — утверждён",
      "finishedAt": "2026-10-20T07:15:36+03:00"
    },
    {
      "id": "build",
      "status": "active",
      "startedAt": "2026-10-20T07:15:36+03:00",
      "note": "4 из 8 тасков готовы"
    },
    {
      "id": "review",
      "status": "active",
      "startedAt": "2026-10-20T07:27:48+03:00",
      "note": "проверено 4 из 8"
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
    "deferred": 3,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Каркас репозитория и ядро karaoke_core",
      "requirements": [
        "R01",
        "R16",
        "R19",
        "R20",
        "R21",
        "R25",
        "R32",
        "R34",
        "R36i",
        "G06"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "core/",
        "storage*",
        "trash*",
        "tests/core/",
        ".gitignore",
        ".env.example",
        "docker-compose.yml",
        "scripts/compose.ps1"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-20T07:15:49+03:00",
      "finishedAt": "2026-10-20T07:30:26+03:00",
      "commit": "2fdec3e",
      "tests": {
        "passed": 59,
        "failed": 0
      },
      "concerns": [],
      "repairFindings": [
        "имя исполнителя на двух уровнях, Cc, mp3-стемы, #VERSION, .env.example, LF"
      ]
    },
    {
      "id": "02",
      "title": "Папка результата (SMB и локальная) и корзина",
      "requirements": [
        "R11",
        "R12",
        "R22",
        "R23",
        "R36i",
        "G01",
        "G03"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "core/karaoke_core/storage*",
        "core/karaoke_core/trash*",
        "tests/core/test_storage*",
        "tests/core/test_trash*"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-20T07:30:26+03:00",
      "commit": "39a517e",
      "repairFindings": [
        "единый target_id, один поиск .txt, restore в чужую цель, ошибки SMB при передаче, probe, .part-тест, save_version, пустая папка исполнителя"
      ],
      "finishedAt": "2026-10-20T07:49:10+03:00",
      "tests": {
        "passed": 208,
        "failed": 0
      }
    },
    {
      "id": "03",
      "title": "Образ worker: UltraSinger из ветки, PyTorch для Pascal, проверка GPU",
      "requirements": [
        "R15",
        "R17",
        "R18",
        "R24",
        "R26",
        "R30",
        "R31"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "worker/Dockerfile",
        "worker/karaoke_worker/gpucheck.py",
        "selfcheck.py",
        "__main__",
        "scripts/export-ultrasinger-patch.ps1",
        "patches/",
        "worker",
        "docker-compose.yml"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-20T07:30:26+03:00",
      "commit": "4a59012",
      "tests": {
        "passed": 264,
        "failed": 0
      },
      "repairFindings": [
        "проверка флагов по реальному списку getopt",
        "одно правило Pascal (runnable_arch)",
        "тесты check() на фейках",
        "__main__ не глотает ImportError внутри runner"
      ],
      "finishedAt": "2026-10-20T08:39:04+03:00"
    },
    {
      "id": "04",
      "title": "Воркер: очередь, генерация, минусовка, выкладка, отмена",
      "requirements": [
        "R08",
        "R09",
        "R10",
        "R12",
        "R13",
        "R14",
        "R16",
        "R19",
        "R20",
        "R21",
        "R22",
        "R26",
        "R36i",
        "R38i",
        "G01",
        "G04"
      ],
      "blockedBy": [
        "01",
        "02",
        "03"
      ],
      "wave": 3,
      "zone": [
        "worker/karaoke_worker/",
        "gpucheck.py",
        "selfcheck.py",
        "tests/worker/"
      ],
      "status": "in-progress",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-20T08:30:44+03:00"
    },
    {
      "id": "05",
      "title": "Web: REST API, авторизация, образ web",
      "requirements": [
        "R02",
        "R04",
        "R05",
        "R06",
        "R07",
        "R08",
        "R09",
        "R10",
        "R11",
        "R12",
        "R13",
        "R21",
        "R23",
        "R26",
        "R30",
        "R37i",
        "G01",
        "G02",
        "G03",
        "G04",
        "G05"
      ],
      "blockedBy": [
        "01",
        "02"
      ],
      "wave": 3,
      "zone": [
        "web/Dockerfile",
        "web/app/",
        "tests/api/",
        "web",
        "docker-compose.yml"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-20T07:49:10+03:00",
      "repairFindings": [
        "статус GPU через ядро",
        "раскладка тома по §3 (uploads/<hex> → songs/<A>/<A - T>/jobs/<id>/in)",
        "пароль не уходит на новый хост",
        "503/413, константы, умолчания из env, WEB_PORT 8090"
      ],
      "finishedAt": "2026-10-20T08:30:44+03:00",
      "commit": "31bc6ae",
      "tests": {
        "passed": 257,
        "failed": 0
      }
    },
    {
      "id": "06",
      "title": "Фронтенд: очередь, новая песня, песни, корзина, настройки",
      "requirements": [
        "R02",
        "R03",
        "R04",
        "R05",
        "R06",
        "R07",
        "R08",
        "R09",
        "R10",
        "R11",
        "R12",
        "R13",
        "R21",
        "R30",
        "G01",
        "G03",
        "G04"
      ],
      "blockedBy": [
        "05"
      ],
      "wave": 4,
      "zone": [
        "web/static/"
      ],
      "status": "repair",
      "retries": 0,
      "repairs": 2,
      "handoffs": 0,
      "startedAt": "2026-10-20T08:30:44+03:00",
      "commit": "81e318e",
      "repairFindings": [
        "закрытие EventSource при смене раздела",
        "догрузка начала лога (история 19)",
        "двойная фраза «недоступна»",
        "TRASH_DAYS из API",
        "ё=е в exists",
        "машиночитаемое поле ошибки",
        "match_key слишком широкий (пунктуация), markField вне details, logFrom/CRLF"
      ]
    },
    {
      "id": "07",
      "title": "Редакторы: исходный текст и слова готовой песни",
      "requirements": [
        "G05",
        "R06",
        "R12",
        "R29",
        "G07"
      ],
      "blockedBy": [
        "06"
      ],
      "wave": 5,
      "zone": [
        "web/static/",
        "web/static/js/new-song.js"
      ],
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
    },
    {
      "id": "08",
      "title": "README и сквозная проверка на реальном железе",
      "requirements": [
        "R01",
        "R02",
        "R18",
        "R22",
        "R30",
        "R33"
      ],
      "blockedBy": [
        "03",
        "04",
        "05",
        "06",
        "07"
      ],
      "wave": 6,
      "zone": [
        "README.md",
        "scripts/"
      ],
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
    }
  ],
  "singlePass": null,
  "tests": {
    "passed": 264,
    "failed": 0
  },
  "debt": {
    "placeholders": [
      "Цель выкладки сейчас — локальная /output; вернуть SMB в «Настройках» (пользователь сам); тестовые задания №1–2 и песни в ./output остались"
    ],
    "assumptions": [],
    "emptyEnv": []
  },
  "additions": [],
  "coverage": {
    "g2": {
      "findings": 4,
      "extras": 20,
      "actions": [
        "дерево репозитория → spec §12",
        "локальная цель: корень LOCAL_OUTPUT_ROOT, любая подпапка из веба",
        "CIFS/Windows-диск → обоснование замены SMB-клиентом в §7, на согласование",
        "selfcheck midi_creator добавлен в историю 56",
        "дополнения — углубления R##/G## (R##.n), оставлены, видны пользователю на гейте"
      ]
    }
  },
  "concerns": [
    "tests/core/test_repo_config.py — проверка паролей пропускает tests/ (фикстуры)",
    "ultrastar fix_zero_length — нет теста на переход через разрыв строки; ветка #RELATIVE без теста и сдвигает последующие строки",
    "ultrastar.beat_to_ms — ValueError без теста",
    "ultrastar.set_header_line дублирует поиск блока заголовков из parse/Song.set_header",
    "db.py — значения по умолчанию 192.168.0.129/karaoke продублированы с compose/.env.example",
    "tests/core/test_db.py:75 — запутанная подготовка теста fail_interrupted",
    "postprocess.py:111 — неназванное правило записи #AUDIO",
    "postprocess — #COVERURL тоже удаляется при несовпадении исполнителя (сверх истории 26)",
    "db.Jobs.update не проверяет переходы конечного автомата §2",
    "db.py:272 — дефолты SMB-хоста захардкожены в ядре (дублируют compose/.env.example)",
    ".gitattributes дублирует tests/core/fixtures/.gitattributes",
    "test_repo_config сканирует env только в core/ — расширить на web/ и worker/",
    "storage/trash: публичные sizes/listdir/delete_file/close/Trash.get сверх «Границ» (записаны в interfaces.md)",
    "tests/core/test_trash.py:683 — тест save_version завязан на то, что sizes() не вызывается (деталь реализации)",
    "storage.delete_dir — ошибки удаления пустой папки исполнителя глотаются молча",
    "web/app/params.py — без DEFAULT_* в окружении форма получает пустые умолчания вместо явной ошибки конфигурации",
    "db.enqueue_with — make_params выполняется под блокировкой записи (докстринг должен запрещать тяжёлую работу)",
    "история 56: флаги ищутся разбором исходника, а не по справке (допустимое отклонение)",
    "selfcheck: getopt принимает уникальный префикс — флаг надо сверять точно со списком long options",
    "__main__ run: нет юнит-теста на проброс ImportError",
    "web/static: дубли field()/songName, литералы-плейсхолдеры 192.168.0.129, ui.h() пропускает нефункциональные on*"
  ],
  "reviewers": {
    "manifestSpec": "a489e47ea70f9876b",
    "craft": "acc007efbffd7f351"
  },
  "blind": null
}
