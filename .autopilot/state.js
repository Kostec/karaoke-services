window.STATE =
{
  "slug": "lyrics-songbook-import",
  "dir": "2026-10-20-lyrics-songbook-import--wip",
  "title": "Текст из сервиса текстов и импорт песен из сборников UltraStar",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T2",
  "briefFile": "2026-10-20-brief.md",
  "memoryFile": "CLAUDE.md",
  "skillDir": "C:/Users/work/.claude/skills/autopilot",
  "startedAt": "2026-10-20T10:18:24+03:00",
  "updatedAt": "2026-10-20T10:40:35+03:00",
  "finishedAt": null,
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
      "status": "active",
      "startedAt": "2026-10-20T10:40:35+03:00",
      "note": "0 из 6 тасков готовы"
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
    "total": 13,
    "done": 0,
    "inTicket": 13,
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
      "status": "in-progress",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-20T10:40:35+03:00"
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
      "status": "in-progress",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-20T10:40:35+03:00"
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
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
    "findings": 2,
    "note": "G2: 2 наполовину — строки usdb (вписаны из usdb_syncer), API прочих сборников (добавлен GitHub, ист. 12a); сверх брифа — углубления R/G, не A"
  },
  "concerns": [],
  "reviewers": {
    "manifestSpec": null,
    "craft": null
  },
  "blind": null
}
