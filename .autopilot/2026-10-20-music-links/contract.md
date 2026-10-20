# Генерация по ссылке на музыку — общий контракт

Запрос пользователя (2026-10-20): «Можно ли сделать импорт ссылкой из YouTube, ВКонтакте, Yandex музыка?» → после проверки: «Делай пункты 1 и 2, DNS тоже поправь».
- п.1 — генерация по ссылке через yt-dlp: YouTube, видео ВКонтакте, RuTube, SoundCloud (всё, что умеет yt-dlp без входа);
- п.2 — Яндекс Музыка по OAuth-токену аккаунта пользователя (подписка Плюс), токен вписывает сам пользователь в «Настройки»; трек, альбом, плейлист;
- аудиозаписи ВКонтакте — НЕ делаем (понятная ошибка);
- DNS: постоянные DNS-серверы и IPv4 в контейнерах.

Это **генерация** (UltraSinger), а не импорт готовой UltraStar-песни: ссылка заменяет загруженный mp3.

## 1. Инфраструктура (таск A)

- `docker-compose.yml`: у `web` и `worker` — `dns: [77.88.8.8, 1.1.1.1]` и `sysctls: [net.ipv6.conf.all.disable_ipv6=1]` (у контейнеров нет IPv6-маршрута, а музыка/Яндекс отдают AAAA первыми).
- `yandex-music` (MarshalX) — зависимость `core` (ставится в web, worker и tests).
- yt-dlp в образе **web**: отдельным слоем `pip install -U "yt-dlp[default]"` с `ARG YTDLP_REFRESH` (как в worker/Dockerfile), НЕ через pyproject (тесты полагаются на отсутствие yt_dlp в образе tests).
- `YTDLP_CMD` передаётся и в web (уже есть в `.env.example`); web без неё — `python -m yt_dlp`.

## 2. `core/karaoke_core/musiclink.py` (таск A)

```python
class MusicLinkError(Exception): ...          # текст по-русски, без токена

@dataclass(frozen=True)
class LinkKind:
    kind: str            # "yandex_track" | "yandex_album" | "yandex_playlist" | "ytdlp"
    url: str             # нормализованная ссылка (без utm_* и прочего мусора)
    ids: dict            # yandex_track: {"track": "148124289", "album": "40620828"}; album: {"album"}; playlist: {"user","kind"} или {"uuid"}

def classify(url: str) -> LinkKind
    # не http(s) → MusicLinkError("Нужна ссылка вида https://…")
    # vk.com|vk.ru /audio… → MusicLinkError("Аудиозаписи ВКонтакте не поддерживаются: VK не отдаёт их сторонним программам. Видео и клипы VK — можно")
    # music.yandex.ru|.com|.by|.kz /album/<a>/track/<t>, /track/<t>, /album/<a>, /users/<u>/playlists/<k>, /playlists/<uuid>
    # иначе — "ytdlp"

@dataclass(frozen=True)
class LinkTrack:
    url: str                     # ссылка на один трек (её и передают в generate как audio_url)
    artist: str                  # может быть "" — тогда UI подсвечивает
    title: str
    duration: float | None       # секунды
    thumbnail: str | None        # URL обложки

@dataclass(frozen=True)
class LinkInfo:
    kind: str                    # как LinkKind.kind
    title: str                   # название трека/альбома/плейлиста
    tracks: list[LinkTrack]      # трек → один элемент

def ytdlp_info(url: str, cmd: list[str], timeout: float = 60) -> LinkInfo
    # subprocess: cmd + ["-4", "-J", "--flat-playlist", "--no-warnings", "--", url]
    # artist = artist|creator|uploader (без " - Topic"); title = track|title;
    # нет artist и в title есть " - " → разделить; плейлист → entries (url каждой записи)
    # ошибка/таймаут → MusicLinkError("Не удалось получить данные по ссылке: <строка ERROR yt-dlp>")

class YandexMusic:
    def __init__(self, token: str, client_factory=None)   # client_factory — шов для тестов
    def info(self, link: LinkKind) -> LinkInfo
    def download(self, link: LinkKind, dest_mp3: Path) -> None   # лучший mp3; пишет через временный файл
    # ошибки → MusicLinkError: нет токена — «Впишите токен Яндекс Музыки в Настройках»;
    # неверный токен — «Яндекс Музыка не приняла токен»; нет прав/451 — «Яндекс Музыка не отдала трек: нужна подписка Плюс (и, возможно, российский IP)»;
    # сеть — «Яндекс Музыка недоступна, попробуйте позже»

# CLI для воркера (отменяемый подпроцесс, подменяется MUSICLINK_CMD в тестах):
#   python -m karaoke_core.musiclink download <url> <dest.mp3>
#   токен — из переменной окружения YANDEX_MUSIC_TOKEN процесса (не в argv, не в лог); код ≠ 0 и последняя строка stderr — русский текст ошибки
```

