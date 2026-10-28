window.STATE =
{
  "version": 2,
  "slug": "player-remote-lyrics",
  "dir": "2026-10-28-player-remote-lyrics--wip",
  "title": "Звук нот и вокал в редакторе и «Прогоне», пульт Rii i8, второй источник текстов",
  "mode": "semi",
  "depth": "deep",
  "tier": "T2",
  "briefFile": "2026-10-28-brief.md",
  "memoryFile": "CLAUDE.md",
  "memoryOwner": "autopilot",
  "skillDir": "C:/Users/work/.agents/skills/autopilot",
  "baseCommit": null,
  "startedAt": "2026-10-28T19:08:27+03:00",
  "updatedAt": "2026-10-28T19:33:39+03:00",
  "finishedAt": null,
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-10-28T19:08:27+03:00",
      "finishedAt": "2026-10-28T19:08:55+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-10-28T19:08:55+03:00",
      "finishedAt": "2026-10-28T19:09:03+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-10-28T19:09:03+03:00",
      "finishedAt": "2026-10-28T19:22:07+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-10-28T19:22:07+03:00",
      "finishedAt": "2026-10-28T19:32:04+03:00"
    },
    {
      "id": "plan",
      "status": "active",
      "startedAt": "2026-10-28T19:32:04+03:00"
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
    "total": 17,
    "done": 0,
    "inTicket": 17,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Пульт Rii i8 на всех экранах и подсказка по клавишам",
      "requirements": [
        "R04",
        "R05",
        "R06",
        "R07",
        "R11i"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "web/static/js/remote.js",
        "web/static/js/remote-logic.js",
        "web/static/js/app.js",
        "web/static/index.html",
        "web/static/js/songs.js",
        "web/static/css/remote.css",
        "tests/frontend/remote-logic.test.mjs"
      ],
      "review": "нет",
      "model": "сильная",
      "status": "pending",
      "retries": 0,
      "repairs": 0
    },
    {
      "id": "02",
      "title": "Мелодия нот и «Вокал» в редакторе и «Прогоне», кликабельное «пианино»",
      "requirements": [
        "R01",
        "R02",
        "R03",
        "R10i",
        "G03",
        "G04",
        "R06",
        "R07"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "web/static/js/tone.js",
        "web/static/js/melody.js",
        "web/static/js/vocals.js",
        "web/static/js/vocals-logic.js",
        "web/static/js/play.js",
        "web/static/js/play-logic.js",
        "web/static/js/editors/",
        "web/static/css/editors.css",
        "tests/frontend/melody.test.mjs",
        "tests/frontend/vocals-logic.test.mjs",
        "tests/frontend/tone.test.mjs",
        "tests/frontend/play-logic.test.mjs"
      ],
      "review": "нет",
      "model": "сильная",
      "status": "pending",
      "retries": 0,
      "repairs": 0
    },
    {
      "id": "03",
      "title": "Тексты из LRCLIB, NetEase и Genius с просмотром; вся очередь видна",
      "requirements": [
        "R08",
        "R09",
        "R12i",
        "G01",
        "G02",
        "G05"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "web/app/lyrics.py",
        "web/app/api_lyrics.py",
        "web/static/js/lyrics-search.js",
        "web/static/js/lyrics-dialog.js",
        "web/static/js/import.js",
        "web/static/js/api.js",
        "web/static/css/app.css",
        "core/karaoke_core/db.py",
        "tests/api/test_lyrics.py",
        "tests/frontend/lyrics-search.test.mjs",
        "tests/core/test_db.py",
        "tests/api/test_queue_order.py"
      ],
      "review": "нет",
      "model": "обычная",
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
    "found": 3,
    "fixed": 3,
    "deferred": 0,
    "items": []
  },
  "concerns": [],
  "blind": null,
  "beats": [
    "2026-10-28T19:08:27+03:00",
    "2026-10-28T19:08:54+03:00",
    "2026-10-28T19:08:55+03:00",
    "2026-10-28T19:09:03+03:00",
    "2026-10-28T19:10:04+03:00",
    "2026-10-28T19:22:00+03:00",
    "2026-10-28T19:22:07+03:00",
    "2026-10-28T19:31:56+03:00",
    "2026-10-28T19:32:04+03:00",
    "2026-10-28T19:33:38+03:00",
    "2026-10-28T19:33:39+03:00"
  ],
  "rev": 13,
  "waiting": null,
  "waits": [
    {
      "kind": "briefing",
      "from": "2026-10-28T19:10:04+03:00",
      "to": "2026-10-28T19:22:00+03:00"
    }
  ],
  "log": [
    {
      "t": "2026-10-28T19:08:27+03:00",
      "k": "init"
    },
    {
      "t": "2026-10-28T19:08:55+03:00",
      "k": "stage",
      "id": "manifest",
      "act": "start"
    },
    {
      "t": "2026-10-28T19:09:03+03:00",
      "k": "stage",
      "id": "briefing",
      "act": "start"
    },
    {
      "t": "2026-10-28T19:10:04+03:00",
      "k": "ask",
      "kind": "briefing",
      "note": "4 вопроса — вокал без минусовки, где работает пульт, порядок поиска текстов, хвосты прошлой сборки"
    },
    {
      "t": "2026-10-28T19:22:00+03:00",
      "k": "answered",
      "kind": "briefing"
    },
    {
      "t": "2026-10-28T19:22:07+03:00",
      "k": "gate",
      "g": "G1",
      "ok": false,
      "open": 17,
      "total": 17
    },
    {
      "t": "2026-10-28T19:22:07+03:00",
      "k": "stage",
      "id": "spec",
      "act": "start"
    },
    {
      "t": "2026-10-28T19:31:56+03:00",
      "k": "gate",
      "g": "G2",
      "ok": true,
      "found": 3,
      "fixed": 3,
      "deferred": 0
    },
    {
      "t": "2026-10-28T19:32:04+03:00",
      "k": "stage",
      "id": "plan",
      "act": "start"
    },
    {
      "t": "2026-10-28T19:33:38+03:00",
      "k": "tier",
      "v": "T2"
    },
    {
      "t": "2026-10-28T19:33:39+03:00",
      "k": "tickets",
      "n": 3
    },
    {
      "t": "2026-10-28T19:33:39+03:00",
      "k": "gate",
      "g": "G3",
      "ok": true,
      "problems": 0
    }
  ],
  "reqList": [
    {
      "id": "R01",
      "text": "«в редакторе нот необходимо включить проигрывание нот во время воспроизведения»",
      "status": "in-ticket"
    },
    {
      "id": "R02",
      "text": "«в редакторе нот нужна фича для включения и отключения вокала»",
      "status": "in-ticket"
    },
    {
      "id": "R03",
      "text": "«во вкладке прогон также нужна фича для включения и отключения вокала»",
      "status": "in-ticket"
    },
    {
      "id": "R04",
      "text": "«нужна поддержка возможности работы с пультом Rii i8»",
      "status": "in-ticket"
    },
    {
      "id": "R05",
      "text": "«а именно поддержка стрелок»",
      "status": "in-ticket"
    },
    {
      "id": "R06",
      "text": "«и хоткеев»",
      "status": "in-ticket"
    },
    {
      "id": "R07",
      "text": "«(должна быть подсказка)»",
      "status": "in-ticket"
    },
    {
      "id": "R08",
      "text": "«нужен ещё один сервис для поиска текстов, например https://genius.com/Fixeye-i-will-build-lyrics»",
      "status": "in-ticket"
    },
    {
      "id": "R09",
      "text": "«LRCLIB часто недоступен»",
      "status": "in-ticket"
    },
    {
      "id": "R10i",
      "text": "(подразумевается) вокал выключается только у песен, где есть минусовка — у прочих переключатель недоступен с понятной причиной",
      "status": "in-ticket"
    },
    {
      "id": "R11i",
      "text": "(подразумевается) на каких экранах работает пульт",
      "status": "in-ticket"
    },
    {
      "id": "R12i",
      "text": "(подразумевается) у Genius нет синхронного текста — вариант без LRC-таймингов",
      "status": "in-ticket"
    },
    {
      "id": "G01",
      "text": "«поищи ещё варианты сервисов»",
      "status": "in-ticket"
    },
    {
      "id": "G02",
      "text": "«нужна функция просмотра текста пере добавлением»",
      "status": "in-ticket"
    },
    {
      "id": "G03",
      "text": "«В редакторе слева есть клавиатура синтезатора, нужно сделать её кликабельной: при нажатии на клавишу должна проигрываться нота»",
      "status": "in-ticket"
    },
    {
      "id": "G04",
      "text": "«4. Ок» — «Прогон» не закрывает звуковой движок синтезатора (из «Известных багов»)",
      "status": "in-ticket"
    },
    {
      "id": "G05",
      "text": "«4. Ок» — очередь показывает только 50 последних заданий (из «Известных багов»)",
      "status": "in-ticket"
    }
  ],
  "gates": {
    "G1": {
      "ok": false,
      "at": "2026-10-28T19:22:07+03:00",
      "open": 17,
      "total": 17
    },
    "G2": {
      "ok": true,
      "at": "2026-10-28T19:31:56+03:00",
      "found": 3,
      "fixed": 3,
      "deferred": 0
    },
    "G3": {
      "ok": true,
      "at": "2026-10-28T19:33:39+03:00",
      "problems": 0
    }
  },
  "result": null
}
