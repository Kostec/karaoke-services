"""Хранилища песен («Настройки → Куда выкладывать»): список, добавление любого типа с проверкой,
правка, удаление, основная цель, обзор папок ПК и вход в Google Диск (OAuth).

Секреты (пароли, Client secret) и токены API никогда не возвращает: только ``has_password`` и
``connected``. Пустой пароль при правке — «не менять», но только при том же адресе и логине."""

from __future__ import annotations

import html
import re
import secrets
import threading
import time
import urllib.parse
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from karaoke_core.db import (LOCAL_OUTPUT_MOUNT, LOCAL_TARGET_ID, NO_DEFAULT_DELETE, NO_LOCAL_DELETE,
                             TARGET_NOT_FOUND, Target,
                             default_target_name)
from karaoke_core.http import HttpError
from karaoke_core.storage import StorageError

from .api_jobs import ctx_of
from .context import ApiError, AppContext

# Корни обзора «Папки ПК»: в Target.path корень ``<имя>`` — это ``/<имя>`` в контейнере;
# здесь — где он реально лежит (тесты подменяют на временные папки).
BROWSE_ROOTS = {"host": "/host", "output": "/output"}
ROOT_NAMES = {"host": "Папки ПК", "output": "Локальное хранилище"}
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", "lost+found"}

YANDEX_DAV_URL = "https://webdav.yandex.ru"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive"
DRAFT_TTL = 600.0  # с: сколько живёт черновик Google Диска в памяти веба
GOOGLE_DENIED = "Google не дал доступ"
GOOGLE_RETRY = "Google не дал доступ, попробуйте ещё раз"
DRAFT_GONE = "Вход в Google устарел — нажмите «Войти через Google» ещё раз"


class TargetIn(BaseModel):
    id: str = ""  # для /test: подставить сохранённый пароль этого хранилища
    name: str = ""
    kind: str = "smb"  # local | smb | webdav | yandex | gdrive
    path: str = ""
    host: str = ""
    share: str = ""
    user: str = ""
    url: str = ""
    preset: str = ""
    client_id: str = ""
    password: str | None = None  # пароль SMB/WebDAV или Client secret Google; пусто — «не менять»


class DefaultIn(BaseModel):
    id: str


router = APIRouter(prefix="/api/targets", tags=["Хранилища"])


# ---------------------------------------------------------------------- сборка и проверка


def _path_parts(raw: str, error: str = "Недопустимый путь") -> list[str]:
    """Части пути из формы/запроса (``\\`` → ``/``); ``..``, ``.`` или двоеточие —
    400 ``field=path`` с текстом ``error``."""
    path = raw.strip().replace("\\", "/")
    parts = [p for p in path.split("/") if p]
    if any(p in ("..", ".") for p in parts) or ":" in path:
        raise ApiError(400, error, field="path")
    return parts


def _rel_path(raw: str) -> str:
    """Папка внутри шары/диска: без ``..``, ``.`` и двоеточий."""
    return "/".join(_path_parts(raw))


LOCAL_PATH_ERROR = "Выберите папку внутри «Папок ПК» или «Локального хранилища»"


def _local_path(raw: str) -> str:
    """Путь «Папки ПК» в контейнере: внутри ``/host`` или ``/output``."""
    parts = _path_parts(raw, LOCAL_PATH_ERROR)
    if not parts or parts[0] not in BROWSE_ROOTS:
        raise ApiError(400, LOCAL_PATH_ERROR, field="path")
    return "/" + "/".join(parts)


def _identity(t: Target) -> tuple:
    """Адрес и логин: при их смене прежний секрет не подставляется."""
    if t.kind == "gdrive":
        return (t.kind, t.client_id)
    return (t.kind, t.host, t.share, t.user, t.url.rstrip("/"))


