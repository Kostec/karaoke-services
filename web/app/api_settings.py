"""Настройки: папка результата, usdb, Яндекс Музыка, уведомления Telegram. Пароли и токены API никогда не возвращает."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel

from karaoke_core import musiclink, telegram
from karaoke_core.db import OutputTarget, Target, TelegramSettings, UsdbAccount
from karaoke_core.storage import StorageError

from .api_jobs import ctx_of
from .api_usdb import usdb_api_error
from .context import ApiError, AppContext, link_api_error
from .usdb import UsdbClient, UsdbError


class OutputIn(BaseModel):
    kind: str = "smb"
    host: str = ""
    share: str = ""
    path: str = ""
    user: str = ""
    password: str | None = None  # пусто или нет поля — «не менять»


class UsdbIn(BaseModel):
    user: str = ""
    password: str | None = None  # пусто или нет поля — «не менять» (при том же логине)


class YandexIn(BaseModel):
    token: str = ""  # пусто: PUT — удалить, test — проверить сохранённый


router = APIRouter(prefix="/api/settings", tags=["Настройки"])


def _target(ctx: AppContext, body: OutputIn) -> OutputTarget:
    kind = body.kind.strip().lower()
    if kind not in ("smb", "local"):
        raise ApiError(400, "Тип папки результата: smb или local", field="kind")
    path = body.path.strip().replace("\\", "/").strip("/")
    if any(part in ("..", ".") for part in path.split("/")) or ":" in path:
        raise ApiError(400, "Недопустимый путь", field="path")
    fields = {"kind": kind, "path": path, "host": body.host.strip(), "share": body.share.strip().strip("/"),
              "user": body.user.strip()}
    if kind == "smb" and (not fields["host"] or not fields["share"]):
        raise ApiError(400, "Укажите адрес сервера и имя шары",
                       field="host" if not fields["host"] else "share")
    # Пустой пароль = «не менять» — только для той же учётки на том же сервере;
    # иначе прежний пароль ушёл бы на чужой хост.
    current = ctx.settings.get_output()
    same = (current.kind, current.host, current.share, current.user) ==         (kind, fields["host"], fields["share"], fields["user"])
    if body.password:
        fields["password"] = body.password
    elif kind == "smb" and same:
        fields["password"] = current.password
    elif kind == "smb" and fields["user"]:
        raise ApiError(400, "Введите пароль: сервер, шара или логин изменились", field="password")
    else:
        fields["password"] = ""  # гостевой доступ или локальная папка
    return OutputTarget(**fields)


def _as_target(target: OutputTarget) -> Target:
    """Прежняя «папка результата» как хранилище — только для проверки доступа."""
    if target.kind == "local":
        t = Target(id="probe", name="Папка ПК", kind="local", path=target.local_root)
    else:
        t = Target(id="probe", name="SMB", kind="smb", host=target.host, share=target.share,
                   path=target.path, user=target.user)
    t.secret = target.password
    return t


def _probe(ctx: AppContext, target: OutputTarget) -> None:
    try:
        storage = ctx.storage_factory(_as_target(target))
    except StorageError as e:
        raise ApiError(400, f"Папка результата недоступна: {e}") from None
    try:
        storage.probe()
    except StorageError as e:
        raise ApiError(400, f"Папка результата недоступна: {e}") from None
    finally:
        try:
            storage.close()
        except Exception:
            pass


def _public(ctx: AppContext, target: OutputTarget) -> dict:
    return {**target.public(), "local_root_host": ctx.env.get("LOCAL_OUTPUT_ROOT", "")}


@router.get("/output", summary="Текущая папка результата (без пароля)")
def get_output(request: Request):
    ctx = ctx_of(request)
    return _public(ctx, ctx.settings.get_output())


@router.put("/output", summary="Сохранить папку результата (только проверенную)")
def put_output(body: OutputIn, request: Request, background: BackgroundTasks):
    ctx = ctx_of(request)
    target = _target(ctx, body)
    _probe(ctx, target)
    saved = ctx.settings.set_output(target)
    ctx.reset_storage()
    background.add_task(ctx.rescan)
    return _public(ctx, saved)


@router.post("/output/test", summary="Проверить цель: записать и удалить пробный файл")
def test_output(body: OutputIn, request: Request):
    ctx = ctx_of(request)
    target = _target(ctx, body)
    _probe(ctx, target)
    return {"ok": True, "label": target.label}


# ---------------------------------------------------------------------- usdb


def _usdb_account(ctx: AppContext, body: UsdbIn) -> UsdbAccount:
    user = body.user.strip()
    if not user:
        raise ApiError(400, "Впишите логин usdb", field="user")
    if body.password:
        return UsdbAccount(user, body.password)
    current = ctx.settings.get_usdb()
    # тот же логин — прежний пароль
    if current.user == user and current.password:
        return UsdbAccount(user, current.password)
    raise ApiError(400, "Введите пароль usdb", field="password")


def _usdb_login(ctx: AppContext, account: UsdbAccount) -> None:
    try:
        UsdbClient(ctx.http, account.user, account.password or "").login()
    except UsdbError as e:
        raise usdb_api_error(e) from None


@router.get("/usdb", summary="Учётка usdb (без пароля)")
def get_usdb(request: Request):
    return ctx_of(request).settings.get_usdb().public()


@router.put("/usdb", summary="Сохранить учётку usdb (только принятую usdb); пустой логин — удалить")
def put_usdb(body: UsdbIn, request: Request):
    ctx = ctx_of(request)
    if not body.user.strip() and not body.password:
        saved = ctx.settings.set_usdb(UsdbAccount("", ""))
    else:
        account = _usdb_account(ctx, body)
        _usdb_login(ctx, account)
        saved = ctx.settings.set_usdb(account)
    ctx.reset_usdb()
    return saved.public()


@router.post("/usdb/test", summary="Проверить вход в usdb (не сохраняет)")
def test_usdb(body: UsdbIn, request: Request):
    ctx = ctx_of(request)
    _usdb_login(ctx, _usdb_account(ctx, body))
    return {"ok": True}


# ---------------------------------------------------------------------- Яндекс Музыка


def _yandex_check(ctx: AppContext, ym_key: str) -> None:
    """Проверить токен Яндекс Музыки; неверный — 400 ``field=token``, сеть — 503."""
    try:
        ctx.yandex_factory(ym_key).check()
    except musiclink.MusicLinkError as e:
        err = link_api_error(e, field="token")
        if err.status == 400:
            err.extra = {"field": "token"}
        raise err from None


def _yandex_public(ctx: AppContext) -> dict:
    return {"has_token": bool(ctx.settings.get_yandex())}


@router.get("/yandex", summary="Яндекс Музыка: есть ли токен (сам токен не возвращается)")
def get_yandex(request: Request):
    return _yandex_public(ctx_of(request))


@router.put("/yandex", summary="Сохранить токен Яндекс Музыки (только принятый); пустой — удалить")
def put_yandex(body: YandexIn, request: Request):
    ctx = ctx_of(request)
    ym_key = body.token.strip()
    if ym_key:
        _yandex_check(ctx, ym_key)
    ctx.settings.set_yandex(ym_key or None)
    return _yandex_public(ctx)


@router.post("/yandex/test", summary="Проверить токен Яндекс Музыки (не сохраняет); пустой — сохранённый")
def test_yandex(body: YandexIn, request: Request):
    ctx = ctx_of(request)
    ym_key = body.token.strip() or ctx.settings.get_yandex()
    if not ym_key:
        raise ApiError(400, musiclink.MSG_NEED_LOGIN, field="token")
    _yandex_check(ctx, ym_key)
    return {"ok": True}


# ---------------------------------------------------------------------- Telegram (уведомления)


class TelegramIn(BaseModel):
    bot_token: str | None = None  # пусто или нет поля — прежний (API его никогда не отдаёт)
    chat_id: str = ""
    on_done: bool = True
    on_failed: bool = True
    on_queue_empty: bool = False


class TelegramProbeIn(BaseModel):
    bot_token: str | None = None  # пусто — сохранённый
    chat_id: str = ""             # пусто — сохранённый (только для проверки)


TELEGRAM_TEST_TEXT = "🔔 Проверка: уведомления karaoke-services приходят сюда"
TELEGRAM_NO_CHAT = "Напишите боту любое сообщение и повторите"


def _telegram_key(ctx: AppContext, typed: str | None) -> str:
    """Токен из формы или сохранённый; формат проверяется до запроса (токен стоит в адресе)."""
    bot_key = (typed or "").strip() or ctx.settings.get_telegram().bot_token
    if not bot_key:
        raise ApiError(400, "Введите токен бота", field="bot_token")
    if not telegram.valid_key(bot_key):
        raise ApiError(400, telegram.MSG_KEY_FORMAT, field="bot_token")
    return bot_key


def _telegram_api_error(e: telegram.TelegramError) -> ApiError:
    if e.network:
        return ApiError(503, str(e))
    return ApiError(400, str(e), **({"field": e.field} if e.field else {}))


@router.get("/telegram", summary="Уведомления Telegram (токен не возвращается — только has_token)")
def get_telegram(request: Request):
    return ctx_of(request).settings.get_telegram().public()


@router.put("/telegram", summary="Сохранить уведомления Telegram; пустой токен — прежний")
def put_telegram(body: TelegramIn, request: Request):
    ctx = ctx_of(request)
    typed = (body.bot_token or "").strip()
    if typed and not telegram.valid_key(typed):
        raise ApiError(400, telegram.MSG_KEY_FORMAT, field="bot_token")
    chat_id = body.chat_id.strip()
    if chat_id and not telegram.valid_chat_id(chat_id):
        raise ApiError(400, telegram.MSG_CHAT_FORMAT, field="chat_id")
    saved = ctx.settings.set_telegram(TelegramSettings(
        typed or None, chat_id, body.on_done, body.on_failed, body.on_queue_empty))
    return saved.public()


@router.post("/telegram/test", summary="Отправить тестовое сообщение (не сохраняет); пустые поля — сохранённые")
def test_telegram(body: TelegramProbeIn, request: Request):
    ctx = ctx_of(request)
    bot_key = _telegram_key(ctx, body.bot_token)
    chat_id = body.chat_id.strip() or ctx.settings.get_telegram().chat_id
    if not chat_id:
        raise ApiError(400, "Впишите chat id или нажмите «Найти чат»", field="chat_id")
    try:
        telegram.send_message(ctx.http, bot_key, chat_id, TELEGRAM_TEST_TEXT)
    except telegram.TelegramError as e:
        raise _telegram_api_error(e) from None
    return {"ok": True}


@router.post("/telegram/find-chat", summary="Chat id последнего, кто писал боту (getUpdates)")
def find_telegram_chat(body: TelegramProbeIn, request: Request):
    ctx = ctx_of(request)
    bot_key = _telegram_key(ctx, body.bot_token)
    try:
        chat_id = telegram.find_chat(ctx.http, bot_key)
    except telegram.TelegramError as e:
        raise _telegram_api_error(e) from None
    if not chat_id:
        raise ApiError(404, TELEGRAM_NO_CHAT)
    return {"chat_id": chat_id}