## 3. Токен в БД (таск A)

- `db.Settings.get_yandex() -> str | None`, `set_yandex(token: str | None)`; ключ `settings["yandex_music"]` (JSON `{"token": …}`); `None`/пусто — удалить.
- Ловушка `test_repo_config`: в коде вне `tests/` не писать `token = …`/`token: …` литералом в одной строке — имена вроде `ym_token`, доступ `d["token"]`.

## 4. REST (таск B, web)

- `POST /api/link/inspect` JSON `{"url": "…"}` → `{"kind", "title", "tracks": [{"url","artist","title","duration","thumbnail","existing_song_id"}]}`; ошибки — 400 `field=url` (текст `MusicLinkError`), нет токена для Яндекса — 400 `code="yandex_no_token"`; сеть — 503. Яндекс — `YandexMusic` из `create_app(..., yandex_factory=)`, остальное — `ytdlp_info` с `YTDLP_CMD`.
- `GET /api/settings/yandex` → `{"has_token": bool}`; `PUT` `{"token": "…"}` (пусто — удалить; сохраняет только после успешной проверки); `POST /api/settings/yandex/test` → `{"ok": true}` или 400 `field=token`.
- `POST /api/jobs/generate`: новое необязательное поле формы `audio_url` — альтернатива файлу `audio` (ровно одно из двух; иначе 400 `field=audio`). Проверяется `classify`. В params: `inputs.audio_url` (без `inputs.audio`), `params.source = "link"`. Перегенерация из `source/` (там уже `input.mp3`) работает как раньше.

## 5. Воркер (таск C)

- `GenerateHandler`: если в `inputs` есть `audio_url` и нет `in/input.mp3` — этап «Загрузка звука» (`STAGE_DOWNLOAD`): Яндекс → `MUSICLINK_CMD` (по умолчанию `python -m karaoke_core.musiclink`) `download <url> <in/input.mp3>` с `YANDEX_MUSIC_TOKEN` из `Settings.get_yandex()` в окружении подпроцесса; остальное → yt-dlp (`download_youtube`, с `-4`), mp3 → `in/input.mp3`, миниатюра → `in/cover.jpg`, если своей обложки нет. Дальше — как обычно (`audio_only_copy` и т.д.). Restart с готовым `in/input.mp3` не качает заново.
- Все вызовы yt-dlp в воркере — с `-4`.
- `MUSICLINK_CMD` — в `.env.example` с русским комментарием; фейк `tests/worker/fixtures/fake_musiclink.py`.

## 6. Интерфейс (таск D)

- Форма новой песни: рядом с «Аудио mp3» — «или ссылка на трек» (YouTube, VK-видео, RuTube, SoundCloud, Яндекс Музыка) + «Получить»: `link/inspect` → исполнитель/название подставляются (если поля пусты), обложка-превью, авто-поиск текста как сейчас (кнопка «Найти текст»); правило 3 с для таймингов LRC берёт `duration` из ответа. Ссылка на альбом/плейлист → подсказка «Это список из N треков — откройте Импорт → Ссылка».
- Импорт → «Ссылка»: если ссылка музыкальная (не zip и не GitHub) — `link/inspect` и список треков на генерацию, тем же видом и логикой, что группа «Музыка для генерации» во вкладке «Папка» (авто-поиск текста, «уже есть», параметры на группу, постановка по одному), только вместо файла — `audio_url`.
- «Настройки» → карточка «Яндекс Музыка»: поле токена, «Проверить», «Сохранить», `has_token`, ссылка-подсказка, как получить токен (без ввода логина/пароля в сервис).
- Аудио VK → текст ошибки сервера как есть.

## Что построил таск A (сверх контракта)

- `musiclink.is_yandex(link)`, `YANDEX_KINDS`; тексты ошибок `MSG_NEED_LOGIN` (нет токена), `MSG_REJECTED` (неверный токен), `MSG_NO_RIGHTS`, `MSG_UNAVAILABLE` (сеть → 503), `MSG_NOT_FOUND` («ничего по этой ссылке» → 400); `main(argv, env, client_factory)` — CLI для тестов
- `YandexMusic.check()` — для `POST /api/settings/yandex/test` (нет uid → `MSG_REJECTED`); `YandexMusic.client()`
- `db.YANDEX_KEY = "yandex_music"`; `set_yandex(None|"")` удаляет
- `.env.example`: `YANDEX_MUSIC_TOKEN=` (читает CLI); `YTDLP_CMD` теперь в общем окружении web и worker
- `ytdlp_info` чистит заголовки видео: «(Official Video)/[4K]/(клип)», повтор исполнителя, перестановка частей по имени канала
- web без deno; метаданные YouTube без него работают
- фикстура `tests/core/fixtures/fake_ytdlp_info.py` — фейк `yt-dlp -J`