def _build(body: TargetIn, old: Target | None) -> Target:
    """Хранилище из полей формы; ``old`` — сохранённое (правка/проверка/повторный вход)."""
    kind = body.kind.strip().lower()
    preset = body.preset.strip().lower()
    if kind == "yandex":
        kind, preset = "webdav", "yandex"
    if kind not in ("local", "smb", "webdav", "gdrive"):
        raise ApiError(400, "Тип хранилища: Папка ПК, SMB, Яндекс Диск, WebDAV или Google Диск", field="kind")
    t = Target(id=old.id if old else "", kind=kind, user=body.user.strip())
    if kind == "local":
        t.path, t.user = _local_path(body.path), ""
        if t.path == LOCAL_OUTPUT_MOUNT:
            raise ApiError(400, "Это и есть «Локальное хранилище»", field="path")
    else:
        t.path = _rel_path(body.path)
    if kind == "smb":
        t.host, t.share = body.host.strip(), body.share.strip().strip("/")
        if not t.host or not t.share:
            raise ApiError(400, "Укажите адрес сервера и имя шары", field="host" if not t.host else "share")
    elif kind == "webdav":
        t.preset = "yandex" if preset == "yandex" else ""
        t.url = YANDEX_DAV_URL if t.preset else body.url.strip().rstrip("/")
        if urllib.parse.urlsplit(t.url).scheme not in ("http", "https") or \
                not urllib.parse.urlsplit(t.url).hostname:
            raise ApiError(400, "Адрес WebDAV должен начинаться с http:// или https://", field="url")
        if t.preset and not t.user:
            raise ApiError(400, "Впишите логин Яндекса", field="user")
    elif kind == "gdrive":
        t.client_id, t.user = body.client_id.strip(), ""
        if not t.client_id:
            raise ApiError(400, "Впишите Client ID", field="client_id")
    t.name = body.name.strip() or (old.name if old else "") or default_target_name(t)

    same = old is not None and _identity(old) == _identity(t)
    values = t._to_dict()
    if body.password:
        values["secret"] = body.password
    elif same:
        values["secret"] = old.secret
    elif kind == "gdrive":
        raise ApiError(400, "Впишите Client secret", field="password")
    elif kind in ("smb", "webdav") and t.user:
        raise ApiError(400, "Введите пароль: адрес или логин изменились" if old else "Введите пароль",
                       field="password")
    else:
        values["secret"] = ""  # гостевой доступ или папка ПК
    values["token"] = old.token if same and kind == "gdrive" else None
    return Target(**values)


def _probe(ctx: AppContext, target: Target) -> None:
    """Записать и удалить пробный файл; сбой — 400 по-русски."""
    probe = Target(**{**target._to_dict(), "id": target.id or "probe"})
    storage = None
    try:
        storage = ctx.storage_factory(probe)
        storage.probe()
    except StorageError as e:
        raise ApiError(400, f"Хранилище недоступно: {e}") from None
    finally:
        if storage is not None:
            try:
                storage.close()
            except Exception:  # noqa: BLE001
                pass


def _get(ctx: AppContext, target_id: str) -> Target:
    target = ctx.settings.get_target(target_id)
    if target is None:
        raise ApiError(404, TARGET_NOT_FOUND)
    return target


def _after_change(ctx: AppContext, target_id: str, background: BackgroundTasks) -> None:
    ctx.reset_storage(target_id)
    if ctx.settings.get_default_target_id() == target_id:
        background.add_task(ctx.rescan)


def _listing(ctx: AppContext) -> dict:
    settings = ctx.settings
    return {"targets": [t.public() for t in settings.get_targets()],
            "default_id": settings.get_default_target_id(),
            "roots": {"host": Path(BROWSE_ROOTS["host"]).is_dir(), "output": True}}


# ---------------------------------------------------------------------- список и правка


@router.get("", summary="Хранилища (без паролей и токенов), основная цель, доступные корни папок ПК")
def list_targets(request: Request):
    return _listing(ctx_of(request))


@router.post("", summary="Добавить хранилище (сохраняется только прошедшее проверку)")
def create_target(body: TargetIn, request: Request):
    ctx = ctx_of(request)
    if body.kind.strip().lower() == "gdrive":
        raise ApiError(400, "Google Диск подключается кнопкой «Войти через Google»", field="kind")
    target = _build(body, None)
    _probe(ctx, target)
    return ctx.settings.save_target(target).public()


@router.post("/test", summary="Проверить хранилище, не сохраняя (с id — подставить сохранённый пароль)")
def test_target(body: TargetIn, request: Request):
    ctx = ctx_of(request)
    old = ctx.settings.get_target(body.id) if body.id and body.id != LOCAL_TARGET_ID else None
    if body.id == LOCAL_TARGET_ID:
        target = ctx.settings.get_target(LOCAL_TARGET_ID)
    else:
        target = _build(body, old)
    _probe(ctx, target)
    return {"ok": True, "label": target.label}


@router.put("/default", summary="Сделать хранилище основной целью (сами хранилища не меняются)")
def set_default(body: DefaultIn, request: Request, background: BackgroundTasks):
    ctx = ctx_of(request)
    _get(ctx, body.id)
    ctx.settings.set_default_target_id(body.id)
    background.add_task(ctx.rescan)
    return _listing(ctx)


