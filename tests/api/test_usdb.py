"""usdb: клиент UsdbClient по HTML-фикстурам (разметка — как разбирает usdb_syncer) и REST поверх него.

Сеть не трогаем: FakeHttp. Фикстуры — tests/api/usdb_fixtures/.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes_http import FakeHttp, response

from app.usdb import UsdbAuthError, UsdbClient, UsdbNotFound, UsdbUnavailable
from karaoke_core.http import HttpError

FIX = Path(__file__).resolve().parent / "usdb_fixtures"
BASE = "https://usdb.animux.de/"
LIST = BASE + "index.php?link=list"
GETTXT = BASE + "index.php?link=gettxt"
DETAIL = BASE + "index.php?link=detail"
PW = "usdb-pw-for-test"


def page(name: str):
    return response(200, (FIX / name).read_bytes(), headers={"content-type": "text/html; charset=utf-8"})


@pytest.fixture
def http() -> FakeHttp:
    return FakeHttp().route("POST", BASE, page("login_ok.html"))


def logins(http: FakeHttp):
    return [r for r in http.requests if r.method == "POST" and r.url == BASE]


# ------------------------------------------------------------------ клиент


def test_login_posts_form_and_rejects_bad_password(http):
    UsdbClient(http, "karaoke", PW).login()
    (req,) = logins(http)
    assert req.data == {"user": "karaoke", "pass": PW, "login": "Login"}
    assert req.session > 0  # вход — в своей cookie-сессии

    bad = FakeHttp().route("POST", BASE, page("login_invalid.html"))
    with pytest.raises(UsdbAuthError) as e:
        UsdbClient(bad, "karaoke", PW).login()
    assert PW not in str(e.value)


def test_login_network_error_is_unavailable():
    down = FakeHttp().route("POST", BASE, HttpError("Нет связи с сервером usdb.animux.de"))
    with pytest.raises(UsdbUnavailable):
        UsdbClient(down, "karaoke", PW).login()


def test_search_request_and_parsed_rows(http):
    http.route("POST", LIST, page("list.html"))
    client = UsdbClient(http, "karaoke", PW)
    result = client.search("Кино", "Звезда", "Russian", 0)

    (req,) = http.calls(LIST)
    assert req.query == {"link": "list"}
    assert req.data == {"interpret": "Кино", "title": "Звезда", "language": "Russian", "order": "rating",
                        "ud": "desc", "limit": "50", "start": "0", "details": "1"}
    assert len(logins(http)) == 1 and req.session == logins(http)[0].session

    assert [(h.id, h.artist, h.title, h.language, h.rating, h.views) for h in result.items] == [
        (10101, "Кино", "Звезда по имени Солнце", "Russian", 4.5, 1234),
        (20202, "Ария & Кипелов", "Я свободен", "Russian", 3.0, 87),
    ]
    assert result.has_more is False

    client.search("", "", "", 50)  # второй запрос — без повторного входа
    assert len(logins(http)) == 1 and http.calls(LIST)[-1].data["start"] == "50"


def test_search_has_more_when_page_is_full(http):
    rows = (FIX / "list.html").read_text("utf-8")
    head, rest = rows.split('<tr class="list_tr1"', 1)
    row, tail = rest.split("</tr>", 1)
    # 49 копий первой строки + вторая строка из хвоста фикстуры = ровно 50
    full = head + "".join(f'<tr class="list_tr1"{row.replace("10101", str(i))}</tr>\n' for i in range(49)) + tail
    http.route("POST", LIST, response(200, full))
    result = UsdbClient(http, "karaoke", PW).search("", "", "Russian", 0)
    assert len(result.items) == 50 and result.has_more is True


def test_relogin_once_when_session_expired(http):
    answers = [page("not_logged_in.html"), page("list.html")]
    http.route("POST", LIST, lambda req: answers.pop(0))
    result = UsdbClient(http, "karaoke", PW).search("Кино", "", "Russian", 0)
    assert len(result.items) == 2 and len(logins(http)) == 2 and len(http.calls(LIST)) == 2


def test_second_not_logged_in_is_auth_error(http):
    http.route("POST", LIST, page("not_logged_in.html"))
    with pytest.raises(UsdbAuthError):
        UsdbClient(http, "karaoke", PW).search("Кино", "", "Russian", 0)
    assert len(logins(http)) == 2 and len(http.calls(LIST)) == 2


def test_fetch_song_txt_youtube_and_cover(http):
    http.route("POST", GETTXT, page("gettxt.html")).route("GET", DETAIL, page("detail.html"))
    song = UsdbClient(http, "karaoke", PW).fetch_song(10101)

    (txt_req,) = http.calls(GETTXT)
    assert txt_req.query == {"link": "gettxt", "id": "10101"} and txt_req.data == {"wd": "1"}
    assert http.calls(DETAIL)[0].query == {"link": "detail", "id": "10101"}

    text = song.txt.decode("utf-8")
    assert text.startswith("#TITLE:Звезда по имени Солнце\n#ARTIST:Кино\n")
    assert ": 12 4 7 снег & <лёд>\nE" in text
    # только из комментариев, без дублей, в порядке появления; vimeo и ссылки вне комментариев — нет
    assert song.youtube == ["https://www.youtube.com/watch?v=AbCdEfGhIj0",
                            "https://www.youtube.com/watch?v=ZyXwVuTsRq9",
                            "https://www.youtube.com/watch?v=Qq_-1234567"]
    assert song.cover_url == "https://usdb.animux.de/data/cover/10101.jpg"


def test_fetch_song_without_cover_and_comments(http):
    http.route("POST", GETTXT, page("gettxt.html")).route("GET", DETAIL, page("detail_nocover.html"))
    song = UsdbClient(http, "karaoke", PW).fetch_song(20202)
    assert song.youtube == [] and song.cover_url is None


def test_fetch_missing_song_is_not_found(http):
    http.route("POST", GETTXT, page("not_found.html"))
    with pytest.raises(UsdbNotFound) as e:
        UsdbClient(http, "karaoke", PW).fetch_song(999)
    assert str(e.value) == "Песня в usdb не найдена"


# ------------------------------------------------------------------ REST


@pytest.fixture
def uc(env, http):
    with env.client(http=http) as c:
        yield c


def save_account(client, user="karaoke", pw=PW):
    return client.put("/api/settings/usdb", json={"user": user, "password": pw})


def test_settings_usdb_never_returns_password(uc, http):
    assert uc.get("/api/settings/usdb").json() == {"user": "", "has_password": False}
    r = save_account(uc)
    assert r.status_code == 200 and PW not in r.text
    assert r.json() == {"user": "karaoke", "has_password": True}
    r = uc.get("/api/settings/usdb")
    assert r.json() == {"user": "karaoke", "has_password": True} and PW not in r.text
    assert logins(http)[-1].data["pass"] == PW  # сохраняется только проверенная учётка


def test_settings_usdb_empty_password_keeps_previous_for_same_user(uc, http):
    save_account(uc)
    r = uc.put("/api/settings/usdb", json={"user": "karaoke", "password": ""})
    assert r.status_code == 200 and r.json()["has_password"] is True
    assert logins(http)[-1].data["pass"] == PW
    # другой логин — прежний пароль туда не уходит
    n = len(logins(http))
    r = uc.put("/api/settings/usdb", json={"user": "other"})
    assert r.status_code == 400 and r.json()["field"] == "password" and len(logins(http)) == n
    assert uc.get("/api/settings/usdb").json()["user"] == "karaoke"


def test_put_usdb_without_password_stores_previous_password(uc, http):
    save_account(uc)
    assert uc.put("/api/settings/usdb", json={"user": "karaoke"}).status_code == 200
    assert uc.get("/api/settings/usdb").json() == {"user": "karaoke", "has_password": True}
    http.route("POST", LIST, page("list.html"))
    n = len(logins(http))
    assert uc.get("/api/usdb/search", params={"title": "x"}).status_code == 200
    # клиент поиска входит с сохранённым паролем — значит, PUT сохранил прежний
    assert len(logins(http)) == n + 1 and logins(http)[-1].data["pass"] == PW


def test_settings_usdb_test_endpoint(uc, http):
    r = uc.post("/api/settings/usdb/test", json={"user": "karaoke", "password": PW})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert uc.get("/api/settings/usdb").json()["user"] == ""  # «Проверить» не сохраняет

    http.route("POST", BASE, page("login_invalid.html"))
    for call in (lambda: uc.post("/api/settings/usdb/test", json={"user": "karaoke", "password": "bad"}),
                 lambda: save_account(uc, pw="bad")):
        r = call()
        assert r.status_code == 400 and r.json() == {"detail": "usdb не принял логин или пароль",
                                                     "field": "password"}
    assert uc.get("/api/settings/usdb").json()["user"] == ""

    http.route("POST", BASE, HttpError("Нет связи с сервером usdb.animux.de"))
    r = uc.post("/api/settings/usdb/test", json={"user": "karaoke", "password": PW})
    assert r.status_code == 503 and r.json()["detail"] == "usdb недоступен, попробуйте позже"


def test_search_without_account(uc, http):
    r = uc.get("/api/usdb/search", params={"artist": "Кино"})
    assert r.status_code == 400
    assert r.json() == {"detail": "Впишите логин и пароль usdb в Настройках", "code": "usdb_no_account"}
    assert http.requests == []


def test_search_items_and_existing_song(env, uc, http):
    save_account(uc)
    env.put_song("Кино/Кино - Звезда по имени Солнце", "#TITLE:Звезда по имени Солнце\n#ARTIST:Кино\n"
                 "#MP3:Кино - Звезда по имени Солнце.mp3\n#BPM:300\n#GAP:0\n: 0 4 5 Бе\nE\n".encode("utf-8"),
                 "Кино - Звезда по имени Солнце")
    assert uc.post("/api/songs/rescan").status_code == 202
    song_id = next(i["song_id"] for i in uc.get("/api/songs").json()["items"] if i["artist"] == "Кино")
    http.route("POST", LIST, page("list.html"))

    r = uc.get("/api/usdb/search", params={"artist": "Кино", "title": "Звезда"})
    assert r.status_code == 200, r.text
    assert http.calls(LIST)[-1].data["language"] == "Russian"  # по умолчанию — русский
    assert r.json() == {"has_more": False, "items": [
        {"id": 10101, "artist": "Кино", "title": "Звезда по имени Солнце", "language": "Russian",
         "rating": 4.5, "views": 1234, "existing_song_id": song_id},
        {"id": 20202, "artist": "Ария & Кипелов", "title": "Я свободен", "language": "Russian",
         "rating": 3.0, "views": 87, "existing_song_id": None}]}

    uc.get("/api/usdb/search", params={"language": "", "start": 50})
    assert http.calls(LIST)[-1].data["language"] == "" and http.calls(LIST)[-1].data["start"] == "50"
    assert len(logins(http)) == 2  # один вход при сохранении, один — сессия клиента поиска


def test_search_errors(uc, http):
    save_account(uc)
    http.route("POST", LIST, HttpError("Сервер usdb.animux.de не ответил вовремя"))
    r = uc.get("/api/usdb/search", params={"artist": "Кино"})
    assert r.status_code == 503 and r.json()["detail"] == "usdb недоступен, попробуйте позже"

    http.route("POST", LIST, page("not_logged_in.html"))
    r = uc.get("/api/usdb/search", params={"artist": "Кино"})
    assert r.status_code == 400 and r.json()["detail"] == "usdb не принял логин или пароль"
    assert PW not in r.text


def test_account_change_resets_client_session(uc, http):
    save_account(uc)
    http.route("POST", LIST, page("list.html"))
    uc.get("/api/usdb/search")
    uc.get("/api/usdb/search")
    session = http.calls(LIST)[-1].session
    save_account(uc, user="second", pw="pw-2")
    uc.get("/api/usdb/search")
    last = logins(http)[-1]
    assert last.data["user"] == "second" and http.calls(LIST)[-1].session not in (0, session)


# ------------------------------------------------------------------ надёжность разбора


def test_login_without_confirmation_warns_and_next_not_logged_in_is_auth_error(caplog):
    other = FakeHttp().route("POST", BASE, response(200, "<html><body>Wartungsarbeiten</body></html>"))
    client = UsdbClient(other, "karaoke", PW)
    with caplog.at_level("WARNING"):
        client.login()
    assert "вход не подтверждён признаком" in caplog.text and PW not in caplog.text
    assert "Wartungsarbeiten" not in caplog.text
    other.route("POST", LIST, page("not_logged_in.html"))
    with pytest.raises(UsdbAuthError):
        client.search("", "", "Russian", 0)
    assert len(logins(other)) == 2 and len(other.calls(LIST)) == 2


def _row(song_id: int, title: str, *, cells: int = 12, attrs: str | None = None) -> str:
    tds = ["", "", "Кино", title, "Rock", "1989", "", "Yes", "Russian", "vasya", "4,5", "10"][:cells]
    attrs = attrs or f'class="list_tr1" data-songid="{song_id}"'
    return f"<tr {attrs}>" + "".join(f"<td onclick=\"x\">{t}</td>" for t in tds) + "</tr>\n"


def test_has_more_counts_table_rows_not_parsed(http):
    body = "<table>" + "".join(_row(i, f"T{i}") for i in range(1, 50)) + _row(99, "broken", cells=3) + "</table>"
    http.route("POST", LIST, response(200, body))
    result = UsdbClient(http, "karaoke", PW).search("", "", "Russian", 0)
    assert len(result.items) == 49 and result.has_more is True


def test_entities_are_unescaped_per_cell_and_attribute_order_does_not_matter(http):
    body = ("<table>" + _row(1, "Song &lt;Live&gt; &amp; more")
            + _row(2, "Второй", attrs='data-songid="2" onmouseover="x" class="list_tr2"') + "</table>")
    http.route("POST", LIST, response(200, body))
    items = UsdbClient(http, "karaoke", PW).search("", "", "", 0).items
    assert [(h.id, h.title) for h in items] == [(1, "Song <Live> & more"), (2, "Второй")]
