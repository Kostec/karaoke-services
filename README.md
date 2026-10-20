# karaoke-services

Домашний сервис для караоке UltraStar: в браузере (с ПК или телефона) загружаешь mp3 и текст —
воркер на видеокарте прогоняет их через [UltraSinger](https://github.com/Kostec/UltraSinger/tree/karaoke-local)
и кладёт готовую песню (`.txt`, mp3, вокал, минусовка, `.mid`) в папку результата: на Samba-шару
Raspberry Pi или в папку на ПК.

Два контейнера в docker compose:

- `web` — веб-интерфейс и REST API (документация API — `http://<адрес>:8090/api/docs`);
- `worker` — очередь заданий, UltraSinger, demucs, ffmpeg на GPU.

## Требования

- Windows 10/11 с **Docker Desktop** на WSL2 (Settings → General → «Use the WSL 2 based engine»).
- Драйвер NVIDIA для Windows с поддержкой CUDA в WSL (любой свежий Game Ready / Studio).
- Видеокарта NVIDIA GTX 10xx или новее, от 6 ГБ видеопамяти (проверено на GTX 1080, 8 ГБ).
- ~30 ГБ на диске: образ worker ~18 ГБ, модели ~6 ГБ (качаются при первой генерации).
- Для выкладки на Pi — Samba-шара с папкой песен UltraStar и учётка с правом записи.

### Почему все команды с `--context desktop-linux`

На этом ПК у Docker Desktop по умолчанию активен **Windows-движок** (он нужен другим проектам), а
сервис работает только на **Linux-движке**. Переключать движок не нужно: каждая команда явно
указывает контекст `desktop-linux`. Чтобы не печатать его каждый раз, есть обёртка:

```powershell
./scripts/compose.ps1 <что угодно после "docker compose">
# то же самое, что
docker --context desktop-linux compose <...>
```

Дальше в README команды записаны через обёртку; из Git Bash/WSL пишите полную форму
`docker --context desktop-linux compose ...` из папки проекта.

## Подготовка `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Каждая переменная описана комментарием в `.env.example`. Обязательно посмотреть:

| Переменная | Что вписать |
|---|---|
| `OUTPUT_KIND` | `smb` — выкладка на шару Pi, `local` — в папку ПК (`LOCAL_OUTPUT_ROOT`). Позже цель меняется в вебе (Настройки) |
| `OUTPUT_SMB_HOST` | **IP-адрес** Pi (сейчас `192.168.0.129`). Имена `pi` / `pi.local` внутри контейнеров не резолвятся. Закрепите IP за Pi в роутере |
| `OUTPUT_SMB_SHARE`, `OUTPUT_SMB_PATH` | имя шары и путь внутри неё до папки песен |
| `OUTPUT_SMB_USER`, `OUTPUT_SMB_PASSWORD` | учётка Samba — **вписываете сами**; API пароль никогда не возвращает |
| `WEB_PASSWORD` | общий пароль на вход (логин любой). Пусто — вход без пароля. Вписываете сами, если нужен |
| `WEB_PORT` | `8090` — порт 8080 на этом ПК бывает занят (jenkins) |
| `LOCAL_OUTPUT_ROOT` | папка ПК, которая видна сервису как `/output` (по умолчанию `./output`) |

`.env` в git не попадает (`.gitignore`). Без `.env` сервис тоже стартует — с умолчаниями из
`.env.example` и пустой учёткой Samba.

## Первый запуск

```powershell
./scripts/compose.ps1 up -d --build
./scripts/compose.ps1 ps
```

Первая сборка образа worker идёт 15–30 минут (torch, UltraSinger). Оба контейнера должны быть в
состоянии `Up`; они перезапускаются сами (`restart: unless-stopped`), в том числе после
перезагрузки ПК, если Docker Desktop стартует вместе с Windows.

### Проверка GPU

```powershell
./scripts/compose.ps1 run --rm worker gpucheck
```

Успех — последняя строка `gpucheck: OK — GPU готов к генерации` и код выхода 0. По пути печатаются:
версии PyTorch/CUDA, имя GPU и VRAM, умножение тензоров на cuda (`OK`), ctranslate2 с `int8: да`
и четыре проверки правок UltraSinger (`[OK]`).

Строка `Архитектуры: sm_50 sm_60 sm_70 … (для этого GPU исполняется: sm_60)` на картах Pascal
(GTX 10xx, compute capability 6.1) — **норма**: в официальных колёсах torch cu126 нет `sm_61`,
а код `sm_60` бинарно совместим с Pascal и реально работает на GTX 1080.

Воркер делает ту же проверку при старте; результат виден в шапке веба
(`GPU: NVIDIA GeForce GTX 1080 ✓`) и в `GET /api/status`.

## Доступ с телефона

1. Узнайте IP ПК в домашней сети: `ipconfig` → «IPv4-адрес» адаптера Wi-Fi/Ethernet
   (обычно `192.168.0.x`).
2. Откройте на телефоне `http://<IP-ПК>:8090`.
3. Если страница не открывается — разрешите порт в брандмауэре Windows. **Это делаете вы сами**,
   в PowerShell, запущенном от имени администратора:

   ```powershell
   New-NetFirewallRule -DisplayName "karaoke-services 8090" -Direction Inbound -Protocol TCP -LocalPort 8090 -Action Allow -Profile Private
   ```

   Правило действует для сетей с профилем «Частная». Если домашняя сеть помечена как «Общедоступная»,
   поменяйте её профиль в параметрах Windows (не открывайте порт для публичных сетей).

## Как пользоваться

**Новая песня.** Исполнитель, название, mp3 (теги ID3 сами заполнят исполнителя, название и
обложку), текст песни (вставить или загрузить файл) и обложка по желанию. «Дополнительно» — модель
Whisper, язык, тип вычислений, batch, VAD, модель demucs. Если такая песня уже есть, сервис
предложит заменить её (старая уйдёт в корзину) или отменить.

**Очередь.** Задания выполняются по одному. Видны этап, процент и живой лог; задание можно
отменить, упавшее — перезапустить, а упавшее на выкладке — выложить повторно без новой генерации.
Причина ошибки показывается по-русски, полный лог — по кнопке.

**Песни.** Всё, что лежит в папке результата: поиск, прослушивание, обложка, отметка о
минусовке. Список обновляется после каждой выкладки и кнопкой «Обновить».

**Минусовка.** Для любой песни из списка (в том числе скачанной с USDB) — кнопка «Минусовка»
(если минусовка уже есть — «Пересоздать минусовку», старый файл уйдёт в корзину): demucs отделяет вокал, в папку песни ложится `… [Instrumental].mp3`, а в `.txt`
меняется только строка `#INSTRUMENTAL`.

**Редакторы.** В карточке песни: «Править текст» — поправить слова и перегенерировать песню с
новым текстом; «Править слова» — поправить слоги, склеить/разбить строки, удалить ноты с прослушиванием
каждой строки. Сохранение заменяет `.txt`, прежняя версия уходит в корзину.

**Корзина.** Удалённые и заменённые песни и версии `.txt` хранятся `TRASH_DAYS` дней (30 по
умолчанию) в томе `data`, их можно восстановить в ту же папку результата.

**Настройки.** Цель выкладки: шара Samba (адрес, шара, путь, логин, пароль) или папка ПК внутри
`LOCAL_OUTPUT_ROOT`; кнопка «Проверить» пробует подключиться и записать. Пароль, введённый в
вебе, хранится только в томе `data`.

## Где хранятся данные и как их бэкапить

| Том docker | В контейнере | Что внутри | Бэкап |
|---|---|---|---|
| `karaoke-services_data` | `/data` | БД заданий и настроек (SQLite), исходники песен, логи, корзина | нужен |
| `karaoke-services_models` | `/models` | модели Whisper, wav2vec2, demucs, словари (~6 ГБ) | не обязателен — скачаются заново |
| `./output` (`LOCAL_OUTPUT_ROOT`) | `/output` | готовые песни при цели «папка ПК» | обычной копией папки |

Бэкап тома `data` в `%USERPROFILE%\karaoke-backup\data.tgz` — вне папки проекта, чтобы архив
(в нём БД и, возможно, пароль Samba из настроек) не попал в git. Сервис на время копирования
останавливается, чтобы SQLite был в целостном состоянии:

```powershell
./scripts/compose.ps1 stop
New-Item -ItemType Directory -Force "$HOME/karaoke-backup" | Out-Null
docker --context desktop-linux run --rm --entrypoint tar -v karaoke-services_data:/v -v "$HOME/karaoke-backup:/b" karaoke-services-worker czf /b/data.tgz -C /v .
./scripts/compose.ps1 start
```

### Восстановление из бэкапа (делаете вы сами)

> **Внимание:** текущие задания, настройки (в т.ч. цель выкладки и пароль Samba из веба), исходники
> песен, логи и корзина будут **заменены** содержимым архива. Всё, что появилось после бэкапа,
> пропадёт. Готовые песни в папке результата не затрагиваются.

Сервисы останавливаются, том `data` очищается и в пустой том распаковывается архив, затем сервисы
запускаются:

```powershell
./scripts/compose.ps1 stop
docker --context desktop-linux run --rm --entrypoint sh -v karaoke-services_data:/v -v "$HOME/karaoke-backup:/b" karaoke-services-worker -c "find /v -mindepth 1 -delete && tar xzf /b/data.tgz -C /v"
./scripts/compose.ps1 start
```

Тома переживают `compose down` и пересборку образов; удаляет их только `compose down -v` — не
делайте так без бэкапа.

## Обновление UltraSinger

Наши правки живут в ветке `karaoke-local` форка `Kostec/UltraSinger`; образ worker собирается из
неё (`ULTRASINGER_GIT` в `.env`). Перенос правок на свежий upstream — в локальном клоне UltraSinger
(`D:/Projects/UltraSinger`, удалённые репозитории `origin` = upstream, `fork` = ваш форк; если у вас
remote называется иначе — подставьте своё).

**Шаги в репозитории UltraSinger (fetch, rebase, push в форк) делаете вы сами** — они меняют вашу
ветку и форк на GitHub. Остальное — команды этого проекта:

```powershell
cd D:/Projects/UltraSinger
# --- действия пользователя: ---
git fetch origin
git checkout karaoke-local
git rebase origin/main            # конфликты — поправить, git add, git rebase --continue
git push --force-with-lease fork karaoke-local
# --- дальше команды проекта: ---
cd D:/Projects/karaoke-services
./scripts/compose.ps1 build worker
./scripts/compose.ps1 run --rm worker gpucheck
./scripts/compose.ps1 up -d
./scripts/export-ultrasinger-patch.ps1
```

- `build worker` скачивает ветку заново. Версии зависимостей UltraSinger берутся из его
  `uv.lock` (кроме torch/torchaudio/torchvision cu126 и `numpy<2.5`, которые задаёт наш образ),
  поэтому обновление upstream не подтянет случайно несовместимые пакеты. Если upstream обновил
  `uv.lock`, новые версии придут вместе с ним — для этого и нужен `gpucheck` после сборки.
- `gpucheck` проверяет и правки: флаги `--lyrics/--vad_onset/--vad_offset`, модуль
  `lyrics_alignment`, `midi_creator` на нулевом сегменте, сигнатуру SwiftF0. `[ОШИБКА]` с
  названием правки значит, что rebase её потерял.
- `export-ultrasinger-patch.ps1` сохраняет `git format-patch origin/main..karaoke-local` в
  `patches/karaoke-local.patch` — резервная копия правок в этом репозитории (закоммитьте её).
  Восстановить: `git checkout -b karaoke-local origin/main` и `git am patches/karaoke-local.patch`.
- Собрать из локальной папки без push: `ULTRASINGER_GIT=D:/Projects/UltraSinger` в `.env`.

## Частые ошибки

| Симптом | Что делать |
|---|---|
| `CUDA out of memory` / «не хватило видеопамяти» | в «Дополнительно» поставить batch `2` (или `1`) или модель Whisper меньше (`medium`); не запускать параллельно игры и другие GPU-задачи |
| Ошибка про `float16` / «compute type не поддерживается» | GTX 10xx не умеет float16 — тип вычислений `int8` (умолчание в `.env`: `DEFAULT_COMPUTE_TYPE=int8`) |
| «Папка результата недоступна», задание упало на выкладке | Pi выключен или сменил IP, неверная учётка, шара не открыта на запись. Проверить в «Настройки» → «Проверить», затем в очереди — «Выложить повторно» |
| Адрес `pi` / `pi.local` не находится | контейнеры не видят mDNS-имена — в `OUTPUT_SMB_HOST` и в настройках только IP |
| `compose up`: `port is already allocated` / `bind: address already in use` | порт занят: поменять `WEB_PORT` в `.env` и выполнить `up -d` |
| В шапке «GPU недоступен» | `./scripts/compose.ps1 run --rm worker gpucheck` покажет причину; обновить драйвер NVIDIA, перезапустить Docker Desktop. Без GPU задания ждут в очереди |
| Первая генерация долго висит на «Подготовке»/распознавании | при первом запуске качаются модели (несколько ГБ) в том `models`; дальше они берутся из тома |
| `error during connect` / `docker` не видит движок | Docker Desktop не запущен или команда без `--context desktop-linux` |

Логи сервисов: `./scripts/compose.ps1 logs --tail 100 worker` (или `web`).

## Тесты

```powershell
./scripts/compose.ps1 --profile test run --build --rm tests
node --test tests/frontend/
```

Первая команда гоняет pytest по `tests/` в Linux-контейнере (ядро, API, воркер с подменой
UltraSinger); на Windows-хосте Python-тесты не запускаются. Вторая — тесты фронтенда на
встроенном `node:test` (проверено на Node.js 24.18.0).
