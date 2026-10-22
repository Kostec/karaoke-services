window.STATE =
{
  "slug": "storage-targets",
  "dir": "2026-10-22-storage-targets--wip",
  "title": "Редактор нот: границы строк перетаскиванием и широкая панель «Текст»; «Песни»: фильтры, zip, переключение и копирование между хранилищами; несколько целей выкладки",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T2",
  "briefFile": "2026-10-22-brief.md",
  "memoryFile": "CLAUDE.md",
  "skillDir": "C:/Users/work/.claude/skills/autopilot",
  "startedAt": "2026-10-22T12:00:25+03:00",
  "updatedAt": "2026-10-22T13:01:05+03:00",
  "finishedAt": null,
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
      "status": "active",
      "startedAt": "2026-10-22T12:58:20+03:00"
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
    "total": 22,
    "done": 0,
    "inTicket": 22,
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
      "status": "in-progress",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-22T13:01:05+03:00"
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
      "status": "in-progress",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-22T13:01:05+03:00"
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
    }
  ],
  "singlePass": null,
  "tests": null,
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
  "concerns": [],
  "reviewers": {
    "manifestSpec": null,
    "craft": null
  },
  "blind": null
}
