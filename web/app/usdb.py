"""Клиент usdb.animux.de: вход, поиск песен, ноты и ссылки YouTube из комментариев.

Запросы и строки-признаки — как у usdb_syncer (``usdb_scraper.py``, ``constants.py``):
вход — POST на корень (``user``, ``pass``, ``login=Login``); ссылка выхода/профиля в ответе — лишь
подтверждение (её нет — предупреждение в лог), сессия — cookie в памяти процесса; «You are not logged in…» в любом ответе — один
повторный вход и повтор запроса. HTML разбирается стандартной библиотекой (``re`` +
``html.parser``), без новых зависимостей; сущности раскрываются в каждой ячейке после снятия
тегов. Пароль не попадает ни в текст ошибок, ни в ``repr``.
"""

from __future__ import annotations

import html
import logging
import re
import threading
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

from karaoke_core.http import HttpError
from karaoke_core.songpack import youtube_watch_url

BASE_URL = "https://usdb.animux.de/"
PAGE_SIZE = 50
TIMEOUT = 20

LOGIN_INVALID = "Login or Password invalid, please try again."
NOT_LOGGED_IN = "You are not logged in. Login to use this function."
DATASET_NOT_FOUND = "Datensatz nicht gefunden"
# Положительный признак входа: у вошедшего на странице есть ссылка выхода или профиля.
# Нет признака — вход всё равно принят (разметка не сверена с живым сайтом), а настоящая
# проверка — «You are not logged in…» на следующем запросе.
_LOGGED_IN_RE = re.compile(r"""[?&]link=(?:logout|profil)\b""", re.I)
NOT_CONFIRMED_LOG = "usdb: вход не подтверждён признаком — проверю на следующем запросе"

log = logging.getLogger("karaoke.web")


class UsdbError(Exception):
    """Ошибка usdb; текст — по-русски, для пользователя."""


class UsdbAuthError(UsdbError):
    def __init__(self, message: str = "usdb не принял логин или пароль"):
        super().__init__(message)


class UsdbUnavailable(UsdbError):
    def __init__(self, message: str = "usdb недоступен, попробуйте позже"):
        super().__init__(message)


class UsdbNotFound(UsdbError):
    def __init__(self, message: str = "Песня в usdb не найдена"):
        super().__init__(message)


@dataclass(frozen=True)
class UsdbHit:
    id: int
    artist: str
    title: str
    language: str
    rating: float
    views: int

    def to_dict(self) -> dict:
        return {"id": self.id, "artist": self.artist, "title": self.title, "language": self.language,
                "rating": self.rating, "views": self.views}


@dataclass(frozen=True)
class UsdbPage:
    items: list[UsdbHit]
    has_more: bool


@dataclass(frozen=True)
class UsdbSong:
    txt: bytes
    youtube: list[str] = field(default_factory=list)
    cover_url: str | None = None


class UsdbClient:
    """Сессия одной учётки usdb. Потокобезопасен: запросы идут по очереди."""

    def __init__(self, http, user: str, pass_: str):
        self._http = http
        self.user = user
        self._pass = pass_
        self._session = None
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return f"UsdbClient(user={self.user!r})"

    # ------------------------------------------------------------------ публичное

    def login(self) -> None:
        """Войти заново; неверная учётка — ``UsdbAuthError``, нет связи — ``UsdbUnavailable``."""
        with self._lock:
            session = self._http.session()
            text = self._text(session, "POST", BASE_URL,
                              data={"user": self.user, "pass": self._pass, "login": "Login"})
            if LOGIN_INVALID in text:
                self._session = None
                raise UsdbAuthError()
            if not _LOGGED_IN_RE.search(text):
                log.warning(NOT_CONFIRMED_LOG)  # без тела страницы и пароля
            self._session = session

    def search(self, artist: str = "", title: str = "", language: str = "", start: int = 0) -> UsdbPage:
        data = {"interpret": artist, "title": title, "language": language, "order": "rating",
                "ud": "desc", "limit": str(PAGE_SIZE), "start": str(max(0, int(start))), "details": "1"}
        text = self._page("POST", "index.php", params={"link": "list"}, data=data)
        items, rows = parse_list_page(text)
        return UsdbPage(items=items, has_more=rows >= PAGE_SIZE)

    def fetch_song(self, song_id: int) -> UsdbSong:
        sid = str(int(song_id))
        txt_page = self._page("POST", "index.php", params={"link": "gettxt", "id": sid}, data={"wd": "1"})
        txt = parse_gettxt(txt_page)
        if txt is None:
            raise UsdbNotFound()
        detail = self._page("GET", "index.php", params={"link": "detail", "id": sid})
        youtube, cover = parse_detail(detail)
        return UsdbSong(txt=txt.encode("utf-8"), youtube=youtube, cover_url=cover)

    # ------------------------------------------------------------------ внутреннее

    def _page(self, method: str, path: str, *, params: dict | None = None, data: dict | None = None) -> str:
        with self._lock:
            for attempt in (1, 2):
                if self._session is None:
                    self.login()
                text = self._text(self._session, method, BASE_URL + path, params=params, data=data)
                if NOT_LOGGED_IN in text:
                    self._session = None
                    if attempt == 2:
                        raise UsdbAuthError()
                    continue
                if DATASET_NOT_FOUND in text:
                    raise UsdbNotFound()
                return text
        raise UsdbAuthError()  # недостижимо

    @staticmethod
    def _text(session, method: str, url: str, **kw) -> str:
        try:
            resp = session.request(method, url, timeout=TIMEOUT, **kw)
        except HttpError:
            raise UsdbUnavailable() from None
        return resp.body.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- разбор HTML