@router.put("/{target_id}", summary="Изменить хранилище (пустой пароль — прежний при том же адресе и логине)")
def update_target(target_id: str, body: TargetIn, request: Request, background: BackgroundTasks):
    ctx = ctx_of(request)
    if target_id == LOCAL_TARGET_ID:
        raise ApiError(400, "Локальное хранилище не меняется")
    old = _get(ctx, target_id)
    target = _build(body, old)
    if target.kind == "gdrive" and not target.token:
        raise ApiError(400, "Client ID изменился — войдите через Google ещё раз", field="client_id")
    _probe(ctx, target)
    saved = ctx.settings.save_target(target)
    _after_change(ctx, target_id, background)
    return saved.public()


@router.delete("/{target_id}", summary="Удалить хранилище из настроек (песни в нём не трогаются)")
def delete_target(target_id: str, request: Request):
    ctx = ctx_of(request)
    try:
        ctx.settings.delete_target(target_id)  # правило удаления — только там
    except ValueError as e:
        status = {NO_LOCAL_DELETE: 400, TARGET_NOT_FOUND: 404, NO_DEFAULT_DELETE: 409}.get(str(e), 409)
        raise ApiError(status, str(e)) from None
    ctx.reset_storage(target_id)
    return {"ok": True}


# ---------------------------------------------------------------------- обзор папок ПК


@router.get("/{target_id}/status", summary="Доступность хранилища: {ok, error, label} (fresh=1 — без кэша)")
def target_status(target_id: str, request: Request, fresh: int = 0):
    ctx = ctx_of(request)
    _get(ctx, target_id)
    st = ctx.output_status(fresh=bool(fresh), target_id=target_id)
    return {"ok": bool(st["ok"]), "error": st.get("error"), "label": st.get("label") or ""}


@router.get("/browse", summary="Подпапки внутри корня «Папки ПК» (/host) или «Локальное хранилище» (/output)")
def browse(request: Request, root: str = "host", path: str = ""):
    if root not in BROWSE_ROOTS:
        raise ApiError(400, "Корень: host или output", field="root")
    parts = _path_parts(path)
    base = Path(BROWSE_ROOTS[root])
    if not base.is_dir():
        raise ApiError(404, f"Корень «{ROOT_NAMES[root]}» не примонтирован")
    folder = base.joinpath(*parts)
    try:
        resolved, top = folder.resolve(), base.resolve()
        resolved.relative_to(top)  # симлинк наружу — тоже выход за корень
    except (OSError, ValueError):
        raise ApiError(400, "Недопустимый путь", field="path") from None
    if not folder.is_dir():
        raise ApiError(404, "Папка не найдена")
    dirs = []
    try:
        for child in folder.iterdir():
            if child.name.startswith((".", "$")) or child.name in SKIP_DIRS:
                continue
            try:
                if child.is_dir() and child.resolve().is_relative_to(top):
                    dirs.append(child.name)
            except OSError:
                continue
    except OSError as e:
        raise ApiError(400, f"Папку не прочитать: {e.strerror or e}") from None
    rel = "/".join(parts)
    return {"root": root, "root_name": ROOT_NAMES[root], "path": rel,
            "abs": str(PurePosixPath("/", root, *parts)),
            "parent": "/".join(parts[:-1]) if parts else None,
            "dirs": sorted(dirs, key=str.casefold)}


# ---------------------------------------------------------------------- Google Диск


def _drafts(request: Request) -> tuple[dict, threading.Lock]:
    state = request.app.state
    if not hasattr(state, "gdrive_drafts"):
        state.gdrive_drafts, state.gdrive_lock = {}, threading.Lock()
    return state.gdrive_drafts, state.gdrive_lock


def _draft(request: Request, draft_id: str) -> dict | None:
    drafts, lock = _drafts(request)
    with lock:
        now = time.monotonic()
        for key in [k for k, d in drafts.items() if now - d["created"] > DRAFT_TTL]:
            drafts.pop(key, None)
        return drafts.get(draft_id)


def _page(title: str, text: str, status: int = 200) -> HTMLResponse:
    body = (f"<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title>"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head>"
            "<body style=\"font-family:system-ui,sans-serif;max-width:36em;margin:3em auto;padding:0 16px\">"
            f"<h2>{html.escape(title)}</h2><p>{html.escape(text)}</p></body></html>")
    return HTMLResponse(body, status_code=status)


