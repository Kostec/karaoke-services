window.STATE =
{
  "slug": "duets-video",
  "dir": "2026-10-21-duets-video--wip",
  "title": "Дуэты (в т.ч. в редакторе нот) и видео к песням: ссылкой или файлом, опция видео при загрузке по ссылке и из usdb",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T2",
  "briefFile": "2026-10-21-brief.md",
  "memoryFile": "CLAUDE.md",
  "skillDir": "C:/Users/work/.claude/skills/autopilot",
  "startedAt": "2026-10-21T21:43:27+03:00",
  "updatedAt": "2026-10-22T02:04:00+03:00",
  "finishedAt": null,
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-10-21T21:43:27+03:00",
      "finishedAt": "2026-10-21T21:47:10+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-10-21T21:45:00+03:00",
      "finishedAt": "2026-10-21T21:47:10+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-10-21T21:47:10+03:00",
      "finishedAt": "2026-10-21T21:55:00+03:00",
      "note": "2 вопроса: объём дуэтов, качество видео"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-10-21T21:55:00+03:00",
      "finishedAt": "2026-10-21T22:12:00+03:00",
      "note": "31 история, G2: 1 пробел + 2 половины — дописаны"
    },
    {
      "id": "plan",
      "status": "done",
      "startedAt": "2026-10-21T22:12:00+03:00",
      "finishedAt": "2026-10-21T22:20:00+03:00",
      "note": "6 тасков, ярус T2, 3 волны"
    },
    {
      "id": "build",
      "status": "done",
      "startedAt": "2026-10-21T22:20:00+03:00",
      "note": "6 из 6 тасков готовы",
      "finishedAt": "2026-10-22T01:05:00+03:00"
    },
    {
      "id": "review",
      "status": "done",
      "startedAt": "2026-10-21T22:37:30+03:00",
      "note": "проверено 6 из 6",
      "finishedAt": "2026-10-22T01:05:00+03:00"
    },
    {
      "id": "final",
      "status": "active",
      "startedAt": "2026-10-22T01:05:00+03:00"
    }
  ],
  "requirements": {
    "total": 13,
    "done": 13,
    "inTicket": 0,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Дуэты: формат и API нот",
      "requirements": [
        "R01",
        "R02"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "core/karaoke_core/ultrastar.py",
        "web/app/notes.py"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-21T22:24:00+03:00",
      "finishedAt": "2026-10-21T23:02:30+03:00",
      "tests": {
        "passed": 623,
        "failed": 0
      },
      "commit": "361857a",
      "files": [
        "core/karaoke_core/ultrastar.py",
        "web/app/notes.py"
      ]
    },
    {
      "id": "02",
      "title": "Дуэты: модель редактора нот",
      "requirements": [
        "R01",
        "R02"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "web/static/js/editors/notes-model.js"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-10-21T22:24:00+03:00",
      "finishedAt": "2026-10-21T23:10:20+03:00",
      "tests": {
        "passed": 136,
        "failed": 0
      },
      "commit": "af7fe58",
      "files": [
        "web/static/js/editors/notes-model.js",
        "web/static/js/editors/notes-panel-logic.js",
        "web/static/js/editors/timeline-math.js"
      ],
      "repairFindings": [
        "break_beat перед P2 теряется при правке (R02.4); тексты ошибок дуэта как у сервера"
      ]
    },
    {
      "id": "03",
      "title": "Дуэты: экран редактора нот",
      "requirements": [
        "R01",
        "R02"
      ],
      "blockedBy": [
        "01",
        "02"
      ],
      "wave": 2,
      "zone": [
        "web/static/js/editors/"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-21T23:02:30+03:00",
      "finishedAt": "2026-10-21T23:47:00+03:00",
      "tests": {
        "passed": 136,
        "failed": 0
      },
      "commit": "00c22cd",
      "files": [
        "web/static/js/editors/notes-editor.js",
        "web/static/js/editors/notes-text-panel.js",
        "web/static/js/editors/notes-tools.js"
      ]
    },
    {
      "id": "04",
      "title": "Видео: ядро и задание video",
      "requirements": [
        "R03",
        "R04",
        "R05",
        "R06",
        "R07",
        "R10i",
        "R11i",
        "G01"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "core/",
        "worker/"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 2,
      "handoffs": 0,
      "startedAt": "2026-10-21T22:24:00+03:00",
      "repairFindings": [
        "тест переноса видео держится на том, что generate игнорирует params.video",
        "тест _save_sources зовёт приватную функцию в обход шва run_forever"
      ],
      "finishedAt": "2026-10-21T23:24:30+03:00",
      "tests": {
        "passed": 624,
        "failed": 0
      },
      "commit": "e4a087e",
      "files": [
        "core/karaoke_core/",
        "worker/karaoke_worker/handlers.py"
      ]
    },
    {
      "id": "05",
      "title": "Видео: диалог на карточке песни",
      "requirements": [
        "R03",
        "R04",
        "R05",
        "R06",
        "R07",
        "R11i",
        "G01"
      ],
      "blockedBy": [
        "04"
      ],
      "wave": 2,
      "zone": [
        "web/app/api_jobs.py",
        "web/static/js/songs.js"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-21T23:24:30+03:00",
      "finishedAt": "2026-10-22T00:05:00+03:00",
      "tests": {
        "passed": 632,
        "failed": 0
      },
      "commit": "70584d3",
      "files": [
        "web/app/api_jobs.py",
        "web/static/js/video-block.js",
        "web/static/js/songs.js"
      ]
    },
    {
      "id": "06",
      "title": "Видео при создании и импорте",
      "requirements": [
        "R05",
        "R06",
        "R07",
        "R08",
        "R09",
        "R12i",
        "G01"
      ],
      "blockedBy": [
        "04",
        "05"
      ],
      "wave": 3,
      "zone": [
        "core/karaoke_core/songpack.py",
        "web/app/api_import.py",
        "web/static/js/import.js"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-22T00:05:00+03:00",
      "finishedAt": "2026-10-22T01:05:00+03:00",
      "tests": {
        "passed": 647,
        "failed": 0
      },
      "commit": "f7e3393",
      "files": [
        "core/karaoke_core/songpack.py",
        "web/app/api_import.py",
        "web/static/js/new-song.js",
        "web/static/js/import.js"
      ]
    },
    {
      "id": "07",
      "title": "Видео: одно правило — одно место",
      "requirements": [
        "R04",
        "R05",
        "R07",
        "R08"
      ],
      "blockedBy": [
        "06"
      ],
      "wave": 4,
      "zone": [
        "core/",
        "web/app/",
        "worker/",
        "web/static/js/video-block.js"
      ],
      "status": "review",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-22T01:31:00+03:00"
    },
    {
      "id": "08",
      "title": "Дуэты: логика экрана под тесты, ↵ у «оба»",
      "requirements": [
        "R01",
        "R02"
      ],
      "blockedBy": [
        "06"
      ],
      "wave": 4,
      "zone": [
        "web/static/js/editors/",
        "web/app/notes.py"
      ],
      "status": "review",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-10-22T01:31:00+03:00"
    }
  ],
  "singlePass": null,
  "tests": {
    "passed": 796,
    "failed": 0
  },
  "debt": {
    "placeholders": [],
    "assumptions": [],
    "emptyEnv": []
  },
  "additions": [
    "«Убрать видео» — ради R04 (A01)"
  ],
  "coverage": {
    "found": 3,
    "fixed": 3,
    "deferred": 0
  },
  "concerns": [
    "notes-panel-logic.js:64 — tapQueue заново выводит партию ноты (дубль partOf)",
    "notes-model.js settle/settleLines — дублированная вставка по времени внутри партии",
    "notes-model.js — шесть литералов [1, 2] для обхода партий",
    "timeline-math.js noteAt — O(n) на каждый тик и у соло",
    "notes-model.js VOICES — экспорт без потребителя",
    "notes-model.test — «оба» vs певец 1 не проверено",
    "notes.py — место ошибки собирается вручную в обход _where",
    "test_songs — нет тестов MANY_SINGERS_REASON",
    "test_songs DUET_FIX_TXT читает фикстуру чужого шва tests/core",
    "notes.py apply_notes — дуэт определяется по форме кортежа _tracks",
    "R02 — нота длины 0 в настоящем файле не даёт сохранить из редактора",
    "handlers.py download_video — разбор сбоев yt-dlp дублирует звуковой",
    "handlers.py _video_name — правило «видеофайл песни» отдельно от Storage.read_song",
    "test_runner_generate::test_traceback… — нестабилен под нагрузкой",
    "test_runner_video::test_sources_skip… — видели только зелёным",
    "notes-editor.js ↵ у строки «оба» на полосе P2 — mergeLineAt ищет предыдущую строку в P1 (не проверено в браузере)",
    "экран: partOf/partNotes/живые ноты/раскладка панели/updateDuet — чистая логика в экране без тестов, дубли модели",
    "три словаря подписей певцов вместо ctx.singerLabel",
    "DUET_HELP — цвета словами отдельно от токенов",
    "notes-text-panel liveLis = new Set([-2]) — маркер-костыль",
    "ручной долг: T/J, перетаскивание слога, ⇠/⇢, Разрезать/Слить/↵ в дуэте и телефон не проверены в браузере",
    "test_video restart — первый 409 даёт старая проверка, не новая ветка",
    "VIDEO_EXTS_TEXT/VIDEO_ACCEPT/VIDEO_HEIGHTS — дубли списков рядом с naming/params",
    "videoError (регулярка) и parse_videogap (float) принимают разные строки",
    "перезапуск завершённого video-задания с файлом падает «Нужно видео…»",
    "нет теста воркера «выбранное видео побеждает перенос старого при замене» (история 30)",
    "api.js appendVideo/videoForm — дубль сборки полей видео",
    "имя файла видео: video у /api/jobs/video vs video_file у generate/import",
    "video-block.js isVideoLink — свой список запретных сайтов рядом с musiclink.classify",
    "video_choice пишет height у file/pack",
    "api_import — ссылка видео «из ссылки песни» выбирается своей цепочкой",
    "songs.js currentVideoGap читает GET /notes"
  ],
  "reviewers": {
    "manifestSpec": "ac1b1b385b8397995",
    "craft": "a0975327a77d7a4bf"
  },
  "blind": {
    "implemented": 10,
    "partial": 1,
    "missing": 0,
    "drift": [],
    "notes": [
      "R08 — генерация с видео по ссылке не запускалась (GPU), проверены интерфейс и код",
      "после задания video список песен не обновляется сам — в таск 07"
    ]
  }
}
