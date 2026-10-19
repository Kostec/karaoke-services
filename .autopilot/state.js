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
  "updatedAt": "2026-10-19T23:55:52+03:00",
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
      "status": "active",
      "startedAt": "2026-10-19T23:49:53+03:00",
      "note": "8 тасков, ярус T2, 6 волн — утверждён"
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
    "total": 44,
    "done": 1,
    "inTicket": 40,
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
    },
    {
      "id": "07",
      "title": "Редакторы: исходный текст и слова готовой песни",
      "requirements": [
        "G05",
        "R06",
        "R12",
        "R29"
      ],
      "blockedBy": [
        "06"
      ],
      "wave": 5,
      "zone": [
        "web/static/"
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
  "tests": null,
  "debt": {
    "placeholders": [],
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
  "concerns": [],
  "reviewers": {
    "manifestSpec": null,
    "craft": null
  },
  "blind": null
}