def _exchange_code(ctx: AppContext, target: Target, code: str, redirect_uri: str) -> str:
    """Код авторизации → токены Google (JSON для ``Target.token``)."""
    from karaoke_core.storage.gdrive import GDriveStorage  # таск 02; лениво — модуль может не загрузиться

    return GDriveStorage.exchange_code(ctx.http, target.client_id, target.secret or "", code, redirect_uri)


@router.post("/gdrive/draft", summary="Черновик Google Диска из полей формы (живёт 10 минут) → {draft}")
def gdrive_draft(body: TargetIn, request: Request):
    ctx = ctx_of(request)
    old = ctx.settings.get_target(body.id) if body.id else None
    if old is not None and old.kind != "gdrive":
        old = None
    target = _build(TargetIn(**{**body.model_dump(), "kind": "gdrive"}), old)
    draft_id = secrets.token_urlsafe(16)
    drafts, lock = _drafts(request)
    with lock:
        drafts[draft_id] = {"target": target, "created": time.monotonic(), "state": "pending",
                            "error": None, "saved": None, "redirect_uri": ""}
    return {"draft": draft_id}


@router.get("/gdrive/auth", summary="Переход на страницу входа Google (новая вкладка)")
def gdrive_auth(request: Request, draft: str = ""):
    d = _draft(request, draft)
    if d is None:
        return _page("Google Диск не подключён", DRAFT_GONE, 404)
    redirect_uri = f"{request.url.scheme}://{request.url.netloc}/api/targets/gdrive/callback"
    d["redirect_uri"] = redirect_uri
    query = urllib.parse.urlencode({
        "client_id": d["target"].client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": GOOGLE_SCOPE, "access_type": "offline", "prompt": "consent", "state": draft})
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{query}", status_code=302)


def _exchange_error(err: Exception, target: Target, code: str) -> str:
    """Текст сбоя обмена кода для страницы и черновика: только известные русские сообщения
    (``StorageError``, ``HttpError`` по-русски, без тела ответа); прочее — общий текст."""
    text = str(err).strip().rstrip(".") if isinstance(err, (StorageError, HttpError)) else ""
    if not re.search("[а-яё]", text, re.I) or any(
            s and s in text for s in (target.secret, code, target.token)):
        return GOOGLE_RETRY
    return text if text.startswith(GOOGLE_DENIED) else f"{GOOGLE_DENIED}: {text}"


def _fail(d: dict, text: str) -> HTMLResponse:
    d["state"], d["error"] = "error", text
    return _page("Google Диск не подключён", f"{text}. Вернитесь в «Настройки» и попробуйте ещё раз.", 400)


@router.get("/gdrive/callback", summary="Возврат из Google: обмен кода на токены, проверка и сохранение")
def gdrive_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    ctx = ctx_of(request)
    d = _draft(request, state)
    if d is None:
        return _page("Google Диск не подключён", DRAFT_GONE, 404)
    if error or not code:
        return _fail(d, f"{GOOGLE_DENIED}: {error or 'нет кода авторизации'}")
    target: Target = d["target"]
    try:
        grant = _exchange_code(ctx, target, code, d["redirect_uri"] or
                               f"{request.url.scheme}://{request.url.netloc}/api/targets/gdrive/callback")
    except Exception as e:  # noqa: BLE001 — любая ошибка обмена — понятное сообщение
        return _fail(d, _exchange_error(e, target, code))
    if not grant:
        return _fail(d, f"{GOOGLE_DENIED}: пустой ответ")
    values = target._to_dict()
    values["token"] = grant
    connected = Target(**values)
    try:
        _probe(ctx, connected)
    except ApiError as e:
        return _fail(d, e.detail)
    if connected.id and ctx.settings.get_target(connected.id) is None:
        connected.id = ""  # хранилище удалили, пока шёл вход
    saved = ctx.settings.save_target(connected)
    ctx.reset_storage(saved.id)
    d["state"], d["error"], d["saved"] = "connected", None, saved.id
    return _page("Google Диск подключён", "Вкладку можно закрыть — хранилище сохранено в «Настройках».")


@router.get("/gdrive/draft/{draft_id}", summary="Состояние входа в Google: pending | connected | error")
def gdrive_draft_state(draft_id: str, request: Request):
    ctx = ctx_of(request)
    d = _draft(request, draft_id)
    if d is None:
        raise ApiError(404, DRAFT_GONE)
    out: dict = {"state": d["state"]}
    if d["error"]:
        out["error"] = d["error"]
    if d["saved"]:
        saved = ctx.settings.get_target(d["saved"])
        if saved is not None:
            out["target"] = saved.public()
    return out