# Сущности (``&lt;``, ``&amp;``) раскрываются в ячейке после снятия тегов — иначе название
# вида «Song <Live>» приняли бы за тег. Атрибуты строки ищутся по отдельности, в любом порядке.

_TR_RE = re.compile(r"<tr\b([^>]*)>(.*?)</tr>", re.S | re.I)
_SONGID_RE = re.compile(r"""\bdata-songid\s*=\s*["']?(\d+)""", re.I)
_LIST_CLASS_RE = re.compile(r"""\bclass\s*=\s*["']?list_tr\d""", re.I)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_TEXTAREA_RE = re.compile(r"<textarea[^>]*>(.*?)</textarea>", re.S | re.I)
_YT_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:[^\s\"'<>]*?&)?v=|embed/|v/|shorts/|live/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")


def _plain(cell: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub("", cell)).split())


def _rating(cell: str) -> float:
    text = _plain(cell).replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return cell.count("/star.png") + 0.5 * cell.count("/half_star.png")


def parse_list_page(text: str) -> tuple[list[UsdbHit], int]:
    """``(разобранные песни, число строк песен в таблице)``: строка без нужных ячеек
    пропускается, но в счёт страницы идёт (по нему решается, есть ли следующая)."""
    hits, rows = [], 0
    for m in _TR_RE.finditer(text):
        attrs = m.group(1)
        sid = _SONGID_RE.search(attrs)
        if not sid or not _LIST_CLASS_RE.search(attrs):
            continue
        rows += 1
        cells = _TD_RE.findall(m.group(2))
        if len(cells) < 12:
            continue
        views = re.sub(r"\D", "", _plain(cells[11]))
        hits.append(UsdbHit(id=int(sid.group(1)), artist=_plain(cells[2]), title=_plain(cells[3]),
                            language=_plain(cells[8]), rating=_rating(cells[10]),
                            views=int(views) if views else 0))
    return hits, rows


def parse_list(text: str) -> list[UsdbHit]:
    """Строки таблицы ``link=list`` (``details=1``): аудио, обложка, исполнитель, название, жанр,
    год, издание, золотые ноты, язык, автор, рейтинг, просмотры."""
    return parse_list_page(text)[0]


def parse_gettxt(text: str) -> str | None:
    m = _TEXTAREA_RE.search(text)
    return html.unescape(m.group(1)).replace("\r\n", "\n") if m else None


class _DetailParser(HTMLParser):
    """Таблицы ``<table border="0" width="500">``: первая — данные песни (обложка — первый img),
    вторая — комментарии (ссылки из ``a``/``iframe``/``embed`` и текст)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.index = -1        # номер текущей таблицы-цели
        self.depth = 0         # вложенность таблиц внутри цели
        self.cover: str | None = None
        self.comments: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            if self.depth:
                self.depth += 1
            elif a.get("border") == "0" and a.get("width") == "500":
                self.index += 1
                self.depth = 1
            return
        if not self.depth:
            return
        if self.index == 0 and tag == "img" and self.cover is None:
            self.cover = a.get("src") or ""
        elif self.index == 1:
            for key in ("href", "src"):
                if a.get(key):
                    self.comments.append(a[key])

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and self.index == 1:
            self.comments.append(data)


def parse_detail(text: str) -> tuple[list[str], str | None]:
    """``(ссылки YouTube из комментариев без дублей, URL обложки | None)``."""
    p = _DetailParser()
    p.feed(text)
    ids: list[str] = []
    for chunk in p.comments:
        for vid in _YT_RE.findall(chunk):
            if vid not in ids:
                ids.append(vid)
    cover = p.cover
    cover_url = urllib.parse.urljoin(BASE_URL, cover) if cover and "nocover" not in cover else None
    return [youtube_watch_url(v) for v in ids], cover_url
