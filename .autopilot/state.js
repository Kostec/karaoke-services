window.STATE =
{
  "version": 2,
  "slug": "songs-ui-ux",
  "dir": "2026-10-26-songs-ui-ux--wip",
  "title": "Удобнее интерфейс: плавающая «+», меню «…» в «Песнях», карточка песни со всем содержимым, свои теги",
  "mode": "semi",
  "depth": "normal",
  "tier": "T1",
  "briefFile": "2026-10-26-brief.md",
  "memoryFile": "CLAUDE.md",
  "memoryOwner": "autopilot",
  "skillDir": "C:/Users/work/.agents/skills/autopilot",
  "baseCommit": null,
  "startedAt": "2026-10-26T16:11:06+03:00",
  "updatedAt": "2026-10-26T16:28:58+03:00",
  "finishedAt": null,
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-10-26T16:11:06+03:00",
      "finishedAt": "2026-10-26T16:11:17+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-10-26T16:11:17+03:00",
      "finishedAt": "2026-10-26T16:11:33+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-10-26T16:11:33+03:00",
      "finishedAt": "2026-10-26T16:14:42+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-10-26T16:14:42+03:00",
      "finishedAt": "2026-10-26T16:28:12+03:00"
    },
    {
      "id": "plan",
      "status": "active",
      "startedAt": "2026-10-26T16:28:12+03:00"
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
    "total": 19,
    "done": 0,
    "inTicket": 19,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Свои теги, сведения и файлы песни на сервере",
      "requirements": [
        "R07",
        "R09",
        "R10",
        "R12",
        "R13",
        "R15",
        "R16",
        "R17i"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "core/karaoke_core/",
        "web/app/",
        "tests/core/",
        "tests/api/"
      ],
      "review": "да — фундамент",
      "model": "сильная",
      "status": "pending",
      "retries": 0,
      "repairs": 0
    },
    {
      "id": "02",
      "title": "«+», меню «…» в «Песнях», свои теги и страница песни",
      "requirements": [
        "R01",
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
        "R14",
        "R15",
        "R16",
        "R17i",
        "R18i",
        "G01"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "web/static/",
        "tests/frontend/"
      ],
      "review": "нет",
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
    "found": 1,
    "fixed": 1,
    "deferred": 0,
    "items": []
  },
  "concerns": [],
  "blind": null,
  "beats": [
    "2026-10-26T16:11:06+03:00",
    "2026-10-26T16:11:17+03:00",
    "2026-10-26T16:11:29+03:00",
    "2026-10-26T16:11:33+03:00",
    "2026-10-26T16:12:07+03:00",
    "2026-10-26T16:14:36+03:00",
    "2026-10-26T16:14:42+03:00",
    "2026-10-26T16:22:11+03:00",
    "2026-10-26T16:22:38+03:00",
    "2026-10-26T16:28:12+03:00",
    "2026-10-26T16:28:57+03:00",
    "2026-10-26T16:28:58+03:00"
  ],
  "rev": 14,
  "waiting": null,
  "waits": [
    {
      "kind": "briefing",
      "from": "2026-10-26T16:12:07+03:00",
      "to": "2026-10-26T16:14:36+03:00"
    },
    {
      "kind": "spec",
      "from": "2026-10-26T16:22:38+03:00",
      "to": "2026-10-26T16:28:12+03:00"
    }
  ],
  "log": [
    {
      "t": "2026-10-26T16:11:06+03:00",
      "k": "init"
    },
    {
      "t": "2026-10-26T16:11:17+03:00",
      "k": "stage",
      "id": "manifest",
      "act": "start"
    },
    {
      "t": "2026-10-26T16:11:33+03:00",
      "k": "stage",
      "id": "briefing",
      "act": "start"
    },
    {
      "t": "2026-10-26T16:12:07+03:00",
      "k": "ask",
      "kind": "briefing",
      "note": "четыре вопроса — вкладка «Новая песня», куда ведёт «+», где хранить свои теги, цвет своих тегов"
    },
    {
      "t": "2026-10-26T16:14:36+03:00",
      "k": "answered",
      "kind": "briefing"
    },
    {
      "t": "2026-10-26T16:14:42+03:00",
      "k": "gate",
      "g": "G1",
      "ok": false,
      "open": 19,
      "total": 19
    },
    {
      "t": "2026-10-26T16:14:42+03:00",
      "k": "stage",
      "id": "spec",
      "act": "start"
    },
    {
      "t": "2026-10-26T16:22:11+03:00",
      "k": "gate",
      "g": "G2",
      "ok": true,
      "found": 1,
      "fixed": 1,
      "deferred": 0
    },
    {
      "t": "2026-10-26T16:22:38+03:00",
      "k": "ask",
      "kind": "spec",
      "note": "согласование макета экранов (G01) до разработки"
    },
    {
      "t": "2026-10-26T16:28:12+03:00",
      "k": "answered",
      "kind": "spec"
    },
    {
      "t": "2026-10-26T16:28:12+03:00",
      "k": "stage",
      "id": "plan",
      "act": "start"
    },
    {
      "t": "2026-10-26T16:28:57+03:00",
      "k": "tier",
      "v": "T1"
    },
    {
      "t": "2026-10-26T16:28:58+03:00",
      "k": "tickets",
      "n": 2
    },
    {
      "t": "2026-10-26T16:28:58+03:00",
      "k": "gate",
      "g": "G3",
      "ok": true,
      "problems": 0
    }
  ],
  "reqList": [
    {
      "id": "R01",
      "text": "«сделать дизайн немного более UI/UX»",
      "status": "in-ticket"
    },
    {
      "id": "R02",
      "text": "«вместо фиксированной кнопки \"Новая пеня\" можно создать flow кнопку \"+\"»",
      "status": "in-ticket"
    },
    {
      "id": "R03",
      "text": "«которая будет оставаться на место независимо от скроллинга»",
      "status": "in-ticket"
    },
    {
      "id": "R04",
      "text": "«Там где можно создать новую песню»",
      "status": "in-ticket"
    },
    {
      "id": "R05",
      "text": "«Во вкладке \"Песни\" многое можно спрятать за \"...\"»",
      "status": "in-ticket"
    },
    {
      "id": "R06",
      "text": "«возможность открыть песню чтобы увидеть всю информацию по ней»",
      "status": "in-ticket"
    },
    {
      "id": "R07",
      "text": "«автор, исполнитель»",
      "status": "in-ticket"
    },
    {
      "id": "R08",
      "text": "«текст»",
      "status": "in-ticket"
    },
    {
      "id": "R09",
      "text": "«видео»",
      "status": "in-ticket"
    },
    {
      "id": "R10",
      "text": "«что для этой песни есть (например, минус, вокал, видео»",
      "status": "in-ticket"
    },
    {
      "id": "R11",
      "text": "«дать возможность их проиграть»",
      "status": "in-ticket"
    },
    {
      "id": "R12",
      "text": "«фоновое изображение»",
      "status": "in-ticket"
    },
    {
      "id": "R13",
      "text": "«и т.д.) и прочая информация»",
      "status": "in-ticket"
    },
    {
      "id": "R14",
      "text": "«Теги на вкладки \"Песни\" оставить - хорошо выглядит»",
      "status": "in-ticket"
    },
    {
      "id": "R15",
      "text": "«дать пользователю возможность добавлять свои» (теги)",
      "status": "in-ticket"
    },
    {
      "id": "R16",
      "text": "«(другим цветом)»",
      "status": "in-ticket"
    },
    {
      "id": "R17i",
      "text": "(подразумевается) свои теги можно снять/удалить и по ним фильтровать, как по встроенным",
      "status": "in-ticket"
    },
    {
      "id": "R18i",
      "text": "(подразумевается) всё, что сейчас есть на карточке «Песен», остаётся доступным (через «…» или карточку песни)",
      "status": "in-ticket"
    },
    {
      "id": "G01",
      "text": "«перед реальным прогоном согласуй дизайн со мной»",
      "status": "in-ticket"
    }
  ],
  "gates": {
    "G1": {
      "ok": false,
      "at": "2026-10-26T16:14:42+03:00",
      "open": 19,
      "total": 19
    },
    "G2": {
      "ok": true,
      "at": "2026-10-26T16:22:11+03:00",
      "found": 1,
      "fixed": 1,
      "deferred": 0
    },
    "G3": {
      "ok": true,
      "at": "2026-10-26T16:28:58+03:00",
      "problems": 0
    }
  },
  "result": null
}
